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
        retry_section = (
            f"\n## Previous Test Output (read carefully before revising)\n\n"
            f"```\n{last_test_output}\n```\n"
        )

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
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")}
    result = subprocess.run(
        ["claude", "-p", prompt, "--dangerously-skip-permissions"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    logger.debug("Claude exit code: %d", result.returncode)
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (exit {result.returncode}):\n{result.stderr}"
        )
    return result.stdout
