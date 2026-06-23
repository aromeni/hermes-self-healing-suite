import pytest
import subprocess
from unittest.mock import patch, MagicMock, call
from github import GithubException
from hermes.orchestrator import parse_stack_trace, run, _commit_workspace_changes


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


def test_commit_workspace_changes_uses_git_add_u(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    tracked = repo / "source.py"
    tracked.write_text("original")
    subprocess.run(["git", "add", "source.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Modify tracked file and also drop an untracked secret next to it
    tracked.write_text("fixed")
    (repo / ".env").write_text("SECRET=hunter2")

    result = _commit_workspace_changes(str(repo), "hotfix/test-branch")

    assert result is True
    # Untracked .env must NOT appear in the commit
    log = subprocess.run(
        ["git", "show", "--name-only", "--format="], cwd=repo, capture_output=True, text=True
    )
    assert "source.py" in log.stdout
    assert ".env" not in log.stdout


@patch("hermes.orchestrator.delete_remote_branch")
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
def test_pr_failure_deletes_remote_branch(
    mock_exists, mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_commit, mock_push, mock_pr, mock_delete,
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix",
    }
    mock_diff.return_value = "diff content"
    mock_claude.return_value = (
        "HERMES_STATUS: FIXED\nHERMES_ROOT_CAUSE: Found it\nHERMES_TEST_RESULT: 1 passed"
    )
    mock_tests.return_value = {"passed": True, "stdout": "1 passed", "stderr": "", "exit_code": 0}
    mock_commit.return_value = True
    mock_pr.side_effect = GithubException(403, {"message": "Forbidden"}, None)

    with pytest.raises(GithubException):
        run(
            stack_trace=SAMPLE_TRACE,
            repo_url="https://github.com/org/repo.git",
            base_branch="main",
            test_command="pytest",
            max_attempts=3,
        )

    mock_push.assert_called_once()
    mock_delete.assert_called_once()


@patch("hermes.orchestrator.invoke_claude")
@patch("hermes.orchestrator.get_commit_diff")
@patch("hermes.orchestrator.get_blame")
@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
@patch("hermes.orchestrator.os.path.exists", return_value=True)
def test_dry_run_returns_roi_result_without_calling_claude(
    mock_exists, mock_mkdtemp, mock_clone, mock_blame, mock_diff, mock_claude, tmp_path
):
    mock_mkdtemp.return_value = str(tmp_path)
    cloned = tmp_path / "repo"
    cloned.mkdir()
    mock_clone.return_value = str(cloned)
    mock_blame.return_value = {
        "commit_hash": "5aea70b2",
        "author": "Rashid",
        "email": "rashid@example.com",
        "summary": "init",
    }
    mock_diff.return_value = "diff content"

    trace = 'File "buggy_math.py", line 2, in add\nAssertionError: expected 3, got -1'
    result = run(
        stack_trace=trace,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
        dry_run=True,
    )

    assert result == {"success": True, "dry_run": True, "pr_url": None}
    mock_claude.assert_not_called()


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
def test_branch_names_are_unique(
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
        "HERMES_STATUS: FIXED\nHERMES_ROOT_CAUSE: Found it\nHERMES_TEST_RESULT: 1 passed"
    )
    mock_tests.return_value = {"passed": True, "stdout": "1 passed", "stderr": "", "exit_code": 0}
    mock_commit.return_value = True
    mock_pr.return_value = "https://github.com/org/repo/pull/1"

    kwargs = dict(
        stack_trace=SAMPLE_TRACE,
        repo_url="https://github.com/org/repo.git",
        base_branch="main",
        test_command="pytest",
        max_attempts=3,
    )
    run(**kwargs)
    run(**kwargs)

    branch_names = [call_args[0][1] for call_args in mock_commit.call_args_list]
    assert branch_names[0] != branch_names[1]
    import re as _re
    for name in branch_names:
        assert _re.match(r"hotfix/hermes-\d{8}-\d{6}-[0-9a-f]{8}$", name), name
