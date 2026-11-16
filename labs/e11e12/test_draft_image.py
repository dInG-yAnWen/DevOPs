import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import draft_image


def make_project(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'main.c').write_text('int main(void){return 0;}\n')
    (root / 'config.h').write_text('#define BASE 4\n')
    (root / 'feature.h').write_text('#define FEATURE 8\n')
    (root / 'Makefile').write_text('app: main.o\n\t$(CC) main.o -o app\n')
    dockerfile = root / 'candidate.Dockerfile'
    dockerfile.write_text('FROM scratch\nCOPY . /work\n')
    return root, dockerfile


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_configuration_id_is_stable_and_sensitive(self):
        inputs = {'main.c': 'a', 'config.h': 'b', 'feature.h': 'c', 'Makefile': 'd'}
        first = draft_image.configuration_id(inputs, 'f' * 64, '12')
        second = draft_image.configuration_id(dict(inputs), 'f' * 64, '12')
        changed = draft_image.configuration_id(dict(inputs, **{'main.c': 'z'}), 'f' * 64, '12')
        self.assertEqual(first, second)
        self.assertRegex(first, r'^[0-9a-f]{64}$')
        self.assertNotEqual(first, changed)

    def test_missing_input_is_rejected(self):
        project = self.root / 'missing'
        project.mkdir()
        (project / 'main.c').write_text('x')
        with self.assertRaisesRegex(ValueError, 'MISSING_INPUT'):
            draft_image.input_hashes(project)

    def test_existing_output_is_rejected(self):
        project, dockerfile = make_project(self.root / 'p1')
        out = self.root / 'out1'
        out.mkdir()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            draft_image.deliver(project, dockerfile, out, 'tag')

    def _patched_run(self, output):
        def fake_run(argv, log_path, cwd=None, timeout=1800):
            log = Path(log_path)
            log.parent.mkdir(parents=True, exist_ok=True)
            if argv[0] == 'docker' and argv[1] == 'run':
                log.write_text(output)
            elif argv[0] == 'docker' and argv[1] == 'save':
                Path(argv[argv.index('-o') + 1]).write_bytes(b'archive')
                log.write_text('saved\n')
            else:
                log.write_text('ok\n')
            return {'argv': [str(x) for x in argv], 'exit_code': 0,
                    'seconds': 0.0, 'log': str(log)}
        return fake_run

    def test_success_manifest_binds_all_fields(self):
        project, dockerfile = make_project(self.root / 'p2')
        out = self.root / 'out2'
        with mock.patch.object(draft_image, 'run', self._patched_run('12\n')), \
                mock.patch.object(draft_image, 'inspect_image',
                                  return_value='sha256:' + 'a' * 64):
            manifest, code = draft_image.deliver(project, dockerfile, out, 'course-draft:test')
        self.assertEqual(code, 0)
        self.assertTrue(manifest['passed'])
        self.assertEqual(manifest['image']['id'], 'sha256:' + 'a' * 64)
        self.assertEqual(manifest['actual_output'], '12\n')
        self.assertTrue(manifest['output_matches'])
        self.assertRegex(manifest['configuration_id'], r'^[0-9a-f]{64}$')
        self.assertTrue(manifest['job_id'].startswith('job-'))
        self.assertTrue(manifest['trace_id'].startswith('trace-'))
        self.assertIsNotNone(manifest['archive']['sha256'])
        saved = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(saved['configuration_id'], manifest['configuration_id'])

    def test_output_mismatch_fails(self):
        project, dockerfile = make_project(self.root / 'p3')
        out = self.root / 'out3'
        with mock.patch.object(draft_image, 'run', self._patched_run('11\n')), \
                mock.patch.object(draft_image, 'inspect_image',
                                  return_value='sha256:' + 'b' * 64):
            manifest, code = draft_image.deliver(project, dockerfile, out, 'course-draft:test')
        self.assertEqual(code, 3)
        self.assertFalse(manifest['passed'])
        self.assertFalse(manifest['output_matches'])


if __name__ == '__main__':
    unittest.main()
