import pytest
from unittest.mock import patch, MagicMock
from hermes.code_agent import build_fix_prompt, invoke_claude


SAMPLE_BLAME = {
    "commit_hash": "abc123def456abc123def456abc123def456abc1",
    "author": "Jane Doe",
    "email": "jane@example.com",
    "summary": "refactor: simplify add function",
}


def test_build_fix_prompt_contains_stack_trace():
    prompt = build_fix_prompt(
        stack_trace="ZeroDivisionError at line 5",
        blame_info=SAMPLE_BLAME,
        commit_diff="- return a + b\n+ return a - b",
        attempt=1,
        max_attempts=3,
        last_test_output="",
    )
    assert "ZeroDivisionError at line 5" in prompt
    assert "Jane Doe" in prompt
    assert "1" in prompt and "3" in prompt


def test_build_fix_prompt_includes_last_test_output():
    prompt = build_fix_prompt(
        stack_trace="Error",
        blame_info=SAMPLE_BLAME,
        commit_diff="diff",
        attempt=2,
        max_attempts=3,
        last_test_output="AssertionError: assert 1 == 2",
    )
    assert "AssertionError: assert 1 == 2" in prompt


def test_invoke_claude_returns_stdout():
    mock_result = MagicMock()
    mock_result.stdout = "HERMES_STATUS: FIXED\nHERMES_ROOT_CAUSE: Found it"
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        response = invoke_claude("/tmp/workspace", "fix this bug")
        assert "HERMES_STATUS: FIXED" in response
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "claude"
        assert call_args[1]["cwd"] == "/tmp/workspace"


def test_invoke_claude_raises_on_nonzero_exit():
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = "command not found: claude"
    mock_result.returncode = 127

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Claude CLI failed"):
            invoke_claude("/tmp/workspace", "fix this")
