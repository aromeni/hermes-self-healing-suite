import pytest
from hermes.test_runner import run_tests, validate_test_command


@pytest.fixture
def passing_test_dir(tmp_path):
    (tmp_path / "test_ok.py").write_text(
        "def test_always_passes():\n    assert 1 == 1\n"
    )
    return str(tmp_path)


@pytest.fixture
def failing_test_dir(tmp_path):
    (tmp_path / "test_fail.py").write_text(
        "def test_always_fails():\n    assert 1 == 2\n"
    )
    return str(tmp_path)


def test_run_tests_passes_on_green_suite(passing_test_dir):
    result = run_tests(passing_test_dir)
    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert "passed" in result["stdout"]


def test_run_tests_fails_on_red_suite(failing_test_dir):
    result = run_tests(failing_test_dir)
    assert result["passed"] is False
    assert result["exit_code"] == 1
    assert "failed" in result["stdout"]


def test_run_tests_captures_stdout(failing_test_dir):
    result = run_tests(failing_test_dir)
    assert "AssertionError" in result["stdout"] or "assert 1 == 2" in result["stdout"]


# --- validate_test_command tests ---

def test_validate_allows_pytest():
    validate_test_command("pytest")  # must not raise


def test_validate_allows_pytest_with_flags():
    validate_test_command("pytest -v tests/")  # must not raise


def test_validate_allows_python_m_pytest():
    validate_test_command("python -m pytest")  # must not raise


def test_validate_allows_npm_test():
    validate_test_command("npm test")  # must not raise


def test_validate_rejects_arbitrary_command():
    with pytest.raises(ValueError, match="not permitted"):
        validate_test_command("rm -rf /")


def test_validate_rejects_curl():
    with pytest.raises(ValueError, match="not permitted"):
        validate_test_command("curl http://evil.com")


def test_validate_rejects_pytest_lookalike():
    with pytest.raises(ValueError, match="not permitted"):
        validate_test_command("pytestevil")


def test_run_tests_raises_on_blocked_command(passing_test_dir):
    with pytest.raises(ValueError, match="not permitted"):
        run_tests(passing_test_dir, test_command="curl http://evil.com")
