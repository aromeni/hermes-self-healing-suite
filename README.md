# Hermes — Autonomous Self-Healing Production Debugger

Hermes is a CLI tool that closes the loop between a production error and a merged fix — automatically. Feed it a stack trace, point it at a repository, and it clones the repo, pinpoints the offending commit via `git blame`, invokes Claude Code as an autonomous SRE agent to diagnose and patch the bug, validates the fix against your test suite, and opens a reviewed GitHub pull request. Zero human intervention required after the initial trigger.

```
Production alert  ──►  hermes fix  ──►  PR opened  ──►  Human reviews & merges
```

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [CLI Reference](#cli-reference)
- [Architecture](#architecture)
- [The SRE Protocol](#the-sre-protocol)
- [Environment Variables](#environment-variables)
- [Running the Test Suite](#running-the-test-suite)
- [Docker](#docker)
- [Project Structure](#project-structure)
- [Limitations](#limitations)

---

## How It Works

Hermes runs a deterministic five-phase pipeline:

```
Phase 0 — Parse & Clone
  Parse the stack trace to extract file, line number, and error type.
  Clone the target repository to a temporary workspace.

Phase 1 — Context Gathering
  Run `git blame` on the offending line to identify the responsible commit and author.
  Fetch the full diff of that commit with `git log -p`.

Phase 2 — Agentic Fix
  Invoke Claude Code CLI with the SRE protocol, the stack trace, blame info, and commit diff.
  Claude runs the test suite first, reads the failures, and applies a minimal targeted fix.

Phase 3 — Validation
  Run the test suite in the cloned workspace.
  If tests fail, feed the output back to Claude and retry (up to max_attempts).

Phase 4 — PR Creation
  Commit the fix to a `hotfix/hermes-<timestamp>` branch.
  Push the branch and open a GitHub pull request with a structured description.
```

If Claude fixes the bug on the first attempt and tests pass, the entire pipeline — from `hermes fix` to an open PR — takes under two minutes.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| [Claude Code CLI](https://claude.ai/code) | Must be on `PATH` as `claude` |
| Git | Must be on `PATH` |
| GitHub personal access token | Needs **Contents: Read & write** and **Pull requests: Read & write** |
| Anthropic API key | Used automatically by the Claude Code CLI |

---

## Installation

Clone this repository and install in editable mode:

```bash
git clone https://github.com/your-org/hermes-self-healing-suite.git
cd hermes-self-healing
pip install -e .
```

Verify the installation:

```bash
hermes --help
```

---

## Configuration

### Credentials — `.env`

Create a `.env` file in the project root. Hermes loads it automatically at startup and it takes precedence over any values already set in your shell environment:

```bash
# .env
ANTHROPIC_API_KEY="sk-ant-..."
GITHUB_TOKEN="github_pat_..."
```

> **Fine-grained PATs** (tokens starting with `github_pat_`) must have **Contents: Read & write** and **Pull requests: Read & write** granted for the target repository under *Repository permissions*.

### Runtime settings — `config.yaml`

`config.yaml` in the project root controls defaults that can all be overridden per-invocation via CLI flags:

```yaml
default_test_command: "pytest"   # test command to run in the cloned repo
max_fix_attempts: 3              # how many times Claude may retry before giving up
workspace_base: "/tmp"           # parent directory for temporary clone workspaces

github:
  token_env_var: "GITHUB_TOKEN"

logging:
  level: "INFO"
```

---

## Usage

### Fix from a raw stack trace

```bash
hermes fix \
  --error 'File "myapp/payments.py", line 87, in process_charge
TypeError: unsupported operand type(s) for +: "int" and "str"' \
  --repo https://github.com/your-org/your-repo.git
```

### Fix from a Sentry JSON payload

Hermes understands the standard Sentry event JSON format. Export the event from Sentry and pass the file path:

```bash
hermes fix \
  --error-file /path/to/sentry_event.json \
  --repo https://github.com/your-org/your-repo.git \
  --base-branch main \
  --test-command "pytest tests/ -x"
```

### Dry-run mode (sales demo / cost estimation)

Use `--dry-run` to see an ROI estimate without spending API credits or touching GitHub:

```bash
hermes fix \
  --error 'File "buggy_math.py", line 2, in add\nAssertionError: expected 3, got -1' \
  --repo https://github.com/your-org/your-repo.git \
  --dry-run
```

Output:

```
💰 HERMES DRY RUN — ROI ESTIMATE
────────────────────────────────────────────
🔍 Error detected: AssertionError in buggy_math.py:2
👤 Offending author: Rashid (5aea70b2)

⏱️  Time saved:
   - Manual fix average: 45 minutes
   - Hermes automated fix: ~4 minutes
   - **Time saved per incident: 41 minutes (91% reduction)**

💵 Cost savings (based on $175/hr engineer rate):
   - Manual cost: $131.25
   - Hermes cost: $11.67 (API credits + overhead)
   - **Net savings per fix: $119.58**

📊 If you run 10 incidents/month:
   - Monthly savings: ~$1,195
   - Annual savings: ~$14,350

🚀 To run the actual fix, remove the --dry-run flag.
────────────────────────────────────────────
```

### Typical output

```
Hermes is analyzing the error...
20:09:38 [INFO] hermes.orchestrator: === Hermes starting ===
20:09:38 [INFO] hermes.orchestrator: Workspace: /tmp/hermes_pw1v8rr
20:09:38 [INFO] hermes.orchestrator: Parsed trace: buggy_math.py line 2 (AssertionError)
20:09:39 [INFO] hermes.git_ops: Clone complete
20:09:39 [INFO] hermes.git_ops: Blame: commit=5aea70b2 author=Rashid
20:09:39 [INFO] hermes.orchestrator: --- Fix attempt 1/3 ---
20:10:10 [INFO] hermes.orchestrator: Claude status: FIXED
20:10:12 [INFO] hermes.test_runner: Test result: PASS (exit code 0)
20:10:13 [INFO] hermes.pr_builder: Branch pushed successfully
20:10:14 [INFO] hermes.pr_builder: PR created: https://github.com/your-org/your-repo/pull/42
PR: https://github.com/your-org/your-repo/pull/42
```

---

## CLI Reference

```
hermes fix [OPTIONS]
```

| Option | Required | Default | Description |
|---|---|---|---|
| `--error TEXT` | One of `--error` or `--error-file` | — | Raw stack trace string |
| `--error-file PATH` | One of `--error` or `--error-file` | — | Path to a Sentry JSON event file |
| `--repo URL` | Yes | — | Target repository URL (`https://` or `git@`) |
| `--base-branch TEXT` | No | `main` | Branch to open the PR against |
| `--test-command TEXT` | No | `pytest` (from `config.yaml`) | Command used to run the test suite |
| `--max-attempts INT` | No | `3` (from `config.yaml`) | Maximum fix-retry cycles before giving up |
| `--dry-run` | No | off | Simulate the fix and print an ROI analysis — does not invoke Claude or create a PR |

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Fix applied and PR opened, or tests were already passing |
| `1` | Pipeline failed — see stderr for details |

---

## Architecture

| Phase | Module | Responsibility |
|---|---|---|
| 0 | `orchestrator.py` | Parse stack trace, create temp workspace, clone repo |
| 1 | `git_ops.py` | `git blame -p` on offending line, `git log -p` on commit |
| 2 | `code_agent.py` | Build structured prompt, invoke `claude -p` subprocess |
| 3 | `test_runner.py` | Run test command, capture stdout/stderr/exit code |
| 4 | `pr_builder.py` | Commit changes, push branch, create PR via PyGithub |

### Module overview

**`hermes/orchestrator.py`**
The central coordinator. Owns the fix-retry loop, interprets Claude's structured output (`HERMES_STATUS`, `HERMES_ROOT_CAUSE`, `HERMES_TEST_RESULT` tags), commits the workspace changes to a timestamped branch, and calls the PR builder. Returns a result dict — `{success, pr_url, error}` — consumed by the CLI.

**`hermes/code_agent.py`**
Builds the prompt from the SRE protocol template plus the current task context (stack trace, blame info, commit diff, previous test output on retries). Invokes Claude Code CLI as a subprocess with `--dangerously-skip-permissions` so it can read and write files in the cloned workspace without interactive prompts.

**`hermes/git_ops.py`**
Wraps `git clone`, `git blame -p`, and `git log -p` using subprocesses. Returns structured dicts with commit hash, author name, email, and summary.

**`hermes/test_runner.py`**
Runs the configured test command in the repo directory and returns pass/fail status plus full stdout/stderr for Claude's retry context.

**`hermes/pr_builder.py`**
Uses PyGithub to open a pull request with a structured body that includes the root cause analysis, the offending author, and the final test output. Handles both HTTPS and SSH repo URL formats.

**`hermes/cli.py`**
Click-based CLI entry point. Loads `.env` via `python-dotenv` (with directory traversal so it works from any subdirectory), parses Sentry JSON if `--error-file` is provided, and calls `orchestrator.run()`.

---

## The SRE Protocol

Claude Code does not operate free-form. Every invocation is governed by `prompts/sre_protocol.md`, a strict six-rule protocol:

1. **Run tests before proposing any fix.** Claude must observe actual test failures before touching any code.
2. **Fix precisely the failing assertion.** No refactoring, no renaming, no changes outside the bug's scope.
3. **Fix → Test → Repeat.** After each fix, Claude re-runs the suite. It stays in this loop until tests pass or attempts are exhausted.
4. **Output structured results.** Claude ends every response with machine-readable `HERMES_STATUS`, `HERMES_ROOT_CAUSE`, and `HERMES_TEST_RESULT` tags so the orchestrator can parse outcomes without natural-language interpretation.
5. **Never modify test files.** Only source files may be changed. If the tests themselves are wrong, Claude reports `HERMES_STATUS: TEST_ERROR`.
6. **No network requests, no new packages.** Claude operates strictly on the local workspace it has been given.

The orchestrator parses `HERMES_STATUS` to decide whether to retry, commit, or abort.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Always | Picked up by the Claude Code CLI subprocess |
| `GITHUB_TOKEN` | Phase 4 only | Used by PyGithub to push branches and create PRs |

Both variables are loaded from `.env` automatically. Shell-level values are overridden by `.env` to prevent stale placeholders from causing authentication failures.

---

## Running the Test Suite

The unit tests mock all external calls (Claude CLI, GitHub API, git operations) and run offline:

```bash
pip install -e .
pytest tests/ -v
```

```
tests/test_cli.py               - CLI flag parsing and Sentry JSON ingestion
tests/test_code_agent.py        - Prompt construction and Claude subprocess invocation
tests/test_orchestrator.py      - Full pipeline logic and retry behaviour
tests/test_pr_builder.py        - GitHub PR creation and URL parsing
tests/test_test_runner.py       - Test command execution and result capture
```

---

## Docker

A `Dockerfile` is provided for running Hermes in a container (e.g. as a webhook handler or CI step):

```bash
docker build -t hermes .
docker run --rm \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e GITHUB_TOKEN="github_pat_..." \
  hermes fix \
    --error 'File "app/main.py", line 10, in handler\nValueError: invalid literal' \
    --repo https://github.com/your-org/your-repo.git
```

The image is based on `python:3.11-slim`, installs Git and the Claude Code CLI, and sets `hermes` as the entrypoint.

---

## Project Structure

```
hermes-self-healing/
├── hermes/
│   ├── __init__.py
│   ├── cli.py            # Click CLI, .env loading, Sentry JSON parsing
│   ├── orchestrator.py   # Pipeline coordinator and fix-retry loop
│   ├── git_ops.py        # clone, blame, diff wrappers
│   ├── code_agent.py     # Prompt builder, Claude Code subprocess invocation
│   ├── test_runner.py    # Test command execution
│   └── pr_builder.py     # Branch push and GitHub PR creation
├── prompts/
│   └── sre_protocol.md   # SRE rules injected into every Claude prompt
├── tests/                # Unit test suite (fully offline, all I/O mocked)
├── test_fixture/         # Minimal repo with a deliberate bug for end-to-end testing
│   ├── buggy_math.py
│   └── test_math.py
├── config.yaml           # Runtime defaults
├── Dockerfile
├── setup.py
└── .env                  # Credentials (not committed)
```

---

## Limitations

- **Stack trace must reference a file that exists in the repository.** Traces pointing to stdlib or virtualenv paths (e.g. `/usr/lib/python3.11/...`) are detected and rejected with a clear error message.
- **Requires a passing test suite before the bug was introduced.** Hermes validates its fix by running your tests. If no tests exist, or the test suite was already broken, it has no signal to work with.
- **Claude Code CLI must be authenticated.** The subprocess inherits the shell environment (minus `ANTHROPIC_API_KEY`, which is passed through the `.env` → environment path). Run `claude --version` to confirm it is installed and logged in.
- **One bug per invocation.** Hermes targets the single line identified by `git blame` on the first failing frame. Multi-file cascading failures require separate invocations or human triage.
- **Max three fix attempts by default.** If Claude cannot produce a passing test suite within `max_fix_attempts` cycles, Hermes exits with code `1` and prints `Human intervention required`.
