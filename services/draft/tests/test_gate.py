"""Unit-only doubles exercise E7's real-run evidence contract and attack surface."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from draft import autobuild as e6
from draft import gate
from test_autobuild import BROKEN, VALID, FakeDocker, FakeProcess


class CaseDocker(FakeDocker):
    def __init__(self, name, *, network_failure=False, ignore_nonzero=False, empty_timeout=False):
        super().__init__(candidate_exit=1 if name == "build-failed" or network_failure else 0,
                         timeout_stage="verify" if name == "runtime-timeout" else None)
        self.name, self.network_failure, self.ignore_nonzero = name, network_failure, ignore_nonzero
        self.empty_timeout = empty_timeout

    def __call__(self, argv, **kwargs):
        if argv[:2] == ["docker", "build"] and Path(argv[argv.index("--file") + 1]).parent.name == "iter-02":
            if self.network_failure:
                return subprocess.CompletedProcess(argv, 1, b"", b"Could not resolve mirrors.aliyun.com\n")
            if self.name == "build-failed":
                return subprocess.CompletedProcess(argv, 1, b"", b"main.c:1:2: error: #error E7_INJECTED_BUILD_FAILURE\n")
        if argv[:2] == ["docker", "run"]:
            if self.name == "runtime-timeout":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"" if self.empty_timeout else gate.TIMEOUT_MARKER, stderr=b"")
            if self.name == "runtime-nonzero":
                return subprocess.CompletedProcess(argv, 0 if self.ignore_nonzero else 23, b"hello E3\n", b"")
        return super().__call__(argv, **kwargs)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        files = {"main.c": b'#include <stdio.h>\nint main(void) { puts("hello E3"); return 0; }\n',
                 "Makefile": b"all:\n\tcc main.c -o hello\n", "README.md": b"fixture\n", ".dockerignore": b"hello\n",
                 "Dockerfile.broken": BROKEN.encode()}
        for name, content in files.items():
            (self.fixture / name).write_bytes(content)
        self.candidate = self.root / "candidate.Dockerfile"
        self.candidate.write_bytes(VALID.encode())
        self.output = self.root / "gate"
        self.runner = e6.run_command
        self.outer_commands = []
        self.network_failure = False
        self.ignore_nonzero = False
        self.baseline_failure = None
        self.empty_timeout = False

    def fake_outer(self, argv, cwd, evidence, timeout):
        if argv[1:4] != ["-m", "draft", "auto-build"]:
            return self.runner(argv, cwd, evidence, timeout)
        self.outer_commands.append(list(argv))
        options = {argv[index][2:].replace("-", "_"): argv[index + 1] for index in range(4, len(argv), 2)}
        name = Path(options["out"]).parent.name
        started = e6.utc_now()
        fake = CaseDocker(name, network_failure=self.network_failure, ignore_nonzero=self.ignore_nonzero,
                          empty_timeout=self.empty_timeout)
        if self.baseline_failure == "network":
            fake.baseline_exit, fake.baseline_log = 1, b"failed to resolve source metadata: network unavailable\n"
        elif self.baseline_failure == "timeout":
            fake.timeout_stage = "baseline"
        with patch.object(e6.subprocess, "Popen", side_effect=lambda args, **kw: FakeProcess(fake, args, **kw)), \
                patch.object(e6.os, "killpg", create=True):
            try:
                result = e6.auto_build(options["fixture"], options["candidate"], options["out"], options["expected_output"],
                                       int(options["timeout"]), int(options["verify_timeout"]), options.get("provenance"))
                code = 0 if result["passed"] else 1
            except (ValueError, OSError) as exc:
                result, code = {"status": "FAILED", "error": str(exc)}, 1
        evidence = Path(evidence)
        evidence.mkdir(parents=True, exist_ok=False)
        e6.write_json(evidence / "stdout.log", result)
        e6.write_new(evidence / "stderr.log", b"")
        record = {"argv": list(argv), "cwd": str(Path(cwd).resolve()), "started_utc": started,
                  "finished_utc": e6.utc_now(), "timeout_seconds": timeout, "exit_code": code,
                  "timed_out": False, "launch_error": None, "stdout_sha256": e6.sha256(evidence / "stdout.log"),
                  "stderr_sha256": e6.sha256(evidence / "stderr.log")}
        e6.write_json(evidence / "command.json", record)
        return record

    def run_gate(self, **kwargs):
        with patch.object(e6, "run_command", side_effect=self.fake_outer):
            return gate.run_gate(self.fixture, self.candidate, self.output, build_timeout=17, **kwargs)

    def rehash(self, root=None):
        root = root or self.output
        (root / "SHA256SUMS.json").unlink()
        gate._manifest(root)

    def edit_json(self, path, mutate):
        value = e6.read_json(path)
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_all_six_cases_pass_and_offline_verifier_never_executes_commands(self):
        result = self.run_gate()
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["complete"])
        self.assertEqual([row["case"] for row in result["cases"]], list(gate.CASES))
        self.assertTrue(all(row["passed"] for row in result["cases"]))
        self.assertEqual(len(self.outer_commands), 6)
        self.assertTrue(all(cmd[1:4] == ["-m", "draft", "auto-build"] for cmd in self.outer_commands))
        self.assertFalse((self.output / "cases/invalid-candidate/run").exists())
        self.assertTrue((self.output / "gate-result.json").is_file())
        self.assertTrue((self.output / "results.csv").is_file())
        with patch.object(e6, "run_command") as execute, patch.object(e6.subprocess, "Popen") as process:
            checked = gate.verify_gate(self.output)
        execute.assert_not_called()
        process.assert_not_called()
        self.assertTrue(checked["verified"])
        self.assertTrue(checked["passed"])

    def test_runtime_exit_23_requires_failed_workflow_even_with_exact_stdout(self):
        result = self.run_gate(cases=["runtime-nonzero"])
        self.assertTrue(result["cases"][0]["passed"])
        run = self.output / "cases/runtime-nonzero/run"
        child = e6.read_json(run / "result.json")
        self.assertEqual(child["status"], "FAILED")
        self.assertTrue(child["verification"]["output_matches"])
        self.assertEqual(child["verification"]["exit_code"], 23)
        self.assertEqual((run / "verify/stdout.log").read_bytes(), b"hello E3\n")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "INCOMPLETE")

    def test_nonzero_case_rejects_incorrectly_successful_runtime(self):
        self.ignore_nonzero = True
        result = self.run_gate(cases=["runtime-nonzero"])
        self.assertFalse(result["cases"][0]["passed"])
        self.assertEqual(result["cases"][0]["observed_workflow_status"], "SUCCEEDED")

    def test_new_runtime_timeout_uses_five_seconds_in_metadata_cli_injection_and_e6(self):
        result = self.run_gate(cases=["runtime-timeout"])
        self.assertTrue(result["cases"][0]["passed"])
        self.assertEqual(e6.read_json(self.output / "run.json")["runtime_timeout_seconds"], 5)
        case = self.output / "cases/runtime-timeout"
        self.assertEqual(e6.read_json(case / "fault-injection.json")["verify_timeout"], 5)
        argv = e6.read_json(case / "workflow/command.json")["argv"]
        self.assertEqual(argv[argv.index("--verify-timeout") + 1], "5")
        self.assertEqual(e6.read_json(case / "run/verify/command.json")["timeout_seconds"], 5)
        self.assertEqual((case / "fixture/main.c").read_bytes(), gate.TIMEOUT_SOURCE)
        self.assertIn(b"sleep(10)", gate.TIMEOUT_SOURCE)

    def test_empty_runtime_timeout_streams_do_not_prove_the_program_started(self):
        self.empty_timeout = True
        result = self.run_gate(cases=["runtime-timeout"])
        row = result["cases"][0]
        self.assertFalse(row["passed"])
        self.assertTrue(row["e6_verified"])
        self.assertEqual(row["observed_workflow_status"], "TIMED_OUT")
        self.assertTrue(gate.verify_gate(self.output)["verified"])
        self.assertFalse(gate.verify_gate(self.output)["cases"][0]["passed"])

    def test_old_one_second_bundle_without_budget_field_retains_its_failed_oracle(self):
        self.empty_timeout = True
        with patch.object(gate, "RUNTIME_TIMEOUT_SECONDS", 1):
            result = self.run_gate()
        self.assertEqual(result["status"], "FAILED")
        metadata = self.output / "run.json"
        self.edit_json(metadata, lambda value: value.pop("runtime_timeout_seconds"))
        self.rehash()
        checked = gate.verify_gate(self.output)
        self.assertTrue(checked["verified"])
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["status"], "FAILED")
        timeout = next(row for row in checked["cases"] if row["case"] == "runtime-timeout")
        self.assertFalse(timeout["passed"])
        case = self.output / "cases/runtime-timeout"
        self.assertEqual(e6.read_json(case / "fault-injection.json")["verify_timeout"], 1)
        self.assertEqual(e6.read_json(case / "run/verify/command.json")["timeout_seconds"], 1)

    def test_unrecognized_or_boolean_recorded_runtime_budget_is_rejected(self):
        self.run_gate(cases=["runtime-timeout"])
        for budget in (True, 2, 30):
            with self.subTest(budget=budget):
                self.edit_json(self.output / "run.json", lambda value: value.update(runtime_timeout_seconds=budget))
                self.rehash()
                with self.assertRaisesRegex(ValueError, "Runtime timeout"):
                    gate.verify_gate(self.output)

    def test_build_network_failure_cannot_pass_build_or_runtime_negatives(self):
        self.network_failure = True
        result = self.run_gate(cases=["build-failed", "runtime-timeout", "runtime-nonzero"])
        self.assertFalse(any(row["passed"] for row in result["cases"]))
        self.assertTrue(all(row["e6_verified"] for row in result["cases"]))

    def test_baseline_network_or_timeout_failure_retains_finalized_failed_gate(self):
        for mode in ("network", "timeout"):
            with self.subTest(mode=mode):
                self.output = self.root / ("gate-" + mode)
                self.baseline_failure = mode
                result = self.run_gate()
                self.assertFalse(result["passed"])
                self.assertEqual(result["status"], "FAILED")
                self.assertTrue((self.output / "gate-result.json").is_file())
                self.assertTrue((self.output / "results.csv").is_file())
                self.assertTrue((self.output / "SHA256SUMS.json").is_file())
                for row in result["cases"]:
                    if row["case"] == "invalid-candidate":
                        self.assertTrue(row["passed"])
                    else:
                        self.assertFalse(row["passed"])
                        self.assertEqual(row["reason"], "BASELINE_MISSING_MAKE_NOT_REPRODUCED")
                        self.assertTrue(row["e6_verified"])
                self.assertFalse(gate.verify_gate(self.output)["passed"])

    def test_source_raw_bytes_provenance_and_only_five_fixture_files_are_preserved(self):
        (self.fixture / "secret.env").write_bytes(b"do not snapshot")
        original = VALID.replace("\n", "\r\n").encode()
        self.candidate.write_bytes(original)
        provenance = self.root / "provenance.json"
        raw = ('{ "candidate_sha256": "' + e6.sha256(self.candidate) + '", "model_call_in_e6": false }\n').encode()
        provenance.write_bytes(raw)
        before = {name: (self.fixture / name).read_bytes() for name in e6.FIXTURE_FILES}
        self.run_gate(provenance=provenance)
        self.assertEqual((self.output / "inputs/candidate.Dockerfile").read_bytes(), original)
        self.assertEqual((self.output / "inputs/provenance.json").read_bytes(), raw)
        self.assertEqual({p.name for p in (self.output / "fixture").iterdir()}, set(e6.FIXTURE_FILES))
        self.assertEqual({name: (self.fixture / name).read_bytes() for name in e6.FIXTURE_FILES}, before)
        for name in ("build-failed", "runtime-timeout", "runtime-nonzero"):
            case = self.output / "cases" / name
            self.assertEqual((case / "candidate.Dockerfile").read_bytes(), original)
            self.assertEqual((case / "fixture/Dockerfile.broken").read_bytes(), before["Dockerfile.broken"])
            self.assertEqual(e6.read_json(case / "fault-injection.json")["changes"][0]["path"], "fixture/main.c")
            self.assertTrue((case / "fault-injection.diff").read_bytes())

    def test_fresh_output_required_before_any_command(self):
        self.output.mkdir()
        with patch.object(e6, "run_command") as execute, self.assertRaises(FileExistsError):
            gate.run_gate(self.fixture, self.candidate, self.output)
        execute.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_selection_or_timeout_fails_before_any_command(self):
        for options in ({"cases": []}, {"cases": ["success", "success"]}, {"cases": ["invented"]},
                        {"build_timeout": True}, {"build_timeout": 0}, {"build_timeout": 1.1}):
            with self.subTest(options=options), patch.object(e6, "run_command") as execute, self.assertRaises(ValueError):
                gate.run_gate(self.fixture, self.candidate, self.output, **options)
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_outer_command_tampering_rejected_even_after_all_hashes_updated(self):
        self.run_gate(cases=["success"])
        command = self.output / "cases/success/workflow/command.json"
        self.edit_json(command, lambda value: value["argv"].__setitem__(3, "version"))
        self.rehash()
        with self.assertRaisesRegex(ValueError, "Command binding"):
            gate.verify_gate(self.output)

    def test_nested_docker_command_tampering_rejected_with_rehashed_bundles(self):
        self.run_gate(cases=["success"])
        run = self.output / "cases/success/run"
        self.edit_json(run / "verify/command.json", lambda value: value["argv"].__setitem__(-1, "sha256:" + "b" * 64))
        self.rehash(run)
        self.rehash()
        with self.assertRaisesRegex(ValueError, "Command binding"):
            gate.verify_gate(self.output)

    def test_missing_case_and_rehashed_manifest_are_rejected(self):
        self.run_gate()
        shutil.rmtree(self.output / "cases/runtime-nonzero")
        self.rehash()
        with self.assertRaisesRegex(ValueError, "Missing or extra"):
            gate.verify_gate(self.output)

    def test_extra_case_and_rehashed_manifest_are_rejected(self):
        self.run_gate(cases=["success"])
        (self.output / "cases/unexpected").mkdir()
        self.rehash()
        with self.assertRaisesRegex(ValueError, "Missing or extra"):
            gate.verify_gate(self.output)

    def test_extra_file_rejected_even_with_rehashed_manifest(self):
        self.run_gate(cases=["success"])
        (self.output / "surprise.txt").write_bytes(b"extra")
        self.rehash()
        with self.assertRaisesRegex(ValueError, "file set"):
            gate.verify_gate(self.output)

    def test_rehashed_undeclared_fixture_mutation_is_rejected(self):
        self.run_gate(cases=["runtime-nonzero"])
        (self.output / "cases/runtime-nonzero/fixture/main.c").write_bytes(gate.TIMEOUT_SOURCE)
        self.rehash()
        with self.assertRaisesRegex(ValueError, "Undeclared fixture"):
            gate.verify_gate(self.output)

    def test_rehashed_result_or_csv_tampering_is_rejected(self):
        self.run_gate(cases=["success"])
        self.edit_json(self.output / "gate-result.json", lambda value: value.update(passed=True, complete=True, status="PASS"))
        self.rehash()
        with self.assertRaisesRegex(ValueError, "JSON/CSV"):
            gate.verify_gate(self.output)

    def test_raw_workflow_stream_changes_fail_its_original_hash(self):
        self.run_gate(cases=["success"])
        (self.output / "cases/success/workflow/stdout.log").write_bytes(b"{}\n")
        self.rehash()
        with self.assertRaisesRegex(ValueError, "stdout hash"):
            gate.verify_gate(self.output)

    def test_partial_gate_never_reports_overall_success(self):
        result = self.run_gate(cases=["success", "wrong-output"])
        self.assertTrue(all(row["passed"] for row in result["cases"]))
        self.assertFalse(result["passed"])
        self.assertFalse(result["complete"])
        verified = gate.verify_gate(self.output)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["status"], "INCOMPLETE")
        self.assertFalse(verified["passed"])

    def exercise_interrupted_child(self, bound, exit_code=None):
        self.output = self.root / ("interrupted-" + str(bound) + "-" + str(exit_code))
        docker, calls = FakeDocker(), []

        def interrupted_runner(argv, cwd, evidence, timeout):
            calls.append(list(argv))
            if argv[0] == "docker":
                with patch.object(e6.subprocess, "Popen", side_effect=lambda args, **kw: FakeProcess(docker, args, **kw)):
                    return self.runner(argv, cwd, evidence, timeout)
            evidence = Path(evidence)
            run = evidence.parent / "run"
            token = "c" * 32
            e6.write_json(run / "run.json", {"trace_id": "e6-b-" + token, "container_name": "e6-draft-" + token,
                                             "evidence_root": str(run if bound else self.root / "unrelated")})
            e6.write_new(evidence / "stdout.log", b"partial child output\n")
            e6.write_new(evidence / "stderr.log", b"stalled child\n")
            record = {"argv": list(argv), "cwd": str(Path(cwd).resolve()), "started_utc": e6.utc_now(),
                      "finished_utc": e6.utc_now(), "timeout_seconds": timeout, "exit_code": exit_code,
                      "timed_out": exit_code is None, "launch_error": None, "stdout_sha256": e6.sha256(evidence / "stdout.log"),
                      "stderr_sha256": e6.sha256(evidence / "stderr.log")}
            e6.write_json(evidence / "command.json", record)
            return record

        with patch.object(e6, "run_command", side_effect=interrupted_runner):
            result = gate.run_gate(self.fixture, self.candidate, self.output, cases=["runtime-timeout"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["cases"][0]["passed"])
        self.assertEqual(result["cases"][0]["reason"], "OUTER_TIMEOUT" if exit_code is None else "E6_EVIDENCE_NOT_VERIFIABLE")
        self.assertEqual((self.output / "cases/runtime-timeout/workflow/stdout.log").read_bytes(), b"partial child output\n")
        if bound:
            self.assertEqual(calls[-2], ["docker", "container", "rm", "--force", "e6-draft-" + "c" * 32])
            self.assertEqual(calls[-1], ["docker", "container", "inspect", "e6-draft-" + "c" * 32])
        else:
            self.assertEqual(len(calls), 1)
        self.assertTrue(gate.verify_gate(self.output)["verified"])

    def test_outer_timeout_preserves_partial_logs_and_only_cleans_own_bound_container(self):
        for bound in (True, False):
            with self.subTest(bound=bound):
                self.exercise_interrupted_child(bound)

    def test_abrupt_child_exit_without_timeout_cleans_only_its_bound_container(self):
        for bound in (True, False):
            with self.subTest(bound=bound):
                self.exercise_interrupted_child(bound, exit_code=-9)


if __name__ == "__main__":
    unittest.main()
