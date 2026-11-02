"""Exercise E6 evidence and failure boundaries with a byte-preserving fake Docker."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from draft import autobuild as e6

IMAGE = "sha256:" + "a" * 64
OTHER_IMAGE = "sha256:" + "b" * 64
BROKEN = (f"FROM {e6.PINNED_FROM}\nWORKDIR /work\nCOPY main.c Makefile ./\n"
          'RUN make\nCMD ["./hello"]\n')
INSTALL = "RUN apt-get update && apt-get install -y --no-install-recommends gcc make libc6-dev && rm -rf /var/lib/apt/lists/*\n"
VALID = BROKEN.replace("WORKDIR /work", INSTALL + "WORKDIR /work")
FAILURE = b'/bin/sh: 1: make: not found\nprocess "/bin/sh -c make" did not complete successfully: exit code: 127\n'


class FakeDocker:
    def __init__(self, *, output=b"hello E3\n", timeout_stage=None, baseline_log=FAILURE,
                 baseline_exit=1, candidate_exit=0, inspect_id=IMAGE, omit_iid=False,
                 cleanup_unavailable=False, missing_docker=False):
        self.output = output
        self.timeout_stage = timeout_stage
        self.baseline_log = baseline_log
        self.baseline_exit = baseline_exit
        self.candidate_exit = candidate_exit
        self.inspect_id = inspect_id
        self.omit_iid = omit_iid
        self.cleanup_unavailable = cleanup_unavailable
        self.missing_docker = missing_docker
        self.commands = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if self.missing_docker:
            raise FileNotFoundError("docker not installed")
        if argv[:2] == ["docker", "build"]:
            baseline = Path(argv[argv.index("--file") + 1]).parent.name == "iter-01"
            stage = "baseline" if baseline else "candidate"
            if self.timeout_stage == stage:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"partial build\xff", stderr=b"build stalled\x00")
            if baseline:
                return subprocess.CompletedProcess(argv, self.baseline_exit, b"", self.baseline_log)
            if not self.omit_iid and self.candidate_exit == 0:
                Path(argv[argv.index("--iidfile") + 1]).write_bytes((IMAGE + "\n").encode())
            return subprocess.CompletedProcess(argv, self.candidate_exit, b"built\xff\n", b"")
        if argv[:3] == ["docker", "image", "inspect"]:
            if self.timeout_stage == "inspect":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"[", stderr=b"inspect stalled")
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Id": self.inspect_id}]).encode(), b"")
        if argv[:2] == ["docker", "run"]:
            if self.timeout_stage == "verify":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"partial\xff", stderr=b"still running\x00")
            return subprocess.CompletedProcess(argv, 0, self.output, b"")
        if argv[:3] == ["docker", "container", "rm"]:
            if self.timeout_stage == "cleanup":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"", stderr=b"cleanup stalled")
            return subprocess.CompletedProcess(argv, 1, b"", b"Error: No such container\n")
        if argv[:3] == ["docker", "container", "inspect"]:
            message = b"Cannot connect to Docker daemon" if self.cleanup_unavailable else b"Error: No such container\n"
            return subprocess.CompletedProcess(argv, 1, b"[]\n", message)
        raise AssertionError(argv)


class FakeProcess:
    """Popen double that exposes cumulative partial streams after timeout/kill."""
    def __init__(self, docker, argv, **kwargs):
        self.docker, self.argv, self.kwargs = docker, argv, kwargs
        self.returncode, self.partial = None, None
        self.pid = 123456789
        self.stdout = self.stderr = None

    def communicate(self, timeout=None):
        if self.partial is not None:
            self.returncode = -9
            return self.partial
        try:
            result = self.docker(self.argv, timeout=timeout, **self.kwargs)
        except subprocess.TimeoutExpired as exc:
            self.partial = (exc.stdout or b"", exc.stderr or b"")
            raise
        self.returncode = result.returncode
        return result.stdout, result.stderr

    def kill(self):
        self.returncode = -9


class AutoBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        files = {"main.c": b'#include <stdio.h>\nint main(void) { puts("hello E3"); }\n',
                 "Makefile": b"all:\n\tcc -o hello main.c\n", "README.md": b"C greeting built with make.\n",
                 ".dockerignore": b"hello\n", "Dockerfile.broken": BROKEN.encode()}
        for name, value in files.items():
            (self.fixture / name).write_bytes(value)
        self.candidate = self.root / "candidate.Dockerfile"
        self.candidate.write_bytes(VALID.encode())
        self.output = self.root / "evidence"

    def run_workflow(self, fake=None, **kwargs):
        fake = fake or FakeDocker()
        with patch.object(e6.subprocess, "Popen", side_effect=lambda argv, **options: FakeProcess(fake, argv, **options)), \
                patch.object(e6.os, "killpg", create=True):
            result = e6.auto_build(self.fixture, self.candidate, self.output, **kwargs)
        return result, fake

    def rehash_manifest(self):
        manifest = {path.relative_to(self.output).as_posix(): e6.sha256(path)
                    for path in sorted(self.output.rglob("*"))
                    if path.is_file() and path != self.output / "SHA256SUMS.json"}
        (self.output / "SHA256SUMS.json").write_text(json.dumps(manifest), encoding="utf-8")

    def edit_json(self, relative, change):
        path = self.output / relative
        value = e6.read_json(path)
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_success_binds_two_no_cache_builds_same_id_resource_limits_and_cleanup(self):
        result, fake = self.run_workflow(timeout=17, verify_timeout=3)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["source_kind"], "REPLAY")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["failure_class"], "EXPECTED_MISSING_MAKE")
        builds = [command for command in fake.commands if command[:2] == ["docker", "build"]]
        self.assertEqual(len(builds), 2)
        for command in builds:
            self.assertIn("--no-cache", command)
            self.assertIn("--iidfile", command)
            self.assertNotIn("--tag", command)
        inspect = next(command for command in fake.commands if command[:3] == ["docker", "image", "inspect"])
        run = next(command for command in fake.commands if command[:2] == ["docker", "run"])
        self.assertEqual(inspect[-1], IMAGE)
        self.assertEqual(run[-1], IMAGE)
        for option, value in (("--network", "none"), ("--cpus", "1"), ("--memory", "256m"), ("--pids-limit", "64")):
            self.assertEqual(run[run.index(option) + 1], value)
        name = run[run.index("--name") + 1]
        self.assertEqual(fake.commands[-2], ["docker", "container", "rm", "--force", name])
        self.assertEqual(fake.commands[-1], ["docker", "container", "inspect", name])
        self.assertTrue(result["cleanup"]["absence_confirmed"])
        with patch.object(e6.subprocess, "run") as invoked:
            verification = e6.verify_evidence(self.output)
        invoked.assert_not_called()
        self.assertTrue(verification["workflow_succeeded"])
        self.assertIn(b"+RUN apt-get", (self.output / "repair.diff").read_bytes())

    def test_only_five_inputs_are_snapshotted_and_original_candidate_bytes_retained(self):
        (self.fixture / "Dockerfile.reference").write_bytes(b"reference answer")
        (self.fixture / ".env").write_bytes(b"SECRET=do-not-copy")
        (self.fixture / "unrelated.txt").write_bytes(b"ignored")
        original = VALID.replace("\n", "\r\n").encode()
        self.candidate.write_bytes(original)
        provenance = self.root / "source.json"
        provenance_bytes = b'{ "source_kind": "OLD_SAVED_CANDIDATE", "model_call_in_e6": false }\n'
        provenance.write_bytes(provenance_bytes)
        self.run_workflow(provenance=provenance)
        self.assertEqual({path.name for path in (self.output / "project").iterdir()}, set(e6.FIXTURE_FILES))
        self.assertEqual((self.output / "inputs/candidate.Dockerfile").read_bytes(), original)
        self.assertEqual((self.output / "iter-02/Dockerfile").read_bytes(), original)
        self.assertEqual((self.output / "inputs/provenance.json").read_bytes(), provenance_bytes)
        self.assertEqual((self.output / "iter-02/build/stdout.log").read_bytes(), b"built\xff\n")

    def test_existing_empty_output_is_not_overwritten_and_no_docker_called(self):
        self.output.mkdir()
        with patch.object(e6.subprocess, "run") as invoked, self.assertRaises(FileExistsError):
            e6.auto_build(self.fixture, self.candidate, self.output)
        invoked.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_candidates_are_rejected_before_output_or_docker(self):
        invalids = [VALID.replace(e6.PINNED_FROM, "python:latest"), VALID.replace("RUN make", "RUN make || true"),
                    VALID.replace('["./hello"]', '["echo", "hello E3"]'), VALID.replace("COPY main.c Makefile ./", "COPY . ."),
                    VALID + "COPY other.c main.c\n", "# syntax=docker/dockerfile:latest\n" + VALID,
                    VALID.replace(INSTALL, "RUN echo install fake\n"), BROKEN]
        for candidate in invalids:
            with self.subTest(candidate=candidate):
                self.candidate.write_bytes(candidate.encode())
                with patch.object(e6.subprocess, "run") as invoked, self.assertRaises(ValueError):
                    e6.auto_build(self.fixture, self.candidate, self.output)
                invoked.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_fixed_mirror_and_bounded_apt_options_are_allowed(self):
        candidate = VALID.replace("RUN apt-get update", "RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources\nRUN apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update")
        self.candidate.write_bytes(candidate.encode())
        self.assertEqual(self.run_workflow()[0]["status"], "SUCCEEDED")
        for command in ("sed -i 's|deb.debian.org|evil.example|g' /etc/apt/sources.list.d/debian.sources",
                        "apt-get -o Acquire::Retries=999 update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*",
                        "apt-get update && apt-get install -y --no-install-recommends gcc make libc6-dev && rm -rf /var/lib/apt/lists/* && touch /work/hello"):
            with self.assertRaises(ValueError):
                e6.validate_dependency_run(command)

    def test_baseline_requires_both_make_not_found_and_shell_127(self):
        for log in (b"/bin/sh: 1: make: not found\n", b"network error: exit code: 127\n", b"TLS timeout"):
            with self.subTest(log=log):
                result, fake = self.run_workflow(FakeDocker(baseline_log=log))
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(len(result["attempts"]), 1)
                self.assertFalse(any(command[:2] == ["docker", "run"] for command in fake.commands))
                self.assertTrue(e6.verify_evidence(self.output)["verified"])
                shutil.rmtree(self.output)

    def test_unexpected_baseline_success_never_runs_candidate(self):
        result, fake = self.run_workflow(FakeDocker(baseline_exit=0))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["attempts"][0]["failure_class"], "UNEXPECTED_SUCCESS")
        self.assertEqual(sum(command[:2] == ["docker", "build"] for command in fake.commands), 1)

    def test_build_timeout_preserves_raw_partial_bytes_and_finally_cleans(self):
        for stage, count in (("baseline", 1), ("candidate", 2)):
            with self.subTest(stage=stage):
                result, fake = self.run_workflow(FakeDocker(timeout_stage=stage), timeout=1)
                self.assertEqual(result["status"], "TIMED_OUT")
                self.assertEqual(len(result["attempts"]), count)
                self.assertEqual((self.output / f"iter-{count:02d}/build/stdout.log").read_bytes(), b"partial build\xff")
                self.assertTrue(result["cleanup"]["absence_confirmed"])
                self.assertFalse(any(command[:2] == ["docker", "run"] for command in fake.commands))
                self.assertFalse(e6.verify_evidence(self.output)["workflow_succeeded"])
                shutil.rmtree(self.output)

    def test_verification_timeout_preserves_raw_bytes_and_cleans_owned_name(self):
        result, fake = self.run_workflow(FakeDocker(timeout_stage="verify"), verify_timeout=1)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertEqual((self.output / "verify/stdout.log").read_bytes(), b"partial\xff")
        self.assertEqual((self.output / "verify/stderr.log").read_bytes(), b"still running\x00")
        self.assertTrue(result["cleanup"]["absence_confirmed"])
        self.assertTrue(e6.verify_evidence(self.output)["verified"])
        self.assertEqual(fake.commands[-1][-1], result["cleanup"]["container_name"])

    def test_inspect_timeout_is_recorded_and_skips_run(self):
        result, fake = self.run_workflow(FakeDocker(timeout_stage="inspect"))
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertFalse(result["verification"]["executed"])
        self.assertFalse(any(command[:2] == ["docker", "run"] for command in fake.commands))

    def test_inexact_program_output_cannot_succeed(self):
        for actual in (b"hello E3", b"hello E3\r\n", b"hello E3\n\n", b"hello E3\nextra\n"):
            with self.subTest(actual=actual):
                result, _ = self.run_workflow(FakeDocker(output=actual))
                self.assertEqual(result["status"], "FAILED")
                self.assertFalse(result["verification"]["output_matches"])
                shutil.rmtree(self.output)

    def test_custom_expected_output_remains_exact(self):
        result, _ = self.run_workflow(FakeDocker(output=b"other\n"), expected_output="other")
        self.assertEqual(result["status"], "SUCCEEDED")

    def test_wrong_inspected_id_or_missing_iid_prevents_program_run(self):
        for fake in (FakeDocker(inspect_id=OTHER_IMAGE), FakeDocker(omit_iid=True)):
            result, _ = self.run_workflow(fake)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["verification"]["executed"])
            self.assertFalse(any(command[:2] == ["docker", "run"] for command in fake.commands))
            shutil.rmtree(self.output)

    def test_candidate_build_failure_is_not_verified(self):
        result, _ = self.run_workflow(FakeDocker(candidate_exit=1))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["attempts"][1]["build_exit_code"], 1)
        self.assertFalse(result["verification"]["executed"])

    def test_missing_docker_is_infrastructure_failure_with_saved_launch_error(self):
        result, _ = self.run_workflow(FakeDocker(missing_docker=True))
        self.assertEqual(result["status"], "INFRASTRUCTURE_FAILURE")
        self.assertIn("FileNotFoundError", result["attempts"][0]["launch_error"])
        self.assertFalse(result["cleanup"]["absence_confirmed"])

    def test_cleanup_daemon_error_or_timeout_cannot_succeed(self):
        for fake, status in ((FakeDocker(cleanup_unavailable=True), "CLEANUP_UNCONFIRMED"),
                             (FakeDocker(timeout_stage="cleanup"), "TIMED_OUT")):
            result, _ = self.run_workflow(fake)
            self.assertEqual(result["status"], status)
            self.assertTrue(result["verification"]["output_matches"])
            self.assertFalse(e6.verify_evidence(self.output)["workflow_succeeded"])
            shutil.rmtree(self.output)

    def test_invalid_budgets_and_multiline_expected_output_are_preflight_errors(self):
        for kwargs in ({"timeout": 0}, {"timeout": float("nan")}, {"verify_timeout": True},
                       {"expected_output": "hello E3\n"}, {"expected_output": "a\x00b"}):
            with self.subTest(kwargs=kwargs), patch.object(e6.subprocess, "run") as invoked, self.assertRaises(ValueError):
                e6.auto_build(self.fixture, self.candidate, self.output, **kwargs)
            invoked.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_provenance_candidate_hash_must_match_original_candidate_bytes(self):
        with patch.object(e6.subprocess, "run") as invoked, self.assertRaisesRegex(ValueError, "candidate_sha256"):
            e6.auto_build(self.fixture, self.candidate, self.output, provenance={"candidate_sha256": "0" * 64})
        invoked.assert_not_called()
        self.run_workflow(provenance={"candidate_sha256": hashlib.sha256(VALID.encode()).hexdigest(), "model_call_in_e6": False})

    def test_evidence_is_portable_to_another_directory_and_never_executes_docker(self):
        self.run_workflow()
        moved = self.root / "downloaded"
        self.output.rename(moved)
        with patch.object(e6.subprocess, "run") as invoked:
            self.assertTrue(e6.verify_evidence(moved)["workflow_succeeded"])
        invoked.assert_not_called()

    def test_raw_stream_change_is_detected_without_manifest_refresh(self):
        self.run_workflow()
        (self.output / "verify/stdout.log").write_bytes(b"edited\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            e6.verify_evidence(self.output)

    def test_rehashed_stream_change_still_fails_original_command_hash(self):
        self.run_workflow()
        (self.output / "iter-01/build/stderr.log").write_bytes(b"edited")
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Original command stderr hash mismatch"):
            e6.verify_evidence(self.output)

    def test_rehashed_semantic_command_tampering_is_rejected(self):
        cases = [("iter-01/build/command.json", lambda record: record["argv"].remove("--no-cache")),
                 ("iter-02/build/command.json", lambda record: record["argv"].__setitem__(-1, "another-project")),
                 ("verify/command.json", lambda record: record["argv"].__setitem__(record["argv"].index("--network") + 1, "host")),
                 ("verify/command.json", lambda record: record["argv"].__setitem__(-1, OTHER_IMAGE)),
                 ("cleanup/command.json", lambda record: record["argv"].__setitem__(-1, "unrelated-container")),
                 ("iter-02/inspect/command.json", lambda record: record["argv"].__setitem__(-1, OTHER_IMAGE))]
        for relative, change in cases:
            with self.subTest(relative=relative):
                self.run_workflow()
                self.edit_json(relative, change)
                self.rehash_manifest()
                with self.assertRaisesRegex(ValueError, "Command binding mismatch"):
                    e6.verify_evidence(self.output)
                shutil.rmtree(self.output)

    def test_rehashed_report_status_or_baseline_classification_is_rejected(self):
        self.run_workflow()
        self.edit_json("result.json", lambda value: value["attempts"][0].__setitem__("failure_class", "OTHER"))
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "not supported"):
            e6.verify_evidence(self.output)

    def test_rehashed_iid_change_cannot_rebind_saved_inspect_and_run(self):
        self.run_workflow()
        (self.output / "iter-02/image-id.txt").write_bytes((OTHER_IMAGE + "\n").encode())
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Command binding mismatch"):
            e6.verify_evidence(self.output)

    def test_rehashed_input_change_fails_input_hash_binding(self):
        self.run_workflow()
        (self.output / "project/main.c").write_bytes(b"replacement\n")
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Fixture source hash mismatch"):
            e6.verify_evidence(self.output)

    def test_rehashed_candidate_change_fails_source_build_binding(self):
        self.run_workflow()
        (self.output / "iter-02/Dockerfile").write_bytes((VALID + "# edited\n").encode())
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Candidate source/build hash"):
            e6.verify_evidence(self.output)

    def test_rehashed_diff_tampering_is_rejected(self):
        self.run_workflow()
        (self.output / "repair.diff").write_bytes(b"invented diff\n")
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Repair diff"):
            e6.verify_evidence(self.output)

    def test_even_rehashed_extra_files_are_rejected(self):
        self.run_workflow()
        (self.output / "extra-secret.txt").write_bytes(b"do not include")
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "file set does not match"):
            e6.verify_evidence(self.output)

    def test_impossible_exit_timeout_metadata_is_rejected_even_when_rehashed(self):
        self.run_workflow()
        self.edit_json("verify/command.json", lambda record: record.__setitem__("timed_out", True))
        self.rehash_manifest()
        with self.assertRaisesRegex(ValueError, "Inconsistent command"):
            e6.verify_evidence(self.output)

    def test_launch_metadata_timestamps_and_replay_claim_are_validated(self):
        for relative, change, message in [
                ("verify/command.json", lambda record: record.__setitem__("started_utc", "not-a-time"), "timestamps"),
                ("run.json", lambda record: record.__setitem__("source_kind", "FRESH_MODEL_RESPONSE"), "replay source")]:
            with self.subTest(relative=relative):
                self.run_workflow()
                self.edit_json(relative, change)
                self.rehash_manifest()
                with self.assertRaisesRegex(ValueError, message):
                    e6.verify_evidence(self.output)
                shutil.rmtree(self.output)


if __name__ == "__main__":
    unittest.main()
