"""Verify public E7 CLI outcomes independently of Docker."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from draft.cli import main


class E7CLITests(unittest.TestCase):
    def invoke(self, arguments):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(arguments)
        return code, json.loads(stream.getvalue())

    def test_gate_forwards_explicit_inputs(self):
        with patch("draft.cli.run_gate", return_value={"passed": True}) as run:
            code, _ = self.invoke(["quality-gate", "--fixture", "f", "--candidate", "c", "--out", "o",
                                   "--provenance", "p", "--build-timeout", "17", "--case", "success"])
        self.assertEqual(code, 0)
        run.assert_called_once_with("f", "c", "o", "p", 17, ["success"])

    def test_partial_gate_is_not_a_full_pass(self):
        with patch("draft.cli.run_gate", return_value={"passed": False, "status": "INCOMPLETE"}):
            code, result = self.invoke(["quality-gate", "--candidate", "c", "--out", "o"])
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "INCOMPLETE")

    def test_offline_failed_gate_stays_nonzero(self):
        with patch("draft.cli.verify_gate", return_value={"verified": True, "passed": False}):
            code, _ = self.invoke(["verify-gate", "--run-dir", "o"])
        self.assertEqual(code, 1)

    def test_offline_success_is_zero(self):
        with patch("draft.cli.verify_gate", return_value={"verified": True, "passed": True}):
            code, _ = self.invoke(["verify-gate", "--run-dir", "o"])
        self.assertEqual(code, 0)

    def test_invalid_gate_input_is_json_failure(self):
        with patch("draft.cli.run_gate", side_effect=ValueError("Existing evidence directory")):
            code, result = self.invoke(["quality-gate", "--candidate", "c", "--out", "o"])
        self.assertEqual(code, 1)
        self.assertIn("Existing", result["error"])


if __name__ == "__main__":
    unittest.main()
