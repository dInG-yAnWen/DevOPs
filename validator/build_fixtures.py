"""Regenerate the E2 schema and clearly synthetic examples; never runs builds."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / 'contracts'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def obj(props, required=None):
    return {'type': 'object', 'properties': props, 'required': list(props) if required is None else required, 'additionalProperties': False}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def arr(items, minimum=0):
    return {'type': 'array', 'items': items, 'minItems': minimum}


def enum(*values):
    return {'enum': list(values)}


def nullable(s):
    return {'anyOf': [s, {'type': 'null'}]}


S = {'type': 'string', 'minLength': 1}
I = {'type': 'integer', 'minimum': 1}
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{40}$'}
URI = {'type': 'string', 'pattern': '^artifact://[a-z0-9-]+/[A-Za-z0-9_-]+/[A-Za-z0-9._-]+$'}
PATH = {'type': 'string', 'pattern': r'^(?!/)(?!.*\\)(?!.*(?:^|/)\.\.(?:/|$))(?!.*:).+$'}
IMAGE = {'type': 'string', 'pattern': '^.+@sha256:[0-9a-f]{64}$'}
TYPES = ['DRAFT', 'FULL_CHECK', 'INCREMENTAL_CHECK', 'REPAIR']
STATES = ['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED']
DEFS = {}
DEFS['Repository'] = obj({'url': {'type': 'string', 'pattern': r'^(https://[^\s]+|ssh://[^\s]+|git@[^\s:]+:[^\s]+)$'}, 'commit': SHA})
DEFS['Build'] = obj({'command': S, 'verify_command': S, 'working_directory': PATH})
DEFS['Execution'] = obj({'timeout_seconds': {**I, 'default': 1800}, 'max_iterations': {**I, 'default': 3}}, ['timeout_seconds'])
DEFS['EnvironmentRequirements'] = obj({'platform': S, 'language': S, 'toolchain': arr(S, 1), 'base_image': S, 'system_dependencies': arr(S), 'network': enum('REQUIRED', 'OPTIONAL', 'DISABLED'), 'environment_variables': {'type': 'object', 'additionalProperties': {'type': 'string'}}, 'ports': arr({'type': 'integer', 'minimum': 1, 'maximum': 65535}), 'test_data': arr(PATH)})
DEFS['Environment'] = obj({'image_ref': IMAGE, 'configuration_id': S, 'dockerfile_uri': URI, 'producer_job_id': S})
DEFS['Artifact'] = obj({'artifact_id': S, 'type': enum('DOCKERFILE', 'IMAGE_METADATA', 'BUILD_LOG', 'VERIFY_LOG', 'ITERATION_PATCH', 'ACTUAL_GRAPH', 'DECLARED_GRAPH', 'ERROR_REPORT', 'PATCH', 'RECHECK_REPORT'), 'uri': URI, 'media_type': S, 'producer_job_id': S, 'repository_url': S, 'commit': SHA, 'configuration_id': S, 'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}})
DEFS['Error'] = obj({'code': enum('INPUT_1001', 'INPUT_1002', 'INPUT_1003', 'INPUT_1004', 'INPUT_1005', 'INPUT_1006', 'JOB_2001', 'ENV_3002', 'EXEC_4001', 'EXEC_4002', 'EXEC_4003', 'EXEC_4004', 'ANALYSIS_5001', 'REPAIR_6001'), 'category': enum('INPUT', 'GOAL_UNMET', 'SYSTEM', 'CONTROL'), 'message': S, 'retryable': {'type': 'boolean'}, 'details': {'type': 'object'}})
DEFS['CommandResult'] = obj({'status': enum('PASSED', 'FAILED', 'NOT_RUN'), 'exit_code': nullable({'type': 'integer'}), 'log_uri': nullable(URI)})
DEFS['Iteration'] = obj({'index': I, 'change_summary': S, 'selection_reason': S, 'patch_uri': nullable(URI), 'build': ref('CommandResult'), 'verify': ref('CommandResult')})
DEFS['Finding'] = obj({'finding_id': S, 'type': enum('MISSING', 'REDUNDANT'), 'target': S, 'dependency': PATH, 'commit': SHA, 'detector': S, 'location': obj({'path': PATH, 'line': I}), 'evidence': obj({'kind': enum('DYNAMIC_TRACE', 'STATIC_INFERENCE', 'MANUAL_FIXTURE', 'INSTRUCTOR_ORACLE'), 'description': S})})
DEFS['Report'] = obj({'schema_version': {'const': '1.0'}, 'repository': ref('Repository'), 'configuration_id': S, 'producer_job_id': S, 'findings': arr(ref('Finding'))})
DEFS['Graph'] = obj({'schema_version': {'const': '1.0'}, 'repository': ref('Repository'), 'configuration_id': S, 'producer_job_id': S, 'kind': enum('ACTUAL_GRAPH', 'DECLARED_GRAPH'), 'nodes': arr(S, 1), 'edges': arr(obj({'target': S, 'dependency': S})), 'source': {'const': 'MANUAL_FIXTURE'}})
DEFS['ImageMetadata'] = obj({'image_ref': IMAGE, 'repository': ref('Repository'), 'configuration_id': S, 'producer_job_id': S, 'available': {'type': 'boolean'}, 'source': {'const': 'MANUAL_FIXTURE'}})
DEFS['RecheckReport'] = obj({'repository': ref('Repository'), 'configuration_id': S, 'producer_job_id': S, 'patch_uri': URI, 'remaining_missing': {'type': 'integer', 'minimum': 0}, 'source': {'const': 'MANUAL_FIXTURE'}})
common = {'repository': ref('Repository'), 'build': ref('Build')}
DEFS['DraftInput'] = obj({**common, 'requirements': ref('EnvironmentRequirements')})
DEFS['FullInput'] = obj({**common, 'environment': ref('Environment')})
DEFS['IncrementalInput'] = obj({**common, 'environment': ref('Environment'), 'base_commit': SHA, 'baseline': obj({'repository_url': S, 'commit': SHA, 'configuration_id': S, 'actual_graph_uri': URI, 'error_report_uri': URI})})
DEFS['RepairInput'] = obj({**common, 'environment': ref('Environment'), 'md_report_uri': URI, 'makefiles': arr(PATH, 1)})
DEFS['DraftOutput'] = obj({'environment': nullable(ref('Environment')), 'iterations': arr(ref('Iteration')), 'build': ref('CommandResult'), 'verify': ref('CommandResult'), 'artifacts': arr(ref('Artifact'))})
DEFS['FullOutput'] = obj({'actual_graph_uri': URI, 'declared_graph_uri': URI, 'error_report_uri': URI, 'artifacts': arr(ref('Artifact'), 3)})
DEFS['IncrementalOutput'] = obj({'actual_graph_uri': URI, 'declared_graph_uri': URI, 'error_report_uri': URI, 'findings_delta': obj({'added': arr(S), 'removed': arr(S)}), 'artifacts': arr(ref('Artifact'), 3)})
DEFS['Candidate'] = obj({'candidate_id': S, 'patch_uri': URI, 'declaration_style': enum('ATOMIC', 'MACRO', 'HYBRID'), 'style_explanation': S, 'decision': enum('ACCEPTED', 'REJECTED'), 'reason': S, 'build': ref('CommandResult'), 'verify': ref('CommandResult'), 'recheck': obj({'status': enum('PASSED', 'FAILED', 'NOT_RUN'), 'remaining_missing': nullable({'type': 'integer', 'minimum': 0}), 'report_uri': nullable(URI)})})
DEFS['RepairOutput'] = obj({'patch_uri': nullable(URI), 'candidates': arr(ref('Candidate')), 'artifacts': arr(ref('Artifact'))})
inputs = ['DraftInput', 'FullInput', 'IncrementalInput', 'RepairInput']
outputs = ['DraftOutput', 'FullOutput', 'IncrementalOutput', 'RepairOutput']
base = {'schema_version': {'const': '1.0'}, 'trace_id': S, 'job_type': enum(*TYPES), 'execution': ref('Execution')}
requests, jobs = [], []
for typ, inp, out in zip(TYPES, inputs, outputs):
    request = obj({**base, 'job_type': {'const': typ}, 'idempotency_key': S, 'input': ref(inp)})
    job = obj({**base, 'job_type': {'const': typ}, 'job_id': S, 'status': enum(*STATES), 'input': ref(inp), 'output': nullable(ref(out)), 'error': nullable(ref('Error'))})
    job['allOf'] = [
        {'if': {'properties': {'status': {'const': 'SUCCEEDED'}}}, 'then': {'properties': {'output': ref(out), 'error': {'type': 'null'}}}},
        {'if': {'properties': {'status': enum('QUEUED', 'RUNNING')}}, 'then': {'properties': {'output': {'type': 'null'}, 'error': {'type': 'null'}}}},
        {'if': {'properties': {'status': enum('FAILED', 'TIMED_OUT', 'CANCELLED')}}, 'then': {'properties': {'error': ref('Error')}}}
    ]
    requests.append(request); jobs.append(job)
DEFS['Request'] = {'oneOf': requests}
DEFS['Job'] = {'oneOf': jobs}
DEFS['Accepted'] = obj({'schema_version': {'const': '1.0'}, 'job_id': S, 'trace_id': S, 'status': {'const': 'QUEUED'}, 'status_url': {'type': 'string', 'pattern': '^/v1/jobs/[A-Za-z0-9_-]+$'}})
DEFS['ApiError'] = obj({'schema_version': {'const': '1.0'}, 'trace_id': S, 'http_status': enum(400, 404, 409, 422), 'error': ref('Error')})
write(C/'task.schema.json', {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'B14 / A14 E2 contract 1.0 (A14 accepted; publication pending)', 'oneOf': [ref('Request'), ref('Job'), ref('Accepted'), ref('ApiError')], '$defs': DEFS})

# All project SHAs, image digests and execution results below are synthetic.
repo = {'url': 'https://example.invalid/a14/make-demo.git', 'commit': '1'*40}
repo1 = {**repo, 'commit': '2'*40}
cfg = 'cfg-demo-linux-amd64-gcc13-mode0'
build = {'command': 'make clean && make', 'verify_command': 'make test', 'working_directory': '.'}
env = {'image_ref': 'registry.example.invalid/b14/make-demo@sha256:'+'a'*64, 'configuration_id': cfg, 'dockerfile_uri': 'artifact://b14-draft/job-draft01/Dockerfile', 'producer_job_id': 'job-draft01'}
manifest = {}


def artifact(authority, job, name, typ, content, repository=repo):
    uri = f'artifact://{authority}/{job}/{name}'
    path = C/'artifacts'/authority/job/name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(content, ensure_ascii=False, indent=2)+'\n').encode() if isinstance(content, dict) else content.encode()
    path.write_bytes(data)
    rec = {'artifact_id': job+'-'+name, 'type': typ, 'uri': uri, 'media_type': 'application/json' if name.endswith('.json') else 'text/plain', 'producer_job_id': job, 'repository_url': repository['url'], 'commit': repository['commit'], 'configuration_id': cfg, 'sha256': hashlib.sha256(data).hexdigest()}
    manifest[uri] = {'path': path.relative_to(ROOT).as_posix(), 'artifact': rec}
    return rec


docker = artifact('b14-draft', 'job-draft01', 'Dockerfile', 'DOCKERFILE', '# MANUAL E2 FIXTURE. Not generated or built by DRAFT.\nFROM gcc:13\nWORKDIR /workspace\nCOPY . .\nRUN make clean && make\nCMD ["make", "test"]\n')
image_meta = artifact('b14-draft', 'job-draft01', 'image.json', 'IMAGE_METADATA', {'image_ref': env['image_ref'], 'repository': repo, 'configuration_id': cfg, 'producer_job_id': 'job-draft01', 'available': False, 'source': 'MANUAL_FIXTURE'})


def logs(authority, job):
    return [artifact(authority, job, n, typ, 'MANUAL E2 FIXTURE: simulated '+n+' exit_code=0; no command was executed.\n') for n, typ in [('build.log', 'BUILD_LOG'), ('verify.log', 'VERIFY_LOG')]]


draft_logs = logs('b14-draft', 'job-draft01')


def result(rec=None, status='PASSED', code=0):
    return {'status': status, 'exit_code': code, 'log_uri': rec['uri'] if rec else None}


finding = {'finding_id': 'md-main-config', 'type': 'MISSING', 'target': 'main.o', 'dependency': 'config.h', 'commit': repo['commit'], 'detector': 'MANUAL_FIXTURE', 'location': {'path': 'Makefile', 'line': 1}, 'evidence': {'kind': 'MANUAL_FIXTURE', 'description': 'Synthetic example: main.c includes config.h; main.o declaration omits config.h.'}}
rd = {**copy.deepcopy(finding), 'finding_id': 'rd-main-unused', 'type': 'REDUNDANT', 'dependency': 'unused.h'}
rd['evidence']['description'] = 'Synthetic example: unused.h is declared but not used in this configuration.'


def report(job, repository, findings):
    return {'schema_version': '1.0', 'repository': repository, 'configuration_id': cfg, 'producer_job_id': job, 'findings': findings}


def analysis_artifacts(job, repository, findings):
    records = []
    for name, typ, deps in [('actual.json', 'ACTUAL_GRAPH', ['main.c', 'config.h']), ('declared.json', 'DECLARED_GRAPH', ['main.c', 'unused.h'])]:
        records.append(artifact('a14-check', job, name, typ, {'schema_version': '1.0', 'repository': repository, 'configuration_id': cfg, 'producer_job_id': job, 'kind': typ, 'nodes': ['main.o', 'main.c', 'config.h', 'unused.h'], 'edges': [{'target': 'main.o', 'dependency': d} for d in deps], 'source': 'MANUAL_FIXTURE'}, repository))
    records.append(artifact('a14-check', job, 'findings.json', 'ERROR_REPORT', report(job, repository, findings), repository))
    return records


full_artifacts = analysis_artifacts('job-full01', repo, [finding, rd])
inc_findings = [{**copy.deepcopy(f), 'commit': repo1['commit']} for f in [finding, rd]]
inc_artifacts = analysis_artifacts('job-incremental01', repo1, inc_findings)
md_report = artifact('a14-check', 'job-full01', 'md.json', 'ERROR_REPORT', report('job-full01', repo, [finding]))
repair_logs = logs('b14-repair', 'job-repair01')
patch = artifact('b14-repair', 'job-repair01', 'fix.patch', 'PATCH', 'diff --git a/Makefile b/Makefile\n--- a/Makefile\n+++ b/Makefile\n@@ -1,2 +1,2 @@\n-main.o: main.c unused.h\n+main.o: main.c unused.h config.h\n \tgcc -c main.c -o main.o\n')
recheck = artifact('b14-repair', 'job-repair01', 'recheck.json', 'RECHECK_REPORT', {'repository': repo, 'configuration_id': cfg, 'producer_job_id': 'job-repair01', 'patch_uri': patch['uri'], 'remaining_missing': 0, 'source': 'MANUAL_FIXTURE'})
requirements = {'platform': 'linux/amd64', 'language': 'C (demo)', 'toolchain': ['GCC 13', 'GNU Make'], 'base_image': 'gcc:13', 'system_dependencies': [], 'network': 'REQUIRED', 'environment_variables': {'MODE': '0'}, 'ports': [], 'test_data': []}
request_inputs = [
    {'repository': repo, 'build': build, 'requirements': requirements},
    {'repository': repo, 'build': build, 'environment': env},
    {'repository': repo1, 'build': build, 'environment': env, 'base_commit': repo['commit'], 'baseline': {'repository_url': repo['url'], 'commit': repo['commit'], 'configuration_id': cfg, 'actual_graph_uri': full_artifacts[0]['uri'], 'error_report_uri': full_artifacts[2]['uri']}},
    {'repository': repo, 'build': build, 'environment': env, 'md_report_uri': md_report['uri'], 'makefiles': ['Makefile']}
]
draft_result = {'environment': env, 'iterations': [{'index': 1, 'change_summary': 'Manual fixture for initial Dockerfile', 'selection_reason': 'Demonstrate successful output structure', 'patch_uri': None, 'build': result(draft_logs[0]), 'verify': result(draft_logs[1])}], 'build': result(draft_logs[0]), 'verify': result(draft_logs[1]), 'artifacts': [docker, image_meta, *draft_logs]}


def check_output(records):
    return {'actual_graph_uri': records[0]['uri'], 'declared_graph_uri': records[1]['uri'], 'error_report_uri': records[2]['uri'], 'artifacts': records}


candidate = {'candidate_id': 'candidate-1', 'patch_uri': patch['uri'], 'declaration_style': 'ATOMIC', 'style_explanation': 'Add an atomic prerequisite while preserving the existing declaration form.', 'decision': 'ACCEPTED', 'reason': 'Simulated build, test and missing-dependency recheck passed.', 'build': result(repair_logs[0]), 'verify': result(repair_logs[1]), 'recheck': {'status': 'PASSED', 'remaining_missing': 0, 'report_uri': recheck['uri']}}
out_values = [draft_result, check_output(full_artifacts), {**check_output(inc_artifacts), 'findings_delta': {'added': [], 'removed': []}}, {'patch_uri': patch['uri'], 'candidates': [candidate], 'artifacts': [patch, *repair_logs, recheck]}]
valid = C/'examples'/'valid'
samples = {}
for typ, inp, output, job in zip(TYPES, request_inputs, out_values, ['job-draft01', 'job-full01', 'job-incremental01', 'job-repair01']):
    name = typ.lower().replace('_check', '')
    req = {'schema_version': '1.0', 'trace_id': 'trace-pair14-demo', 'job_type': typ, 'execution': {'timeout_seconds': 1800, **({'max_iterations': 3} if typ == 'DRAFT' else {})}, 'idempotency_key': 'pair14-'+name+'-001', 'input': inp}
    response = {k: copy.deepcopy(v) for k, v in req.items() if k != 'idempotency_key'}
    response.update(job_id=job, status='SUCCEEDED', output=output, error=None)
    samples[name+'_request'] = req; samples[name+'_result'] = response
    samples[name+'_accepted'] = {'schema_version': '1.0', 'job_id': job, 'trace_id': req['trace_id'], 'status': 'QUEUED', 'status_url': '/v1/jobs/'+job}
for state in ['QUEUED', 'RUNNING', 'TIMED_OUT', 'CANCELLED', 'FAILED']:
    x = copy.deepcopy(samples['draft_result']); x.update(status=state, output=None)
    if state in ['TIMED_OUT', 'CANCELLED', 'FAILED']:
        x['error'] = {'code': {'TIMED_OUT': 'EXEC_4002', 'CANCELLED': 'EXEC_4004', 'FAILED': 'EXEC_4001'}[state], 'category': 'CONTROL' if state == 'CANCELLED' else 'SYSTEM', 'message': 'Manual fixture: '+state, 'retryable': state != 'CANCELLED', 'details': {}}
    samples['draft_'+state.lower()] = x
goal = copy.deepcopy(samples['draft_result']); goal['status'] = 'FAILED'; goal['output']['environment'] = None
goal['output']['iterations'] = []
for i in range(1,4):
    failurelog = artifact('b14-draft', 'job-draft01', f'failed-{i}.log', 'BUILD_LOG', f'MANUAL E2 FIXTURE: attempt {i} build exit_code=2. No actual execution.\n')
    goal['output']['artifacts'].append(failurelog)
    goal['output']['iterations'].append({'index': i, 'change_summary': 'Simulated dependency adjustment', 'selection_reason': 'Simulated unsuccessful attempt', 'patch_uri': None, 'build': result(failurelog, 'FAILED', 2), 'verify': result(None, 'NOT_RUN', None)})
goal['output']['build'] = goal['output']['iterations'][-1]['build']; goal['output']['verify'] = result(None, 'NOT_RUN', None)
goal['output']['artifacts'] = [r for r in goal['output']['artifacts'] if r['type'] != 'IMAGE_METADATA']
goal['error'] = {'code': 'ENV_3002', 'category': 'GOAL_UNMET', 'message': 'Maximum DRAFT attempts exhausted; no usable image produced.', 'retryable': False, 'details': {'reason': 'ITERATION_LIMIT', 'attempts': 3}}
samples['draft_goal_unmet'] = goal
failed_repair = copy.deepcopy(samples['repair_result']); failed_repair['status'] = 'FAILED'; failed_repair['output']['patch_uri'] = None
failed_repair['output']['candidates'][0].update(decision='REJECTED', reason='Simulated test failure: candidate rejected.')
rejected_log = artifact('b14-repair', 'job-repair01', 'rejected-verify.log', 'VERIFY_LOG', 'MANUAL E2 FIXTURE: simulated test exit_code=1; candidate rejected. No actual execution.\n')
failed_repair['output']['artifacts'].append(rejected_log)
failed_repair['output']['candidates'][0]['verify'] = result(rejected_log, 'FAILED', 1)
failed_repair['output']['candidates'][0]['recheck'] = {'status': 'NOT_RUN', 'remaining_missing': None, 'report_uri': None}
failed_repair['output']['artifacts'] = [r for r in failed_repair['output']['artifacts'] if r['type'] != 'RECHECK_REPORT']
failed_repair['error'] = {'code': 'REPAIR_6001', 'category': 'GOAL_UNMET', 'message': 'All candidates rejected.', 'retryable': False, 'details': {}}
samples['repair_goal_unmet'] = failed_repair
samples['input_error'] = {'schema_version': '1.0', 'trace_id': 'trace-pair14-demo', 'http_status': 422, 'error': {'code': 'INPUT_1002', 'category': 'INPUT', 'message': 'INCREMENTAL_CHECK requires baseline.', 'retryable': False, 'details': {'field': 'input.baseline'}}}
for name, value in samples.items():
    write(valid/(name+'.json'), value)
invalids = {}
x = copy.deepcopy(samples['draft_request']); x['job_type'] = 'ABC'; invalids['unknown_job_type'] = x
x = copy.deepcopy(samples['incremental_request']); del x['input']['baseline']; invalids['missing_baseline'] = x
x = copy.deepcopy(samples['draft_request']); x['input']['repository']['commit'] = 'main'; invalids['short_commit'] = x
x = copy.deepcopy(samples['incremental_request']); x['input']['baseline']['configuration_id'] = 'wrong'; invalids['baseline_configuration_mismatch'] = x
x = copy.deepcopy(samples['repair_request']); x['input']['md_report_uri'] = full_artifacts[2]['uri']; invalids['repair_contains_rd'] = x
x = copy.deepcopy(samples['repair_request']); x['input']['repository']['commit'] = '3'*40; invalids['repair_commit_mismatch'] = x
x = copy.deepcopy(samples['draft_result']); x['output']['verify']['exit_code'] = 1; invalids['false_success'] = x
for name, value in invalids.items():
    write(C/'examples'/'invalid'/(name+'.json'), value)
write(C/'artifact-manifest.json', {'schema_version': '1.0', 'source': 'MANUAL_FIXTURE', 'artifacts': manifest})
print(f'Generated schema, {len(samples)} valid examples, {len(invalids)} invalid examples and {len(manifest)} artifacts.')
