#!/usr/bin/env python3
"""E5 teaching-scale DRAFT evidence driver; never calls a model or an API.

baseline --out NEW_DIR
candidate --run-dir DIR --dockerfile FILE --name NAME [--response FILE]
          [--provenance FILE]
finalize --run-dir DIR --selected NAME --reason TEXT
verify --run-dir DIR

The two prompts and the fixture-specific error localization adapt the supplied
course lab. This is not the original paper benchmark or an automatic generator.
All command stdout/stderr files contain the original bytes, including on timeout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE_FILES = ("main.c", "Makefile", "README.md", ".dockerignore", "Dockerfile.broken")
PINNED_FROM = "m.daocloud.io/docker.io/library/python@sha256:f82c96458eedc847b233e582eb31336f4954b39cae020b6dcf5b3ed0e5cbcd74"
EXPECTED_OUTPUT = b"hello E3\n"
KEYWORDS = ("error", "unknown", "missing", "no such file or directory", "failed to execute",
            "execution failed", "file not found", "not specified", "unable to locate package",
            "no matching distribution found for")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content.encode("utf-8") if isinstance(content, str) else content)


def write_json(path, value):
    write_new(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_command(argv, cwd, evidence, timeout):
    """Run one command in a fresh directory and save raw streams and metadata."""
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    record = {"argv": [str(x) for x in argv], "cwd": str(Path(cwd).resolve()),
              "started_utc": utc_now(), "timeout_seconds": timeout,
              "exit_code": None, "timed_out": False, "launch_error": None}
    stdout, stderr = b"", b""
    try:
        process = subprocess.run(record["argv"], cwd=record["cwd"], capture_output=True,
                                 timeout=timeout, check=False)
        stdout, stderr = process.stdout, process.stderr
        record["exit_code"] = process.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        record["timed_out"] = True
    except OSError as exc:
        record["launch_error"] = f"{type(exc).__name__}: {exc}"
    record["finished_utc"] = utc_now()
    write_new(evidence / "stdout.log", stdout)
    write_new(evidence / "stderr.log", stderr)
    record["stdout_sha256"] = sha256(evidence / "stdout.log")
    record["stderr_sha256"] = sha256(evidence / "stderr.log")
    write_json(evidence / "command.json", record)
    return record


def succeeded(record):
    return record["exit_code"] == 0 and not record["timed_out"] and not record["launch_error"]


def command_log(directory):
    return ((Path(directory) / "stdout.log").read_bytes() + b"\n" +
            (Path(directory) / "stderr.log").read_bytes()).decode("utf-8", errors="replace")


def classify_baseline(record, log):
    if record["timed_out"]:
        return "TIMED_OUT"
    if record["launch_error"]:
        return "INFRASTRUCTURE_FAILURE"
    # Docker/BuildKit returns 1, while the failed RUN shell reports 127.
    missing = re.search(r"/bin/(?:ba)?sh:\s*(?:\d+:\s*)?make:\s*not found", log)
    shell_127 = re.search(r"(?:exit code:\s*127\b|non-zero code:\s*127\b)", log)
    if record["exit_code"] not in (None, 0, 124) and missing and shell_127:
        return "EXPECTED_MISSING_MAKE"
    return "UNEXPECTED_SUCCESS" if succeeded(record) else "INFRASTRUCTURE_OR_OTHER_FAILURE"


def _instructions(text):
    if "```" in text:
        raise ValueError("Pass Dockerfile text without Markdown fences")
    pending, instructions = "", []
    for line in text.splitlines():
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            if re.match(r"#\s*(syntax|escape)\s*=", stripped, re.I):
                raise ValueError("Dockerfile parser directives are outside this fixture")
            continue
        pending += stripped[:-1] + " " if stripped.endswith("\\") else stripped
        if not stripped.endswith("\\"):
            fields = pending.split(None, 1)
            if len(fields) != 2:
                raise ValueError("Invalid Dockerfile instruction")
            instructions.append((fields[0].upper(), fields[1].strip()))
            pending = ""
    if pending:
        raise ValueError("Unterminated Dockerfile continuation")
    return instructions


def validate_candidate(text):
    """Allow dependency-install RUNs before the unchanged five core instructions."""
    instructions = _instructions(text)
    if not instructions or instructions[0] != ("FROM", PINNED_FROM):
        raise ValueError("FROM must retain the exact original pinned image and digest")
    index = 1
    while index < len(instructions) and instructions[index][0] == "RUN":
        if instructions[index][1] == "make":
            raise ValueError("Dependency installation must precede WORKDIR and COPY")
        index += 1
    expected = [("WORKDIR", "/work"), ("COPY", "main.c Makefile ./"),
                ("RUN", "make"), ("CMD", '["./hello"]')]
    actual = instructions[index:]
    if len(actual) != len(expected):
        raise ValueError("Only dependency-install RUNs before WORKDIR may be added")
    for (kind, value), (want_kind, want_value) in zip(actual, expected):
        if kind != want_kind:
            raise ValueError("Preserve FROM, WORKDIR, COPY, RUN make and CMD in order")
        if kind == "CMD":
            try:
                valid = json.loads(value) == ["./hello"]
            except json.JSONDecodeError:
                valid = False
        else:
            valid = value == want_value
        if not valid:
            raise ValueError(f"Preserve exact {want_kind} {want_value}")
    return {"valid": True, "pinned_from": PINNED_FROM,
            "policy": "Only dependency-install RUN instructions before WORKDIR may be added"}


def make_prompts(root):
    baseline = root / "baseline"
    result = read_json(baseline / "result.json")
    log = command_log(baseline / "build")
    if classify_baseline(read_json(baseline / "build/command.json"), log) != "EXPECTED_MISSING_MAKE":
        raise ValueError("Prompts require an actual make-not-found shell-127 build failure")
    dockerfile = (root / "project/Dockerfile.broken").read_text(encoding="utf-8")
    readme = (root / "project/README.md").read_text(encoding="utf-8")
    lines = log.splitlines()
    note = ("Fixture-specific teaching localization and teaching adaptations of the course "
            "DRAFT prompts; not verbatim paper templates or the original paper algorithm.")
    localization = {"provenance": "SCRIPT_FROM_ACTUAL_BUILD_LOG", "note": note,
                    "build_exit_code": result["build_exit_code"],
                    "stream_order": "stdout then stderr; each original stream is retained separately",
                    "keyword_matches": [{"line": n, "text": line,
                                         "keywords": [k for k in KEYWORDS if k in line.lower()]}
                                        for n, line in enumerate(lines, 1)
                                        if any(k in line.lower() for k in KEYWORDS)],
                    "root_cause_lines": [{"line": n, "text": line}
                                         for n, line in enumerate(lines, 1)
                                         if re.search(r"/bin/(?:ba)?sh:.*make: not found", line)]}
    write_json(baseline / "error-localization.json", localization)
    instruction = (note + "\n\nRepair the failed Dockerfile using the actual build evidence.\n"
                   "Preserve the exact pinned FROM image and digest, WORKDIR /work, "
                   "COPY main.c Makefile ./, RUN make and CMD [\"./hello\"], in order.\n"
                   "Only add dependency-install RUN instructions between FROM and WORKDIR.\n"
                   "Do not bypass the build, suppress failure, change project files, or print a replacement answer.\n"
                   "Return one complete Dockerfile in a fenced Dockerfile code block.\n"
                   "It will undergo a real no-cache build and exact program-output verification.\n")
    inputs = ("\nFailed Dockerfile:\n```dockerfile\n" + dockerfile.rstrip() +
              "\n```\n\nLast up to 50 lines of actual build streams:\n```text\n" +
              "\n".join(lines[-50:]) + "\n```\n")
    write_new(baseline / "prompt-error-driven.txt", instruction + inputs)
    write_new(baseline / "prompt-context-driven.txt", instruction +
              "\nProject README context:\n```text\n" + readme.rstrip() + "\n```\n" + inputs)


def baseline(out, fixture=None, build_timeout=600):
    out, fixture = Path(out).resolve(), Path(fixture or REPO / "fixtures/draft").resolve()
    # Refuse before running anything or writing inside an existing directory.
    out.mkdir(parents=True, exist_ok=False)
    project = out / "project"
    project.mkdir()
    for name in FIXTURE_FILES:
        source = fixture / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or non-regular fixture file: {name}")
        write_new(project / name, source.read_bytes())
    if _instructions((project / "Dockerfile.broken").read_text(encoding="utf-8"))[0] != ("FROM", PINNED_FROM):
        raise ValueError("Fixture FROM differs from the fixed original digest")
    run_id = uuid.uuid4().hex[:16]
    metadata = {"schema_version": 1, "run_id": run_id, "created_utc": utc_now(),
                "scope": "E5 teaching-scale DRAFT evidence; no automatic model/API calls",
                "fixture_source": str(fixture), "pinned_from": PINNED_FROM,
                "driver_sha256": sha256(Path(__file__).resolve()),
                "source_files": {name: sha256(project / name) for name in FIXTURE_FILES},
                "environment": {"platform": platform.platform(), "machine": platform.machine(),
                                "python": sys.version, "executable": sys.executable}}
    head = run_command(["git", "rev-parse", "HEAD"], REPO, out / "environment/git-head", 30)
    metadata["repository_commit"] = ((out / "environment/git-head/stdout.log").read_text().strip()
                                     if succeeded(head) else None)
    run_command(["git", "status", "--porcelain"], REPO, out / "environment/git-status", 30)
    docker = run_command(["docker", "version", "--format", "{{json .}}"], out,
                         out / "environment/docker-version", 30)
    write_json(out / "run.json", metadata)
    baseline_dir = out / "baseline"
    baseline_dir.mkdir()
    if not succeeded(docker):
        result = {"status": "INFRASTRUCTURE_FAILURE", "expected_failure": False,
                  "build_executed": False, "build_exit_code": None,
                  "reason": "Docker CLI/daemon unavailable; inspect environment/docker-version"}
    else:
        record = run_command(["docker", "build", "--no-cache", "--progress=plain", "--file",
                              str(project / "Dockerfile.broken"), "--iidfile",
                              str(baseline_dir / "image-id.txt"), str(project)],
                             out, baseline_dir / "build", build_timeout)
        status = classify_baseline(record, command_log(baseline_dir / "build"))
        result = {"status": status, "expected_failure": status == "EXPECTED_MISSING_MAKE",
                  "build_executed": True, "build_exit_code": record["exit_code"],
                  "timed_out": record["timed_out"], "launch_error": record["launch_error"]}
    write_json(baseline_dir / "result.json", result)
    if result["expected_failure"]:
        make_prompts(out)
    return result


def check_source(root):
    metadata = read_json(root / "run.json")
    if metadata.get("pinned_from") != PINNED_FROM:
        raise ValueError("Recorded fixed FROM has changed")
    if set(metadata.get("source_files", {})) != set(FIXTURE_FILES):
        raise ValueError("Snapshot must contain exactly the five fixture inputs")
    if {p.name for p in (root / "project").iterdir()} != set(FIXTURE_FILES):
        raise ValueError("Unexpected files in immutable fixture snapshot")
    for name, expected in metadata["source_files"].items():
        path = root / "project" / name
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Fixture source hash mismatch: {name}")
    if _instructions((root / "project/Dockerfile.broken").read_text())[0] != ("FROM", PINNED_FROM):
        raise ValueError("Snapshot FROM has changed")
    return metadata


def check_open(root):
    if (root / "result.json").exists() or (root / "SHA256SUMS.json").exists():
        raise ValueError("Run is finalized; use a fresh run directory")
    check_source(root)
    result = read_json(root / "baseline/result.json")
    if not result.get("expected_failure"):
        raise ValueError("Candidate requires a baseline with the actual expected failure")
    if classify_baseline(read_json(root / "baseline/build/command.json"),
                         command_log(root / "baseline/build")) != "EXPECTED_MISSING_MAKE":
        raise ValueError("Baseline evidence does not support expected failure")


def cleanup_container(root, candidate_dir, container_name):
    record = run_command(["docker", "container", "rm", "--force", container_name], root,
                         candidate_dir / "cleanup", 30)
    inspect = run_command(["docker", "container", "inspect", container_name], root,
                          candidate_dir / "cleanup-inspect", 30)
    log = command_log(candidate_dir / "cleanup-inspect").lower()
    absent = (not inspect["timed_out"] and not inspect["launch_error"] and
              inspect["exit_code"] != 0 and ("no such container" in log or "no such object" in log))
    return {"container_name": container_name, "remove_exit_code": record["exit_code"],
            "absence_confirmed": absent}


def candidate(run_dir, dockerfile, name, response=None, provenance=None,
              build_timeout=600, run_timeout=30):
    root = Path(run_dir).resolve()
    if not NAME_RE.fullmatch(name):
        raise ValueError("Candidate name must match [a-z0-9][a-z0-9_-]{0,47}")
    check_open(root)
    source = Path(dockerfile).resolve().read_bytes()
    # Read optional inputs before creating the candidate directory.
    reply = Path(response).resolve().read_bytes() if response else None
    origin = Path(provenance).resolve().read_bytes() if provenance else None
    if origin is not None:
        json.loads(origin.decode("utf-8"))
    directory = root / "candidates" / name
    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "Dockerfile", source)
    if reply is not None:
        write_new(directory / "model-response.txt", reply)
    if origin is not None:
        write_new(directory / "provenance.json", origin)
    result = {"name": name, "created_utc": utc_now(), "dockerfile_sha256": sha256(directory / "Dockerfile"),
              "response_recorded": reply is not None, "provenance_recorded": origin is not None,
              "passed": False, "build_exit_code": None, "verify_exit_code": None,
              "image_id": None, "output_matches": False}
    try:
        result["validation"] = validate_candidate(source.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        result.update(status="INVALID_CANDIDATE", reason=str(exc))
        write_json(directory / "result.json", result)
        return result
    build = run_command(["docker", "build", "--no-cache", "--progress=plain", "--file",
                         str(directory / "Dockerfile"), "--iidfile", str(directory / "image-id.txt"),
                         str(root / "project")], root, directory / "build", build_timeout)
    result["build_exit_code"] = build["exit_code"]
    if not succeeded(build):
        result["status"] = "TIMED_OUT" if build["timed_out"] else "BUILD_FAILED"
        result["launch_error"] = build["launch_error"]
        write_json(directory / "result.json", result)
        return result
    try:
        image_id = (directory / "image-id.txt").read_text(encoding="ascii").strip()
        if not IMAGE_RE.fullmatch(image_id):
            raise ValueError("Docker did not produce a valid sha256 image ID")
        inspect = run_command(["docker", "image", "inspect", image_id], root, directory / "image-inspect", 30)
        if not succeeded(inspect):
            raise ValueError("Could not inspect the image built by this candidate")
        objects = json.loads((directory / "image-inspect/stdout.log").read_bytes())
        if len(objects) != 1 or objects[0].get("Id") != image_id:
            raise ValueError("Inspected image ID differs from the iidfile")
        write_json(directory / "image.json", objects[0])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(status="IMAGE_EVIDENCE_FAILED", reason=str(exc))
        write_json(directory / "result.json", result)
        return result
    result["image_id"] = image_id
    container_name = f"e5-{read_json(root / 'run.json')['run_id']}-{name}"
    verify = run_command(["docker", "run", "--rm", "--name", container_name,
                          "--network", "none", "--cpus", "1", "--memory", "256m",
                          "--pids-limit", "64", image_id], root, directory / "verify", run_timeout)
    # The generated name belongs exclusively to this candidate. Never prune containers.
    result["cleanup"] = cleanup_container(root, directory, container_name)
    result["verify_exit_code"] = verify["exit_code"]
    result["output_matches"] = (directory / "verify/stdout.log").read_bytes() == EXPECTED_OUTPUT
    result["passed"] = succeeded(verify) and result["output_matches"] and result["cleanup"]["absence_confirmed"]
    result["status"] = ("PASSED" if result["passed"] else "TIMED_OUT" if verify["timed_out"]
                        else "CLEANUP_UNCONFIRMED" if not result["cleanup"]["absence_confirmed"]
                        else "VERIFY_FAILED")
    result["launch_error"] = verify["launch_error"]
    write_json(directory / "result.json", result)
    check_source(root)
    return result


def candidate_summary(root):
    summaries = []
    base = root / "candidates"
    for directory in sorted(base.iterdir()) if base.exists() else []:
        if not directory.is_dir() or not (directory / "result.json").is_file():
            raise ValueError(f"Incomplete candidate evidence: {directory.name}")
        result = read_json(directory / "result.json")
        if result.get("name") != directory.name or sha256(directory / "Dockerfile") != result["dockerfile_sha256"]:
            raise ValueError(f"Candidate identity/hash mismatch: {directory.name}")
        if result.get("passed"):
            validate_candidate((directory / "Dockerfile").read_text(encoding="utf-8"))
            build = read_json(directory / "build/command.json")
            verify = read_json(directory / "verify/command.json")
            image = (directory / "image-id.txt").read_text(encoding="ascii").strip()
            if (not succeeded(build) or not succeeded(verify) or not IMAGE_RE.fullmatch(image)
                    or result["image_id"] != image or verify["argv"][-1] != image
                    or read_json(directory / "image.json").get("Id") != image
                    or (directory / "verify/stdout.log").read_bytes() != EXPECTED_OUTPUT
                    or not result.get("cleanup", {}).get("absence_confirmed")):
                raise ValueError(f"Candidate success unsupported by evidence: {directory.name}")
        summaries.append(result)
    return summaries


def finalize(run_dir, selected, reason):
    root = Path(run_dir).resolve()
    check_open(root)
    if not reason.strip():
        raise ValueError("A concrete selection reason is required")
    if not NAME_RE.fullmatch(selected):
        raise ValueError("Invalid selected candidate name")
    candidates = candidate_summary(root)
    chosen = next((item for item in candidates if item["name"] == selected), None)
    if not chosen or not chosen["passed"]:
        raise ValueError("Select a candidate with actual successful build and exact output verification")
    pending = []
    if len(candidates) < 2:
        pending.append("Two prompt strategies have not both been represented by candidate records")
    for item in candidates:
        directory = root / "candidates" / item["name"]
        if not (directory / "model-response.txt").is_file() or not (directory / "provenance.json").is_file():
            pending.append(f"Raw model response/provenance missing: {item['name']}")
    for name in ("error-localization.json", "prompt-error-driven.txt", "prompt-context-driven.txt"):
        if not (root / "baseline" / name).is_file():
            pending.append(f"Missing E5 artifact: {name}")
    result = {"schema_version": 1, "finalized_utc": utc_now(), "scope": "E5 teaching-scale DRAFT",
              "baseline_expected_failure": True, "selected_candidate": selected,
              "selection_reason": reason, "selected_image_id": chosen["image_id"],
              "build_and_exact_output_verified": True, "e5_records_complete": not pending,
              "pending": pending, "candidates": candidates,
              "limits": ["No model/API calls are made by this driver",
                         "Model generation facts depend on the separately recorded original responses/provenance",
                         "TinyGreeting is a course fixture, not the original paper benchmark",
                         "No E6 service or E7 gate is implemented"]}
    write_json(root / "result.json", result)
    manifest = {str(p.relative_to(root)).replace(os.sep, "/"): sha256(p)
                for p in sorted(root.rglob("*")) if p.is_file()}
    write_json(root / "SHA256SUMS.json", manifest)
    verify_run(root)
    return result


def verify_run(run_dir):
    root = Path(run_dir).resolve()
    manifest = read_json(root / "SHA256SUMS.json")
    actual = {str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*")
              if p.is_file() and p.name != "SHA256SUMS.json"}
    if actual != set(manifest):
        raise ValueError("Evidence file set differs from the finalized manifest")
    for name, expected in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe path in evidence manifest")
        path = root / relative
        if path.is_symlink() or sha256(path) != expected:
            raise ValueError(f"Evidence hash mismatch: {name}")
    check_source(root)
    if classify_baseline(read_json(root / "baseline/build/command.json"),
                         command_log(root / "baseline/build")) != "EXPECTED_MISSING_MAKE":
        raise ValueError("Baseline is not an expected make-not-found failure")
    summaries = candidate_summary(root)
    result = read_json(root / "result.json")
    selected = next((item for item in summaries if item["name"] == result["selected_candidate"]), None)
    if not selected or not selected["passed"] or selected["image_id"] != result["selected_image_id"]:
        raise ValueError("Final selection is not supported by candidate evidence")
    return {"verified": True, "files_checked": len(manifest),
            "e5_records_complete": result["e5_records_complete"], "pending": result["pending"]}


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Must be positive")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    initial = sub.add_parser("baseline")
    initial.add_argument("--out", required=True)
    initial.add_argument("--build-timeout", type=positive_int, default=600)
    repair = sub.add_parser("candidate")
    repair.add_argument("--run-dir", required=True)
    repair.add_argument("--dockerfile", required=True)
    repair.add_argument("--name", required=True)
    repair.add_argument("--response")
    repair.add_argument("--provenance", help="Existing JSON record; copied without inventing model provenance")
    repair.add_argument("--build-timeout", type=positive_int, default=600)
    repair.add_argument("--run-timeout", type=positive_int, default=30)
    finish = sub.add_parser("finalize")
    finish.add_argument("--run-dir", required=True)
    finish.add_argument("--selected", required=True)
    finish.add_argument("--reason", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "baseline":
            result = baseline(args.out, build_timeout=args.build_timeout)
            passed = result["expected_failure"]
        elif args.command == "candidate":
            result = candidate(args.run_dir, args.dockerfile, args.name, args.response,
                               args.provenance, args.build_timeout, args.run_timeout)
            passed = result["passed"]
        elif args.command == "finalize":
            result = finalize(args.run_dir, args.selected, args.reason)
            passed = result["e5_records_complete"]
        else:
            result = verify_run(args.run_dir)
            passed = result["e5_records_complete"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if passed else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
