"""Portable unit doubles for collector failure propagation; no Docker execution."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("collector", ROOT / "e7/scripts/collect_e7.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
IMAGE = "sha256:" + "d" * 64
ORIGINAL_READ_BYTES = Path.read_bytes
ORIGINAL_STAT = Path.stat


class CollectorChecks(unittest.TestCase):
    def execute(self, scenario):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "collection"
        calls = []

        def fake(argv, cwd, evidence, timeout):
            label = evidence.name
            calls.append((label, argv))
            evidence.mkdir(parents=True)
            stdout, stderr, code, timed_out = b"", b"", 0, False
            if label == "source-revision":
                stdout = b"a" * 40 + b"\n"
            elif label == "source-status" and scenario == "dirty":
                stdout = b" M dirty.py\n"
            elif label == "service-build":
                (output / "service-image-id.txt").write_text(IMAGE)
            elif label == "service-inspect":
                stdout = json.dumps([{"Id": IMAGE}]).encode()
            elif label.startswith("service-") and label.endswith("-sha256"):
                module = label.removeprefix("service-").removesuffix("-sha256") + ".py"
                stdout = (c.sha256(ROOT / "services/draft/draft" / module) + "  /app/draft/" + module).encode()
            elif label == "service-tests":
                if scenario == "unit-failed":
                    code, stdout = 1, b"1 failed\n"
                else:
                    stdout = b"2 passed in 0.02s\n"
                    (output / "service-tests.xml").write_text('<testsuites><testsuite tests="2" failures="0" errors="0" /></testsuites>')
            elif label == "quality-gate":
                (output / "gate").mkdir()
                if scenario in ("timeout", "oom", "bad-metadata"):
                    code, timed_out = (None, True) if scenario == "timeout" else (137, False)
                    child = output / "gate/cases/runtime-timeout/run"
                    child.mkdir(parents=True)
                    suffix = "a" * 32
                    metadata = {"container_name": "e6-draft-" + suffix,
                                "trace_id": "e6-b-" + suffix,
                                "evidence_root": "/evidence/gate/cases/runtime-timeout/run"}
                    if scenario == "bad-metadata":
                        metadata["trace_id"] = "wrong"
                    (child / "run.json").write_text(json.dumps(metadata))
                else:
                    (output / "gate/SHA256SUMS.json").write_text("{}")
            elif label == "unit-oracle-failure":
                code = 0 if scenario == "wrong-oracle-passed" else 1
                stdout = b"AssertionError: E7_INTENTIONAL_WRONG_VERSION_ORACLE\n1 failed\n"
            elif label == "unit-oracle-recovery":
                stdout = b"1 passed\n"
            elif label.endswith("cleanup-inspect"):
                code, stderr = 1, b"Error: No such container\n"
            record = {"argv": argv, "exit_code": code, "timed_out": timed_out, "launch_error": None}
            (evidence / "stdout.log").write_bytes(stdout)
            (evidence / "stderr.log").write_bytes(stderr)
            (evidence / "command.json").write_text(json.dumps(record))
            return record

        def read_bytes(path):
            return b"NAME=test\n" if path.as_posix() == "/etc/os-release" else ORIGINAL_READ_BYTES(path)

        def stat(path, *args, **kwargs):
            return SimpleNamespace(st_gid=123) if path.as_posix() == "/var/run/docker.sock" else ORIGINAL_STAT(path, *args, **kwargs)

        verified = {"passed": True, "complete": True, "verified": True, "status": "PASS"}
        with patch.object(c, "os", SimpleNamespace(name="posix", getuid=lambda: 1001, getgid=lambda: 1001)), \
             patch.object(c, "run_command", side_effect=fake), \
             patch.object(c, "verify_gate", return_value=verified), \
             patch.object(Path, "read_bytes", read_bytes), patch.object(Path, "stat", stat):
            result = c.collect(output, 10, 10)
        self.assertTrue((output / "collection.json").is_file())
        self.assertTrue((output / "COLLECTION_SHA256SUMS.json").is_file())
        manifest = json.loads((output / "COLLECTION_SHA256SUMS.json").read_text())
        self.assertTrue(all(c.sha256(output / name) == digest for name, digest in manifest.items()))
        self.assertTrue(result["collector_absence_confirmed"])
        return result, calls, output

    def test_success(self):
        result, calls, _ = self.execute("success")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["service_tests_passed"], 2)
        self.assertFalse(result["local_oracle_demonstration"]["github_proof"])
        labels = [label for label, _ in calls]
        self.assertIn("unit-oracle-failure-cleanup-inspect", labels)
        self.assertIn("unit-oracle-recovery-cleanup-inspect", labels)

    def test_unit_failure_blocks_gate(self):
        result, calls, _ = self.execute("unit-failed")
        self.assertEqual(result["status"], "FAILED")
        self.assertNotIn("quality-gate", [label for label, _ in calls])

    def test_dirty_source_blocks_build(self):
        result, calls, _ = self.execute("dirty")
        self.assertEqual(result["status"], "FAILED")
        self.assertNotIn("service-build", [label for label, _ in calls])

    def test_timeout_targets_only_recorded_child(self):
        result, calls, _ = self.execute("timeout")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["emergency_child_cleanup"][0]["container_name"], "e6-draft-" + "a" * 32)
        self.assertTrue(result["emergency_child_cleanup"][0]["absence_confirmed"])

    def test_oom_targets_recorded_child(self):
        result, calls, _ = self.execute("oom")
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["emergency_child_cleanup"][0]["absence_confirmed"])

    def test_forged_metadata_does_not_remove_child(self):
        result, calls, _ = self.execute("bad-metadata")
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("cleanup_error", result)
        self.assertFalse(any(label.startswith("emergency-child-") for label, _ in calls))

    def test_wrong_oracle_unexpected_success_fails_collection(self):
        result, _, _ = self.execute("wrong-oracle-passed")
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("unit-oracle-failure", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
