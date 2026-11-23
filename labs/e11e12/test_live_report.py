"""Small regressions for live provenance, legacy binding, and early rejection."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
import live_report as live

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e13e14'))
from handoff_a_to_b import make_handoff


class LiveReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.project = self.repo / 'project'
        self.project.mkdir(parents=True)
        for name, raw in {'Makefile': b'main.o: main.c config.h\n',
                          'main.c': b'#include "config.h"\n',
                          'helper.c': b'int helper(void) { return 7; }\r\n',
                          'config.h': b'#define BASE 5\n'}.items():
            (self.project / name).write_bytes(raw)
        self.git('init')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@localhost', 'commit', '-m', 'input')
        self.sha = self.git('rev-parse', 'HEAD').strip()
        self.inputs = live.input_fingerprints(self.project)
        self.source = self.root / 'a-run'
        self.source.mkdir()
        self.out = self.root / 'b-run'
        self.out.mkdir()

    def git(self, *args):
        return subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(self.repo), *args],
                              check=True, capture_output=True, text=True).stdout

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(value, indent=2) + '\n').encode())

    def artifact(self, relative):
        raw = (self.source / relative).read_bytes()
        return {'uri': 'artifact://job-a/' + relative, 'sha256': live.digest(raw), 'bytes': len(raw)}

    def request(self, fingerprints=True, full=False):
        data = {'commit': self.sha, 'findings': []}
        if fingerprints:
            data['input_sha256'] = self.inputs
        artifacts = []
        if full:
            self.write_json(self.source / 'target-full/findings.json',
                            {'status': 'SUCCEEDED', 'input_sha256': self.inputs})
            artifacts.append(self.artifact('target-full/findings.json'))
            shutil.copytree(self.project, self.source / 'target-project/project')
        stage = {'schema_version': 'e11e12-1', 'kind': 'incremental-check',
                 'status': 'SUCCEEDED', 'commit': self.sha, 'job_id': 'job-a',
                 'trace_id': 'trace-a', 'data': data, 'artifacts': artifacts}
        self.write_json(self.source / 'incremental-check.json', stage)
        self.write_json(self.source / 'result.json',
                        {'schema_version': 'e11e12-1', 'status': 'SUCCEEDED',
                         'target_commit': self.sha, 'job_id': 'job-a', 'trace_id': 'trace-a',
                         'stages': [{'name': 'incremental-check',
                                     'artifact': self.artifact('incremental-check.json')}]})
        self.fixed = self.root / 'fixed-md.json'
        raw = (json.dumps(make_handoff(self.source / 'result.json', self.sha), indent=2) + '\n').encode()
        self.fixed.write_bytes(raw.replace(b'\n', b'\r\n'))
        return {'mode': 'e11-b', 'repo': str(self.repo), 'base': self.sha, 'target': self.sha,
                'project_path': 'project', 'fixed_report': str(self.fixed),
                'fixed_report_sha256': live.digest(self.fixed.read_bytes()),
                'source_result': str(self.source / 'result.json')}

    def bind(self, prepared):
        return live.bind_live_inputs(prepared, self.repo, self.sha, self.project, 'project', self.out)

    def test_present_fingerprints_need_no_full_report_or_a_snapshot(self):
        request = self.request()
        raw = self.fixed.read_bytes()
        current, files = self.bind(live.preflight_fixed_report(request, self.out))
        self.assertEqual(current['input_sha256'], self.inputs)
        self.assertFalse(json.loads(files[0].read_bytes())['derived_missing_fingerprints'])
        self.assertEqual((self.out / 'fixed-md-input.json').read_bytes(), raw)

    def test_missing_fingerprints_use_bound_evidence_without_changing_original(self):
        request = self.request(fingerprints=False, full=True)
        raw = self.fixed.read_bytes()
        current, files = self.bind(live.preflight_fixed_report(request, self.out))
        self.assertEqual(current['input_sha256'], self.inputs)
        self.assertTrue(json.loads(files[0].read_bytes())['derived_missing_fingerprints'])
        self.assertNotIn('input_sha256', json.loads(raw)['data'])
        self.assertEqual((self.out / 'fixed-md-input.json').read_bytes(), raw)

    def test_missing_fingerprints_cannot_be_filled_without_source_evidence(self):
        prepared = live.preflight_fixed_report(self.request(fingerprints=False), self.out)
        with self.assertRaises(live.ReportError) as caught:
            self.bind(prepared)
        self.assertEqual(caught.exception.code, 'SOURCE_INPUTS_REQUIRED')

    def test_c2_and_c3_rejected_before_snapshot_or_draft(self):
        request = self.request()
        for case, expected in [('old-target', 'STALE_REPORT'), ('changed-bytes', 'ARTIFACT_HASH_MISMATCH')]:
            changed = dict(request)
            if case == 'old-target':
                changed['target'] = 'a' * 40
            else:
                self.fixed.write_bytes(self.fixed.read_bytes() + b'\n')
            with patch.object(pipeline, 'snapshot') as snapshot:
                result = pipeline.execute(changed, self.root / case)
            self.assertEqual(result['error']['code'], expected)
            snapshot.assert_not_called()

    def test_changed_source_stage_hash_is_rejected(self):
        request = self.request()
        stage = self.source / 'incremental-check.json'
        stage.write_bytes(stage.read_bytes() + b'\n')
        with self.assertRaises(live.ReportError) as caught:
            live.preflight_fixed_report(request, self.out)
        self.assertEqual(caught.exception.code, 'ARTIFACT_HASH_MISMATCH')

    def test_dirty_target_cannot_supply_fingerprints(self):
        prepared = live.preflight_fixed_report(self.request(), self.out)
        (self.project / 'main.c').write_bytes(b'changed\n')
        with self.assertRaises(live.ReportError) as caught:
            self.bind(prepared)
        self.assertEqual(caught.exception.code, 'STALE_REPORT')

    def test_legacy_without_source_requires_no_new_fields(self):
        request = self.request()
        legacy = json.loads(self.fixed.read_bytes())
        del legacy['source_report']
        self.write_json(self.fixed, legacy)
        for key in ('source_result', 'fixed_report_sha256'):
            del request[key]
        current, files = self.bind(live.preflight_fixed_report(request, self.out))
        self.assertEqual(current, legacy['data'])
        self.assertEqual(files, [])


if __name__ == '__main__':
    unittest.main()
