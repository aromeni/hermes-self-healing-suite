import pytest
from unittest.mock import patch, MagicMock
from hermes.orchestrator import parse_stack_trace, run


SAMPLE_TRACE = """Traceback (most recent call last):
  File "myapp/math.py", line 42, in add
    return a - b
AssertionError: expected 3, got -1"""


def test_parse_stack_trace_extracts_file_and_line():
    result = parse_stack_trace(SAMPLE_TRACE)
    assert result["file_path"] == "myapp/math.py"
    assert result["line_number"] == 42
    assert "AssertionError" in result["error_type"]


def test_parse_stack_trace_handles_missing_info():
    result = parse_stack_trace("SomeError: something went wrong")
    assert result["file_path"] == "unknown"
    assert result["line_number"] == 1


@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
def test_run_returns_error_when_file_not_in_repo(mock_mkdtemp, mock_clone, tmp_path):
    mock_mkdtemp.return_value = str(tmp_path)
    # Clone returns an empty dir — the file from the trace won't exist there
    cloned = tmp_path / "repo"
    cloned.mkdir()
    mock_clone.return_value = str(cloned)

    trace = 'File "/usr/lib/python3.11/random.py", line 100, in choice\nAssertionError: boom'
    result = run(
        stack_trace=trace,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
    )

    assert result["success"] is False
    assert "not found in repository" in result["error"]
    assert result["pr_url"] is None


@patch("hermes.orchestrator.create_github_pr")
@patch("hermes.orchestrator.push_branch")
@patch("hermes.orchestrator._commit_workspace_changes")
@patch("hermes.orchestrator.invoke_claude")
@patch("hermes.orchestrator.run_tests")
@patch("hermes.orchestrator.get_commit_diff")
@patch("hermes.orchestrator.get_blame")
@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
@patch("hermes.orchestrator.os.path.exists", return_value=True)
def test_run_success_on_first_attempt(
    mock_exists, mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_commit, mock_push, mock_pr,
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix",
    }
    mock_diff.return_value = "diff content"
    mock_claude.return_value = (
        "HERMES_STATUS: FIXED\n"
        "HERMES_ROOT_CAUSE: Found the bug\n"
        "HERMES_TEST_RESULT: 1 passed"
    )
    mock_tests.return_value = {"passed": True, "stdout": "1 passed", "stderr": "", "exit_code": 0}
    mock_commit.return_value = True
    mock_pr.return_value = "https://github.com/org/repo/pull/1"

    result = run(
        stack_trace=SAMPLE_TRACE,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
    )

    assert result["success"] is True
    assert result["pr_url"] == "https://github.com/org/repo/pull/1"
    mock_claude.assert_called_once()


@patch("hermes.orchestrator.create_github_pr")
@patch("hermes.orchestrator.push_branch")
@patch("hermes.orchestrator.invoke_claude")
@patch("hermes.orchestrator.run_tests")
@patch("hermes.orchestrator.get_commit_diff")
@patch("hermes.orchestrator.get_blame")
@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
@patch("hermes.orchestrator.os.path.exists", return_value=True)
def test_run_fails_after_max_attempts(
    mock_exists, mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_push, mock_pr,
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix",
    }
    mock_diff.return_value = "diff content"
    mock_claude.return_value = (
        "HERMES_STATUS: FAILED\n"
        "HERMES_ROOT_CAUSE: Could not fix\n"
        "HERMES_TEST_RESULT: 1 failed"
    )
    mock_tests.return_value = {"passed": False, "stdout": "1 failed", "stderr": "", "exit_code": 1}

    result = run(
        stack_trace=SAMPLE_TRACE,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
    )

    assert result["success"] is False
    assert result["pr_url"] is None
    assert mock_claude.call_count == 3
    mock_pr.assert_not_called()


@patch("hermes.orchestrator.create_github_pr")
@patch("hermes.orchestrator.push_branch")
@patch("hermes.orchestrator._commit_workspace_changes")
@patch("hermes.orchestrator.invoke_claude")
@patch("hermes.orchestrator.run_tests")
@patch("hermes.orchestrator.get_commit_diff")
@patch("hermes.orchestrator.get_blame")
@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
@patch("hermes.orchestrator.os.path.exists", return_value=True)
def test_run_no_changes_skips_pr(
    mock_exists, mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_commit, mock_push, mock_pr,
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix",
    }
    mock_diff.return_value = "diff content"
    mock_claude.return_value = (
        "HERMES_STATUS: FIXED\n"
        "HERMES_ROOT_CAUSE: Found the bug\n"
        "HERMES_TEST_RESULT: 1 passed"
    )
    mock_tests.return_value = {"passed": True, "stdout": "1 passed", "stderr": "", "exit_code": 0}
    mock_commit.return_value = False  # no file changes

    result = run(
        stack_trace=SAMPLE_TRACE,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
    )

    assert result["success"] is True
    assert result["pr_url"] is None
    mock_push.assert_not_called()
    mock_pr.assert_not_called()
