"""Run E14's four Compose services on one pinned teaching project."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PORTS = {'buildchecker': 18081, 'echecker': 18082, 'draft': 18083, 'mdfixer': 18084}
PORTS = {role:int(os.environ.get('E14_'+role.upper()+'_PORT',port)) for role,port in PORTS.items()}
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'labs/e11e12'))
from pipeline import snapshot as project_snapshot, project_directory


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def container_path(path):
    return '/course/' + path.resolve().relative_to(ROOT.resolve()).as_posix()


def host_path(value):
    if not isinstance(value, str) or not value.startswith('/course/'):
        raise ValueError('Expected /course path')
    path = (ROOT / value[len('/course/'):]).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Path escapes repository')
    return path


def command(argv, cwd, log):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(p.stdout + p.stderr, encoding='utf-8')
    if p.returncode:
        raise ValueError(f'{argv[0]} failed; inspect {log}')
    return p.stdout.strip()


def snapshot(repo, revision, target, logs, project_path='.'):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use a full Git commit SHA')
    return project_snapshot(repo, revision, target, logs, project_path)


class StageFailure(ValueError):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response or {}


def call(role, payload, evidence):
    req = urllib.request.Request(f'http://127.0.0.1:{PORTS[role]}/v1/run',
                                 data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        timeout = max(720, 2*float(payload.get('build_timeout',600))+120) if role=='draft' else 720
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        try:
            failure = json.loads(body)
        except ValueError:
            failure = {'status': 'FAILED', 'error': body}
        save(evidence, {'role': role, 'http': exc.code, **failure})
        if (failure.get('role'),failure.get('job_id'),failure.get('trace_id')) != (
                role,payload['job_id'],payload['trace_id']):
            raise StageFailure(f'{role} error response identity mismatch',
                               {'status':'FAILED','received':failure}) from exc
        raise StageFailure(f'{role} HTTP {exc.code}', failure) from exc
    except (OSError, urllib.error.URLError) as exc:
        failure = {'role': role, 'status': 'FAILED', 'error': str(exc)}
        save(evidence, failure)
        raise StageFailure(f'{role} transport failed', failure) from exc
    save(evidence, data)
    if (data.get('role'), data.get('job_id'), data.get('trace_id')) != (
            role, payload['job_id'], payload['trace_id']):
        raise StageFailure(f'{role} response identity mismatch', data)
    if data['status'] != 'SUCCEEDED':
        raise ValueError(f'{role} did not succeed')
    return data


def execute(request, out):
    if out.exists():
        raise ValueError('Use a new output directory')
    if (not out.resolve().is_relative_to((ROOT / 'work').resolve())
            or out.resolve() == (ROOT / 'work').resolve()):
        raise ValueError('Output must be inside work/')
    out.mkdir(parents=True)
    job = 'job-' + uuid.uuid4().hex
    trace = 'trace-' + uuid.uuid4().hex
    result = {'schema_version': 'e14-compose-1', 'job_id': job, 'trace_id': trace,
              'status': 'RUNNING', 'stages': []}
    save(out / 'request.json', request)

    def payload(project, folder, **extra):
        return {'project': container_path(project), 'out': container_path(folder),
                'job_id': job, 'trace_id': trace, **extra}

    def stage(name, commit, data):
        item = {'name': name, 'commit': commit, 'job_id': job, 'trace_id': trace, 'status': 'SUCCEEDED', 'data': data}
        path = out / (name + '.json')
        save(path, item)
        result['stages'].append({'name': name, 'artifact': {'uri': path.name, 'sha256': digest(path)}})

    try:
        repo = host_path(request['repo'])
        candidate = host_path(request['candidate'])
        if not repo.is_relative_to((ROOT/'data').resolve()) or not candidate.is_relative_to((ROOT/'data').resolve()):
            raise ValueError('Input project and candidate must be in data/')
        project_path = request.get('project_path', '.')
        base_root = out / 'base-project'
        target_root = out / 'target-project'
        logs = out / 'logs'
        base_sha = snapshot(repo, request['base'], base_root, logs, project_path)
        target_sha = snapshot(repo, request['target'], target_root, logs, project_path)
        base = project_directory(base_root, project_path)
        target = project_directory(target_root, project_path)
        result.update(base_commit=base_sha, target_commit=target_sha)

        drafted = call('draft', payload(target, out / 'draft-build',
                                        candidate=container_path(candidate),
                                        expected_output=request.get('expected_output', '1'),
                                        build_timeout=request.get('build_timeout', 600)),
                       out / 'draft-response.json')
        stage('draft', target_sha, drafted)

        base_full = call('buildchecker', payload(base, out / 'baseline-full'), out / 'baseline-response.json')
        target_full = call('buildchecker', payload(target, out / 'target-full'), out / 'target-response.json')
        stage('full-check', base_sha, {'base': base_full, 'target': target_full})

        increment = call('echecker', payload(target, out / 'incremental', base=container_path(base),
                                            baseline_graph=container_path(out / 'baseline-full/actual-graph.json'),
                                            target_findings=container_path(out / 'target-full/findings.json'),
                                            target_commit=target_sha), out / 'incremental-response.json')
        stage('incremental-check', target_sha, increment)

        repair = call('mdfixer', payload(target, out / 'repair-work',
                                        report=increment['report'], report_sha256=increment['sha256'],
                                        target_commit=target_sha,
                                        expected_output=request.get('expected_output', '1'),
                                        header_probe=request.get('header_probe')), out / 'repair-response.json')
        stage('repair', target_sha, repair)

        final = call('buildchecker', payload(target, out / 'final-full'), out / 'recheck-response.json')
        missing = [x for x in final['result']['findings'] if x['type'] == 'MISSING']
        if missing:
            raise ValueError(f'Recheck has {len(missing)} missing dependencies')
        stage('recheck', target_sha, {'result': final, 'remaining_missing': 0})
        result['status'] = 'SUCCEEDED'
    except Exception as exc:
        failure = getattr(exc, 'response', {})
        result.update(status='TIMED_OUT' if failure.get('status') == 'TIMED_OUT' else 'FAILED',
                      error=str(exc), failure=failure)
    result['artifacts'] = [{'uri': path.relative_to(out).as_posix(), 'sha256': digest(path),
                            'bytes': path.stat().st_size} for path in sorted(out.rglob('*'))
                           if path.is_file() and '.git' not in path.parts and not path.is_symlink()]
    save(out / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = execute(json.loads(args.request.read_text(encoding='utf-8')), args.out.resolve())
    print(json.dumps({'status': result['status'], 'job_id': result['job_id'],
                      'stages': [x['name'] for x in result['stages']],
                      'error': result.get('error')}, ensure_ascii=False))
    return 0 if result['status'] == 'SUCCEEDED' else 1


if __name__ == '__main__':
    sys.exit(main())
