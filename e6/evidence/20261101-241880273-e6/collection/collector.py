#!/usr/bin/env python3
"""Build/test the E6 service image and collect one isolated real cloud run."""
from pathlib import Path
import argparse
import json
import os
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/draft"))
from draft.autobuild import read_json, run_command, sha256, succeeded, verify_evidence, write_json, write_new


def collect(output, build_timeout=1200, workflow_timeout=600):
    if os.name != "posix":
        raise ValueError("Collect on the assigned Linux cloud host with Docker")
    if build_timeout <= 0 or workflow_timeout <= 0:
        raise ValueError("Timeouts must be positive")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new collection directory")
    output.mkdir(parents=True)
    trace = uuid.uuid4().hex
    tag = "b14-e6-service:" + trace
    name = "b14-e6-collector-" + trace
    report = {"status": "FAILED", "service_tag": tag, "service_image_id": None,
              "source_kind": "E5_SAVED_CANDIDATE_REPLAY", "workflow": None}

    def command(label, argv, budget=30):
        return run_command(argv, ROOT, output / label, budget)

    def required(label, argv, budget=30):
        result = command(label, argv, budget)
        if not succeeded(result):
            raise ValueError(label + " failed; inspect original command evidence")
        return result

    def absence(label, container):
        command(label + "-cleanup", ["docker", "container", "rm", "--force", container])
        record = command(label + "-cleanup-inspect", ["docker", "container", "inspect", container])
        log = (output / (label + "-cleanup-inspect") / "stderr.log").read_text(errors="replace")
        return (record["exit_code"] not in (None, 0) and not record["timed_out"] and
                record["launch_error"] is None and re.search(r"no such (?:object|container)", log, re.I) is not None)

    def service_command(label, image, argv, budget=30):
        container = name + "-" + label
        try:
            return required(label, ["docker", "run", "--rm", "--name", container, "--network", "none", image, *argv], budget)
        finally:
            if not absence(label, container):
                raise ValueError(label + " container absence was not confirmed")

    try:
        required("source-revision", ["git", "rev-parse", "HEAD"])
        required("source-status", ["git", "status", "--porcelain"])
        if (output / "source-status/stdout.log").read_bytes().strip():
            raise ValueError("Commit source changes before collecting E6 evidence")
        required("git-identity", ["git", "var", "GIT_AUTHOR_IDENT"])
        required("environment", ["uname", "-a"])
        required("docker-version", ["docker", "version", "--format", "{{json .}}"])
        write_new(output / "os-release.txt", Path("/etc/os-release").read_bytes())
        sources = [*sorted((ROOT / "services/draft").rglob("*.py")),
                   ROOT / "services/draft/Dockerfile", ROOT / "requirements-dev.lock",
                   *sorted((ROOT / "e6/scripts").glob("*.py")),
                   *sorted((ROOT / "e6/candidates").rglob("*")),
                   *sorted((ROOT / "fixtures/draft").glob("*")), ROOT / "fixtures/draft/.dockerignore"]
        write_json(output / "source-files.json", {
            p.relative_to(ROOT).as_posix(): sha256(p) for p in sources if p.is_file()
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
        service_command("service-toolchain", image, ["cat", "/opt/toolchain.lock"])
        service_command("service-core-sha256", image, ["sha256sum", "/app/draft/autobuild.py"])
        built_hash = (output / "service-core-sha256/stdout.log").read_text().split()[0]
        if built_hash != sha256(ROOT / "services/draft/draft/autobuild.py"):
            raise ValueError("Service image contains different E6 implementation bytes")
        service_command("service-tests", image, ["python3", "-m", "pytest", "-q"], 120)
        socket_gid = str(Path("/var/run/docker.sock").stat().st_gid)
        run = command("workflow", ["docker", "run", "--rm", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}", "--group-add", socket_gid, "--env", "HOME=/tmp",
            "--cpus", "2", "--memory", "1g", "--pids-limit", "256",
            "--volume", "/var/run/docker.sock:/var/run/docker.sock",
            "--volume", f"{ROOT}:/workspace:ro", "--volume", f"{output}:/evidence", image,
            "python3", "-m", "draft", "auto-build", "--fixture", "/workspace/fixtures/draft",
            "--candidate", "/workspace/e6/candidates/context-mirror/Dockerfile",
            "--provenance", "/workspace/e6/candidates/context-mirror/provenance.json",
            "--out", "/evidence/run", "--timeout", str(workflow_timeout), "--verify-timeout", "30"],
            2 * workflow_timeout + 180)
        if (output / "run/SHA256SUMS.json").is_file():
            report["workflow"] = verify_evidence(output / "run")
            write_json(output / "offline-verification.json", report["workflow"])
        if not succeeded(run) or not report["workflow"] or not report["workflow"]["workflow_succeeded"]:
            raise ValueError("E6 workflow did not succeed; retain the failed run evidence")
        required("contract-tests", [sys.executable, "validator/validate.py", "--suite"], 120)
        report["status"] = "SUCCEEDED"
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        report["error"] = str(exc)
    finally:
        report["collector_absence_confirmed"] = absence("collector", name)
        if not report["collector_absence_confirmed"]:
            report["status"] = "FAILED"
            report["cleanup_error"] = "Collector container absence was not confirmed"
        write_json(output / "collection.json", report)
        write_json(output / "COLLECTION_SHA256SUMS.json", {
            p.relative_to(output).as_posix(): sha256(p) for p in sorted(output.rglob("*")) if p.is_file()
        })
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--service-build-timeout", type=int, default=1200)
    parser.add_argument("--build-timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        result = collect(args.out, args.service_build_timeout, args.build_timeout)
    except (ValueError, OSError) as exc:
        result = {"status": "FAILED", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
