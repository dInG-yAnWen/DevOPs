"""Intentional incorrect oracle for the E7 rejected-PR demonstration."""
from draft.cli import main


def test_e7_version_success_oracle():
    assert main(["version"]) == 1, "E7_INTENTIONAL_WRONG_VERSION_ORACLE"
