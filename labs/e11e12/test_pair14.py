import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pair14
import pipeline
import server


class Pair14Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / 'handoff'
        self.bundle.mkdir()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'E12 test fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.workdir = 'fixture/project'
        project = self.repo / self.workdir
        project.mkdir(parents=True)
        self.makefile = f'{self.workdir}/Makefile'
        (project / 'Makefile').write_bytes(b'main.o: main.c\n\tcc -c main.c -o main.o\n')
        (project / 'main.c').write_bytes(b'int main(void) { return 0; }\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'C0')
        self.base = self.git('rev-parse', 'HEAD')
        (project / 'feature.h').write_bytes(b'#define FEATURE 2\n')
        (project / 'main.c').write_bytes(b'#include "feature.h"\nint main(void) { return FEATURE; }\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'C1')
        self.target = self.git('rev-parse', 'HEAD')
        self.url = 'https://github.com/example/repository.git'
        self.repository = {'url': self.url, 'commit': self.target}
        self.trace = 'trace-test-fixture'
        self.cfg = 'cfg-test-fixture'
        self.image = 'registry.example.invalid/test@sha256:' + 'a' * 64
        self.report = {
            'schema_version': '1.0', 'repository': self.repository, 'configuration_id': self.cfg,
            'producer_job_id': 'job-target', 'findings': [{
                'finding_id': 'md-feature', 'type': 'MISSING', 'target': 'main.o', 'dependency': 'feature.h',
                'commit': self.target, 'detector': 'contract test',
                'location': {'path': self.makefile, 'line': 1},
                'evidence': {'kind': 'DYNAMIC_TRACE', 'description': 'Synthetic report payload for the contract test'},
            }],
        }
        self.spec = self.handoff()

    def git(self, *args):
        return subprocess.check_output(
            ['git', '-c', 'core.autocrlf=false', '-C', str(self.repo), *args],
            encoding='utf-8',
        ).strip()

    def stage(self, job, commit):
        return {'job_id': job, 'commit': commit, 'trace_id': self.trace, 'status': 'SUCCEEDED',
                'configuration_id': self.cfg, 'image_ref': self.image}

    def file(self, name, raw):
        (self.bundle / name).write_bytes(raw)
        return {'path': name, 'sha256': pair14.sha256(raw)}

    def artifact(self, namespace, job_id, kind, name, raw):
        reference = self.file(name, raw)
        return {'path': name, 'artifact': {
            'artifact_id': f'{job_id}-{name}', 'producer_job_id': job_id,
            'uri': f'artifact://{namespace}/{job_id}/{name}', 'type': kind,
            'media_type': 'application/json' if name.endswith('.json') else 'text/plain',
            'repository_url': self.url, 'commit': self.target, 'configuration_id': self.cfg,
            'sha256': reference['sha256'],
        }}

    def graph(self, stage, kind, filename, source):
        payload = {'repository': {'url': self.url, 'commit': stage['commit']}, 'kind': kind,
                   'producer_job_id': stage['job_id'], 'configuration_id': self.cfg,
                   'source': source, 'edges': []}
        return self.file(filename, json.dumps(payload).encode())

    def handoff(self):
        draft = self.stage('job-draft', self.target)
        draft.update(
            dockerfile=self.artifact('b14-draft', 'job-draft', 'DOCKERFILE', 'Dockerfile', b'# test input\n'),
            build_log=self.artifact('b14-draft', 'job-draft', 'BUILD_LOG', 'build.log', b'test log\n'),
            verify_log=self.artifact('b14-draft', 'job-draft', 'VERIFY_LOG', 'verify.log', b'test log\n'),
            build_exit_code=0, verify_exit_code=0,
        )
        baseline = self.stage('job-baseline', self.base)
        baseline.update(actual_graph=self.graph(baseline, 'ACTUAL_GRAPH', 'baseline-actual.json', 'DYNAMIC_TRACE'),
                        declared_graph=self.graph(baseline, 'DECLARED_GRAPH', 'baseline-declared.json', 'MAKE_DATABASE'))
        current = self.stage('job-target', self.target)
        current.update(base_commit=self.base,
                       actual_graph=self.graph(current, 'ACTUAL_GRAPH', 'target-actual.json', 'STATIC_INFERENCE'),
                       declared_graph=self.graph(current, 'DECLARED_GRAPH', 'target-declared.json', 'MAKE_DATABASE'),
                       md_report=self.artifact('a14-check', 'job-target', 'ERROR_REPORT', 'md.json',
                                               json.dumps(self.report).encode()))
        repair = {
            'schema_version': '1.0', 'trace_id': self.trace, 'job_type': 'REPAIR',
            'execution': {'timeout_seconds': 15}, 'idempotency_key': 'repair-test-fixture',
            'input': {
                'repository': self.repository,
                'build': {'command': 'make clean && make', 'verify_command': './app', 'working_directory': self.workdir},
                'environment': {'image_ref': self.image, 'configuration_id': self.cfg,
                                'producer_job_id': draft['job_id'], 'dockerfile_uri': draft['dockerfile']['artifact']['uri']},
                'md_report_uri': current['md_report']['artifact']['uri'],
                'makefiles': [self.makefile],
            },
        }
        return {'repair_request': repair, 'draft': draft, 'full_check': baseline,
                'incremental_check': current, 'recheck_file': 'recheck-return.json'}

    def request(self):
        handoff = self.file('handoff.json', json.dumps(self.spec).encode())
        return {'mode': 'e12', 'repo': str(self.repo), 'base': self.base, 'target': self.target,
                'handoff': str(self.bundle / handoff['path']), 'handoff_sha256': handoff['sha256']}

    def test_rejects_old_or_fixture_report(self):
        self.report['repository'] = dict(self.repository, commit=self.base)
        with self.assertRaisesRegex(pair14.HandoffError, 'another commit'):
            pair14.load_md_report(json.dumps(self.report), self.repository, self.cfg, 'job-target', [self.makefile])
        self.report['repository'] = self.repository
        self.report['findings'][0]['evidence']['kind'] = 'MANUAL_FIXTURE'
        with self.assertRaisesRegex(pair14.HandoffError, 'actual detector'):
            pair14.load_md_report(json.dumps(self.report), self.repository, self.cfg, 'job-target', [self.makefile])

    def test_tampered_report_stops_before_patch(self):
        request = self.request()
        (self.bundle / 'md.json').write_bytes(b'{}')
        output = self.root / 'output'
        result = pipeline.execute(request, output)
        self.assertEqual(result['error']['code'], 'ARTIFACT_HASH_MISMATCH')
        self.assertFalse((output / 'candidate.patch').exists())

    def test_rejects_recheck_for_another_patch(self):
        job = 'job-patch-mismatch'
        recheck = self.stage('job-recheck', self.target)
        recheck.update(repository_url=self.url, patch_uri=f'artifact://b14-repair/{job}/candidate.patch',
                       patch_sha256='0' * 64)
        self.file('recheck-return.json', json.dumps(recheck).encode())
        result = pipeline.execute(self.request(), self.root / 'output', job)
        self.assertEqual(result['error']['code'], 'ARTIFACT_BINDING_MISMATCH')
        self.assertEqual([stage['name'] for stage in result['stages']],
                         ['draft', 'full-check', 'incremental-check', 'repair'])

    def test_archives_a14_failure_without_success_logs(self):
        job = 'job-recheck-rejected'
        repair = self.spec['repair_request']['input']
        patchfile = self.root / 'expected.patch'
        pair14.candidate(self.repo, self.base, repair, self.report, patchfile)
        uri = f'artifact://b14-repair/{job}/candidate.patch'
        failure = {'status': 'FAILED', 'reason': 'Program output differs from expected value', 'patch_uri': uri}
        recheck = self.stage('job-recheck', self.target)
        recheck.update(status='FAILED', repository_url=self.url, patch_uri=uri,
                       patch_sha256=pair14.sha256(patchfile.read_bytes()),
                       a14_failure=self.file('failure.json', json.dumps(failure).encode()))
        self.file('recheck-return.json', json.dumps(recheck).encode())
        output = self.root / 'output'
        result = pipeline.execute(self.request(), output, job)
        self.assertEqual(result['error']['code'], 'RECHECK_FAILED')
        stage = json.loads((output / 'recheck.json').read_bytes())
        self.assertEqual(stage['status'], 'FAILED')
        self.assertFalse(stage['data']['accepted'])
        self.assertEqual(json.loads((output / 'a14-recheck-failure.json').read_bytes()), failure)

    def test_loopback_e12_submit_download_recheck_and_idempotency(self):
        store = server.Store(self.root / 'jobs', data_root=self.root)
        self.addCleanup(store.pool.shutdown)
        with server.create_server('127.0.0.1', 0, store) as http:
            worker = threading.Thread(target=http.serve_forever, daemon=True)
            worker.start()
            try:
                self.run_api(http.server_port)
            finally:
                http.shutdown()
                worker.join()

    def run_api(self, port):
        url = f'http://127.0.0.1:{port}'
        opener = build_opener(ProxyHandler({}))

        def get_json(path):
            with opener.open(url + path, timeout=5) as response:
                return json.load(response)

        def submit(job_input):
            body = json.dumps({'idempotency_key': 'sample-api-run', 'input': job_input}).encode()
            return opener.open(Request(url + '/v1/jobs', body, {'Content-Type': 'application/json'}), timeout=5)

        self.assertEqual(get_json('/health')['status'], 'ok')
        job_input = self.request()
        with submit(job_input) as response:
            self.assertEqual(response.status, 202)
            job = json.load(response)['job_id']
        with submit(job_input) as response:
            self.assertEqual(json.load(response)['job_id'], job)
        with self.assertRaises(HTTPError) as error:
            submit(dict(job_input, target=self.base))
        self.assertEqual(error.exception.code, 409)
        path = f'/v1/jobs/{job}'
        deadline = time.monotonic() + 10
        while True:
            try:
                manifest = get_json(path + '/files/candidate-manifest.json')
                break
            except HTTPError as error:
                if error.code != 404 or time.monotonic() >= deadline:
                    self.fail(f'Candidate was not published: {get_json(path)}')
                time.sleep(0.05)
        with opener.open(url + manifest['download_path'], timeout=5) as response:
            patch = response.read()
            self.assertEqual(response.headers['X-Content-SHA256'], pair14.sha256(patch))
        self.assertEqual(manifest['artifact']['sha256'], pair14.sha256(patch))
        self.assertIn(f'diff --git a/{self.makefile} b/{self.makefile}'.encode(), patch)
        self.assertIn(f'+++ b/{self.makefile}'.encode(), patch)
        self.assertIn(b'+main.o: main.c feature.h', patch)
        recheck = self.stage('job-recheck', self.target)
        recheck.update(repository_url=self.url, patch_uri=manifest['artifact']['uri'],
                       patch_sha256=manifest['artifact']['sha256'], build_exit_code=0, verify_exit_code=0,
                       findings=self.file('recheck-findings.json', b'{"findings":[]}'),
                       build_log=self.file('recheck-build.log', b'test log\n'),
                       verify_log=self.file('recheck-verify.log', b'test log\n'))
        native = {'repository': self.repository, 'configuration_id': self.cfg,
                  'producer_job_id': recheck['job_id'], 'patch_uri': recheck['patch_uri'],
                  'patch_sha256': recheck['patch_sha256'], 'source': 'DYNAMIC_TRACE',
                  'remaining_missing': 0, 'status': 'SUCCEEDED'}
        recheck['a14_result'] = self.file('a14-recheck.json', json.dumps(native).encode())
        pending = self.bundle / 'recheck.tmp'
        pending.write_bytes(json.dumps(recheck).encode())
        pending.replace(self.bundle / 'recheck-return.json')
        deadline = time.monotonic() + 10
        while (state := get_json(path))['status'] in ('QUEUED', 'RUNNING') and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(state['status'], 'SUCCEEDED', state)
        self.assertEqual(state['trace_id'], self.trace)
        result = get_json(path + '/artifacts')
        self.assertEqual(result['trace_id'], self.trace)
        self.assertEqual([stage['name'] for stage in result['stages']],
                         ['draft', 'full-check', 'incremental-check', 'repair', 'recheck'])
        for stage in result['stages']:
            with self.subTest(stage=stage['name']):
                with opener.open(url + path + '/files/' + stage['name'] + '.json', timeout=5) as response:
                    body = response.read()
                    self.assertEqual(response.headers['X-Content-SHA256'], stage['artifact']['sha256'])
                self.assertEqual(pair14.sha256(body), stage['artifact']['sha256'])
                envelope = json.loads(body)
                self.assertEqual(envelope['job_id'], job)
                self.assertEqual(envelope['trace_id'], self.trace)
        rechecked = get_json(path + '/files/recheck.json')
        self.assertTrue(rechecked['data']['accepted'])
        self.assertEqual(rechecked['data']['remaining_missing'], 0)
        self.assertEqual(self.git('status', '--porcelain'), '')
