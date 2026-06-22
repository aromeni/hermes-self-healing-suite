import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch
from hermes.cli import cli


def test_fix_with_error_string_succeeds():
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {
            "success": True,
            "pr_url": "https://github.com/org/repo/pull/1",
            "error": None,
        }
        result = runner.invoke(cli, [
            "fix",
            "--error", "AssertionError at math.py line 5",
            "--repo", "https://github.com/org/repo.git",
        ])
    assert result.exit_code == 0
    assert "PR:" in result.output


def test_fix_with_error_file_succeeds(tmp_path):
    payload = tmp_path / "error.json"
    payload.write_text(json.dumps({
        "exception": {
            "values": [{
                "type": "AssertionError",
                "value": "assert -1 == 5",
                "stacktrace": {"frames": [{"filename": "buggy_math.py", "lineno": 2}]},
            }]
        }
    }))
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {
            "success": True,
            "pr_url": "https://github.com/org/repo/pull/2",
            "error": None,
        }
        result = runner.invoke(cli, [
            "fix",
            "--error-file", str(payload),
            "--repo", "https://github.com/org/repo.git",
        ])
    assert result.exit_code == 0


def test_fix_exits_nonzero_on_failure():
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {
            "success": False,
            "pr_url": None,
            "error": "Max attempts reached",
        }
        result = runner.invoke(cli, [
            "fix",
            "--error", "SomeError",
            "--repo", "https://github.com/org/repo.git",
        ])
    assert result.exit_code == 1


def test_fix_requires_error_or_error_file():
    runner = CliRunner()
    result = runner.invoke(cli, ["fix", "--repo", "https://github.com/org/repo.git"])
    assert result.exit_code != 0
