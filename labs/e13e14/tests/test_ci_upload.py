import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_ci_upload import prepare


class CIUploadTests(unittest.TestCase):
    def test_manifest_bound_hidden_file_keeps_original_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'ci-e14/base-project'
            source.mkdir(parents=True)
            data = b'*.o\napp\n'
            (source / '.gitignore').write_bytes(data)
            manifest = [{'uri':'base-project/.gitignore', 'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)}]
            (source.parent / 'result.json').write_text(json.dumps({'artifacts':manifest}))
            audit = prepare(root, root / 'upload')
            self.assertTrue(audit['complete'])
            self.assertEqual((root / 'upload/ci-e14/base-project/.gitignore').read_bytes(), data)

    def test_partial_failure_keeps_only_scoped_safe_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / 'ci-e14/logs'
            logs.mkdir(parents=True)
            (logs / 'build.log').write_text('build failed: missing make')
            (logs / '.env').write_text('must not be uploaded')
            (logs / 'credentials.json').write_text('must not be uploaded')
            (logs / '.hidden').mkdir()
            (logs / '.hidden/log.txt').write_text('must not be uploaded')
            (logs / '.git').mkdir()
            (logs / '.git/config').write_text('must not be uploaded')
            (root / 'ci-e14-services.log').write_text('draft failed')
            (root / 'unrelated.log').write_text('must not be uploaded')
            audit = prepare(root, root / 'upload')
            self.assertFalse(audit['complete'])
            self.assertEqual(audit['state'], 'partial')
            self.assertFalse(audit['result_present'])
            self.assertEqual(set(audit['copied']), {'ci-e14/logs/build.log','ci-e14-services.log'})

    def test_sensitive_content_is_excluded_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / 'ci-e14/logs'
            logs.mkdir(parents=True)
            fake = 'sk-' + 'FAKE0123456789' * 3
            (logs / 'failed.log').write_text('diagnostic ' + fake)
            audit = prepare(root, root / 'upload')
            self.assertFalse(audit['complete'])
            self.assertFalse((root / 'upload/ci-e14/logs/failed.log').exists())
            self.assertNotIn(fake, (root / 'upload/upload-audit.json').read_text())

    def test_json_credentials_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / 'ci-e14/logs'
            logs.mkdir(parents=True)
            (logs / 'failed.json').write_text(json.dumps({'password':'FAKE_TEST_PASSWORD_12345'}))
            audit = prepare(root, root / 'upload')
            self.assertFalse(audit['complete'])
            self.assertFalse((root / 'upload/ci-e14/logs/failed.json').exists())

    def test_existing_staging_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'upload').mkdir()
            (root / 'upload/.env').write_text('untrusted prior content')
            with self.assertRaises(FileExistsError):
                prepare(root, root / 'upload')

    def test_path_escape_is_rejected_even_when_manifest_declares_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'ci-e14'
            source.mkdir()
            (root / 'outside.txt').write_text('must not be uploaded')
            invalid = ['../outside.txt', '/etc/passwd', 'C:/secret.txt', 'logs/../outside.txt', 'logs/.git/config']
            (source / 'result.json').write_text(json.dumps({'artifacts':[{'uri':uri} for uri in invalid]}))
            audit = prepare(root, root / 'upload')
            self.assertFalse(audit['complete'])
            self.assertEqual(len(audit['errors']), len(invalid))
            self.assertEqual(audit['copied'], ['ci-e14/result.json'])

    def test_manifest_hash_mismatch_blocks_complete_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / 'ci-e14/logs'
            logs.mkdir(parents=True)
            (logs / 'build.log').write_text('actual failure log')
            manifest = [{'uri':'logs/build.log', 'sha256':'0'*64, 'bytes':1}]
            (logs.parent / 'result.json').write_text(json.dumps({'artifacts':manifest}))
            audit = prepare(root, root / 'upload')
            self.assertFalse(audit['complete'])
            self.assertTrue((root / 'upload/ci-e14/logs/build.log').is_file())


if __name__ == '__main__':
    unittest.main()
