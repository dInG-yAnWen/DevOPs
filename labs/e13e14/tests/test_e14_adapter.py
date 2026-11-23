import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[2]/'e11e12')]
import orchestrate
import service
from test_project_profile import project_repo, HEADER_PROBE


class E14Adapters(unittest.TestCase):
    def test_project_path_and_probe_reach_four_role_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'data').mkdir()
            project, commit = project_repo(root/'data/repo', nested=True)
            candidate = root/'data/candidate.Dockerfile'
            candidate.write_text('candidate')
            request = {'repo':'/course/data/repo','candidate':'/course/data/candidate.Dockerfile',
                       'base':commit,'target':commit,'project_path':'e13/projects/a14',
                       'expected_output':'15','header_probe':HEADER_PROBE}
            calls = []

            def call(role, payload, evidence):
                calls.append((role,payload))
                if role == 'echecker':
                    return {'status':'SUCCEEDED','report':'/course/work/run/incremental/report.json','sha256':'a'*64}
                return {'status':'SUCCEEDED','result':{'findings':[]}}

            with patch.object(orchestrate,'ROOT',root), patch.object(orchestrate,'call',side_effect=call):
                result = orchestrate.execute(request,root/'work/run')
            self.assertEqual(result['status'],'SUCCEEDED',result)
            self.assertEqual([x['name'] for x in result['stages']],
                             ['draft','full-check','incremental-check','repair','recheck'])
            self.assertEqual(result['target_commit'],commit)
            self.assertTrue(all(p['project'].endswith('/e13/projects/a14') for _,p in calls))
            self.assertEqual({p['job_id'] for _,p in calls},{result['job_id']})
            self.assertEqual({p['trace_id'] for _,p in calls},{result['trace_id']})
            repair = next(p for role,p in calls if role=='mdfixer')
            self.assertEqual(repair['expected_output'],'15')
            self.assertEqual(repair['header_probe'],HEADER_PROBE)
            self.assertEqual((project/'adjustment.h').read_text(),'#define ADJUSTMENT 3\n')

    def test_preflight_failure_still_preserves_request_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = {'repo':'/course/../../outside','candidate':'/course/data/candidate'}
            with patch.object(orchestrate,'ROOT',root):
                result = orchestrate.execute(request,root/'work/failure')
            self.assertEqual(result['status'],'FAILED')
            self.assertEqual(json.loads((root/'work/failure/request.json').read_text()),request)
            self.assertTrue((root/'work/failure/result.json').is_file())

    def test_mdfixer_passes_behavior_configuration_to_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root/'work/project'
            project.mkdir(parents=True)
            report = root/'work/report.json'
            report.write_text(json.dumps({'schema_version':'e11e12-1','kind':'incremental-check',
                'status':'SUCCEEDED','commit':'a'*40,'job_id':'job-test','trace_id':'trace-test','data':{}}))
            data = {'project':str(project),'out':str(root/'work/repair'),'report':str(report),
                    'report_sha256':service.sha(report),'target_commit':'a'*40,
                    'job_id':'job-test','trace_id':'trace-test','expected_output':'15','header_probe':HEADER_PROBE}
            with patch.object(service,'ROOT',root), patch.object(service,'ROLE','mdfixer'), \
                    patch.object(service,'patch',return_value=('patch\n',[])), \
                    patch.object(service,'validate',return_value={'accepted':True}) as validate:
                result = service.run(data)
            self.assertEqual(result['status'],'SUCCEEDED')
            self.assertEqual(validate.call_args.kwargs,{'expected_output':'15','header_probe':HEADER_PROBE})
            self.assertEqual((root/'work/repair/candidate.patch').read_bytes(),b'patch\n')


class HttpBoundaries(unittest.TestCase):
    def server(self):
        server = HTTPServer(('127.0.0.1',0),service.Handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_real_http_success_carries_and_checks_job_trace(self):
        port = self.server()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(service,'ROLE','draft'), \
                patch.object(service,'run',return_value={'status':'SUCCEEDED'}), \
                patch.dict(orchestrate.PORTS,{'draft':port}), contextlib.redirect_stdout(io.StringIO()):
            result = orchestrate.call('draft',{'job_id':'job-1','trace_id':'trace-1'},Path(tmp)/'response.json')
        self.assertEqual((result['role'],result['job_id'],result['trace_id']),('draft','job-1','trace-1'))

    def test_timeout_preserves_http_error_identity_and_status(self):
        port = self.server()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(service,'ROLE','draft'), \
                patch.object(service,'run',side_effect=ValueError('DRAFT_TIMED_OUT: test injection')), \
                patch.object(service.traceback,'print_exc'), \
                patch.dict(orchestrate.PORTS,{'draft':port}), contextlib.redirect_stdout(io.StringIO()):
            evidence = Path(tmp)/'response.json'
            with self.assertRaises(orchestrate.StageFailure) as caught:
                orchestrate.call('draft',{'job_id':'job-1','trace_id':'trace-1'},evidence)
            saved = json.loads(evidence.read_text())
            self.assertEqual(saved['status'],'TIMED_OUT')
            self.assertEqual(saved['job_id'],'job-1')
            self.assertEqual(caught.exception.response['error_code'],'TIMEOUT')


if __name__ == '__main__':
    unittest.main()
