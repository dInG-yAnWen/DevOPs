"""E6 public CLI behavior without Docker or third-party test dependencies."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from draft.cli import build_parser, main


class E6CLITest(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_auto_build_forwards_inputs_and_budgets(self):
        with patch("draft.cli.auto_build", return_value={"status": "SUCCEEDED"}) as run:
            code, result = self.invoke([
                "auto-build", "--fixture", "project", "--candidate", "fixed.Dockerfile",
                "--provenance", "source.json", "--out", "output", "--timeout", "17",
                "--verify-timeout", "3",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "SUCCEEDED")
        run.assert_called_once_with("project", "fixed.Dockerfile", "output", "hello E3", 17, 3, "source.json")

    def test_timeout_is_a_nonzero_cli_result(self):
        with patch("draft.cli.auto_build", return_value={"status": "TIMED_OUT"}):
            code, result = self.invoke(["auto-build", "--candidate", "c", "--out", "o"])
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "TIMED_OUT")

    def test_preflight_error_is_json_and_nonzero(self):
        with patch("draft.cli.auto_build", side_effect=ValueError("Use a new directory")):
            code, result = self.invoke(["auto-build", "--candidate", "c", "--out", "o"])
        self.assertEqual(code, 1)
        self.assertIn("new directory", result["error"])

    def test_integrity_valid_failure_does_not_become_success(self):
        with patch("draft.cli.verify_evidence", return_value={"verified": True, "status": "FAILED"}):
            code, _ = self.invoke(["verify-evidence", "--run-dir", "run"])
        self.assertEqual(code, 1)

    def test_successful_evidence_is_zero(self):
        with patch("draft.cli.verify_evidence", return_value={"verified": True, "status": "SUCCEEDED"}):
            code, _ = self.invoke(["verify-evidence", "--run-dir", "run"])
        self.assertEqual(code, 0)

    def test_invalid_budgets_are_rejected(self):
        for option, value in (("--timeout", "0"), ("--verify-timeout", "-1")):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                build_parser().parse_args(["auto-build", "--candidate", "c", "--out", "o", option, value])


if __name__ == "__main__":
    unittest.main()
