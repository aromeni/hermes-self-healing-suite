import pytest
from hermes.test_runner import run_tests


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
