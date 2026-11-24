import importlib.util
from pathlib import Path
import unittest


script = Path(__file__).resolve().parents[2] / 'scripts/secret_scan.py'
spec = importlib.util.spec_from_file_location('course_scanner', script)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class RegexAssignmentTests(unittest.TestCase):
    def test_compiled_pattern_in_source_and_git_diff(self):
        definition = 'FIELD_TOKEN' + ' = ' + "re.compile(r'(?i)[a-z]+')"
        self.assertEqual(scanner.scan_text(definition, 'source.py'), [])
        self.assertEqual(scanner.scan_text('+' + definition, 'git-history'), [])

    def test_quoted_value_and_separate_token_are_still_reported(self):
        literal = 'FIELD_TOKEN' + ' = ' + repr('re.compile(r')
        self.assertEqual(len(scanner.scan_text(literal, 'source.py')), 1)
        fixture = 'sk-' + 'F' * 24
        definition = 'FIELD_TOKEN' + ' = ' + "re.compile(r'" + fixture + "')"
        hits = scanner.scan_text(definition, 'source.py')
        self.assertEqual(len(hits), 1)
        self.assertIn('LLM/API Key', hits[0])
