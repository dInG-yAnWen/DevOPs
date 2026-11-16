"""B14's side of the E12 handoff using the agreed 1.0 MD report."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from lab import input_fingerprints, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'validator'))
from validate import schema_check, validate_report_payload


class HandoffError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def check(condition, code, message):
    if not condition:
        raise HandoffError(code, message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def read_checked(path, expected):
    raw = path.read_bytes()
    check(sha256(raw) == expected, 'ARTIFACT_HASH_MISMATCH', f'{path.name}: SHA-256 mismatch')
    return raw


def contained(root, filename):
    relative = Path(filename)
    path = (root / relative).resolve()
    check(not relative.is_absolute() and '..' not in relative.parts
          and path.is_relative_to(root) and '.git' not in path.relative_to(root).parts,
          'INVALID_ARTIFACT_PATH', f'Path must stay inside the handoff directory: {filename}')
    return path


def write_json(path, obj):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return path


def archive(root, reference, destination):
    raw = read_checked(contained(root, reference['path']), reference['sha256'])
    check(bool(raw), 'INVALID_ARTIFACT', f'{reference["path"]}: empty evidence')
    destination.write_bytes(raw)
    return destination


def archive_artifact(root, reference, destination, kind, context):
    artifact = reference['artifact']
    schema_check(artifact, 'Artifact')
    check(artifact['type'] == kind, 'ARTIFACT_TYPE_MISMATCH', f'Expected {kind}')
    for field, value in context.items():
        check(artifact[field] == value, 'ARTIFACT_BINDING_MISMATCH', f'{kind}: {field} mismatch')
    return archive(root, {**reference, 'sha256': artifact['sha256']}, destination)


def load_md_report(raw, repository, configuration_id, producer, makefiles):
    report = json.loads(raw)
    check(isinstance(report, dict), 'INVALID_REPORT', 'Expected a 1.0 report object')
    actual = report.get('repository')
    if isinstance(actual, dict):
        check(actual.get('commit') == repository['commit'], 'STALE_REPORT', 'MD report belongs to another commit')
    validate_report_payload(report, repository, configuration_id, md_only=True)
    check(report['producer_job_id'] == producer, 'ARTIFACT_BINDING_MISMATCH', 'MD report producer mismatch')
    for finding in report['findings']:
        check(finding['location']['path'] in makefiles,
              'ARTIFACT_BINDING_MISMATCH', 'Finding location is outside the repair Makefile list')
        check(finding['evidence']['kind'] in ('DYNAMIC_TRACE', 'STATIC_INFERENCE'),
              'FIXTURE_REPORT', 'E12 handoff requires findings from the actual detector')
    return report


def git(checkout, *args):
    result = subprocess.run(
        ['git', '-c', 'core.autocrlf=false', '-C', str(checkout), *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
    )
    check(result.returncode == 0, 'GIT_COMMAND_FAILED', result.stderr.strip())
    return result.stdout.strip()


def local_path(filename, workdir):
    path = PurePosixPath(filename)
    if workdir != '.' and path.is_relative_to(workdir):
        path = path.relative_to(workdir)
    return path.as_posix()


def candidate(repo, base, repair, report, destination):
    repository, build = repair['repository'], repair['build']
    commit = repository['commit']
    workdir = build['working_directory'].rstrip('/')
    makefile = 'Makefile' if workdir == '.' else f'{workdir}/Makefile'
    check(set(repair['makefiles']) in ({makefile}, {'Makefile'}),
          'UNSUPPORTED_PROJECT', 'Expected one project Makefile')
    with tempfile.TemporaryDirectory(prefix='pair14-') as scratch:
        checkout = Path(scratch) / 'checkout'
        git(repo, 'rev-parse', '--verify', f'{base}^{{commit}}')
        git(repo, 'clone', '--no-checkout', '--no-hardlinks', str(repo), str(checkout))
        git(checkout, 'checkout', '--detach', commit)
        project = contained(checkout, workdir)
        source = contained(checkout, makefile)
        check(source.is_file() and not (project / 'Makefile').is_symlink(),
              'UNSUPPORTED_PROJECT', 'Expected a regular Makefile')
        lines = source.read_text(encoding='utf-8').splitlines()
        findings = []
        for finding in report['findings']:
            check(finding['location']['line'] <= len(lines), 'INVALID_FINDING', 'Finding line is outside Makefile')
            target = local_path(finding['target'], workdir)
            dependency = local_path(finding['dependency'], workdir)
            check(contained(project, dependency).is_file(), 'INVALID_FINDING',
                  'Finding dependency is missing from the project')
            findings.append({**finding, 'target': target, 'dependency': dependency})
        internal = {**report, 'commit': commit, 'findings': findings,
                    'input_sha256': input_fingerprints(project)}
        diff, edits = patch(project, internal)
        check(bool(diff), 'NO_MISSING_DEPENDENCY', 'MDFixer produced no changes')
        # Convert E8-E10's project-relative headers to paths relative to the Git checkout.
        _, _, body = diff.split('\n', 2)
        raw = (f'diff --git a/{makefile} b/{makefile}\n'
               f'--- a/{makefile}\n+++ b/{makefile}\n{body}').encode('utf-8')
        pending = Path(scratch) / 'candidate.patch'
        pending.write_bytes(raw)
        git(checkout, 'apply', '--index', '--check', str(pending))
        destination.write_bytes(raw)
    return edits


def check_stage(data, commit, trace_id, environment, statuses=('SUCCEEDED',)):
    check(isinstance(data, dict) and isinstance(data.get('job_id'), str) and bool(data['job_id']),
          'ARTIFACT_BINDING_MISMATCH', 'Missing upstream Job ID')
    check(data.get('status') in statuses, 'INVALID_STAGE_STATUS', f'{data["job_id"]}: unexpected status')
    expected = {'commit': commit, 'trace_id': trace_id,
                'configuration_id': environment['configuration_id'], 'image_ref': environment['image_ref']}
    for field, value in expected.items():
        check(data.get(field) == value, 'ARTIFACT_BINDING_MISMATCH', f'{field} mismatch in {data["job_id"]}')


def archive_graph(root, reference, destination, kind, repository, data):
    path = archive(root, reference, destination)
    graph = json.loads(path.read_bytes())
    expected = {'repository': repository, 'kind': kind, 'producer_job_id': data['job_id'],
                'configuration_id': data['configuration_id']}
    check(isinstance(graph, dict) and all(graph.get(key) == value for key, value in expected.items()),
          'ARTIFACT_BINDING_MISMATCH', f'{kind} graph belongs to another job or configuration')
    check(graph.get('source') in ('DYNAMIC_TRACE', 'STATIC_INFERENCE', 'MAKE_DATABASE'),
          'INVALID_ARTIFACT', f'{kind} graph must retain the actual detector source')
    check(isinstance(graph.get('edges'), list), 'INVALID_ARTIFACT', f'{kind} graph lacks edges')
    return path


def run_pair14(request, out, result, stage):
    handoff = Path(request['handoff']).resolve()
    root = handoff.parent
    source = read_checked(handoff, request['handoff_sha256'])
    spec = json.loads(source)
    repair_request = spec['repair_request']
    schema_check(repair_request, 'Request')
    check(repair_request['job_type'] == 'REPAIR', 'INVALID_HANDOFF', 'Expected a 1.0 REPAIR request')
    check('max_iterations' not in repair_request['execution'], 'INVALID_HANDOFF', 'max_iterations is DRAFT-only')
    repair = repair_request['input']
    repo, cfg = repair['repository'], repair['environment']['configuration_id']
    base, target, trace_id = request['base'], request['target'], repair_request['trace_id']
    check(isinstance(base, str) and re.fullmatch('[0-9a-f]{40}', base) and base != target,
          'INVALID_HANDOFF', 'Expected a distinct full baseline SHA')
    check(repo['commit'] == target, 'STALE_REPORT', 'REPAIR target differs from the E12 target')
    result.update(base_commit=base, target_commit=target, trace_id=trace_id)
    (out / 'handoff.json').write_bytes(source)

    env = repair['environment']
    common = {'repository_url': repo['url'], 'commit': target, 'configuration_id': cfg}
    draft = spec['draft']
    check_stage(draft, target, trace_id, env)
    check(draft['job_id'] == env['producer_job_id'], 'ARTIFACT_BINDING_MISMATCH', 'DRAFT Job ID mismatch')
    check(all(type(draft[key]) is int and draft[key] == 0 for key in ('build_exit_code', 'verify_exit_code')),
          'DRAFT_FAILED', 'DRAFT build and verification must have exit code 0')
    draft_context = {**common, 'producer_job_id': draft['job_id']}
    check(draft['dockerfile']['artifact']['uri'] == env['dockerfile_uri'],
          'ARTIFACT_BINDING_MISMATCH', 'Dockerfile URI mismatch')
    draft_dir = out / 'draft-evidence'
    draft_dir.mkdir()
    draft_files = [
        archive_artifact(root, draft[key], draft_dir / name, kind, draft_context)
        for key, name, kind in [('dockerfile', 'Dockerfile', 'DOCKERFILE'),
                                ('build_log', 'build.log', 'BUILD_LOG'),
                                ('verify_log', 'verify.log', 'VERIFY_LOG')]
    ]
    stage('draft', target, {'producer_job_id': draft['job_id'], 'environment': env}, draft_files)

    baseline = spec['full_check']
    check_stage(baseline, base, trace_id, env)
    prior_repo = {**repo, 'commit': base}
    full_files = [archive_graph(root, baseline['actual_graph'], out / 'baseline-actual.json',
                                'ACTUAL_GRAPH', prior_repo, baseline),
                  archive_graph(root, baseline['declared_graph'], out / 'baseline-declared.json',
                                'DECLARED_GRAPH', prior_repo, baseline)]
    stage('full-check', base, {'producer_job_id': baseline['job_id']}, full_files)

    current = spec['incremental_check']
    check_stage(current, target, trace_id, env)
    check(current['base_commit'] == base, 'ARTIFACT_BINDING_MISMATCH', 'Incremental baseline mismatch')
    reference = current['md_report']
    check(reference['artifact']['uri'] == repair['md_report_uri'],
          'ARTIFACT_BINDING_MISMATCH', 'MD report URI mismatch')
    report_path = archive_artifact(root, reference, out / 'md-only.json', 'ERROR_REPORT',
                                   {**common, 'producer_job_id': current['job_id']})
    report = load_md_report(report_path.read_bytes(), repo, cfg, current['job_id'], repair['makefiles'])
    current_files = [report_path,
                     archive_graph(root, current['actual_graph'], out / 'target-actual.json',
                                   'ACTUAL_GRAPH', repo, current),
                     archive_graph(root, current['declared_graph'], out / 'target-declared.json',
                                   'DECLARED_GRAPH', repo, current)]
    stage('incremental-check', target, {'producer_job_id': current['job_id'],
                                        'md_report': reference['artifact']}, current_files)

    patchfile = out / 'candidate.patch'
    edits = candidate(Path(request['repo']).resolve(), base, repair, report, patchfile)
    job_id = result['job_id']
    patch_artifact = {
        **common, 'artifact_id': f'{job_id}-candidate', 'type': 'PATCH',
        'uri': f'artifact://b14-repair/{job_id}/candidate.patch', 'media_type': 'text/x-diff',
        'producer_job_id': job_id, 'sha256': sha256(patchfile.read_bytes()),
    }
    manifest = write_json(out / 'candidate-manifest.json', {
        'artifact': patch_artifact, 'trace_id': trace_id, 'image_ref': env['image_ref'],
        'apply_from': '.', 'makefiles': repair['makefiles'],
        'download_path': f'/v1/jobs/{job_id}/files/candidate.patch',
    })
    stage('repair', target, {'patch': patch_artifact, 'edits': edits}, [patchfile, manifest])

    returned = contained(root, spec['recheck_file'])
    timeout = repair_request['execution']['timeout_seconds']
    deadline = time.monotonic() + timeout
    while not returned.is_file():
        if time.monotonic() >= deadline:
            raise HandoffError('RECHECK_TIMEOUT', 'A14 recheck evidence did not arrive before the deadline')
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    recheck = json.loads(returned.read_bytes())
    check_stage(recheck, target, trace_id, env, ('SUCCEEDED', 'FAILED'))
    check(recheck.get('repository_url') == repo['url']
          and recheck.get('patch_uri') == patch_artifact['uri']
          and recheck.get('patch_sha256') == patch_artifact['sha256'],
          'ARTIFACT_BINDING_MISMATCH', 'Recheck does not identify this candidate')
    received = write_json(out / 'recheck-evidence.json', recheck)
    if recheck['status'] == 'FAILED' and 'a14_failure' in recheck:
        failure_path = archive(root, recheck['a14_failure'], out / 'a14-recheck-failure.json')
        failure = json.loads(failure_path.read_bytes())
        check(isinstance(failure, dict) and failure.get('status') == 'FAILED'
              and failure.get('patch_uri') == patch_artifact['uri'] and isinstance(failure.get('reason'), str),
              'ARTIFACT_BINDING_MISMATCH', 'A14 failure does not identify this candidate')
        logs = [archive(root, recheck[f'{kind}_log'], out / f'recheck-{kind}.log')
                for kind in ('build', 'verify') if f'{kind}_log' in recheck]
        stage('recheck', target, {'producer_job_id': recheck['job_id'], 'patch_uri': patch_artifact['uri'],
                                  'accepted': False, 'reason': failure['reason']},
              [received, failure_path, *logs], status='FAILED')
        raise HandoffError('RECHECK_FAILED', 'A14 could not complete candidate recheck')
    files = [received, archive(root, recheck['findings'], out / 'recheck-findings.json'),
             archive(root, recheck['build_log'], out / 'recheck-build.log'),
             archive(root, recheck['verify_log'], out / 'recheck-verify.log'),
             archive(root, recheck['a14_result'], out / 'a14-recheck.json')]
    findings = json.loads(files[1].read_bytes())
    if isinstance(findings, dict):
        findings = findings.get('findings')
    check(isinstance(findings, list) and all(isinstance(f, dict) and f.get('type') in ('MISSING', 'REDUNDANT')
                                             for f in findings),
          'INVALID_RECHECK', 'Expected an array of actual MD/RD findings')
    remaining = sum(f['type'] == 'MISSING' for f in findings)
    native = json.loads(files[4].read_bytes())
    expected = {'repository': repo, 'configuration_id': cfg, 'producer_job_id': recheck['job_id'],
                'patch_uri': patch_artifact['uri'], 'patch_sha256': patch_artifact['sha256'],
                'source': 'DYNAMIC_TRACE', 'remaining_missing': remaining}
    check(isinstance(native, dict) and all(native.get(key) == value for key, value in expected.items()),
          'ARTIFACT_BINDING_MISMATCH', 'A14 recheck does not match this candidate or the raw findings')
    accepted = (remaining == 0 and recheck['status'] == 'SUCCEEDED' and native.get('status') == 'SUCCEEDED'
                and all(type(recheck[key]) is int and recheck[key] == 0
                        for key in ('build_exit_code', 'verify_exit_code')))
    stage('recheck', target, {'producer_job_id': recheck['job_id'], 'patch_uri': patch_artifact['uri'],
                              'remaining_missing': remaining, 'accepted': accepted}, files,
          status='SUCCEEDED' if accepted else 'FAILED')
    check(accepted, 'RECHECK_FAILED', 'Candidate failed build, behavior verification or MD recheck')
