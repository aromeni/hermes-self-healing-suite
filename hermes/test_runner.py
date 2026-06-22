import logging
import subprocess

logger = logging.getLogger(__name__)


def run_tests(workspace_dir: str, test_command: str = "pytest") -> dict:
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
