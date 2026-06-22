# Hermes: Autonomous Self-Healing Production Debugger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that accepts a production stack trace, autonomously identifies the bug via git blame, invokes Claude Code to propose and validate a fix (up to 3 attempts), and opens a GitHub PR with the patch and root-cause analysis.

**Architecture:** A linear 5-phase state machine in `orchestrator.py` wires together four single-responsibility modules: `git_ops` (repo cloning + blame), `code_agent` (Claude CLI invocation), `test_runner` (pytest capture), and `pr_builder` (GitHub PR creation). The `cli.py` entry point routes CLI arguments into the orchestrator. All workspace operations use an ephemeral `tempfile.mkdtemp()` directory.

**Tech Stack:** Python 3.10+, Click, GitPython, PyYAML, PyGithub, requests, subprocess, logging, pytest

## Global Constraints

- Python 3.10+ minimum
- `from github import Github` — never `from PyGithub import ...`
- All git shell operations via `subprocess.run`
- `GITHUB_TOKEN` read from `os.environ` — never hardcoded
- PRs created with `draft=False`
- Claude CLI invoked as `["claude", "-p", prompt, "--dangerously-skip-permissions"]` in workspace directory
- Logging uses `logging.getLogger(__name__)` in every module — no bare `print()` in library code
- 3-attempt maximum for the agentic fix loop; exit code 1 on full failure
- Workspace: `tempfile.mkdtemp(prefix="hermes_")` — NOT auto-deleted (for post-mortem inspection)
- Branch name format: `hotfix/hermes-{timestamp}` where timestamp is `%Y%m%d-%H%M%S`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `hermes/__init__.py`
- Create: `Dockerfile`
- Create: `setup.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: nothing consumed by other tasks — pure configuration

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p hermes prompts test_fixture tests docs/superpowers/plans
```

- [ ] **Step 2: Write requirements.txt**

```text
click>=8.1.0
gitpython>=3.1.40
pyyaml>=6.0
requests>=2.31.0
PyGithub>=2.1.1
pytest>=7.4.0
```

- [ ] **Step 3: Write config.yaml**

```yaml
# Hermes configuration — override via environment variables where noted
default_test_command: "pytest"
max_fix_attempts: 3
workspace_base: "/tmp"

github:
  # Set GITHUB_TOKEN environment variable — never put the token here
  token_env_var: "GITHUB_TOKEN"

# Target repo — can also be passed directly via CLI
target_repo:
  url: ""           # e.g. https://github.com/org/repo.git
  default_branch: "main"

logging:
  level: "INFO"     # DEBUG for verbose output
```

- [ ] **Step 4: Write hermes/__init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Write setup.py**

```python
from setuptools import setup, find_packages

setup(
    name="hermes",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.0",
        "gitpython>=3.1.40",
        "pyyaml>=6.0",
        "requests>=2.31.0",
        "PyGithub>=2.1.1",
    ],
    entry_points={
        "console_scripts": [
            "hermes=hermes.cli:main",
        ],
    },
    python_requires=">=3.10",
)
```

- [ ] **Step 6: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | sh

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install -e .

ENTRYPOINT ["hermes"]
```

- [ ] **Step 7: Write .gitignore**

```
__pycache__/
*.py[cod]
.env
*.egg-info/
dist/
build/
.pytest_cache/
/tmp/hermes_*
```

- [ ] **Step 8: Commit**

```bash
git init && git add requirements.txt config.yaml hermes/__init__.py Dockerfile setup.py .gitignore
git commit -m "chore: initial project scaffolding"
```

---

### Task 2: SRE Protocol Prompt

**Files:**
- Create: `prompts/sre_protocol.md`

**Interfaces:**
- Produces: `prompts/sre_protocol.md` — read by `code_agent.py:build_fix_prompt()`

- [ ] **Step 1: Write prompts/sre_protocol.md**

```markdown
# Hermes SRE Protocol — Autonomous Fix Mode

You are an expert Site Reliability Engineer operating inside an automated repair pipeline. You have been given:

1. A production stack trace identifying the failing file, line number, and error type
2. `git blame` output identifying the commit and author responsible for the offending line
3. The full diff of that commit (`git log -p`)
4. The test suite output from the most recent run (if this is a retry)

## Mandatory Rules — No Exceptions

**RULE 1: Run the tests before proposing any fix.**
Execute `pytest` (or the test command provided) immediately upon starting. Do not output a proposed fix until you have seen the test output at least once. If all tests pass without any changes, output `HERMES_STATUS: ALREADY_PASSING` and stop.

**RULE 2: Do not guess. Fix precisely the failing assertion.**
Read the test failure output carefully. Identify the single line or logic block that causes the failure. Change only that. Do not refactor, rename, or restructure code outside the scope of the fix.

**RULE 3: Fix → Test → Repeat (max 3 cycles total across all attempts).**
After applying your fix, run the tests again. If they still fail, read the new output and revise your fix. You have been given attempt number and remaining attempts in the prompt — respect them.

**RULE 4: Output structured results.**
When tests pass, end your response with this exact block:

```
HERMES_STATUS: FIXED
HERMES_ROOT_CAUSE: <one paragraph describing the bug: what the code did wrong, why it was wrong, and what the fix does>
HERMES_TEST_RESULT: <paste the final pytest output here>
```

If you exhaust your attempts without a passing test, end with:

```
HERMES_STATUS: FAILED
HERMES_ROOT_CAUSE: <what you attempted and why it didn't work>
HERMES_TEST_RESULT: <paste the final pytest output>
```

**RULE 5: Never modify test files.**
You may only modify source files. If the tests themselves are wrong, output `HERMES_STATUS: TEST_ERROR` and explain in HERMES_ROOT_CAUSE.

**RULE 6: Use only the tools available in this workspace.**
Do not install new packages. Do not make network requests. Operate only on the local files you can see.
```

- [ ] **Step 2: Commit**

```bash
git add prompts/sre_protocol.md
git commit -m "docs: add SRE protocol system prompt for Claude fix agent"
```

---

### Task 3: git_ops.py

**Files:**
- Create: `hermes/git_ops.py`
- Test: `tests/test_git_ops.py`

**Interfaces:**
- Consumes: nothing from other Hermes modules
- Produces:
  - `clone_repo(repo_url: str, dest_dir: str) -> str` — returns path to cloned repo root
  - `get_blame(repo_dir: str, file_path: str, line_number: int) -> dict` — returns `{"commit_hash": str, "author": str, "email": str, "summary": str}`
  - `get_commit_diff(repo_dir: str, commit_hash: str) -> str` — returns full `git log -p` output as string

- [ ] **Step 1: Write the failing tests**

Create `tests/__init__.py` (empty) and `tests/test_git_ops.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_git_ops.py -v
```

Expected: `ImportError: cannot import name 'clone_repo' from 'hermes.git_ops'`

- [ ] **Step 3: Implement hermes/git_ops.py**

```python
import logging
import subprocess

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, dest_dir: str) -> str:
    logger.info("Cloning %s → %s", repo_url, dest_dir)
    result = subprocess.run(
        ["git", "clone", repo_url, dest_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed:\n{result.stderr}")
    logger.info("Clone complete")
    return dest_dir


def get_blame(repo_dir: str, file_path: str, line_number: int) -> dict:
    logger.info("Running git blame on %s line %d", file_path, line_number)
    result = subprocess.run(
        ["git", "blame", "-p", "-L", f"{line_number},{line_number}", file_path],
        cwd=repo_dir, capture_output=True, text=True
    )
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
    result = subprocess.run(
        ["git", "log", "-p", "-n", "1", commit_hash],
        cwd=repo_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed:\n{result.stderr}")
    return result.stdout
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_git_ops.py -v
```

Expected: all 3 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes/git_ops.py tests/__init__.py tests/test_git_ops.py
git commit -m "feat: implement git_ops — clone, blame, and diff"
```

---

### Task 4: test_runner.py

**Files:**
- Create: `hermes/test_runner.py`
- Test: `tests/test_test_runner.py`

**Interfaces:**
- Consumes: nothing from other Hermes modules
- Produces:
  - `run_tests(workspace_dir: str, test_command: str = "pytest") -> dict` — returns `{"passed": bool, "stdout": str, "stderr": str, "exit_code": int}`

- [ ] **Step 1: Write failing tests**

Create `tests/test_test_runner.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_test_runner.py -v
```

Expected: `ImportError: cannot import name 'run_tests'`

- [ ] **Step 3: Implement hermes/test_runner.py**

```python
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
    logger.info("Test result: %s (exit code %d)", "PASS" if passed else "FAIL", result.returncode)
    if not passed:
        logger.debug("Test stdout:\n%s", result.stdout)
    return {
        "passed": passed,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_test_runner.py -v
```

Expected: all 3 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes/test_runner.py tests/test_test_runner.py
git commit -m "feat: implement test_runner — captures pytest output and exit code"
```

---

### Task 5: code_agent.py

**Files:**
- Create: `hermes/code_agent.py`
- Test: `tests/test_code_agent.py`

**Interfaces:**
- Consumes: `prompts/sre_protocol.md` — read from disk at `build_fix_prompt()` time
- Produces:
  - `build_fix_prompt(stack_trace: str, blame_info: dict, commit_diff: str, attempt: int, max_attempts: int, last_test_output: str) -> str`
  - `invoke_claude(workspace_dir: str, prompt: str) -> str` — returns Claude's stdout response

- [ ] **Step 1: Write failing tests**

Create `tests/test_code_agent.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_code_agent.py -v
```

Expected: `ImportError: cannot import name 'build_fix_prompt'`

- [ ] **Step 3: Implement hermes/code_agent.py**

```python
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_PROTOCOL_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "sre_protocol.md")


def _load_protocol() -> str:
    path = os.path.abspath(_PROTOCOL_PATH)
    with open(path) as f:
        return f.read()


def build_fix_prompt(
    stack_trace: str,
    blame_info: dict,
    commit_diff: str,
    attempt: int,
    max_attempts: int,
    last_test_output: str,
) -> str:
    protocol = _load_protocol()
    retry_section = ""
    if last_test_output:
        retry_section = f"\n## Previous Test Output (read carefully before revising)\n\n```\n{last_test_output}\n```\n"

    return f"""{protocol}

---

# Current Task — Attempt {attempt} of {max_attempts}

## Stack Trace

```
{stack_trace}
```

## Git Blame — Offending Commit

- **Commit:** `{blame_info['commit_hash']}`
- **Author:** {blame_info['author']} <{blame_info['email']}>
- **Summary:** {blame_info['summary']}

## Commit Diff

```diff
{commit_diff}
```
{retry_section}
Begin by running the test suite now. Do not propose a fix first.
"""


def invoke_claude(workspace_dir: str, prompt: str) -> str:
    logger.info("Invoking Claude Code in %s", workspace_dir)
    result = subprocess.run(
        ["claude", "-p", prompt, "--dangerously-skip-permissions"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    logger.debug("Claude exit code: %d", result.returncode)
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (exit {result.returncode}):\n{result.stderr}"
        )
    return result.stdout
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_code_agent.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes/code_agent.py tests/test_code_agent.py
git commit -m "feat: implement code_agent — claude CLI invocation and prompt builder"
```

---

### Task 6: pr_builder.py

**Files:**
- Create: `hermes/pr_builder.py`
- Test: `tests/test_pr_builder.py`

**Interfaces:**
- Consumes: `os.environ["GITHUB_TOKEN"]`
- Produces:
  - `push_branch(repo_dir: str, branch_name: str) -> None`
  - `create_github_pr(repo_url: str, branch_name: str, base_branch: str, root_cause: str, author: str, test_output: str) -> str` — returns PR URL
  - `_parse_github_repo(repo_url: str) -> tuple[str, str]` — (owner, repo_name)
  - `_build_pr_body(root_cause: str, author: str, test_output: str) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pr_builder.py`:

```python
import os
import pytest
from unittest.mock import patch, MagicMock
from hermes.pr_builder import create_github_pr, push_branch, _build_pr_body, _parse_github_repo


def test_parse_github_repo_https():
    owner, name = _parse_github_repo("https://github.com/acme/myrepo.git")
    assert owner == "acme"
    assert name == "myrepo"


def test_parse_github_repo_ssh():
    owner, name = _parse_github_repo("git@github.com:acme/myrepo.git")
    assert owner == "acme"
    assert name == "myrepo"


def test_build_pr_body_contains_author_and_root_cause():
    body = _build_pr_body(
        root_cause="The add function subtracted instead of adding.",
        author="Jane Doe",
        test_output="1 passed in 0.12s",
    )
    assert "Jane Doe" in body
    assert "The add function subtracted instead of adding." in body
    assert "1 passed in 0.12s" in body


def test_create_github_pr_calls_github_api():
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/acme/myrepo/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    mock_github = MagicMock()
    mock_github.get_repo.return_value = mock_repo

    with patch("hermes.pr_builder.Github", return_value=mock_github):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            url = create_github_pr(
                repo_url="https://github.com/acme/myrepo.git",
                branch_name="hotfix/hermes-20260622-120000",
                base_branch="main",
                root_cause="Bug: subtraction instead of addition.",
                author="Jane Doe",
                test_output="1 passed",
            )

    assert url == "https://github.com/acme/myrepo/pull/42"
    mock_repo.create_pull.assert_called_once()
    call_kwargs = mock_repo.create_pull.call_args[1]
    assert call_kwargs["draft"] is False
    assert "Jane Doe" in call_kwargs["body"]
    assert "Bug: subtraction instead of addition." in call_kwargs["body"]
    assert "1 passed" in call_kwargs["body"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_pr_builder.py -v
```

Expected: `ImportError: cannot import name 'create_github_pr'`

- [ ] **Step 3: Implement hermes/pr_builder.py**

```python
import logging
import os
import re
import subprocess
from github import Github

logger = logging.getLogger(__name__)


def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    match = re.search(r"github\.com[:/](.+?)/(.+?)(?:\.git)?$", repo_url)
    if not match:
        raise ValueError(f"Cannot parse GitHub repo URL: {repo_url}")
    return match.group(1), match.group(2)


def _build_pr_body(root_cause: str, author: str, test_output: str) -> str:
    return f"""## Hermes Autonomous Patch

**Automated fix generated by Hermes — review before merging.**

---

### Root Cause Analysis

{root_cause}

---

### Offending Author

{author}

---

### Test Results (Final Run)

```
{test_output}
```

---

*Generated by Hermes Self-Healing Debugger*
"""


def push_branch(repo_dir: str, branch_name: str) -> None:
    logger.info("Pushing branch %s", branch_name)
    result = subprocess.run(
        ["git", "push", "origin", branch_name],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git push failed:\n{result.stderr}")
    logger.info("Branch pushed successfully")


def create_github_pr(
    repo_url: str,
    branch_name: str,
    base_branch: str,
    root_cause: str,
    author: str,
    test_output: str,
) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set")

    owner, repo_name = _parse_github_repo(repo_url)
    g = Github(token)
    repo = g.get_repo(f"{owner}/{repo_name}")

    title = f"[Hermes] Automated fix on {branch_name}"
    body = _build_pr_body(root_cause=root_cause, author=author, test_output=test_output)

    logger.info("Creating PR: %s → %s on %s/%s", branch_name, base_branch, owner, repo_name)
    pr = repo.create_pull(
        title=title,
        body=body,
        head=branch_name,
        base=base_branch,
        draft=False,
    )
    logger.info("PR created: %s", pr.html_url)
    return pr.html_url
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
pytest tests/test_pr_builder.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes/pr_builder.py tests/test_pr_builder.py
git commit -m "feat: implement pr_builder — PyGithub PR creation with root-cause body"
```

---

### Task 7: orchestrator.py

**Files:**
- Create: `hermes/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes:
  - `git_ops.clone_repo`, `git_ops.get_blame`, `git_ops.get_commit_diff`
  - `test_runner.run_tests`
  - `code_agent.build_fix_prompt`, `code_agent.invoke_claude`
  - `pr_builder.push_branch`, `pr_builder.create_github_pr`
- Produces:
  - `parse_stack_trace(trace: str) -> dict` — returns `{"file_path": str, "line_number": int, "error_type": str, "raw": str}`
  - `run(stack_trace: str, repo_url: str, base_branch: str, test_command: str, max_attempts: int) -> dict` — returns `{"success": bool, "pr_url": str | None, "error": str | None}`

- [ ] **Step 1: Write failing tests**

Create `tests/test_orchestrator.py`:

```python
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


@patch("hermes.orchestrator.create_github_pr")
@patch("hermes.orchestrator.push_branch")
@patch("hermes.orchestrator.invoke_claude")
@patch("hermes.orchestrator.run_tests")
@patch("hermes.orchestrator.get_commit_diff")
@patch("hermes.orchestrator.get_blame")
@patch("hermes.orchestrator.clone_repo")
@patch("hermes.orchestrator.tempfile.mkdtemp")
def test_run_success_on_first_attempt(
    mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_push, mock_pr
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix"
    }
    mock_diff.return_value = "diff content"
    mock_claude.return_value = (
        "HERMES_STATUS: FIXED\n"
        "HERMES_ROOT_CAUSE: Found the bug\n"
        "HERMES_TEST_RESULT: 1 passed"
    )
    mock_tests.return_value = {"passed": True, "stdout": "1 passed", "stderr": "", "exit_code": 0}
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
def test_run_fails_after_max_attempts(
    mock_mkdtemp, mock_clone, mock_blame, mock_diff,
    mock_tests, mock_claude, mock_push, mock_pr
):
    mock_mkdtemp.return_value = "/tmp/hermes_test"
    mock_clone.return_value = "/tmp/hermes_test/repo"
    mock_blame.return_value = {
        "commit_hash": "a" * 40,
        "author": "Dev", "email": "dev@co.com", "summary": "fix"
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: `ImportError: cannot import name 'parse_stack_trace'`

- [ ] **Step 3: Implement hermes/orchestrator.py**

```python
import logging
import re
import subprocess
import tempfile
from datetime import datetime

from hermes.git_ops import clone_repo, get_blame, get_commit_diff
from hermes.test_runner import run_tests
from hermes.code_agent import build_fix_prompt, invoke_claude
from hermes.pr_builder import push_branch, create_github_pr

logger = logging.getLogger(__name__)

_STATUS_RE = re.compile(r"HERMES_STATUS:\s*(\w+)")
_ROOT_CAUSE_RE = re.compile(r"HERMES_ROOT_CAUSE:\s*(.+?)(?=HERMES_|\Z)", re.DOTALL)
_TEST_RESULT_RE = re.compile(r"HERMES_TEST_RESULT:\s*(.+?)(?=HERMES_|\Z)", re.DOTALL)


def parse_stack_trace(trace: str) -> dict:
    file_match = re.search(r'File "(.+?)", line (\d+)', trace)
    error_match = re.search(r"^(\w*Error|\w*Exception)", trace, re.MULTILINE)

    file_path = file_match.group(1) if file_match else "unknown"
    line_number = int(file_match.group(2)) if file_match else 1
    error_type = error_match.group(1) if error_match else "UnknownError"

    return {"file_path": file_path, "line_number": line_number, "error_type": error_type, "raw": trace}


def _extract_claude_output(response: str) -> tuple[str, str, str]:
    status_m = _STATUS_RE.search(response)
    root_cause_m = _ROOT_CAUSE_RE.search(response)
    test_result_m = _TEST_RESULT_RE.search(response)

    status = status_m.group(1) if status_m else "UNKNOWN"
    root_cause = root_cause_m.group(1).strip() if root_cause_m else response[:500]
    test_result = test_result_m.group(1).strip() if test_result_m else ""
    return status, root_cause, test_result


def _commit_workspace_changes(repo_dir: str, branch_name: str) -> None:
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"fix: automated patch by Hermes [{branch_name}]"],
        cwd=repo_dir, check=True, capture_output=True,
    )


def run(
    stack_trace: str,
    repo_url: str,
    base_branch: str = "main",
    test_command: str = "pytest",
    max_attempts: int = 3,
) -> dict:
    logger.info("=== Hermes starting ===")
    workspace = tempfile.mkdtemp(prefix="hermes_")
    logger.info("Workspace: %s", workspace)

    # Phase 0: Parse trace + clone
    trace_info = parse_stack_trace(stack_trace)
    logger.info(
        "Parsed trace: %s line %d (%s)",
        trace_info["file_path"], trace_info["line_number"], trace_info["error_type"]
    )
    repo_dir = clone_repo(repo_url, workspace + "/repo")

    # Phase 1: Context gathering
    blame_info = get_blame(repo_dir, trace_info["file_path"], trace_info["line_number"])
    commit_diff = get_commit_diff(repo_dir, blame_info["commit_hash"])

    # Phase 2-3: Agentic fix loop
    last_test_output = ""
    root_cause = ""

    for attempt in range(1, max_attempts + 1):
        logger.info("--- Fix attempt %d/%d ---", attempt, max_attempts)
        prompt = build_fix_prompt(
            stack_trace=stack_trace,
            blame_info=blame_info,
            commit_diff=commit_diff,
            attempt=attempt,
            max_attempts=max_attempts,
            last_test_output=last_test_output,
        )

        try:
            response = invoke_claude(repo_dir, prompt)
        except RuntimeError as e:
            logger.error("Claude invocation failed: %s", e)
            return {"success": False, "pr_url": None, "error": str(e)}

        status, root_cause, _ = _extract_claude_output(response)
        logger.info("Claude status: %s", status)

        if status == "ALREADY_PASSING":
            logger.info("Tests already passing — no fix needed")
            return {"success": True, "pr_url": None, "error": None}

        test_result = run_tests(repo_dir, test_command)
        last_test_output = test_result["stdout"]

        if test_result["passed"]:
            logger.info("Tests PASSED on attempt %d", attempt)
            break
        else:
            logger.warning("Tests FAILED on attempt %d", attempt)
            if attempt == max_attempts:
                logger.error("All %d attempts exhausted — human intervention required", max_attempts)
                return {
                    "success": False,
                    "pr_url": None,
                    "error": f"Max fix attempts ({max_attempts}) reached. Human intervention required.",
                }

    # Phase 4: PR creation
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = f"hotfix/hermes-{timestamp}"
    _commit_workspace_changes(repo_dir, branch_name)
    push_branch(repo_dir, branch_name)

    pr_url = create_github_pr(
        repo_url=repo_url,
        branch_name=branch_name,
        base_branch=base_branch,
        root_cause=root_cause,
        author=f"{blame_info['author']} <{blame_info['email']}>",
        test_output=last_test_output,
    )

    logger.info("=== Hermes complete. PR: %s ===", pr_url)
    return {"success": True, "pr_url": pr_url, "error": None}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: implement orchestrator — 5-phase state machine"
```

---

### Task 8: cli.py

**Files:**
- Create: `hermes/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `orchestrator.run` (imported as `orchestrator_run`)
- Produces: `hermes fix` CLI command; `main()` entry point

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli.py`:

```python
import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch
from hermes.cli import cli


def test_fix_with_error_string_succeeds():
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {"success": True, "pr_url": "https://github.com/org/repo/pull/1", "error": None}
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
                "stacktrace": {"frames": [{"filename": "buggy_math.py", "lineno": 2}]}
            }]
        }
    }))
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {"success": True, "pr_url": "https://github.com/org/repo/pull/2", "error": None}
        result = runner.invoke(cli, [
            "fix",
            "--error-file", str(payload),
            "--repo", "https://github.com/org/repo.git",
        ])
    assert result.exit_code == 0


def test_fix_exits_nonzero_on_failure():
    runner = CliRunner()
    with patch("hermes.cli.orchestrator_run") as mock_run:
        mock_run.return_value = {"success": False, "pr_url": None, "error": "Max attempts reached"}
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Implement hermes/cli.py**

```python
import json
import logging
import sys
import click
import yaml

from hermes.orchestrator import run as orchestrator_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _load_config() -> dict:
    try:
        with open("config.yaml") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _parse_sentry_json(path: str) -> str:
    with open(path) as f:
        payload = json.load(f)
    try:
        exc = payload["exception"]["values"][0]
        error_type = exc.get("type", "UnknownError")
        value = exc.get("value", "")
        frames = exc.get("stacktrace", {}).get("frames", [])
        lines = [f"{error_type}: {value}"]
        for frame in frames:
            filename = frame.get("filename", "unknown")
            lineno = frame.get("lineno", 0)
            lines.append(f'  File "{filename}", line {lineno}')
        return "\n".join(lines)
    except (KeyError, IndexError, TypeError):
        return json.dumps(payload)


@click.group()
def cli():
    """Hermes — Autonomous self-healing production debugger."""


@cli.command()
@click.option("--error", default=None, help="Raw stack trace string")
@click.option("--error-file", default=None, type=click.Path(exists=True), help="Path to JSON error payload (Sentry format)")
@click.option("--repo", required=True, help="Target repository URL")
@click.option("--base-branch", default="main", show_default=True)
@click.option("--test-command", default=None)
@click.option("--max-attempts", default=None, type=int)
def fix(error, error_file, repo, base_branch, test_command, max_attempts):
    """Diagnose a production error and create an automated fix PR."""
    if not error and not error_file:
        raise click.UsageError("Provide either --error or --error-file")

    config = _load_config()
    effective_test_command = test_command or config.get("default_test_command", "pytest")
    effective_max_attempts = max_attempts or config.get("max_fix_attempts", 3)

    stack_trace = _parse_sentry_json(error_file) if error_file else error
    click.echo("Hermes is analyzing the error...")

    result = orchestrator_run(
        stack_trace=stack_trace,
        repo_url=repo,
        base_branch=base_branch,
        test_command=effective_test_command,
        max_attempts=effective_max_attempts,
    )

    if result["success"]:
        click.echo(f"PR: {result['pr_url']}" if result["pr_url"] else "Tests already passing — no fix needed.")
        sys.exit(0)
    else:
        click.echo(f"Failed: {result['error']}", err=True)
        sys.exit(1)


def main():
    cli()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cli.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Install and smoke test**

```bash
pip install -e .
hermes --help
hermes fix --help
```

Expected: help text appears with `fix` subcommand and all options listed.

- [ ] **Step 6: Commit**

```bash
git add hermes/cli.py tests/test_cli.py setup.py
git commit -m "feat: implement CLI entry point — fix command with click"
```

---

### Task 9: Test Fixture

**Files:**
- Create: `test_fixture/buggy_math.py`
- Create: `test_fixture/test_math.py`
- Create: `test_fixture/README.md`

**Interfaces:**
- Produces: a self-contained broken Python repo for end-to-end testing

- [ ] **Step 1: Write test_fixture/buggy_math.py**

```python
def add(a, b):
    return a - b  # BUG: should be a + b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b
```

- [ ] **Step 2: Write test_fixture/test_math.py**

```python
from buggy_math import add, multiply, divide
import pytest


def test_add_positive_numbers():
    assert add(2, 3) == 5  # FAILS: returns -1


def test_add_negative_numbers():
    assert add(-1, -2) == -3  # FAILS: returns 1


def test_multiply():
    assert multiply(3, 4) == 12


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(5, 0)
```

- [ ] **Step 3: Confirm the fixture is broken as designed**

```bash
cd test_fixture && pytest -v; cd ..
```

Expected output:
```
FAILED test_math.py::test_add_positive_numbers - AssertionError: assert -1 == 5
FAILED test_math.py::test_add_negative_numbers - AssertionError: assert 1 == -3
2 failed, 3 passed
```

- [ ] **Step 4: Write test_fixture/README.md**

```markdown
# Hermes Test Fixture

A minimal broken Python repo. `add()` in `buggy_math.py` subtracts instead of adding.

## Run Hermes against this fixture

```bash
# 1. Init as a local git repo
cd test_fixture
git init && git config user.email "dev@test.com" && git config user.name "Dev"
git add . && git commit -m "feat: add math utilities"
cd ..

# 2. Trigger Hermes
hermes fix \
  --error 'File "buggy_math.py", line 2, in add
AssertionError: assert -1 == 5' \
  --repo "file://$(pwd)/test_fixture" \
  --test-command "pytest"
```
```

- [ ] **Step 5: Commit**

```bash
git add test_fixture/
git commit -m "test: add end-to-end fixture with intentional bug in add()"
```

---

### Task 10: Full Suite Validation + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests across `test_git_ops`, `test_test_runner`, `test_code_agent`, `test_pr_builder`, `test_orchestrator`, `test_cli` pass. Zero failures.

- [ ] **Step 2: Write README.md**

```markdown
# Hermes — Autonomous Self-Healing Production Debugger

Hermes accepts a production stack trace, clones the repo, invokes Claude Code to find and fix the bug, validates the fix via your test suite, and opens a GitHub PR — zero human intervention after the initial trigger.

## Prerequisites

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed globally (`claude` on PATH)
- `GITHUB_TOKEN` env var with `repo` scope
- `ANTHROPIC_API_KEY` env var (used by Claude Code CLI)

## Installation

```bash
pip install -e .
```

## Usage

```bash
# From a raw stack trace
hermes fix \
  --error 'File "myapp/math.py", line 42, in add
AssertionError: expected 5, got -1' \
  --repo https://github.com/your-org/repo.git

# From a Sentry JSON payload
hermes fix \
  --error-file /path/to/sentry_event.json \
  --repo https://github.com/your-org/repo.git \
  --base-branch main \
  --test-command "pytest tests/"
```

## End-to-end test with local fixture

```bash
cd test_fixture
git init && git config user.email "dev@test.com" && git config user.name "Dev"
git add . && git commit -m "init"
cd ..

hermes fix \
  --error 'File "buggy_math.py", line 2, in add
AssertionError: assert -1 == 5' \
  --repo "file://$(pwd)/test_fixture" \
  --test-command "pytest"
```

## Architecture

| Phase | Module | Action |
|---|---|---|
| 0 | orchestrator | Parse stack trace, clone repo to temp dir |
| 1 | git_ops | `git blame -p` + `git log -p` for commit context |
| 2 | code_agent | Invoke `claude -p` with SRE protocol prompt |
| 3 | test_runner | Run pytest, capture stdout/stderr/exit code |
| 4 | pr_builder | Push hotfix branch, create GitHub PR via PyGithub |

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | Phase 4 | GitHub API auth (repo scope) |
| `ANTHROPIC_API_KEY` | Always | Picked up by Claude Code CLI |

## Configuration

Edit `config.yaml` to set defaults for test command, max attempts, and workspace directory.
```

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: add README with full usage, architecture table, and fixture guide"
```
