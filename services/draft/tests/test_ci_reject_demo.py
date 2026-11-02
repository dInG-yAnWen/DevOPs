"""Corrected oracle: the version command is successful."""
from draft.cli import main


def test_e7_version_success_oracle():
    assert main(["version"]) == 0
