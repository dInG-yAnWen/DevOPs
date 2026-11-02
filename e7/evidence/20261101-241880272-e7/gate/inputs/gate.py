"""E7 real-CLI acceptance cases and portable, offline evidence verification.

The gate replays a saved candidate; it does not generate a candidate or call a
model. Hashes and independent oracles establish local evidence consistency,
not a signed execution attestation.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
import sys
import uuid

from . import autobuild as e6

CASES = ("success", "wrong-output", "invalid-candidate", "build-failed",
         "runtime-timeout", "runtime-nonzero")
EXPECTED = "hello E3"
WRONG_EXPECTED = "E7 intentionally incorrect expected output"
BUILD_MARKER = "E7_INJECTED_BUILD_FAILURE"
TIMEOUT_MARKER = b"E7_TIMEOUT_STARTED\n"
RUNTIME_TIMEOUT_SECONDS = 5
TIMEOUT_SOURCE = (b'#include <stdio.h>\n#include <unistd.h>\n'
                  b'int main(void) { puts("E7_TIMEOUT_STARTED"); fflush(stdout); '
                  b'sleep(10); puts("hello E3"); return 0; }\n')
NONZERO_SOURCE = b'#include <stdio.h>\nint main(void) { puts("hello E3"); return 23; }\n'
CSV_FIELDS = ("case", "passed", "expected_workflow_status", "workflow_exit_code",
              "e6_verified", "observed_workflow_status", "reason")


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _selection(cases):
    selected = list(CASES if cases is None else cases)
    if not selected or any(name not in CASES for name in selected) or len(set(selected)) != len(selected):
        raise ValueError("Cases must be a nonempty, unique subset of the six E7 cases")
    return [name for name in CASES if name in selected]


def _runtime_timeout(metadata):
    # Original E7 bundles omitted this field and used one second. Preserve
    # their original argv, fault injection and oracle when verifying them.
    value = metadata.get("runtime_timeout_seconds", 1)
    if type(value) is not int or value not in (1, 5):
        raise ValueError("Runtime timeout must be the recorded E7 budget of 1 or 5 seconds")
    return value


def _mutation(name, originals, candidate, runtime_timeout_seconds=RUNTIME_TIMEOUT_SECONDS):
    sources, modified_candidate = dict(originals), candidate
    if name == "build-failed":
        sources["main.c"] = b"#error E7_INJECTED_BUILD_FAILURE\n" + sources["main.c"]
    elif name == "runtime-timeout":
        sources["main.c"] = TIMEOUT_SOURCE
    elif name == "runtime-nonzero":
        sources["main.c"] = NONZERO_SOURCE
    elif name == "invalid-candidate":
        modified_candidate, count = re.subn(rb"(?im)^[ \t]*CMD[ \t]+[^\r\n]*",
                                            b'CMD ["echo", "hello E3"]', candidate)
        if count != 1 or modified_candidate == candidate:
            raise ValueError("Candidate must have one CMD line for the documented CMD fault injection")
        try:
            e6.validate_candidate(modified_candidate.decode("utf-8"))
        except ValueError:
            pass
        else:
            raise ValueError("CMD fault injection did not invalidate the candidate")
    before = {"fixture/" + key: value for key, value in originals.items()}
    before["candidate.Dockerfile"] = candidate
    after = {"fixture/" + key: value for key, value in sources.items()}
    after["candidate.Dockerfile"] = modified_candidate
    changes, diff = [], ""
    for path in sorted(before):
        if before[path] != after[path]:
            changes.append({"path": path, "before_sha256": _digest(before[path]),
                            "after_sha256": _digest(after[path])})
            diff += "".join(difflib.unified_diff(before[path].decode("utf-8").splitlines(keepends=True),
                                               after[path].decode("utf-8").splitlines(keepends=True),
                                               fromfile="original/" + path, tofile=name + "/" + path))
    injection = {"schema_version": 1, "case": name, "changes": changes,
                 "expected_output": WRONG_EXPECTED if name == "wrong-output" else EXPECTED,
                 "verify_timeout": runtime_timeout_seconds if name == "runtime-timeout" else 30,
                 "source_kind": "REPLAY_WITH_EXPLICIT_FAULT_INJECTION", "model_call_in_e7": False}
    return sources, modified_candidate, injection, diff.encode("utf-8")


def _paths(metadata):
    style = metadata.get("path_style")
    if style not in ("windows", "posix"):
        raise ValueError("Invalid E7 command path style")
    cls, module = (PureWindowsPath, ntpath) if style == "windows" else (PurePosixPath, posixpath)
    for key in ("evidence_root", "command_cwd", "python_executable"):
        value = metadata.get(key)
        if not isinstance(value, str) or not cls(value).is_absolute() or ".." in cls(value).parts:
            raise ValueError("Invalid E7 original absolute path: " + key)
    if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", cls(metadata["python_executable"]).name, re.I):
        raise ValueError("E7 must invoke the Python executable")
    return lambda *parts: module.join(metadata["evidence_root"], *parts)


def _argv(metadata, name):
    join = _paths(metadata)
    result = [metadata["python_executable"], "-m", "draft", "auto-build", "--fixture", join("cases", name, "fixture"),
              "--candidate", join("cases", name, "candidate.Dockerfile"), "--out", join("cases", name, "run"),
              "--expected-output", WRONG_EXPECTED if name == "wrong-output" else EXPECTED,
              "--timeout", str(metadata["build_timeout"]), "--verify-timeout", str(_runtime_timeout(metadata)) if name == "runtime-timeout" else "30"]
    if metadata["provenance_sha256"] is not None:
        result += ["--provenance", join("inputs", "provenance.json")]
    return result


def _command(root, relative, argv, cwd, timeout):
    return e6._checked_command(root, relative, argv, {"evidence_root": cwd}, timeout)


def _safe_container(run, expected_root):
    try:
        value = e6.read_json(run / "run.json")
        if not isinstance(value, dict):
            return None
        match = re.fullmatch(r"e6-b-([0-9a-f]{32})", value.get("trace_id", ""))
        if (not match or value.get("container_name") != "e6-draft-" + match[1]
                or value.get("evidence_root") != expected_root):
            return None
        return value["container_name"]
    except (ValueError, OSError, TypeError):
        return None


def _emergency_cleanup(case, metadata, name):
    """An interrupted child may leave its container; touch only its bound name."""
    join = _paths(metadata)
    container = _safe_container(case / "run", join("cases", name, "run"))
    e6.write_json(case / "emergency-cleanup.json", {"performed": container is not None, "container_name": container})
    if container is not None:
        e6.run_command(["docker", "container", "rm", "--force", container], case, case / "emergency-cleanup", 30)
        e6.run_command(["docker", "container", "inspect", container], case, case / "emergency-cleanup-inspect", 30)


def _needs_emergency_cleanup(case, metadata, name, record):
    if record["timed_out"]:
        return True
    join = _paths(metadata)
    if _safe_container(case / "run", join("cases", name, "run")) is None:
        return False
    try:
        e6.verify_evidence(case / "run")
        cleanup = e6.read_json(case / "run/result.json")["cleanup"]
        return not (cleanup["removal_confirmed"] and cleanup["absence_confirmed"])
    except (ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError):
        return True


def _oracle(root, metadata, name, record):
    case, run = root / "cases" / name, root / "cases" / name / "run"
    expected_status = {"success": "SUCCEEDED", "wrong-output": "FAILED", "invalid-candidate": "PREFLIGHT_REJECTED",
                       "build-failed": "FAILED", "runtime-timeout": "TIMED_OUT", "runtime-nonzero": "FAILED"}[name]
    row = {"case": name, "passed": False, "expected_workflow_status": expected_status,
           "workflow_exit_code": record["exit_code"], "e6_verified": False,
           "observed_workflow_status": "UNVERIFIED", "reason": "WORKFLOW_COMMAND_FAILED"}
    if record["timed_out"] or record["launch_error"] is not None:
        row["reason"] = "OUTER_TIMEOUT" if record["timed_out"] else "WORKFLOW_LAUNCH_FAILED"
        return row
    if name == "invalid-candidate":
        try:
            value = json.loads((case / "workflow/stdout.log").read_text(encoding="utf-8"), object_pairs_hook=e6._unique_object)
            valid = (record["exit_code"] == 1 and not run.exists() and value.get("status") == "FAILED"
                     and isinstance(value.get("error"), str) and "CMD" in value["error"])
        except (ValueError, OSError, AttributeError, UnicodeError):
            valid = False
        row.update(passed=valid, observed_workflow_status="PREFLIGHT_REJECTED" if valid else "UNVERIFIED",
                   reason="INVALID_CMD_REJECTED_BEFORE_OUTPUT_AND_DOCKER" if valid else "PREFLIGHT_REJECTION_NOT_PROVEN")
        return row
    try:
        checked = e6.verify_evidence(run)
    except (ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError):
        row["reason"] = "E6_EVIDENCE_NOT_VERIFIABLE"
        return row
    result, run_metadata = e6.read_json(run / "result.json"), e6.read_json(run / "run.json")
    join = _paths(metadata)
    source = {key: e6.sha256(case / "fixture" / key) for key in e6.FIXTURE_FILES}
    bound = (run_metadata["evidence_root"] == join("cases", name, "run")
             and run_metadata["fixture_source"] == join("cases", name, "fixture")
             and run_metadata["candidate_source"] == join("cases", name, "candidate.Dockerfile")
             and run_metadata["input_sha256"] == source
             and run_metadata["candidate_sha256"] == e6.sha256(case / "candidate.Dockerfile")
             and run_metadata["provenance_sha256"] == metadata["provenance_sha256"]
             and run_metadata["driver_sha256"] == metadata["autobuild_sha256"]
             and run_metadata["build_timeout"] == metadata["build_timeout"]
             and run_metadata["verify_timeout"] == (_runtime_timeout(metadata) if name == "runtime-timeout" else 30)
             and run_metadata["expected_output"] == (WRONG_EXPECTED if name == "wrong-output" else EXPECTED))
    if not bound:
        raise ValueError("E6 replay input/command binding differs from E7: " + name)
    row.update(e6_verified=checked["verified"], observed_workflow_status=result["status"])
    if len(result["attempts"]) != 2 or result["attempts"][0]["failure_class"] != "EXPECTED_MISSING_MAKE":
        row["reason"] = "BASELINE_MISSING_MAKE_NOT_REPRODUCED"
        return row
    try:
        reported = json.loads((case / "workflow/stdout.log").read_text(encoding="utf-8"), object_pairs_hook=e6._unique_object)
    except (ValueError, UnicodeError):
        reported = None
    base_ok = (reported == result and record["exit_code"] == (0 if name == "success" else 1)
               and len(result["attempts"]) == 2 and result["attempts"][0]["failure_class"] == "EXPECTED_MISSING_MAKE"
               and result["cleanup"]["removal_confirmed"] and result["cleanup"]["absence_confirmed"])
    if name == "build-failed":
        build = e6.read_json(run / "iter-02/build/command.json")
        valid = (base_ok and result["status"] == "FAILED" and result["reason"] == "CANDIDATE_BUILD_FAILED"
                 and build["exit_code"] == 1 and not build["timed_out"] and build["launch_error"] is None
                 and BUILD_MARKER in e6.command_log(run / "iter-02/build")
                 and not result["verification"]["executed"] and not (run / "verify").exists())
    else:
        verify_path = run / "verify/command.json"
        verify = e6.read_json(verify_path) if verify_path.is_file() else None
        actual = (run / "verify/stdout.log").read_bytes() if verify else None
        build = e6.read_json(run / "iter-02/build/command.json")
        base_ok = base_ok and e6.succeeded(build) and verify is not None and result["verification"]["executed"]
        if name == "success":
            valid = base_ok and result["status"] == "SUCCEEDED" and e6.succeeded(verify) and actual == e6._expected(EXPECTED)
        elif name == "wrong-output":
            valid = (base_ok and result["status"] == "FAILED" and e6.succeeded(verify)
                     and actual == e6._expected(EXPECTED) and result["verification"]["output_matches"] is False)
        elif name == "runtime-timeout":
            valid = (base_ok and result["status"] == "TIMED_OUT" and verify["timed_out"] is True
                     and verify["exit_code"] is None and verify["launch_error"] is None
                     and actual == TIMEOUT_MARKER and result["verification"]["output_matches"] is False)
        else:
            valid = (base_ok and result["status"] == "FAILED" and verify["exit_code"] == 23
                     and not verify["timed_out"] and verify["launch_error"] is None
                     and actual == e6._expected(EXPECTED) and result["verification"]["output_matches"] is True)
    row.update(passed=bool(valid), reason="EXPECTED_BEHAVIOR_VERIFIED" if valid else "EXPECTED_BEHAVIOR_NOT_PROVEN")
    return row


def _csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _result(metadata, rows):
    complete = metadata["selected_cases"] == list(CASES)
    passed = complete and all(row["passed"] for row in rows)
    return {"schema_version": 1, "trace_id": metadata["trace_id"], "source_kind": "REPLAY",
            "model_call_in_e7": False, "passed": passed, "complete": complete,
            "status": "PASS" if passed else "FAILED" if complete else "INCOMPLETE",
            "expected_cases": list(CASES), "selected_cases": metadata["selected_cases"], "cases": rows}


def _manifest(root):
    manifest = {path.relative_to(root).as_posix(): e6.sha256(path) for path in sorted(root.rglob("*"))
                if path.is_file() and path != root / "SHA256SUMS.json"}
    e6.write_json(root / "SHA256SUMS.json", manifest)


def run_gate(fixture, candidate, output, provenance=None, build_timeout=600, cases=None):
    """Run fresh real ``python -m draft auto-build`` processes, then self-verify."""
    if type(build_timeout) is not int or build_timeout <= 0:
        raise ValueError("Build timeout must be a positive integer")
    selected = _selection(cases)
    fixture_arg, candidate_arg, supplied = Path(fixture), Path(candidate), Path(output)
    if e6._linked(fixture_arg) or e6._linked(candidate_arg) or e6._linked(supplied):
        raise ValueError("Linked gate input or output paths are unsupported")
    fixture, candidate, root = fixture_arg.resolve(), candidate_arg.resolve(), supplied.absolute()
    if root.exists():
        raise FileExistsError("Gate output already exists: " + str(root))
    root = root.resolve()
    if root == fixture or fixture in root.parents:
        raise ValueError("Gate output must be outside the fixture")
    sources = {}
    for name in e6.FIXTURE_FILES:
        path = fixture / name
        if not path.is_file() or e6._linked(path):
            raise ValueError("Missing or linked fixture input: " + name)
        sources[name] = path.read_bytes()
    e6._validate_broken(sources["Dockerfile.broken"])
    if not candidate.is_file():
        raise ValueError("Candidate must be an ordinary file")
    candidate_bytes = candidate.read_bytes()
    e6.validate_candidate(candidate_bytes.decode("utf-8"))
    original_provenance = None
    if provenance is not None:
        if isinstance(provenance, dict):
            original_provenance = (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        else:
            path = Path(provenance)
            if not path.is_file() or e6._linked(path):
                raise ValueError("Provenance must be an ordinary file")
            original_provenance = path.read_bytes()
        e6._validate_provenance(original_provenance, _digest(candidate_bytes))
    # Construct all mutations before creating output; malformed inputs do not
    # leave an ambiguous bundle or launch any command.
    mutations = {name: _mutation(name, sources, candidate_bytes, RUNTIME_TIMEOUT_SECONDS) for name in selected}
    root.mkdir(parents=True, exist_ok=False)
    for name, value in sources.items():
        e6.write_new(root / "fixture" / name, value)
    e6.write_new(root / "inputs/candidate.Dockerfile", candidate_bytes)
    e6.write_new(root / "inputs/gate.py", Path(__file__).read_bytes())
    e6.write_new(root / "inputs/autobuild.py", Path(e6.__file__).read_bytes())
    if original_provenance is not None:
        e6.write_new(root / "inputs/provenance.json", original_provenance)
    metadata = {"schema_version": 1, "trace_id": "e7-g-" + uuid.uuid4().hex, "source_kind": "REPLAY",
                "model_call_in_e7": False, "created_utc": e6.utc_now(), "evidence_root": str(root),
                "command_cwd": str(Path(__file__).resolve().parents[1]), "python_executable": str(Path(sys.executable).resolve()),
                "path_style": "windows" if os.name == "nt" else "posix", "build_timeout": build_timeout,
                "runtime_timeout_seconds": RUNTIME_TIMEOUT_SECONDS,
                "outer_timeout": 2 * build_timeout + 180, "expected_cases": list(CASES), "selected_cases": selected,
                "input_sha256": {name: _digest(value) for name, value in sources.items()},
                "candidate_sha256": _digest(candidate_bytes),
                "provenance_sha256": _digest(original_provenance) if original_provenance is not None else None,
                "gate_sha256": e6.sha256(root / "inputs/gate.py"), "autobuild_sha256": e6.sha256(root / "inputs/autobuild.py")}
    e6.write_json(root / "run.json", metadata)
    rows = []
    for name in selected:
        case = root / "cases" / name
        project, candidate_bytes_case, injection, diff = mutations[name]
        for path, value in project.items():
            e6.write_new(case / "fixture" / path, value)
        e6.write_new(case / "candidate.Dockerfile", candidate_bytes_case)
        e6.write_json(case / "fault-injection.json", injection)
        e6.write_new(case / "fault-injection.diff", diff)
        record = e6.run_command(_argv(metadata, name), metadata["command_cwd"], case / "workflow", metadata["outer_timeout"])
        if _needs_emergency_cleanup(case, metadata, name, record):
            _emergency_cleanup(case, metadata, name)
        rows.append(_oracle(root, metadata, name, record))
    result = _result(metadata, rows)
    e6.write_json(root / "gate-result.json", result)
    e6.write_new(root / "results.csv", _csv(rows))
    _manifest(root)
    verify_gate(root)
    return result


def _possible_e6_files(provenance):
    files = {"SHA256SUMS.json", "run.json", "result.json", "repair.diff", "inputs/candidate.Dockerfile", "inputs/autobuild.py",
             "iter-01/Dockerfile", "iter-02/Dockerfile", "iter-01/image-id.txt", "iter-02/image-id.txt"}
    files.update("project/" + name for name in e6.FIXTURE_FILES)
    if provenance:
        files.add("inputs/provenance.json")
    for stage in ("iter-01/build", "iter-02/build", "iter-02/inspect", "verify", "cleanup", "cleanup-inspect"):
        files.update(stage + "/" + name for name in ("command.json", "stdout.log", "stderr.log"))
    return files


def verify_gate(directory):
    """Recompute file bindings, raw command oracles and CSV/JSON without Docker."""
    supplied = Path(directory)
    if e6._linked(supplied):
        raise ValueError("Linked gate roots are unsupported")
    root = supplied.resolve()
    actual = e6._manifest(root)
    metadata = e6.read_json(root / "run.json")
    if (not isinstance(metadata, dict) or metadata.get("schema_version") != 1 or metadata.get("source_kind") != "REPLAY"
            or metadata.get("model_call_in_e7") is not False
            or not re.fullmatch(r"e7-g-[0-9a-f]{32}", metadata.get("trace_id", ""))
            or metadata.get("expected_cases") != list(CASES)
            or metadata.get("selected_cases") != _selection(metadata.get("selected_cases", []))):
        raise ValueError("Invalid E7 replay metadata or case selection")
    if type(metadata.get("build_timeout")) is not int or metadata["build_timeout"] <= 0:
        raise ValueError("Invalid E7 build timeout")
    if metadata.get("outer_timeout") != 2 * metadata["build_timeout"] + 180:
        raise ValueError("Outer timeout differs from the declared two-build budget")
    runtime_timeout_seconds = _runtime_timeout(metadata)
    join = _paths(metadata)
    sources = {name: (root / "fixture" / name).read_bytes() for name in e6.FIXTURE_FILES}
    if metadata.get("input_sha256") != {name: _digest(value) for name, value in sources.items()}:
        raise ValueError("Original fixture hash binding mismatch")
    e6._validate_broken(sources["Dockerfile.broken"])
    candidate = (root / "inputs/candidate.Dockerfile").read_bytes()
    e6.validate_candidate(candidate.decode("utf-8"))
    if metadata.get("candidate_sha256") != _digest(candidate):
        raise ValueError("Original candidate hash binding mismatch")
    for name in ("gate", "autobuild"):
        if e6.sha256(root / "inputs" / (name + ".py")) != metadata.get(name + "_sha256"):
            raise ValueError("Driver source snapshot hash mismatch: " + name)
    expected_files = {"run.json", "gate-result.json", "results.csv", "inputs/gate.py", "inputs/autobuild.py", "inputs/candidate.Dockerfile"}
    expected_files.update("fixture/" + name for name in e6.FIXTURE_FILES)
    if metadata.get("provenance_sha256") is not None:
        path = root / "inputs/provenance.json"
        if e6.sha256(path) != metadata["provenance_sha256"]:
            raise ValueError("Original E6 provenance hash binding mismatch")
        e6._validate_provenance(path.read_bytes(), metadata["candidate_sha256"])
        expected_files.add("inputs/provenance.json")
    case_directory = root / "cases"
    if {p.name for p in case_directory.iterdir()} != set(metadata["selected_cases"]):
        raise ValueError("Missing or extra gate case directory")
    rows, records = [], []
    for name in metadata["selected_cases"]:
        prefix, case = "cases/" + name + "/", root / "cases" / name
        modified, modified_candidate, injection, diff = _mutation(name, sources, candidate, runtime_timeout_seconds)
        for path, content in modified.items():
            if (case / "fixture" / path).read_bytes() != content:
                raise ValueError("Undeclared fixture mutation: " + name + "/" + path)
            expected_files.add(prefix + "fixture/" + path)
        if (case / "candidate.Dockerfile").read_bytes() != modified_candidate:
            raise ValueError("Undeclared candidate mutation: " + name)
        if e6.read_json(case / "fault-injection.json") != injection or (case / "fault-injection.diff").read_bytes() != diff:
            raise ValueError("Fault injection record/diff mismatch: " + name)
        expected_files.update(prefix + part for part in ("candidate.Dockerfile", "fault-injection.json", "fault-injection.diff",
                                                       "workflow/command.json", "workflow/stdout.log", "workflow/stderr.log"))
        record = _command(root, prefix + "workflow", _argv(metadata, name), metadata["command_cwd"], metadata["outer_timeout"])
        records.append(record)
        if (case / "run/SHA256SUMS.json").is_file():
            e6.verify_evidence(case / "run")
        row = _oracle(root, metadata, name, record)
        rows.append(row)
        nested = {path[len(prefix + "run/"):] for path in actual if path.startswith(prefix + "run/")}
        if row["e6_verified"]:
            # E6's verifier has independently checked the exact nested file set.
            expected_files.update(prefix + "run/" + path for path in nested)
        elif nested:
            if name == "invalid-candidate" or not nested.issubset(_possible_e6_files(metadata["provenance_sha256"] is not None)):
                raise ValueError("Unexpected partial E6 evidence files: " + name)
            expected_files.update(prefix + "run/" + path for path in nested)
        if _needs_emergency_cleanup(case, metadata, name, record):
            container = _safe_container(case / "run", join("cases", name, "run"))
            if e6.read_json(case / "emergency-cleanup.json") != {"performed": container is not None, "container_name": container}:
                raise ValueError("Emergency cleanup scope differs from interrupted child")
            expected_files.add(prefix + "emergency-cleanup.json")
            if container is not None:
                for stage, argv in (("emergency-cleanup", ["docker", "container", "rm", "--force", container]),
                                    ("emergency-cleanup-inspect", ["docker", "container", "inspect", container])):
                    _command(root, prefix + stage, argv, join("cases", name), 30)
                    expected_files.update(prefix + stage + "/" + part for part in ("command.json", "stdout.log", "stderr.log"))
    for earlier, later in zip(records, records[1:]):
        if e6.datetime.fromisoformat(earlier["finished_utc"]) > e6.datetime.fromisoformat(later["started_utc"]):
            raise ValueError("E7 workflow command order differs from case order")
    if actual != expected_files:
        raise ValueError("Gate file set differs from the exact declared workflow")
    computed = _result(metadata, rows)
    if e6.read_json(root / "gate-result.json") != computed or (root / "results.csv").read_bytes() != _csv(rows):
        raise ValueError("Gate JSON/CSV is not supported by original evidence")
    return {"verified": True, "passed": computed["passed"], "workflow_succeeded": computed["passed"],
            "status": computed["status"], "complete": computed["complete"], "cases": rows,
            "files_checked": len(actual), "trace_id": metadata["trace_id"], "source_kind": "REPLAY",
            "scope": "Offline saved evidence consistency; no Docker or model commands executed"}
