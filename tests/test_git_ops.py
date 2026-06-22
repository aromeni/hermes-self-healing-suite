import os
import subprocess
import pytest
from hermes.git_ops import clone_repo, get_blame, get_commit_diff


@pytest.fixture
def local_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    target = repo / "math.py"
    target.write_text("# line 1\n# line 2\ndef add(a, b):\n    return a - b  # bug\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)
    return str(repo)


def test_clone_repo_creates_directory(tmp_path, local_git_repo):
    dest = str(tmp_path / "clone")
    result = clone_repo(local_git_repo, dest)
    assert os.path.isdir(result)
    assert os.path.exists(os.path.join(result, "math.py"))


def test_get_blame_returns_commit_info(local_git_repo):
    info = get_blame(local_git_repo, "math.py", 4)
    assert "commit_hash" in info
    assert len(info["commit_hash"]) == 40
    assert info["author"] == "Test"


def test_get_commit_diff_returns_diff_string(local_git_repo):
    blame = get_blame(local_git_repo, "math.py", 4)
    diff = get_commit_diff(local_git_repo, blame["commit_hash"])
    assert "def add" in diff
    assert "return a - b" in diff
