"""Verify A's unchanged report before B builds or derives repair inputs."""

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from lab import input_fingerprints


class ReportError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise ReportError(code, message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_object(raw):
    value = json.loads(raw)
    require(isinstance(value, dict), 'INVALID_REPORT', 'Expected a JSON object')
    return value


def source_artifact(root, item, job_id):
    """Resolve a job URI without letting it leave the received result directory."""
    prefix = f'artifact://{job_id}/'
    uri = item['uri']
    require(isinstance(uri, str) and uri.startswith(prefix),
            'SOURCE_REPORT_MISMATCH', 'Source artifact belongs to another job')
    relative = PurePosixPath(uri[len(prefix):])
    require(not relative.is_absolute() and '..' not in relative.parts
            and '.git' not in relative.parts and '\\' not in str(relative)
            and ':' not in str(relative),
            'INVALID_ARTIFACT_PATH', 'Source artifact must stay inside its run')
    path = (root / relative.as_posix()).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file(),
            'INVALID_ARTIFACT_PATH', 'Source artifact is missing or outside its run')
    return path, relative


def archive_source(result_path, destination):
    """Copy only the adapter's evidence chain, preserving every source byte."""
    root = result_path.resolve().parent
    result_raw = result_path.read_bytes()
    result = json_object(result_raw)
    stages = [s for s in result['stages'] if s.get('name') == 'incremental-check']
    require(len(stages) == 1, 'SOURCE_REPORT_MISMATCH',
            'Expected exactly one source incremental-check stage')
    stage_path, relative = source_artifact(root, stages[0]['artifact'], result['job_id'])
    require(relative.as_posix() == 'incremental-check.json',
            'SOURCE_REPORT_MISMATCH', 'Unexpected incremental-check path')
    stage_raw = stage_path.read_bytes()
    stage = json_object(stage_raw)
    destination.mkdir(parents=True)
    (destination / 'result.json').write_bytes(result_raw)
    (destination / relative).write_bytes(stage_raw)
    for item in stage.get('artifacts', []):
        path, relative = source_artifact(root, item, result['job_id'])
        require(relative.as_posix() not in ('result.json', 'incremental-check.json'),
                'SOURCE_REPORT_MISMATCH', 'Source artifact shadows a report')
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(path.read_bytes())
    return root, stage


def preflight_fixed_report(request, out):
    """C2/C3 and A's provenance are checked before any checkout or DRAFT build."""
    raw = Path(request['fixed_report']).read_bytes()
    (out / 'fixed-md-input.json').write_bytes(raw)
    expected_hash = request.get('fixed_report_sha256')
    if expected_hash is not None:
        require(isinstance(expected_hash, str) and re.fullmatch('[0-9a-f]{64}', expected_hash),
                'INVALID_REQUEST', 'fixed_report_sha256 must be a lowercase SHA-256')
        require(digest(raw) == expected_hash, 'ARTIFACT_HASH_MISMATCH',
                'Fixed report content changed during transfer')
    envelope = json_object(raw)
    live = 'source_report' in envelope or 'source_result' in request
    if live:
        require(bool(request.get('source_result')) and expected_hash is not None,
                'SOURCE_REPORT_REQUIRED',
                'Live reports require source_result and fixed_report_sha256')
        require(re.fullmatch('[0-9a-f]{40}', request['target']) is not None,
                'INVALID_REQUEST', 'Live report target must be a complete lowercase Git SHA')
    require(envelope.get('schema_version') == 'e11e12-1',
            'SCHEMA_MISMATCH', 'Expected e11e12-1')
    require(envelope.get('kind') == 'fixed-md', 'ARTIFACT_TYPE_MISMATCH', 'Expected fixed-md')
    require(envelope.get('status') == 'SUCCEEDED', 'UPSTREAM_FAILED', 'A report did not succeed')
    # Legacy requests can still use Git revision names; resolve those at snapshot time.
    if re.fullmatch('[0-9a-f]{40}', request['target']):
        require(envelope.get('commit') == request['target']
                and envelope.get('data', {}).get('commit') == request['target'],
                'STALE_REPORT', 'Fixed report belongs to another commit')
    prepared = {'envelope': envelope, 'raw': raw, 'live': live,
                'data': copy.deepcopy(envelope['data'])}
    if live:
        archived = out / 'source-a'
        root, source_stage = archive_source(Path(request['source_result']), archived)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e13e14'))
        from handoff_a_to_b import make_handoff
        try:
            verified = make_handoff(archived / 'result.json', request['target'])
        except ValueError as exc:
            code = 'ARTIFACT_HASH_MISMATCH' if 'hash or size mismatch' in str(exc) else 'SOURCE_REPORT_MISMATCH'
            raise ReportError(code, str(exc)) from exc
        require(verified == envelope, 'SOURCE_REPORT_MISMATCH',
                'Fixed report differs from the verified A report')
        prepared.update(source_root=root, source_stage=source_stage)
    return prepared


def git_bytes(repo, *arguments):
    process = subprocess.run(['git', '-C', str(repo), *arguments],
                             capture_output=True, timeout=60)
    require(process.returncode == 0, 'SOURCE_COMMIT_MISMATCH',
            process.stderr.decode('utf-8', errors='replace').strip())
    return process.stdout


def bind_live_inputs(prepared, repo, target_sha, target, project_path, out):
    """Derive missing legacy fingerprints only after binding bytes to Git objects.

    The external report stays unchanged. B's derived data and receipt are separate
    artifacts, and lab.patch retains its existing strict fingerprint comparison.
    """
    envelope = prepared['envelope']
    require(envelope.get('commit') == target_sha
            and prepared['data'].get('commit') == target_sha,
            'STALE_REPORT', 'Fixed report data commit mismatch')
    if not prepared['live']:
        return prepared['data'], []
    prefix = PurePosixPath(project_path).as_posix()
    tree = f'{target_sha}:' + ('' if prefix == '.' else prefix)
    inputs = {}
    for entry in git_bytes(repo, 'ls-tree', '-z', tree).split(b'\0'):
        if not entry:
            continue
        metadata, filename = entry.split(b'\t', 1)
        mode, kind, _ = metadata.split()
        name = filename.decode('utf-8')
        if name != 'Makefile' and Path(name).suffix not in ('.c', '.h'):
            continue
        require(kind == b'blob' and mode in (b'100644', b'100755'),
                'SOURCE_COMMIT_MISMATCH', 'Profile input must be a regular Git file')
        object_path = name if prefix == '.' else prefix + '/' + name
        inputs[name] = digest(git_bytes(repo, 'cat-file', 'blob', f'{target_sha}:{object_path}'))
    require(bool(inputs) and inputs == input_fingerprints(target),
            'STALE_REPORT', 'B snapshot inputs differ from target Git blobs')
    require(not git_bytes(target, 'status', '--porcelain=v1', '--untracked-files=all', '--', '.'),
            'STALE_REPORT', 'B target project snapshot is not clean')
    current = prepared['data']
    derived = 'input_sha256' not in current
    evidence = envelope['source_report']
    checks = ['target Git blobs', 'B clean target snapshot bytes']
    if derived:
        stage = prepared['source_stage']
        job = envelope['source_report']['job_id']
        uri = f'artifact://{job}/target-full/findings.json'
        reports = [x for x in stage.get('artifacts', []) if x['uri'] == uri]
        require(len(reports) == 1, 'SOURCE_INPUTS_REQUIRED',
                'Reports missing fingerprints require hash-bound target-full input evidence')
        # This is the preserved copy already checked by the teacher adapter.
        full_raw = (out / 'source-a/target-full/findings.json').read_bytes()
        require(digest(full_raw) == reports[0]['sha256'], 'ARTIFACT_HASH_MISMATCH',
                'Preserved A target-full report changed')
        full = json_object(full_raw)
        observed = full.get('input_sha256', {})
        selected = {name: value for name, value in observed.items()
                    if name == 'Makefile' or Path(name).suffix in ('.c', '.h')}
        require(full.get('status') == 'SUCCEEDED' and selected == inputs,
                'SOURCE_INPUT_MISMATCH', 'A full-check inputs differ from target Git blobs')
        a_snapshot = prepared['source_root'] / 'target-project'
        if prefix != '.':
            a_snapshot = a_snapshot / prefix
        require(input_fingerprints(a_snapshot) == inputs, 'SOURCE_INPUT_MISMATCH',
                'A snapshot input set differs from target Git blobs')
        archived = out / 'source-a/target-project'
        if prefix != '.':
            archived = archived / prefix
        archived.mkdir(parents=True, exist_ok=True)
        for name, expected in inputs.items():
            path = a_snapshot / name
            require(path.resolve().is_relative_to(prepared['source_root']) and not path.is_symlink(),
                    'INVALID_ARTIFACT_PATH', 'A snapshot input is outside its run')
            raw = path.read_bytes()
            require(digest(raw) == expected, 'SOURCE_INPUT_MISMATCH',
                    f'A snapshot input differs from target Git blob: {name}')
            (archived / name).write_bytes(raw)
        evidence = reports[0]
        checks += ['A full-check input hashes', 'A target snapshot bytes']
    require(derived or current['input_sha256'] == inputs,
            'STALE_REPORT', 'A incremental fingerprints differ from target Git blobs')
    current['input_sha256'] = inputs
    receipt = {
        'schema_version': 'e13-live-input-binding-1',
        'commit': target_sha, 'project_path': prefix,
        'source_report': envelope['source_report'],
        'fixed_report_sha256': digest(prepared['raw']),
        'input_evidence': evidence, 'input_sha256': inputs,
        'derived_missing_fingerprints': derived,
        'checks': checks,
    }
    receipt_path = out / 'fixed-md-input-binding.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return current, [receipt_path]
