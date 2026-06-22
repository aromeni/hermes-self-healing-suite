import logging
import subprocess

logger = logging.getLogger(__name__)

ALLOWED_TEST_COMMANDS = [
    "pytest",
    "python -m pytest",
    "npm test",
    "jest",
    "go test",
    "cargo test",
]


def validate_test_command(command: str) -> None:
    if not any(
        command == allowed or command.startswith(allowed + " ")
        for allowed in ALLOWED_TEST_COMMANDS
    ):
        raise ValueError(
            f"Test command '{command}' is not permitted. "
            f"Allowed commands: {', '.join(ALLOWED_TEST_COMMANDS)}"
        )


def run_tests(workspace_dir: str, test_command: str = "pytest") -> dict:
    validate_test_command(test_command)
    logger.info("Running tests in %s with command: %s", workspace_dir, test_command)
    result = subprocess.run(
        test_command.split(),
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
    passed = result.returncode == 0
    logger.info(
        "Test result: %s (exit code %d)", "PASS" if passed else "FAIL", result.returncode
    )
    if not passed:
        logger.debug("Test stdout:\n%s", result.stdout)
    return {
        "passed": passed,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }
