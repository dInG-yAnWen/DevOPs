#!/usr/bin/env python3
"""Collect an isolated real E7 quality gate without modifying E6 evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/draft"))
from draft.autobuild import FIXTURE_FILES, read_json, run_command, sha256, succeeded, verify_evidence, write_json, write_new
from draft.gate import verify_gate

CASE_COUNT = 6
CHILD_NAME = re.compile(r"e6-draft-([0-9a-f]{32})\Z")


def _repository_input(value, default):
    path = Path(value if value is not None else ROOT / default)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_symlink() or not path.is_file():
        raise ValueError("Candidate and provenance must be regular repository files")
    path = path.resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("Candidate and provenance must be inside the mounted repository") from exc
    return path, "/workspace/" + relative


def collect(output, build_timeout=1200, gate_build_timeout=600, candidate=None, provenance=None):
    if os.name != "posix":
        raise ValueError("Collect on a Linux host with Docker")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in (build_timeout, gate_build_timeout)):
        raise ValueError("Timeouts must be positive integers")
    candidate, mounted_candidate = _repository_input(candidate, "e6/candidates/context-mirror/Dockerfile")
    provenance, mounted_provenance = _repository_input(provenance, "e6/candidates/context-mirror/provenance.json")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new collection directory")
    if output == ROOT / "fixtures/draft" or ROOT / "fixtures/draft" in output.parents:
        raise ValueError("Collection output must be outside the immutable fixture")
    output.mkdir(parents=True)
    trace = uuid.uuid4().hex
    tag = "b14-e7-service:" + trace
    name = "b14-e7-collector-" + trace
    # E6 permits two builds and bounded inspect, run and cleanup for each case.
    gate_budget = CASE_COUNT * (2 * gate_build_timeout + 180) + 180
    report = {"schema_version": 1, "status": "FAILED", "service_tag": tag,
              "service_image_id": None, "source_revision": None,
              "source_kind": "E7_SAVED_CANDIDATE_VALIDATION", "gate": None,
              "gate_timeout_seconds": gate_budget,
              "candidate": candidate.relative_to(ROOT).as_posix(),
              "provenance": provenance.relative_to(ROOT).as_posix()}
    gate_record = None
    gate_started = False

    def command(label, argv, budget=30):
        return run_command(argv, ROOT, output / label, budget)

    def required(label, argv, budget=30):
        result = command(label, argv, budget)
        if not succeeded(result):
            raise ValueError(label + " failed; inspect its original command evidence")
        return result

    def absence(label, container):
        command(label + "-cleanup", ["docker", "container", "rm", "--force", container])
        record = command(label + "-cleanup-inspect", ["docker", "container", "inspect", container])
        raw = (output / (label + "-cleanup-inspect") / "stderr.log").read_text(errors="replace")
        return (record["exit_code"] not in (None, 0) and not record["timed_out"] and
                record["launch_error"] is None and re.search(r"\bno such (?:object|container)\b", raw, re.I) is not None)

    def service_command(label, image, argv, budget=30, mounts=()):
        container = name + "-" + label
        arguments = ["docker", "run", "--rm", "--name", container, "--network", "none",
                     "--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp",
                     "--cpus", "1", "--memory", "512m", "--pids-limit", "128"]
        for mount in mounts:
            arguments += ["--volume", mount]
        try:
            return command(label, [*arguments, image, *argv], budget)
        finally:
            if not absence(label, container):
                raise ValueError(label + " container absence was not confirmed")

    def required_service(label, image, argv, budget=30, mounts=()):
        record = service_command(label, image, argv, budget, mounts)
        if not succeeded(record):
            raise ValueError(label + " failed; inspect its original command evidence")
        return record

    def emergency_child_cleanup():
        results = []
        # Recover only names bound to this bundle. Fully verified, finalized E6
        # runs already prove absence and their original evidence stays untouched.
        for metadata_path in sorted((output / "gate/cases").glob("*/run/run.json")):
            item = {"metadata": metadata_path.relative_to(output).as_posix(), "absence_confirmed": False}
            try:
                metadata = read_json(metadata_path)
                container = metadata.get("container_name", "")
                match = CHILD_NAME.fullmatch(container) if isinstance(container, str) else None
                mounted_root = "/evidence/" + metadata_path.parent.relative_to(output).as_posix()
                if not match or metadata.get("trace_id") != "e6-b-" + match.group(1) or metadata.get("evidence_root") != mounted_root:
                    raise ValueError("Emergency cleanup refused unbound child metadata")
                item["container_name"] = container
                verify_path = metadata_path.parent / "verify/command.json"
                if verify_path.is_file():
                    argv = read_json(verify_path).get("argv", [])
                    if argv[:5] != ["docker", "run", "--rm", "--name", container]:
                        raise ValueError("Emergency cleanup refused a child command/name mismatch")
                finalized = False
                if (metadata_path.parent / "SHA256SUMS.json").is_file():
                    try:
                        verified = verify_evidence(metadata_path.parent)
                        prior = read_json(metadata_path.parent / "result.json")
                        finalized = verified.get("verified") is True and prior.get("cleanup", {}).get("absence_confirmed") is True
                    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                        item["prior_verification_error"] = str(exc)
                item["already_finalized"] = finalized
                item["absence_confirmed"] = finalized or absence("emergency-child-" + str(len(results) + 1), container)
            except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                item["error"] = str(exc)
            results.append(item)
        write_json(output / "emergency-child-cleanup.json", results)
        if not all(item["absence_confirmed"] for item in results):
            raise ValueError("A gate child container could not be confirmed absent")
        return results

    try:
        required("source-revision", ["git", "rev-parse", "HEAD"])
        revision = (output / "source-revision/stdout.log").read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValueError("Git did not return a full source revision")
        report["source_revision"] = revision
        required("source-status", ["git", "status", "--porcelain", "--untracked-files=all"])
        if (output / "source-status/stdout.log").read_bytes().strip():
            raise ValueError("Commit source changes before collecting E7 evidence")
        required("source-commit", ["git", "show", "--no-patch", "--format=fuller", "HEAD"])
        required("environment", ["uname", "-a"])
        required("docker-version", ["docker", "version", "--format", "{{json .}}"])
        write_new(output / "os-release.txt", Path("/etc/os-release").read_bytes())
        sources = {candidate, provenance, ROOT / "services/draft/Dockerfile", ROOT / "services/draft/pytest.ini",
                   ROOT / "requirements-dev.lock", ROOT / "scripts/secret_scan.py",
                   ROOT / ".github/workflows/e7-quality-gate.yml", ROOT / ".dockerignore", ROOT / ".gitattributes"}
        sources.update((ROOT / "services/draft").rglob("*.py"))
        sources.update((ROOT / "e7/scripts").glob("*.py"))
        sources.update((ROOT / "e7/tests").rglob("*.py"))
        sources.update(path for path in (ROOT / "e7/ci").rglob("*") if "__pycache__" not in path.parts)
        sources.update(path for path in (ROOT / "e7/candidates").rglob("*"))
        sources.update(ROOT / "fixtures/draft" / item for item in FIXTURE_FILES)
        write_json(output / "source-files.json", {
            path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(sources) if path.is_file()
        })
        write_new(output / "collector.py", Path(__file__).read_bytes())
        required("service-build", ["docker", "build", "--progress=plain", "--file", "services/draft/Dockerfile",
                                   "--iidfile", str(output / "service-image-id.txt"), "--tag", tag, "."], build_timeout)
        image = (output / "service-image-id.txt").read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("Service build did not supply a full image ID")
        report["service_image_id"] = image
        required("service-inspect", ["docker", "image", "inspect", image])
        if read_json(output / "service-inspect/stdout.log")[0]["Id"] != image:
            raise ValueError("Service image identity mismatch")
        required_service("service-toolchain", image, ["cat", "/opt/toolchain.lock"])
        for module in ("autobuild.py", "gate.py"):
            label = "service-" + module.removesuffix(".py") + "-sha256"
            required_service(label, image, ["sha256sum", "/app/draft/" + module])
            actual = (output / label / "stdout.log").read_text().split()[0]
            if actual != sha256(ROOT / "services/draft/draft" / module):
                raise ValueError("Service image contains different implementation bytes: " + module)
        required_service("service-tests", image,
                         ["python3", "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider",
                          "--junitxml=/evidence/service-tests.xml"], 180, (f"{output}:/evidence",))
        test_log = (output / "service-tests/stdout.log").read_text(errors="replace")
        count = re.search(r"\b([1-9][0-9]*) passed\b", test_log)
        junit = ET.parse(output / "service-tests.xml").getroot()
        suites = list(junit.iter("testsuite"))
        if not count or not suites or any(int(suite.get("failures", "0")) or int(suite.get("errors", "0")) for suite in suites):
            raise ValueError("Service tests did not provide an explicit successful test count")
        report["service_tests_passed"] = int(count.group(1))
        socket_gid = str(Path("/var/run/docker.sock").stat().st_gid)
        gate_started = True
        gate_record = command("quality-gate", ["docker", "run", "--rm", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}", "--group-add", socket_gid, "--env", "HOME=/tmp",
            "--cpus", "2", "--memory", "1g", "--pids-limit", "256",
            "--volume", "/var/run/docker.sock:/var/run/docker.sock",
            "--volume", f"{ROOT}:/workspace:ro", "--volume", f"{output}:/evidence", image,
            "python3", "-m", "draft", "quality-gate", "--fixture", "/workspace/fixtures/draft",
            "--candidate", mounted_candidate, "--provenance", mounted_provenance,
            "--out", "/evidence/gate", "--build-timeout", str(gate_build_timeout)], gate_budget)
        if (output / "gate/SHA256SUMS.json").is_file():
            report["gate"] = verify_gate(output / "gate")
            write_json(output / "offline-verification.json", report["gate"])
        if not succeeded(gate_record) or not report["gate"] or not all(
                report["gate"].get(field) is True for field in ("passed", "complete", "verified")):
            raise ValueError("E7 quality gate did not pass; retain the failed evidence")
        required("contract-tests", [sys.executable, "validator/validate.py", "--suite"], 120)
        oracle = {}
        for label, path, expected in (("unit-oracle-failure", "e7/ci/rejection-demo/test_ci_reject_demo.py", 1),
                                      ("unit-oracle-recovery", "e7/ci/rejection-demo/fixed/test_ci_reject_demo.py", 0)):
            record = service_command(label, image,
                ["python3", "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", "tests/test_ci_reject_demo.py"],
                60, (f"{ROOT / path}:/app/tests/test_ci_reject_demo.py:ro",))
            stdout = (output / label / "stdout.log").read_text(errors="replace")
            valid = record["exit_code"] == expected and not record["timed_out"] and record["launch_error"] is None
            if expected == 1:
                valid = valid and "AssertionError" in stdout and "1 failed" in stdout and "E7_INTENTIONAL_WRONG_VERSION_ORACLE" in stdout
            else:
                valid = valid and "1 passed" in stdout
            oracle[label] = {"expected_exit_code": expected, "observed_exit_code": record["exit_code"], "passed": valid}
            if not valid:
                raise ValueError(label + " did not exhibit the expected test-oracle behavior")
        report["local_oracle_demonstration"] = {"kind": "LOCAL_TEST_ORACLE_SELF_CHECK", "github_proof": False, "checks": oracle}
        report["status"] = "SUCCEEDED"
    except (OSError, ValueError, KeyError, IndexError, TypeError, ET.ParseError) as exc:
        report["error"] = str(exc)
    finally:
        try:
            report["collector_absence_confirmed"] = absence("collector", name)
            if not report["collector_absence_confirmed"]:
                raise ValueError("Collector container absence was not confirmed")
            gate_finalized = gate_record is not None and succeeded(gate_record) and report["gate"] and all(
                report["gate"].get(field) is True for field in ("passed", "complete", "verified"))
            if gate_started and not gate_finalized:
                report["emergency_child_cleanup"] = emergency_child_cleanup()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report["status"] = "FAILED"
            report["cleanup_error"] = str(exc)
        write_json(output / "collection.json", report)
        write_json(output / "COLLECTION_SHA256SUMS.json", {
            path.relative_to(output).as_posix(): sha256(path) for path in sorted(output.rglob("*")) if path.is_file()
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--provenance")
    parser.add_argument("--service-build-timeout", type=int, default=1200)
    parser.add_argument("--build-timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        result = collect(args.out, args.service_build_timeout, args.build_timeout, args.candidate, args.provenance)
    except (ValueError, OSError) as exc:
        result = {"status": "FAILED", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
