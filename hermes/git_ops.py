import logging
import subprocess

logger = logging.getLogger(__name__)

_CLONE_TIMEOUT = 120
_GIT_TIMEOUT = 120


def clone_repo(repo_url: str, dest_dir: str, branch: str = "main") -> str:
    logger.info("Cloning %s (branch: %s) → %s", repo_url, branch, dest_dir)
    try:
        result = subprocess.run(
            ["git", "clone", "--branch", branch, repo_url, dest_dir],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"git clone timed out after {_CLONE_TIMEOUT}s — "
            "repository may be too large or the network is slow"
        )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed:\n{result.stderr}")
    logger.info("Clone complete")
    return dest_dir


def get_blame(repo_dir: str, file_path: str, line_number: int) -> dict:
    logger.info("Running git blame on %s line %d", file_path, line_number)
    try:
        result = subprocess.run(
            ["git", "blame", "-p", "-L", f"{line_number},{line_number}", file_path],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git blame timed out after {_GIT_TIMEOUT}s")
    if result.returncode != 0:
        raise RuntimeError(f"git blame failed:\n{result.stderr}")

    lines = result.stdout.splitlines()
    commit_hash = lines[0].split()[0]
    info = {"commit_hash": commit_hash, "author": "", "email": "", "summary": ""}

    for line in lines:
        if line.startswith("author "):
            info["author"] = line[7:]
        elif line.startswith("author-mail "):
            info["email"] = line[12:].strip("<>")
        elif line.startswith("summary "):
            info["summary"] = line[8:]

    logger.info("Blame: commit=%s author=%s", commit_hash[:8], info["author"])
    return info


def get_commit_diff(repo_dir: str, commit_hash: str) -> str:
    logger.info("Fetching diff for commit %s", commit_hash[:8])
    try:
        result = subprocess.run(
            ["git", "log", "-p", "-n", "1", commit_hash],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git log timed out after {_GIT_TIMEOUT}s")
    if result.returncode != 0:
        raise RuntimeError(f"git log failed:\n{result.stderr}")
    return result.stdout
