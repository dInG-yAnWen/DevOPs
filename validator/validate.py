"""E2 contract checks: JSON Schema + semantic checks + local artifact resolution.

This is an offline contract validator, not an HTTP server or build executor.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.deps').is_dir():
    sys.path.insert(0, str(ROOT / '.deps'))
try:
    from jsonschema import Draft202012Validator
    BACKEND = 'jsonschema (Draft 2020-12)'
except ImportError:
    from schema_subset import Draft202012Validator
    BACKEND = 'offline subset (only keywords used by this contract)'


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


SCHEMA = read_json(ROOT / 'contracts/task.schema.json')
MANIFEST = read_json(ROOT / 'contracts/artifact-manifest.json')['artifacts']


def schema_check(value, kind=None):
    schema = SCHEMA if kind is None else {'$schema': SCHEMA['$schema'], '$defs': SCHEMA['$defs'], '$ref': '#/$defs/' + kind}
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        err = errors[0]
        if err.context:
            # Keep diagnostics readable instead of echoing the entire payload.
            reasons = list(dict.fromkeys(e.message for e in err.context))[:6]
            raise ContractError('Schema: ' + '; '.join(reasons))
        raise ContractError('Schema: ' + err.message)


def resolve(uri):
    require(uri in MANIFEST, f'Unknown local artifact URI: {uri}')
    item = MANIFEST[uri]
    path = (ROOT / item['path']).resolve()
    require(path.is_relative_to((ROOT / 'contracts/artifacts').resolve()), 'Artifact path escapes allowed root')
    require(path.is_file(), f'Artifact not readable: {uri}')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == item['artifact']['sha256'], f'Artifact digest mismatch: {uri}')
    return path, item['artifact']


def bound(uri, typ, repo=None, cfg=None):
    path, record = resolve(uri)
    require(record['type'] == typ, f'{uri}: expected {typ}')
    if repo:
        require((record['repository_url'], record['commit']) == (repo['url'], repo['commit']), f'{uri}: repository/commit mismatch')
    if cfg:
        require(record['configuration_id'] == cfg, f'{uri}: configuration mismatch')
    return path, record


def command(value):
    status, code, uri = value['status'], value['exit_code'], value['log_uri']
    if status == 'NOT_RUN':
        require(code is None and uri is None, 'NOT_RUN must have null exit_code/log_uri')
    else:
        require(type(code) is int and uri is not None, 'Executed command requires exit_code/log_uri')
        require((status == 'PASSED') == (code == 0), 'Command status contradicts exit_code')
        _, rec = resolve(uri)
        require(rec['type'] in ['BUILD_LOG', 'VERIFY_LOG'], 'Command log must refer to log artifact')


def walk(value):
    if isinstance(value, dict):
        if set(value) == {'status', 'exit_code', 'log_uri'}:
            command(value)
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
    elif isinstance(value, str) and value.startswith('artifact://'):
        resolve(value)


def validate_report(path, repo, cfg, md_only=False):
    report = read_json(path)
    schema_check(report, 'Report')
    require(report['repository'] == repo and report['configuration_id'] == cfg, 'Report repository/commit/configuration mismatch')
    ids = [f['finding_id'] for f in report['findings']]
    require(len(ids) == len(set(ids)), 'Duplicate finding_id')
    require(all(f['commit'] == repo['commit'] for f in report['findings']), 'Finding commit mismatch')
    if md_only:
        require(bool(ids) and all(f['type'] == 'MISSING' for f in report['findings']), 'REPAIR accepts nonempty MD-only reports')
    return report


def validate(value):
    schema_check(value)
    walk(value)
    if 'http_status' in value:
        error = value['error']
        allowed = {400: ['INPUT_1001'], 404: ['JOB_2001'], 409: ['INPUT_1006'], 422: ['INPUT_1001', 'INPUT_1002', 'INPUT_1003', 'INPUT_1004', 'INPUT_1005']}
        require(error['code'] in allowed[value['http_status']] and error['category'] == 'INPUT', 'HTTP error code/category mismatch')
        return
    if 'input' not in value:
        require(value['status_url'] == '/v1/jobs/' + value['job_id'], 'Accepted status_url mismatch')
        return
    typ, inp = value['job_type'], value['input']
    repo = inp['repository']
    cfg = inp.get('environment', {}).get('configuration_id')
    if typ == 'DRAFT':
        require('max_iterations' in value['execution'], 'Canonical DRAFT execution requires max_iterations')
    else:
        require('max_iterations' not in value['execution'], 'max_iterations is DRAFT-only')
        env = inp['environment']
        _, record = bound(env['dockerfile_uri'], 'DOCKERFILE', cfg=cfg)
        require(record['repository_url'] == repo['url'], 'Environment repository mismatch')
        require(record['producer_job_id'] == env['producer_job_id'], 'Environment producer mismatch')
        if typ != 'INCREMENTAL_CHECK':
            require(record['commit'] == repo['commit'], 'Environment commit mismatch')
    if typ == 'INCREMENTAL_CHECK':
        base = inp['baseline']
        require(inp['base_commit'] != repo['commit'], 'Incremental base and current commit must differ')
        require(base['repository_url'] == repo['url'] and base['commit'] == inp['base_commit'] and base['configuration_id'] == cfg, 'Baseline repository/commit/configuration mismatch')
        old = {'url': repo['url'], 'commit': inp['base_commit']}
        graph_path, _ = bound(base['actual_graph_uri'], 'ACTUAL_GRAPH', old, cfg)
        graph = read_json(graph_path)
        require(graph['repository'] == old and graph['configuration_id'] == cfg, 'Baseline graph payload mismatch')
        report_path, _ = bound(base['error_report_uri'], 'ERROR_REPORT', old, cfg)
        baseline_report = validate_report(report_path, old, cfg)
    if typ == 'REPAIR':
        path, _ = bound(inp['md_report_uri'], 'ERROR_REPORT', repo, cfg)
        report = validate_report(path, repo, cfg, md_only=True)
        require(all(f['location']['path'] in inp['makefiles'] for f in report['findings']), 'MD location missing from makefiles')
    if 'status' not in value:
        return
    state, output, error = value['status'], value['output'], value['error']
    if state == 'TIMED_OUT':
        require(error['code'] == 'EXEC_4002' and error['category'] == 'SYSTEM', 'Timeout error mismatch')
    elif state == 'CANCELLED':
        require(error['code'] == 'EXEC_4004' and error['category'] == 'CONTROL', 'Cancellation error mismatch')
    elif state == 'FAILED':
        require(error['category'] in ['SYSTEM', 'GOAL_UNMET'], 'FAILED must separate SYSTEM and GOAL_UNMET')
        require(error['code'] not in ['EXEC_4002', 'EXEC_4004'] and not error['code'].startswith(('INPUT_', 'JOB_')), 'Invalid FAILED error code')
        if error['category'] == 'GOAL_UNMET':
            require((typ, error['code']) in [('DRAFT', 'ENV_3002'), ('DRAFT', 'EXEC_4003'), ('REPAIR', 'REPAIR_6001')], 'Controlled failure code mismatch')
            require(output is not None, 'Controlled failure must preserve attempt/candidate evidence')
    if output is None:
        return
    for artifact in output['artifacts']:
        _, canonical = resolve(artifact['uri'])
        require(artifact == canonical, 'Artifact metadata differs from manifest')
        require(artifact['producer_job_id'] == value['job_id'], 'Output artifact producer mismatch')
        require(artifact['commit'] == repo['commit'] and artifact['repository_url'] == repo['url'], 'Output artifact source mismatch')
        if cfg:
            require(artifact['configuration_id'] == cfg, 'Output artifact configuration mismatch')
    published = {a['uri'] for a in output['artifacts']}
    if typ == 'DRAFT':
        iterations = output['iterations']
        require(len(iterations) <= value['execution']['max_iterations'], 'DRAFT exceeds iteration budget')
        require([i['index'] for i in iterations] == list(range(1, len(iterations)+1)), 'Iteration indices must be consecutive')
        if state == 'SUCCEEDED':
            require(output['environment'] is not None and iterations, 'DRAFT success requires environment and attempts')
            require(output['build']['status'] == output['verify']['status'] == 'PASSED', 'DRAFT success requires build and verify pass')
            require(output['build'] == iterations[-1]['build'] and output['verify'] == iterations[-1]['verify'], 'Final DRAFT result contradicts last iteration')
            env = output['environment']
            path, rec = bound(env['dockerfile_uri'], 'DOCKERFILE', repo, env['configuration_id'])
            require(env['producer_job_id'] == value['job_id'] == rec['producer_job_id'], 'DRAFT producer mismatch')
            require(env['dockerfile_uri'] in published, 'Dockerfile must be published')
            metas = [a for a in output['artifacts'] if a['type'] == 'IMAGE_METADATA']
            require(len(metas) == 1, 'Success requires one image metadata record')
            require(read_json(resolve(metas[0]['uri'])[0])['image_ref'] == env['image_ref'], 'Image metadata mismatch')
        elif state == 'FAILED' and error['category'] == 'GOAL_UNMET':
            require(output['environment'] is None and iterations, 'Unmet DRAFT cannot publish usable environment')
            require(output['build']['status'] != 'PASSED' or output['verify']['status'] != 'PASSED', 'Unmet DRAFT has successful final commands')
            if error['details'].get('reason') == 'ITERATION_LIMIT':
                require(len(iterations) == value['execution']['max_iterations'], 'Iteration-limit failure before budget exhausted')
    elif typ in ['FULL_CHECK', 'INCREMENTAL_CHECK']:
        for key, artifact_type in [('actual_graph_uri', 'ACTUAL_GRAPH'), ('declared_graph_uri', 'DECLARED_GRAPH'), ('error_report_uri', 'ERROR_REPORT')]:
            require(output[key] in published, f'{key} must be published')
            bound(output[key], artifact_type, repo, cfg)
        report = validate_report(resolve(output['error_report_uri'])[0], repo, cfg)
        if typ == 'INCREMENTAL_CHECK':
            current = {f['finding_id'] for f in report['findings']}
            previous = {f['finding_id'] for f in baseline_report['findings']}
            delta = output['findings_delta']
            require(set(delta['added']) == current-previous and set(delta['removed']) == previous-current, 'Incorrect findings delta')
    elif typ == 'REPAIR':
        accepted = []
        for candidate in output['candidates']:
            require(candidate['patch_uri'] in published, 'Candidate patch not published')
            bound(candidate['patch_uri'], 'PATCH', repo, cfg)
            recheck = candidate['recheck']
            if recheck['status'] == 'NOT_RUN':
                require(recheck['remaining_missing'] is None and recheck['report_uri'] is None, 'NOT_RUN recheck must be null')
            else:
                require(recheck['report_uri'] in published, 'Recheck report not published')
                path, _ = bound(recheck['report_uri'], 'RECHECK_REPORT', repo, cfg)
                data = read_json(path)
                require(data['patch_uri'] == candidate['patch_uri'] and data['remaining_missing'] == recheck['remaining_missing'], 'Recheck payload mismatch')
                require((recheck['status'] == 'PASSED') == (recheck['remaining_missing'] == 0), 'Recheck status/count mismatch')
            if candidate['decision'] == 'ACCEPTED':
                require(candidate['build']['status'] == candidate['verify']['status'] == recheck['status'] == 'PASSED', 'Accept patch only after build/test/recheck pass')
                accepted.append(candidate['patch_uri'])
        if state == 'SUCCEEDED':
            require(output['patch_uri'] in accepted, 'REPAIR success requires accepted patch')
        else:
            require(output['patch_uri'] is None and not accepted, 'Failed repair cannot advertise accepted patch')


def suite():
    print('Schema backend: '+BACKEND)
    Draft202012Validator.check_schema(SCHEMA)
    total = 1
    kinds = {'ACTUAL_GRAPH': 'Graph', 'DECLARED_GRAPH': 'Graph', 'ERROR_REPORT': 'Report', 'IMAGE_METADATA': 'ImageMetadata', 'RECHECK_REPORT': 'RecheckReport'}
    for uri, item in MANIFEST.items():
        schema_check(item['artifact'], 'Artifact')
        path, record = resolve(uri)
        require(record['uri'] == uri, 'Manifest URI mismatch')
        if record['type'] in kinds:
            payload = read_json(path)
            schema_check(payload, kinds[record['type']])
            require(payload['repository'] == {'url': record['repository_url'], 'commit': record['commit']} and payload['configuration_id'] == record['configuration_id'] and payload['producer_job_id'] == record['producer_job_id'], 'Artifact payload/provenance mismatch')
            if record['type'] in ['ACTUAL_GRAPH', 'DECLARED_GRAPH']:
                require(payload['kind'] == record['type'], 'Graph kind mismatch')
                require(all(e['target'] in payload['nodes'] and e['dependency'] in payload['nodes'] for e in payload['edges']), 'Graph edge references unknown node')
        total += 1
    valid = sorted((ROOT/'contracts/examples/valid').glob('*.json'))
    invalid = sorted((ROOT/'contracts/examples/invalid').glob('*.json'))
    for path in valid:
        validate(read_json(path)); print('PASS valid/' + path.name); total += 1
    for path in invalid:
        try:
            validate(read_json(path))
        except ContractError:
            print('PASS rejected/' + path.name); total += 1
        else:
            raise ContractError('Invalid example accepted: '+path.name)
    mutations = [
        ('draft_request', ['execution', 'max_iterations'], 0),
        ('draft_request', ['execution', 'timeout_seconds'], 0),
        ('draft_request', ['schema_version'], '2.0'),
        ('draft_request', ['input', 'build', 'working_directory'], '../escape'),
        ('draft_request', ['input', 'build', 'unexpected'], True),
        ('incremental_request', ['input', 'baseline', 'commit'], '4'*40),
        ('incremental_request', ['input', 'baseline', 'repository_url'], 'https://example.invalid/other.git'),
        ('repair_request', ['input', 'makefiles'], ['other.mk']),
        ('draft_result', ['output', 'environment', 'producer_job_id'], 'wrong'),
        ('draft_result', ['output', 'artifacts', 0, 'sha256'], '0'*64),
        ('draft_result', ['output', 'environment', 'dockerfile_uri'], 'artifact://b14-draft/job-draft01/absent'),
        ('draft_timed_out', ['error', 'code'], 'ENV_3002'),
        ('draft_cancelled', ['error', 'category'], 'SYSTEM'),
        ('draft_goal_unmet', ['execution', 'max_iterations'], 4),
        ('full_result', ['error'], {'code':'ANALYSIS_5001','category':'SYSTEM','message':'wrong','retryable':False,'details':{}}),
        ('incremental_result', ['output', 'findings_delta', 'added'], ['invented']),
        ('repair_result', ['output', 'candidates', 0, 'recheck', 'remaining_missing'], 1),
        ('repair_result', ['output', 'candidates', 0, 'decision'], 'REJECTED'),
        ('draft_accepted', ['status_url'], '/v1/jobs/wrong'),
        ('input_error', ['http_status'], 409)
    ]
    for name, keys, replacement in mutations:
        value = read_json(ROOT/'contracts/examples/valid'/(name+'.json'))
        parent = value
        for key in keys[:-1]:
            parent = parent[key]
        parent[keys[-1]] = replacement
        try:
            validate(value)
        except ContractError:
            total += 1
        else:
            raise ContractError(f'Mutation accepted: {name} {keys}')
    # Resolver must reject unknown and traversal URIs without touching external files.
    for uri in ['artifact://b14-draft/job-draft01/../../README.md', 'artifact://unknown/job/file']:
        try:
            resolve(uri)
        except ContractError:
            total += 1
        else:
            raise ContractError('Unsafe/unknown URI accepted')
    print(f'PASS: {total} checks (schema=1, artifacts={len(MANIFEST)}, valid={len(valid)}, invalid={len(invalid)}, mutations={len(mutations)}, resolver=2)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?')
    parser.add_argument('--suite', action='store_true')
    parser.add_argument('--read-artifact', metavar='URI')
    args = parser.parse_args()
    try:
        if args.read_artifact:
            path, _ = resolve(args.read_artifact)
            print(path.read_text(encoding='utf-8'), end='')
        elif args.path:
            validate(read_json(args.path)); print('PASS: '+args.path)
        else:
            suite()
    except (ContractError, OSError, ValueError) as error:
        print('FAIL: '+str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
