"""Prepare fresh, pinned E14 inputs from the exchanged Git bundles (no network)."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())


def git(*args, cwd=None):
    return subprocess.check_output(['git', *map(str, args)], cwd=cwd).decode().strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(a14_bundle, a14_package, b14_bundle, b14_spec, sample_request):
    inputs = ROOT/'data/e14-inputs'
    requests = ROOT/'data/e14-requests'
    if inputs.exists() or requests.exists():
        raise ValueError('Preserve existing E14 inputs; use a fresh independent workspace')
    sample = json.loads(sample_request.read_text(encoding='utf-8'))
    for field in ('repo','candidate','fixed_report'):
        value = sample.get(field)
        if value and not value.startswith('/course/'):
            sample[field] = '/course/'+Path(value).resolve().relative_to(ROOT.resolve()).as_posix()
    with zipfile.ZipFile(a14_package) as package:
        a14_spec = json.loads(package.read('project.json'))
        a14_candidate = package.read('e11-a/target-project/e13/projects/a14/candidate.Dockerfile')
    specs = {'a14': a14_spec, 'b14': json.loads(b14_spec.read_text(encoding='utf-8'))}
    inputs.mkdir(parents=True)
    for name, bundle in (('a14', a14_bundle), ('b14', b14_bundle)):
        spec = specs[name]
        folder = inputs/name
        folder.mkdir()
        repo = folder/'repo'
        git('clone', '--no-checkout', bundle.resolve(), repo)
        git('config', 'core.autocrlf', 'false', cwd=repo)
        for revision in (spec['base'], spec['target']):
            if git('rev-parse', '--verify', revision+'^{commit}', cwd=repo) != revision:
                raise ValueError('Bundle does not contain the specified complete SHA')
        git('checkout', '--detach', spec['target'], cwd=repo)
        candidate = folder/'candidate.Dockerfile'
        if name == 'a14':
            candidate.write_bytes(a14_candidate)
        else:
            candidate.write_bytes(subprocess.check_output(
                ['git', 'show', spec['target']+':'+spec['project_path']+'/candidate.Dockerfile'], cwd=repo))
        request = {'mode': 'e12', 'project_label': name+'-actual-project',
                   'repo': '/course/'+repo.relative_to(ROOT).as_posix(),
                   'project_path': spec['project_path'], 'base': spec['base'], 'target': spec['target'],
                   'candidate': '/course/'+candidate.relative_to(ROOT).as_posix(),
                   'expected_output': spec['target_output'], 'header_probe': spec['header_probe'],
                   'build_timeout': 600}
        save(requests/(name+'.json'), request)
    sample['project_label'] = 'unchanged-teaching-fixture-regression'
    save(requests/'fixed.json', sample)
    b14 = json.loads((requests/'b14.json').read_text(encoding='utf-8'))
    save(requests/'fault-timeout.json', dict(b14, build_timeout=0.01,
         project_label='b14-isolated-draft-timeout-injection'))
    save(requests/'recovery.json', dict(b14, project_label='b14-new-normal-task-after-timeout'))
    save(inputs/'input-manifest.json', {
        'status': 'PREPARED_NOT_EXECUTED',
        'sources': {p.name: {'sha256': sha(p)} for p in (a14_bundle,a14_package,b14_bundle,b14_spec)},
        'projects': specs,
        'requests': {p.name: sha(p) for p in sorted(requests.glob('*.json'))},
        'note': 'Local input preparation is not an E13/E14 gate or release approval.',
    })
    return requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('a14-bundle', 'a14-package', 'b14-bundle', 'b14-spec'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--sample-request', type=Path, default=ROOT/'data/integration-sample/e12.json')
    args = parser.parse_args()
    print(prepare(args.a14_bundle,args.a14_package,args.b14_bundle,args.b14_spec,args.sample_request))


if __name__ == '__main__':
    main()
