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
| `GITHUB_TOKEN` | Phase 4 | GitHub API auth (`repo` scope) |
| `ANTHROPIC_API_KEY` | Always | Picked up automatically by Claude Code CLI |

## Configuration

Edit `config.yaml` to set defaults for test command, max attempts, and workspace path.

## Running the test suite

```bash
pip install -e .
pytest tests/ -v
```
