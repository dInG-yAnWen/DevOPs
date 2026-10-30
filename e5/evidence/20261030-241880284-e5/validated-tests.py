"""Evidence and failure boundaries; Docker is simulated, never required by these tests."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_e5.py"
SPEC = importlib.util.spec_from_file_location("run_e5", SCRIPT)
e5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e5)
IMAGE = "sha256:" + "a" * 64
BROKEN = (f"FROM {e5.PINNED_FROM}\nWORKDIR /work\nCOPY main.c Makefile ./\n"
          'RUN make\nCMD ["./hello"]\n')
VALID = BROKEN.replace("WORKDIR /work", "RUN apt-get update && apt-get install -y --no-install-recommends gcc make libc6-dev && rm -rf /var/lib/apt/lists/*\nWORKDIR /work")
FAILURE = b'/bin/sh: 1: make: not found\nprocess "/bin/sh -c make" did not complete successfully: exit code: 127\n'


class FakeDocker:
    def __init__(self, output=e5.EXPECTED_OUTPUT, timeout_run=False, infrastructure=False):
        self.output = output
        self.timeout_run = timeout_run
        self.infrastructure = infrastructure
        self.commands = []

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, b"b" * 40 + b"\n", b"")
        if argv[:2] == ["docker", "version"]:
            if self.infrastructure:
                raise FileNotFoundError("docker not installed")
            return subprocess.CompletedProcess(argv, 0, b'{"Server":{"Version":"test"}}\n', b"")
        if argv[:2] == ["docker", "build"]:
            dockerfile = argv[argv.index("--file") + 1]
            if dockerfile.endswith("Dockerfile.broken"):
                return subprocess.CompletedProcess(argv, 1, b"", FAILURE)
            Path(argv[argv.index("--iidfile") + 1]).write_text(IMAGE + "\n")
            return subprocess.CompletedProcess(argv, 0, b"built\n", b"")
        if argv[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Id": IMAGE}]).encode(), b"")
        if argv[:2] == ["docker", "run"]:
            if self.timeout_run:
                raise subprocess.TimeoutExpired(argv, 1, output=b"partial", stderr=b"still running")
            return subprocess.CompletedProcess(argv, 0, self.output, b"")
        if argv[:3] == ["docker", "container", "rm"]:
            return subprocess.CompletedProcess(argv, 1, b"", b"No such container\n")
        if argv[:3] == ["docker", "container", "inspect"]:
            return subprocess.CompletedProcess(argv, 1, b"[]\n", b"Error: No such container\n")
        raise AssertionError(argv)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        platform_patch = patch.object(e5.platform, "platform", return_value="Linux-test")
        machine_patch = patch.object(e5.platform, "machine", return_value="x86_64")
        platform_patch.start()
        machine_patch.start()
        self.addCleanup(platform_patch.stop)
        self.addCleanup(machine_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        contents = {"main.c": b"int main(void) { return 0; }\n", "Makefile": b"all:\n\tcc main.c\n",
                    "README.md": b"A C program built with Make.\n", ".dockerignore": b"hello\n",
                    "Dockerfile.broken": BROKEN.encode()}
        for name, content in contents.items():
            (self.fixture / name).write_bytes(content)
        self.run_dir = self.root / "run"
        self.dockerfile = self.root / "candidate.Dockerfile"
        self.dockerfile.write_text(VALID)

    def start(self, fake=None):
        fake = fake or FakeDocker()
        with patch.object(e5.subprocess, "run", fake):
            result = e5.baseline(self.run_dir, self.fixture)
        self.assertTrue(result["expected_failure"])
        return fake

    def test_baseline_requires_actual_missing_make_and_shell_127(self):
        record = {"exit_code": 1, "timed_out": False, "launch_error": None}
        self.assertEqual(e5.classify_baseline(record, FAILURE.decode()), "EXPECTED_MISSING_MAKE")
        for log in ("network timeout exit code: 127", "/bin/sh: 1: make: not found", "TLS handshake timeout"):
            self.assertEqual(e5.classify_baseline(record, log), "INFRASTRUCTURE_OR_OTHER_FAILURE")
        self.assertEqual(e5.classify_baseline(dict(record, timed_out=True), FAILURE.decode()), "TIMED_OUT")

    def test_missing_docker_records_infrastructure_and_no_prompt(self):
        with patch.object(e5.subprocess, "run", FakeDocker(infrastructure=True)):
            result = e5.baseline(self.run_dir, self.fixture)
        self.assertEqual(result["status"], "INFRASTRUCTURE_FAILURE")
        self.assertFalse(result["build_executed"])
        self.assertFalse((self.run_dir / "baseline/prompt-error-driven.txt").exists())
        record = e5.read_json(self.run_dir / "environment/docker-version/command.json")
        self.assertIn("FileNotFoundError", record["launch_error"])

    def test_existing_baseline_directory_never_overwritten(self):
        self.run_dir.mkdir()
        sentinel = self.run_dir / "sentinel"
        sentinel.write_bytes(b"keep")
        with patch.object(e5.subprocess, "run") as invoked:
            with self.assertRaises(FileExistsError):
                e5.baseline(self.run_dir, self.fixture)
        invoked.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_source_hash_change_rejected_before_candidate_execution(self):
        self.start()
        (self.run_dir / "project/main.c").write_bytes(b"modified")
        with patch.object(e5.subprocess, "run") as invoked:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                e5.candidate(self.run_dir, self.dockerfile, "candidate-01")
        invoked.assert_not_called()

    def test_invalid_candidate_rejected_before_docker(self):
        self.start()
        self.dockerfile.write_text(VALID.replace(e5.PINNED_FROM, "python:latest"))
        with patch.object(e5.subprocess, "run") as invoked:
            result = e5.candidate(self.run_dir, self.dockerfile, "bad")
        self.assertEqual(result["status"], "INVALID_CANDIDATE")
        invoked.assert_not_called()

    def test_candidate_core_instructions_cannot_be_bypassed(self):
        self.assertTrue(e5.validate_candidate(VALID)["valid"])
        for invalid in (VALID.replace("RUN make", "RUN make || true"),
                        VALID.replace('["./hello"]', '["echo", "hello E3"]'),
                        VALID + "COPY replacement.c main.c\n",
                        VALID.replace("COPY main.c Makefile ./", "COPY . ."),
                        "# syntax=docker/dockerfile:latest\n" + VALID):
            with self.assertRaises(ValueError):
                e5.validate_candidate(invalid)

    def test_wrong_output_rejected_and_actual_image_id_used(self):
        self.start()
        fake = FakeDocker(output=b"hello E3\nextra\n")
        with patch.object(e5.subprocess, "run", fake):
            result = e5.candidate(self.run_dir, self.dockerfile, "wrong-output")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "VERIFY_FAILED")
        run = next(cmd for cmd in fake.commands if cmd[:2] == ["docker", "run"])
        self.assertEqual(run[-1], IMAGE)
        self.assertEqual(run[run.index("--network") + 1], "none")
        self.assertTrue(result["cleanup"]["absence_confirmed"])

    def test_timeout_preserves_streams_and_only_cleans_named_container(self):
        self.start()
        fake = FakeDocker(timeout_run=True)
        with patch.object(e5.subprocess, "run", fake):
            result = e5.candidate(self.run_dir, self.dockerfile, "timeout", run_timeout=1)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertEqual((self.run_dir / "candidates/timeout/verify/stdout.log").read_bytes(), b"partial")
        run = next(cmd for cmd in fake.commands if cmd[:2] == ["docker", "run"])
        cleanup = next(cmd for cmd in fake.commands if cmd[:3] == ["docker", "container", "rm"])
        self.assertEqual(cleanup[-1], run[run.index("--name") + 1])
        self.assertNotIn("prune", " ".join(sum(fake.commands, [])))

    def test_existing_candidate_never_overwritten(self):
        fake = self.start()
        with patch.object(e5.subprocess, "run", fake):
            e5.candidate(self.run_dir, self.dockerfile, "once")
        before = (self.run_dir / "candidates/once/result.json").read_bytes()
        with patch.object(e5.subprocess, "run") as invoked:
            with self.assertRaises(FileExistsError):
                e5.candidate(self.run_dir, self.dockerfile, "once")
        invoked.assert_not_called()
        self.assertEqual((self.run_dir / "candidates/once/result.json").read_bytes(), before)

    def test_finalize_integrity_and_missing_generation_records_are_explicit(self):
        fake = self.start()
        with patch.object(e5.subprocess, "run", fake):
            result = e5.candidate(self.run_dir, self.dockerfile, "one")
        self.assertTrue(result["passed"])
        result = e5.finalize(self.run_dir, "one", "Build and exact output passed")
        self.assertFalse(result["e5_records_complete"])
        self.assertTrue(e5.verify_run(self.run_dir)["verified"])
        (self.run_dir / "baseline/build/stderr.log").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            e5.verify_run(self.run_dir)

    def test_build_timeout_is_not_success_and_skips_program_execution(self):
        self.start()
        fake = FakeDocker()
        def timeout_build(argv, **kwargs):
            if argv[:2] == ["docker", "build"]:
                raise subprocess.TimeoutExpired(argv, 1, output=b"partial build", stderr=b"network stalled")
            return fake(argv, **kwargs)
        with patch.object(e5.subprocess, "run", timeout_build):
            result = e5.candidate(self.run_dir, self.dockerfile, "build-timeout", build_timeout=1)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertFalse(any(cmd[:2] == ["docker", "run"] for cmd in fake.commands))

    def add_model_candidate(self, fake, name, strategy, mode="fresh response to the saved prompt"):
        response = self.root / f"{name}-response.txt"
        response.write_bytes(b"```dockerfile\n" + self.dockerfile.read_bytes() + b"```\n")
        provenance = self.root / f"{name}-provenance.json"
        provenance.write_text(json.dumps({"strategy": strategy, "generation_mode": mode,
                                         "prompt_sha256": e5.sha256(self.run_dir / "baseline" / f"prompt-{strategy}.txt")}))
        with patch.object(e5.subprocess, "run", fake):
            return e5.candidate(self.run_dir, self.dockerfile, name, response, provenance)

    def test_two_actual_strategies_complete_and_negative_case_need_not_pass(self):
        fake = self.start()
        self.add_model_candidate(fake, "error", "error-driven")
        self.add_model_candidate(fake, "context", "context-driven")
        self.dockerfile.write_text(VALID.replace("RUN make", "RUN make || true"))
        with patch.object(e5.subprocess, "run") as invoked:
            negative = e5.candidate(self.run_dir, self.dockerfile, "invalid-negative")
        invoked.assert_not_called()
        self.assertFalse(negative["passed"])
        result = e5.finalize(self.run_dir, "context", "Both outputs passed; context candidate retained")
        self.assertTrue(result["e5_records_complete"])
        self.assertTrue(e5.verify_run(self.run_dir)["verified"])
        with self.assertRaisesRegex(ValueError, "finalized"):
            e5.candidate(self.run_dir, self.dockerfile, "late")

    def test_duplicate_strategy_cannot_complete(self):
        fake = self.start()
        self.add_model_candidate(fake, "error-one", "error-driven")
        self.add_model_candidate(fake, "error-two", "error-driven")
        result = e5.finalize(self.run_dir, "error-one", "Both built successfully")
        self.assertFalse(result["e5_records_complete"])
        self.assertTrue(any("context-driven" in item for item in result["pending"]))

    def test_wrong_prompt_hash_and_edited_candidate_do_not_count_as_model_records(self):
        fake = self.start()
        self.add_model_candidate(fake, "error", "error-driven")
        self.add_model_candidate(fake, "context", "context-driven")
        provenance = self.run_dir / "candidates/error/provenance.json"
        data = e5.read_json(provenance)
        data["prompt_sha256"] = "0" * 64
        provenance.write_text(json.dumps(data))
        (self.run_dir / "candidates/context/model-response.txt").write_text("```dockerfile\nFROM altered\n```\n")
        result = e5.finalize(self.run_dir, "context", "Recorded build passed but provenance is invalid")
        self.assertFalse(result["e5_records_complete"])
        self.assertEqual(result["model_evidence"], [])
        self.assertEqual(len(result["candidate_record_warnings"]), 2)

    def test_added_nested_manifest_is_detected(self):
        fake = self.start()
        with patch.object(e5.subprocess, "run", fake):
            e5.candidate(self.run_dir, self.dockerfile, "one")
        e5.finalize(self.run_dir, "one", "Actual output is correct")
        (self.run_dir / "candidates/one/SHA256SUMS.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "file set differs"):
            e5.verify_run(self.run_dir)

    def test_cleanup_daemon_failure_cannot_be_reported_as_absence(self):
        fake = self.start()
        def unavailable_cleanup(argv, **kwargs):
            if argv[:3] == ["docker", "container", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, b"", b"Cannot connect to Docker daemon")
            return fake(argv, **kwargs)
        with patch.object(e5.subprocess, "run", unavailable_cleanup):
            result = e5.candidate(self.run_dir, self.dockerfile, "cleanup-failure")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "CLEANUP_UNCONFIRMED")

    def test_replay_cannot_satisfy_fresh_dual_strategy_requirement(self):
        fake = self.start()
        self.add_model_candidate(fake, "error", "error-driven")
        self.add_model_candidate(fake, "context", "context-driven", "replay of a saved course response")
        result = e5.finalize(self.run_dir, "error", "Actual output passed; other strategy is replay")
        self.assertFalse(result["e5_records_complete"])
        self.assertEqual(result["fresh_strategies"], ["error-driven"])

    def test_finalize_rejects_stream_changed_before_manifest(self):
        fake = self.start()
        with patch.object(e5.subprocess, "run", fake):
            e5.candidate(self.run_dir, self.dockerfile, "one")
        (self.run_dir / "candidates/one/build/stderr.log").write_bytes(b"accidentally overwritten")
        with self.assertRaisesRegex(ValueError, "command hash mismatch"):
            e5.finalize(self.run_dir, "one", "Output was correct")

    def test_finalize_rejects_changed_network_mode(self):
        fake = self.start()
        with patch.object(e5.subprocess, "run", fake):
            e5.candidate(self.run_dir, self.dockerfile, "one")
        path = self.run_dir / "candidates/one/verify/command.json"
        record = e5.read_json(path)
        record["argv"][record["argv"].index("--network") + 1] = "host"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "success unsupported"):
            e5.finalize(self.run_dir, "one", "Output was correct")

    def test_dependency_run_whitelist_allows_only_fixed_adaptations(self):
        install = ("apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=2 "
                   "-o Acquire::http::Timeout=30 update && "
                   "apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends build-essential "
                   "&& rm -rf /var/lib/apt/lists/*")
        e5.validate_dependency_run(install)
        e5.validate_dependency_run("sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources")
        for command in ("mkdir -p /work && printf fake > /work/hello && chmod +x /work/hello",
                        install + " && ln -s /bin/true /usr/local/bin/make",
                        install.replace("Acquire::Retries=2", "Acquire::Retries=999"),
                        "sed -i 's|deb.debian.org|evil.example|g' /etc/apt/sources.list.d/debian.sources"):
            with self.assertRaises(ValueError):
                e5.validate_dependency_run(command)

    def add_adaptation(self, fake, text, parent_hash=None):
        self.dockerfile.write_text(text)
        provenance = self.root / "adaptation-provenance.json"
        provenance.write_text(json.dumps({"generation_mode": "MANUAL_ENVIRONMENT_ADAPTATION",
                                         "parent_candidate_name": "context",
                                         "parent_sha256": parent_hash or e5.sha256(self.run_dir / "candidates/context/Dockerfile"),
                                         "reason": "Use the course server's reachable Debian mirror"}))
        with patch.object(e5.subprocess, "run", fake):
            return e5.candidate(self.run_dir, self.dockerfile, "adapted", provenance=provenance)

    def test_manual_mirror_adaptation_preserves_original_fresh_lineage(self):
        fake = self.start()
        self.add_model_candidate(fake, "error", "error-driven")
        self.add_model_candidate(fake, "context", "context-driven")
        adapted = VALID.replace("RUN apt-get update", "RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources\nRUN apt-get -o Acquire::ForceIPv4=true update")
        self.assertTrue(self.add_adaptation(fake, adapted)["passed"])
        result = e5.finalize(self.run_dir, "adapted", "Original model dependency fix plus recorded network adaptation")
        self.assertTrue(result["e5_records_complete"])
        self.assertEqual(result["selected_source_kind"], "ENVIRONMENT_ADAPTATION")
        self.assertEqual(result["selected_source"]["parent_candidate_name"], "context")
        self.assertTrue(e5.verify_run(self.run_dir)["verified"])

    def test_adaptation_cannot_change_install_packages_or_parent_hash(self):
        fake = self.start()
        self.add_model_candidate(fake, "error", "error-driven")
        self.add_model_candidate(fake, "context", "context-driven")
        self.add_adaptation(fake, VALID.replace("gcc make libc6-dev", "build-essential"))
        with self.assertRaisesRegex(ValueError, "changes more than"):
            e5.finalize(self.run_dir, "adapted", "Changed package set is outside environment adaptation")
        path = self.run_dir / "candidates/adapted/provenance.json"
        metadata = e5.read_json(path)
        metadata["parent_sha256"] = "0" * 64
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "parent_sha256"):
            e5.finalize(self.run_dir, "adapted", "Wrong parent hash must be rejected")


if __name__ == "__main__":
    unittest.main()
