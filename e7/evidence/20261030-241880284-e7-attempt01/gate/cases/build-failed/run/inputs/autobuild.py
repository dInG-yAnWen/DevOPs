"""Independent E6 two-build replay and offline evidence consistency checks.

Only the Python standard library is used. No model or API is called. The saved
manifest detects file changes; semantic checks bind the recorded Docker commands,
image, inputs, exact output and cleanup. This is not a signed execution attestation.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
import shlex
import signal
import subprocess
import uuid
from datetime import datetime, timezone

FIXTURE_FILES = ("main.c", "Makefile", "README.md", ".dockerignore", "Dockerfile.broken")
PINNED_FROM = "m.daocloud.io/docker.io/library/python@sha256:f82c96458eedc847b233e582eb31336f4954b39cae020b6dcf5b3ed0e5cbcd74"
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
CORE = [("WORKDIR", "/work"), ("COPY", "main.c Makefile ./"), ("RUN", "make"), ("CMD", '["./hello"]')]
COMMAND_KEYS = {"argv", "cwd", "started_utc", "finished_utc", "timeout_seconds", "exit_code", "timed_out", "launch_error", "stdout_sha256", "stderr_sha256"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value.encode("utf-8") if isinstance(value, str) else value)


def write_json(path, value):
    write_new(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


def _linked(path):
    path = Path(path)
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Timeouts must be finite positive numbers")
    return value


def _expected(value):
    if not isinstance(value, str) or any(c in value for c in ("\r", "\n", "\x00")):
        raise ValueError("Expected output must be one text line without line terminators")
    return (value + "\n").encode("utf-8")


def _instructions(text):
    if "```" in text:
        raise ValueError("Dockerfile must not contain Markdown fences")
    pending, result = "", []
    for line in text.splitlines():
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            if re.match(r"#\s*(syntax|escape)\s*=", stripped, re.I):
                raise ValueError("Dockerfile parser directives are unsupported")
            continue
        pending += stripped[:-1] + " " if stripped.endswith("\\") else stripped
        if not stripped.endswith("\\"):
            fields = pending.split(None, 1)
            if len(fields) != 2:
                raise ValueError("Invalid Dockerfile instruction")
            result.append((fields[0].upper(), fields[1].strip()))
            pending = ""
    if pending:
        raise ValueError("Unterminated Dockerfile continuation")
    return result


def validate_dependency_run(command):
    """Fixed E5 dependency and mirror policy, copied here without E5 imports."""
    mirror = ["sed", "-i", "s|deb.debian.org|mirrors.aliyun.com|g", "/etc/apt/sources.list.d/debian.sources"]
    if shlex.split(command) == mirror:
        return "MIRROR"
    parts = command.split("&&")
    if len(parts) != 3:
        raise ValueError("RUN must use the fixed apt-install pipeline or mirror adaptation")
    options = {"Acquire::ForceIPv4=true", "Acquire::Retries=2", "Acquire::http::Timeout=30"}

    def apt_tokens(part):
        tokens, result, index = shlex.split(part), [], 0
        while index < len(tokens):
            if tokens[index] == "-o":
                if index + 1 >= len(tokens) or tokens[index + 1] not in options:
                    raise ValueError("Unsupported apt option")
                index += 2
            else:
                result.append(tokens[index])
                index += 1
        return result

    update, install, clean = apt_tokens(parts[0]), apt_tokens(parts[1]), shlex.split(parts[2])
    allowed = (["apt-get", "install", "-y", "--no-install-recommends", "build-essential"],
               ["apt-get", "install", "-y", "--no-install-recommends", "gcc", "make", "libc6-dev"])
    if update != ["apt-get", "update"] or install not in allowed or clean != ["rm", "-rf", "/var/lib/apt/lists/*"]:
        raise ValueError("RUN differs from the allowed dependency-install pipeline")
    return "INSTALL"


def validate_candidate(text):
    instructions = _instructions(text)
    if not instructions or instructions[0] != ("FROM", PINNED_FROM):
        raise ValueError("FROM must retain the exact original pinned image and digest")
    index, installs = 1, 0
    while index < len(instructions) and instructions[index][0] == "RUN":
        installs += validate_dependency_run(instructions[index][1]) == "INSTALL"
        index += 1
    actual = instructions[index:]
    if len(actual) != len(CORE):
        raise ValueError("Only dependency-install RUNs before WORKDIR may be added")
    for (kind, value), (wanted_kind, wanted_value) in zip(actual, CORE):
        valid = kind == wanted_kind
        if kind == "CMD":
            try:
                valid = valid and json.loads(value) == ["./hello"]
            except json.JSONDecodeError:
                valid = False
        else:
            valid = valid and value == wanted_value
        if not valid:
            raise ValueError(f"Preserve exact {wanted_kind} {wanted_value}")
    if not installs:
        raise ValueError("Candidate must add a permitted dependency installation")
    return {"valid": True, "pinned_from": PINNED_FROM}


def _validate_broken(content):
    if _instructions(content.decode("utf-8")) != [("FROM", PINNED_FROM), *CORE]:
        raise ValueError("Broken fixture must retain the exact pinned FROM and original instructions")


def _repair_diff(broken, candidate):
    return "".join(difflib.unified_diff(broken.decode("utf-8").splitlines(keepends=True),
                                       candidate.decode("utf-8").splitlines(keepends=True),
                                       fromfile="Dockerfile.broken", tofile="Dockerfile.candidate")).encode("utf-8")


def _validate_provenance(content, candidate_sha256):
    value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("Provenance must be a JSON object")
    if "candidate_sha256" in value and value["candidate_sha256"] != candidate_sha256:
        raise ValueError("Provenance candidate_sha256 differs from candidate bytes")


def run_command(argv, cwd, evidence, timeout):
    """Capture original bytes, including partial timeout streams, without a shell."""
    timeout = _timeout(timeout)
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    record = {"argv": [str(x) for x in argv], "cwd": str(Path(cwd).resolve()),
              "started_utc": utc_now(), "timeout_seconds": timeout,
              "exit_code": None, "timed_out": False, "launch_error": None}
    stdout, stderr = b"", b""
    try:
        process = subprocess.Popen(record["argv"], cwd=record["cwd"], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name == "posix")
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            record["timed_out"] = True
            stdout, stderr = exc.stdout or b"", exc.stderr or b""
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                process.kill()
            try:
                # communicate returns the cumulative original bytes, not an append.
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as final:
                stdout, stderr = final.stdout or stdout, final.stderr or stderr
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            return_code = None
        else:
            return_code = process.returncode
        record["exit_code"] = return_code
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
    return record["exit_code"] == 0 and not record["timed_out"] and record["launch_error"] is None


def command_log(directory):
    directory = Path(directory)
    return (directory.joinpath("stdout.log").read_bytes() + b"\n" + directory.joinpath("stderr.log").read_bytes()).decode("utf-8", errors="replace")


def classify_baseline(record, log):
    if record["timed_out"]:
        return "TIMED_OUT"
    if record["launch_error"]:
        return "INFRASTRUCTURE_FAILURE"
    missing = re.search(r"/bin/(?:ba)?sh:\s*(?:\d+:\s*)?make:\s*(?:not found|command not found)", log)
    shell_127 = re.search(r"(?:exit code:\s*127\b|non-zero code:\s*127\b)", log)
    if record["exit_code"] not in (None, 0, 124) and missing and shell_127:
        return "EXPECTED_MISSING_MAKE"
    return "UNEXPECTED_SUCCESS" if succeeded(record) else "INFRASTRUCTURE_OR_OTHER_FAILURE"


def _image_id(path):
    try:
        value = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if IMAGE_RE.fullmatch(value) else None


def _inspect_matches(directory, image_id):
    try:
        value = read_json(Path(directory) / "stdout.log")
        return isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) and value[0].get("Id") == image_id
    except (ValueError, OSError, TypeError, UnicodeError):
        return False


def _absent(record, directory):
    return (not record["timed_out"] and record["launch_error"] is None and
            record["exit_code"] not in (None, 0) and
            re.search(r"\bno such (?:container|object)\b", command_log(directory), re.I) is not None)


def _command(root, relative):
    return read_json(root / relative / "command.json")


def _command_exists(root, relative):
    return (root / relative / "command.json").is_file()


def _step_status(record):
    if record["timed_out"]:
        return "TIMED_OUT"
    return "INFRASTRUCTURE_FAILURE" if record["launch_error"] else "FAILED"


def _evaluate(root, metadata):
    """Derive all report claims from saved command records and original streams."""
    baseline = _command(root, "iter-01/build")
    baseline_class = classify_baseline(baseline, command_log(root / "iter-01/build"))
    attempts = [{"iteration": 1, "role": "BASELINE", "dockerfile_sha256": sha256(root / "iter-01/Dockerfile"),
                 "build_exit_code": baseline["exit_code"], "timed_out": baseline["timed_out"],
                 "launch_error": baseline["launch_error"], "failure_class": baseline_class}]
    status, reason, image_id = _step_status(baseline), "BASELINE_DID_NOT_REPRODUCE_MISSING_MAKE", None
    verification = {"executed": False, "expected_output": metadata["expected_output"], "output_matches": False}
    if baseline_class == "EXPECTED_MISSING_MAKE":
        build = _command(root, "iter-02/build")
        attempts.append({"iteration": 2, "role": "CANDIDATE", "dockerfile_sha256": sha256(root / "iter-02/Dockerfile"),
                         "build_exit_code": build["exit_code"], "timed_out": build["timed_out"], "launch_error": build["launch_error"],
                         "failure_class": "NONE" if succeeded(build) else _step_status(build)})
        status, reason = _step_status(build), "CANDIDATE_BUILD_FAILED"
        if succeeded(build):
            image_id = _image_id(root / "iter-02/image-id.txt")
            status, reason = "FAILED", "MISSING_OR_INVALID_IMAGE_ID"
            if image_id:
                inspect = _command(root, "iter-02/inspect")
                status, reason = _step_status(inspect), "IMAGE_INSPECTION_FAILED"
                if succeeded(inspect) and _inspect_matches(root / "iter-02/inspect", image_id):
                    verify = _command(root, "verify")
                    actual = (root / "verify/stdout.log").read_bytes()
                    output_matches = actual == _expected(metadata["expected_output"])
                    verification = {"executed": True, "expected_output": metadata["expected_output"],
                                    "exit_code": verify["exit_code"], "timed_out": verify["timed_out"],
                                    "launch_error": verify["launch_error"], "output_matches": output_matches,
                                    "stdout_sha256": sha256(root / "verify/stdout.log"), "image_id": image_id}
                    status, reason = _step_status(verify), "PROGRAM_EXIT_OR_OUTPUT_FAILED"
                    if succeeded(verify) and output_matches:
                        status, reason = "SUCCEEDED", "BUILD_AND_EXACT_OUTPUT_VERIFIED"
    removal, inspect = _command(root, "cleanup"), _command(root, "cleanup-inspect")
    absence = _absent(inspect, root / "cleanup-inspect")
    removal_ok = succeeded(removal) or _absent(removal, root / "cleanup")
    cleanup = {"container_name": metadata["container_name"], "removal_confirmed": removal_ok, "absence_confirmed": absence}
    if status == "SUCCEEDED" and not (removal_ok and absence):
        status = "TIMED_OUT" if removal["timed_out"] or inspect["timed_out"] else "CLEANUP_UNCONFIRMED"
        reason = "CONTAINER_CLEANUP_UNCONFIRMED"
    return {"schema_version": 1, "trace_id": metadata["trace_id"], "source_kind": "REPLAY", "status": status,
            "passed": status == "SUCCEEDED", "reason": reason, "attempts": attempts, "verification": verification,
            "cleanup": cleanup, "image_id": image_id, "input_sha256": metadata["input_sha256"],
            "candidate_sha256": metadata["candidate_sha256"], "provenance_sha256": metadata["provenance_sha256"],
            "driver_sha256": metadata["driver_sha256"]}


def auto_build(fixture, candidate, output, expected_output="hello E3", timeout=600, verify_timeout=30, provenance=None):
    """Reproduce missing make, build one validated saved candidate, verify and clean."""
    _timeout(timeout)
    _timeout(verify_timeout)
    _expected(expected_output)
    fixture_arg, candidate_arg = Path(fixture), Path(candidate)
    if _linked(fixture_arg) or _linked(candidate_arg):
        raise ValueError("Linked fixture roots or candidate inputs are unsupported")
    fixture, candidate, output = fixture_arg.resolve(), candidate_arg.resolve(), Path(output).absolute()
    if output.exists() or _linked(output):
        raise FileExistsError(f"Output already exists: {output}")
    output = output.resolve()
    if output == fixture or fixture in output.parents:
        raise ValueError("Output must be outside the fixture")
    sources = {}
    for name in FIXTURE_FILES:
        path = fixture / name
        if not path.is_file() or _linked(path):
            raise ValueError(f"Missing or non-regular fixture input: {name}")
        sources[name] = path.read_bytes()
    _validate_broken(sources["Dockerfile.broken"])
    if not candidate.is_file():
        raise ValueError("Candidate is not a regular file")
    candidate_bytes = candidate.read_bytes()
    validate_candidate(candidate_bytes.decode("utf-8"))
    provenance_bytes = None
    if provenance is not None:
        if isinstance(provenance, dict):
            provenance_bytes = (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        else:
            path = Path(provenance)
            if _linked(path) or not path.is_file():
                raise ValueError("Provenance is not a regular file")
            provenance_bytes = path.read_bytes()
            # Preserve original bytes; validation only establishes it is JSON.
    if provenance_bytes is not None:
        _validate_provenance(provenance_bytes, hashlib.sha256(candidate_bytes).hexdigest())
    source_bytes = Path(__file__).read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    for name, content in sources.items():
        write_new(output / "project" / name, content)
    write_new(output / "inputs/candidate.Dockerfile", candidate_bytes)
    write_new(output / "inputs/autobuild.py", source_bytes)
    if provenance_bytes is not None:
        write_new(output / "inputs/provenance.json", provenance_bytes)
    write_new(output / "iter-01/Dockerfile", sources["Dockerfile.broken"])
    write_new(output / "iter-02/Dockerfile", candidate_bytes)
    write_new(output / "repair.diff", _repair_diff(sources["Dockerfile.broken"], candidate_bytes))
    run_id = uuid.uuid4().hex
    metadata = {"schema_version": 1, "trace_id": "e6-b-" + run_id, "source_kind": "REPLAY", "created_utc": utc_now(),
                "evidence_root": str(output), "path_style": "windows" if os.name == "nt" else "posix",
                "fixture_source": str(fixture), "candidate_source": str(candidate), "pinned_from": PINNED_FROM,
                "container_name": "e6-draft-" + run_id, "expected_output": expected_output,
                "build_timeout": timeout, "verify_timeout": verify_timeout, "cleanup_timeout": 30,
                "input_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in sources.items()},
                "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest() if provenance_bytes is not None else None,
                "driver_sha256": hashlib.sha256(source_bytes).hexdigest()}
    write_json(output / "run.json", metadata)

    def build(number):
        directory = output / f"iter-{number:02d}"
        return run_command(["docker", "build", "--no-cache", "--progress=plain", "--file", str(directory / "Dockerfile"),
                            "--iidfile", str(directory / "image-id.txt"), str(output / "project")],
                           output, directory / "build", timeout)

    try:
        baseline = build(1)
        if classify_baseline(baseline, command_log(output / "iter-01/build")) == "EXPECTED_MISSING_MAKE":
            fixed = build(2)
            if succeeded(fixed):
                image_id = _image_id(output / "iter-02/image-id.txt")
                if image_id:
                    inspect = run_command(["docker", "image", "inspect", image_id], output, output / "iter-02/inspect", verify_timeout)
                    if succeeded(inspect) and _inspect_matches(output / "iter-02/inspect", image_id):
                        run_command(["docker", "run", "--rm", "--name", metadata["container_name"], "--network", "none",
                                     "--cpus", "1", "--memory", "256m", "--pids-limit", "64", image_id],
                                    output, output / "verify", verify_timeout)
    finally:
        run_command(["docker", "container", "rm", "--force", metadata["container_name"]], output, output / "cleanup", 30)
        run_command(["docker", "container", "inspect", metadata["container_name"]], output, output / "cleanup-inspect", 30)
    result = _evaluate(output, metadata)
    write_json(output / "result.json", result)
    manifest = {path.relative_to(output).as_posix(): sha256(path) for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "SHA256SUMS.json", manifest)
    verify_evidence(output)
    return result


def _checked_command(root, relative, expected_argv, metadata, timeout):
    directory = root / relative
    record = read_json(directory / "command.json")
    if set(record) != COMMAND_KEYS:
        raise ValueError(f"Unexpected command metadata fields: {relative}")
    if record["argv"] != expected_argv or record["cwd"] != metadata["evidence_root"]:
        raise ValueError(f"Command binding mismatch: {relative}")
    if record["timeout_seconds"] != timeout:
        raise ValueError(f"Command timeout differs from declared limit: {relative}")
    _timeout(record["timeout_seconds"])
    if type(record["timed_out"]) is not bool:
        raise ValueError(f"Invalid timeout flag: {relative}")
    code, launch_error = record["exit_code"], record["launch_error"]
    if record["timed_out"]:
        valid = code is None and launch_error is None
    elif launch_error is not None:
        valid = code is None and isinstance(launch_error, str) and bool(launch_error)
    else:
        valid = type(code) is int
    if not valid:
        raise ValueError(f"Inconsistent command exit/timeout/launch metadata: {relative}")
    try:
        start, finish = (datetime.fromisoformat(record[name]) for name in ("started_utc", "finished_utc"))
        valid = start.utcoffset() is not None and finish.utcoffset() is not None and finish >= start
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError(f"Invalid command timestamps: {relative}")
    for stream in ("stdout", "stderr"):
        if record[f"{stream}_sha256"] != sha256(directory / f"{stream}.log"):
            raise ValueError(f"Original command {stream} hash mismatch: {relative}")
    return record


def _manifest(root):
    if _linked(root) or not root.is_dir():
        raise ValueError("Evidence root must be an ordinary directory")
    paths = list(root.rglob("*"))
    if any(_linked(path) for path in paths):
        raise ValueError("Linked evidence files or directories are unsupported")
    manifest = read_json(root / "SHA256SUMS.json")
    if not isinstance(manifest, dict):
        raise ValueError("Evidence manifest must be a JSON object")
    actual = {path.relative_to(root).as_posix() for path in paths if path.is_file() and path != root / "SHA256SUMS.json"}
    if actual != set(manifest):
        raise ValueError("Evidence file set differs from finalized manifest")
    for name, expected in manifest.items():
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name or "\\" in name or ":" in name or
                not isinstance(expected, str) or not HASH_RE.fullmatch(expected)):
            raise ValueError("Unsafe path or digest in evidence manifest")
        if sha256(root / name) != expected:
            raise ValueError(f"Evidence hash mismatch: {name}")
    return actual


def verify_evidence(directory):
    """Verify a portable saved bundle offline; never executes Docker or models.

    A valid failed run is verifiable evidence, but workflow_succeeded is false.
    Integrity is local consistency, not proof against complete evidence fabrication.
    """
    supplied = Path(directory)
    if _linked(supplied):
        raise ValueError("Linked evidence roots are unsupported")
    root = supplied.resolve()
    actual = _manifest(root)
    metadata = read_json(root / "run.json")
    if metadata.get("schema_version") != 1 or metadata.get("source_kind") != "REPLAY" or metadata.get("pinned_from") != PINNED_FROM:
        raise ValueError("Invalid evidence schema, replay source or pinned base")
    match = re.fullmatch(r"e6-b-([0-9a-f]{32})", metadata.get("trace_id", ""))
    if not match or metadata.get("container_name") != "e6-draft-" + match[1]:
        raise ValueError("Container name is not bound to the unique workflow trace")
    style = metadata.get("path_style")
    if style not in ("windows", "posix"):
        raise ValueError("Invalid command path style")
    path_class, path_module = (PureWindowsPath, ntpath) if style == "windows" else (PurePosixPath, posixpath)
    original_root = metadata.get("evidence_root")
    if not isinstance(original_root, str) or not path_class(original_root).is_absolute() or ".." in path_class(original_root).parts:
        raise ValueError("Invalid original command working directory")
    join = lambda *parts: path_module.join(original_root, *parts)
    _timeout(metadata["build_timeout"])
    _timeout(metadata["verify_timeout"])
    if metadata.get("cleanup_timeout") != 30:
        raise ValueError("Cleanup timeout must be the fixed 30 seconds")
    _expected(metadata["expected_output"])
    source_hashes = metadata.get("input_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(FIXTURE_FILES):
        raise ValueError("Snapshot must contain exactly the five fixed fixture inputs")
    if {path.name for path in (root / "project").iterdir()} != set(FIXTURE_FILES):
        raise ValueError("Unexpected files in immutable fixture snapshot")
    for name, expected in source_hashes.items():
        if sha256(root / "project" / name) != expected:
            raise ValueError(f"Fixture source hash mismatch: {name}")
    _validate_broken((root / "project/Dockerfile.broken").read_bytes())
    if (root / "iter-01/Dockerfile").read_bytes() != (root / "project/Dockerfile.broken").read_bytes():
        raise ValueError("Baseline Dockerfile differs from original broken fixture")
    candidate = (root / "inputs/candidate.Dockerfile").read_bytes()
    validate_candidate(candidate.decode("utf-8"))
    if sha256(root / "inputs/candidate.Dockerfile") != metadata.get("candidate_sha256") or (root / "iter-02/Dockerfile").read_bytes() != candidate:
        raise ValueError("Candidate source/build hash binding mismatch")
    if sha256(root / "inputs/autobuild.py") != metadata.get("driver_sha256"):
        raise ValueError("Driver source snapshot hash mismatch")
    provenance_present = metadata.get("provenance_sha256") is not None
    if provenance_present:
        if sha256(root / "inputs/provenance.json") != metadata["provenance_sha256"]:
            raise ValueError("Provenance bytes hash mismatch")
        _validate_provenance((root / "inputs/provenance.json").read_bytes(), metadata["candidate_sha256"])
    if (root / "repair.diff").read_bytes() != _repair_diff((root / "project/Dockerfile.broken").read_bytes(), candidate):
        raise ValueError("Repair diff does not describe the original and selected Dockerfiles")
    expected_files = {"run.json", "result.json", "repair.diff", "inputs/candidate.Dockerfile", "inputs/autobuild.py", "iter-01/Dockerfile", "iter-02/Dockerfile"}
    expected_files.update("project/" + name for name in FIXTURE_FILES)
    if provenance_present:
        expected_files.add("inputs/provenance.json")
    records = []

    def checked(relative, argv, timeout):
        expected_files.update(relative + "/" + name for name in ("command.json", "stdout.log", "stderr.log"))
        record = _checked_command(root, relative, argv, metadata, timeout)
        records.append(record)
        return record

    def build(number):
        directory = f"iter-{number:02d}"
        iid = root / directory / "image-id.txt"
        if iid.is_file():
            expected_files.add(directory + "/image-id.txt")
        return checked(directory + "/build", ["docker", "build", "--no-cache", "--progress=plain", "--file", join(directory, "Dockerfile"),
                                              "--iidfile", join(directory, "image-id.txt"), join("project")], metadata["build_timeout"])

    baseline = build(1)
    if classify_baseline(baseline, command_log(root / "iter-01/build")) == "EXPECTED_MISSING_MAKE":
        fixed = build(2)
        if succeeded(fixed):
            image_id = _image_id(root / "iter-02/image-id.txt")
            if image_id:
                inspect = checked("iter-02/inspect", ["docker", "image", "inspect", image_id], metadata["verify_timeout"])
                if succeeded(inspect) and _inspect_matches(root / "iter-02/inspect", image_id):
                    checked("verify", ["docker", "run", "--rm", "--name", metadata["container_name"], "--network", "none", "--cpus", "1",
                                       "--memory", "256m", "--pids-limit", "64", image_id], metadata["verify_timeout"])
    checked("cleanup", ["docker", "container", "rm", "--force", metadata["container_name"]], 30)
    checked("cleanup-inspect", ["docker", "container", "inspect", metadata["container_name"]], 30)
    if expected_files != actual:
        raise ValueError("Evidence file set does not match the executed workflow stages")
    for earlier, later in zip(records, records[1:]):
        if datetime.fromisoformat(earlier["finished_utc"]) > datetime.fromisoformat(later["started_utc"]):
            raise ValueError("Recorded command order differs from workflow order")
    computed = _evaluate(root, metadata)
    if read_json(root / "result.json") != computed:
        raise ValueError("Reported result is not supported by original command evidence")
    return {"passed": True, "verified": True, "workflow_succeeded": computed["passed"], "status": computed["status"],
            "trace_id": computed["trace_id"], "source_kind": "REPLAY", "files_checked": len(actual),
            "image_id": computed["image_id"], "candidate_sha256": computed["candidate_sha256"],
            "scope": "Offline saved evidence consistency; builds were not rerun"}
