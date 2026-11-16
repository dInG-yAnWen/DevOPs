"""Build and verify a DRAFT candidate image for a target checkout.

The tool snapshots the build inputs, builds a candidate Dockerfile, runs the
resulting image offline with fixed limits, and records a manifest containing
the configuration id, job/trace ids, image id, logs and a portable archive.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCHEMA = 'e11e12-draft-image-1'
INPUTS = ('main.c', 'config.h', 'feature.h', 'Makefile')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def input_hashes(project):
    project = Path(project)
    missing = [name for name in INPUTS if not (project / name).is_file()]
    if missing:
        raise ValueError('MISSING_INPUT ' + ','.join(missing))
    return {name: sha256_file(project / name) for name in INPUTS}


def configuration_id(inputs, dockerfile_sha256, expected_output):
    payload = json.dumps(
        {'inputs': inputs, 'dockerfile': dockerfile_sha256,
         'expected_output': expected_output},
        sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def run(argv, log_path, cwd=None, timeout=1800):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with log_path.open('wb') as log:
        proc = subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                              timeout=timeout)
    return {'argv': [str(x) for x in argv], 'exit_code': proc.returncode,
            'seconds': round(time.time() - started, 3), 'log': str(log_path)}


def inspect_image(ref):
    return subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', ref],
        text=True).strip()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def deliver(project, dockerfile, out, tag, expected_output='12', push_ref=None):
    project = Path(project).resolve()
    dockerfile = Path(dockerfile).resolve()
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('OUTPUT_EXISTS ' + str(out))

    inputs = input_hashes(project)
    dockerfile_sha = sha256_file(dockerfile)
    config_id = configuration_id(inputs, dockerfile_sha, expected_output)
    job_id = 'job-' + uuid.uuid4().hex
    trace_id = 'trace-' + uuid.uuid4().hex

    out.mkdir(parents=True)
    snapshot = out / 'project'
    snapshot.mkdir()
    for name in INPUTS:
        (snapshot / name).write_bytes((project / name).read_bytes())
    (out / 'candidate.Dockerfile').write_bytes(dockerfile.read_bytes())

    build = run(['docker', 'build', '--no-cache', '--progress=plain',
                 '-f', str(dockerfile), '-t', tag, str(project)],
                out / 'build.log')
    manifest = {
        'schema': SCHEMA,
        'job_id': job_id,
        'trace_id': trace_id,
        'configuration_id': config_id,
        'project': {'path': str(project), 'inputs': inputs},
        'dockerfile': {'path': str(dockerfile), 'sha256': dockerfile_sha},
        'image': {'ref': tag, 'id': None, 'repo_digest': None},
        'expected_output': expected_output,
        'build': build,
        'verify': None,
        'actual_output': None,
        'output_matches': False,
        'archive': None,
        'push': None,
        'passed': False,
    }

    if build['exit_code'] != 0:
        manifest['reason'] = 'BUILD_FAILED'
        save_json(out / 'manifest.json', manifest)
        return manifest, 2

    image_id = inspect_image(tag)
    manifest['image']['id'] = image_id

    verify = run(['docker', 'run', '--rm', '--network', 'none',
                  '--cpus', '1', '--memory', '256m', '--pids-limit', '64',
                  image_id], out / 'verify.log')
    actual = (out / 'verify.log').read_text(encoding='utf-8', errors='replace')
    manifest['verify'] = verify
    manifest['actual_output'] = actual
    manifest['output_matches'] = (
        verify['exit_code'] == 0 and actual == expected_output + '\n')

    archive = out / 'image.tar'
    save_result = run(['docker', 'save', '-o', str(archive), image_id],
                      out / 'save.log')
    manifest['archive'] = {
        'path': str(archive),
        'sha256': sha256_file(archive) if archive.is_file() else None,
        'save': save_result,
    }

    if push_ref:
        push = run(['docker', 'push', push_ref], out / 'push.log')
        manifest['push'] = push
        if push['exit_code'] == 0:
            repo_digest = subprocess.check_output(
                ['docker', 'image', 'inspect', '--format',
                 '{{join .RepoDigests "\\n"}}', push_ref],
                text=True).strip()
            manifest['image']['repo_digest'] = repo_digest.splitlines()[0] if repo_digest else None

    manifest['passed'] = bool(
        manifest['output_matches']
        and archive.is_file()
        and manifest['archive']['sha256']
        and (not push_ref or (manifest['push'] and manifest['push']['exit_code'] == 0)))
    manifest['reason'] = 'BUILD_AND_EXACT_OUTPUT_VERIFIED' if manifest['passed'] else 'VERIFY_FAILED'
    save_json(out / 'manifest.json', manifest)
    return manifest, 0 if manifest['passed'] else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--dockerfile', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--expected-output', default='12')
    parser.add_argument('--push-ref')
    args = parser.parse_args(argv)
    manifest, code = deliver(args.project, args.dockerfile, args.out, args.tag,
                             args.expected_output, args.push_ref)
    print(json.dumps({
        'job_id': manifest['job_id'],
        'trace_id': manifest['trace_id'],
        'configuration_id': manifest['configuration_id'],
        'image_id': manifest['image']['id'],
        'passed': manifest['passed'],
        'reason': manifest['reason'],
        'manifest': str(Path(args.out).resolve() / 'manifest.json'),
    }, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
