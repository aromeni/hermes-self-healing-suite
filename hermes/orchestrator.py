import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime

import click

from hermes.git_ops import clone_repo, get_blame, get_commit_diff
from hermes.test_runner import run_tests
from hermes.code_agent import build_fix_prompt, invoke_claude
from github import GithubException
from hermes.pr_builder import push_branch, create_github_pr, delete_remote_branch

logger = logging.getLogger(__name__)

_STATUS_RE = re.compile(r"HERMES_STATUS:\s*(\w+)")
_ROOT_CAUSE_RE = re.compile(r"HERMES_ROOT_CAUSE:\s*(.+?)(?=HERMES_|\Z)", re.DOTALL)
_TEST_RESULT_RE = re.compile(r"HERMES_TEST_RESULT:\s*(.+?)(?=HERMES_|\Z)", re.DOTALL)


def parse_stack_trace(trace: str) -> dict:
    all_frames = re.findall(r'File "(.+?)", line (\d+)', trace)
    file_match = all_frames[-1] if all_frames else None
    error_match = re.search(r"^(\w*Error|\w*Exception)", trace, re.MULTILINE)

    file_path = file_match[0] if file_match else "unknown"
    line_number = int(file_match[1]) if file_match else 1
    error_type = error_match.group(1) if error_match else "UnknownError"

    return {
        "file_path": file_path,
        "line_number": line_number,
        "error_type": error_type,
        "raw": trace,
    }


def _extract_claude_output(response: str) -> tuple[str, str, str]:
    status_m = _STATUS_RE.search(response)
    root_cause_m = _ROOT_CAUSE_RE.search(response)
    test_result_m = _TEST_RESULT_RE.search(response)

    status = status_m.group(1) if status_m else "UNKNOWN"
    root_cause = root_cause_m.group(1).strip() if root_cause_m else response[:500]
    test_result = test_result_m.group(1).strip() if test_result_m else ""
    return status, root_cause, test_result


def _commit_workspace_changes(repo_dir: str, branch_name: str) -> bool:
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, check=True, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("git status timed out after 30s")
    if not status_result.stdout.strip():
        logger.info("No changes to commit — bug was already fixed or Claude made no edits")
        return False

    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=repo_dir, check=True, capture_output=True, timeout=30,
    )
    subprocess.run(
        ["git", "add", "-u"],
        cwd=repo_dir, check=True, capture_output=True, timeout=30,
    )
    subprocess.run(
        ["git", "commit", "-m", f"fix: automated patch by Hermes [{branch_name}]"],
        cwd=repo_dir, check=True, capture_output=True, timeout=30,
    )
    return True


def _print_roi_analysis(trace_info: dict, blame_info: dict) -> None:
    file_name = trace_info["file_path"].split("/")[-1]
    line = trace_info["line_number"]
    error_type = trace_info["error_type"]
    author = blame_info["author"]
    commit_short = blame_info["commit_hash"][:8]

    click.echo("💰 HERMES DRY RUN — ROI ESTIMATE")
    click.echo("────────────────────────────────────────────")
    click.echo(f"🔍 Error detected: {error_type} in {file_name}:{line}")
    click.echo(f"👤 Offending author: {author} ({commit_short})")
    click.echo("")
    click.echo("⏱️  Time saved:")
    click.echo("   - Manual fix average: 45 minutes")
    click.echo("   - Hermes automated fix: ~4 minutes")
    click.echo("   - **Time saved per incident: 41 minutes (91% reduction)**")
    click.echo("")
    click.echo("💵 Cost savings (based on $175/hr engineer rate):")
    click.echo("   - Manual cost: $131.25")
    click.echo("   - Hermes cost: $11.67 (API credits + overhead)")
    click.echo("   - **Net savings per fix: $119.58**")
    click.echo("")
    click.echo("📊 If you run 10 incidents/month:")
    click.echo("   - Monthly savings: ~$1,195")
    click.echo("   - Annual savings: ~$14,350")
    click.echo("")
    click.echo("🚀 To run the actual fix, remove the --dry-run flag.")
    click.echo("────────────────────────────────────────────")


def run(
    stack_trace: str,
    repo_url: str,
    base_branch: str = "main",
    test_command: str = "pytest",
    max_attempts: int = 3,
    workspace_base: str | None = None,
    dry_run: bool = False,
) -> dict:
    logger.info("=== Hermes starting ===")
    workspace = tempfile.mkdtemp(prefix="hermes_", dir=workspace_base)
    logger.info("Workspace: %s", workspace)

    try:
        # Phase 0: Parse trace + clone
        trace_info = parse_stack_trace(stack_trace)
        logger.info(
            "Parsed trace: %s line %d (%s)",
            trace_info["file_path"],
            trace_info["line_number"],
            trace_info["error_type"],
        )
        repo_dir = clone_repo(repo_url, workspace + "/repo", branch=base_branch)

        # Phase 1: Context gathering
        # Guard: stdlib/venv paths won't exist in the cloned repo and will crash git blame
        if trace_info["file_path"] != "unknown" and not os.path.exists(
            os.path.join(repo_dir, trace_info["file_path"])
        ):
            logger.warning(
                "File '%s' not found in cloned repo — likely a stdlib or venv path",
                trace_info["file_path"],
            )
            return {
                "success": False,
                "pr_url": None,
                "error": (
                    f"File '{trace_info['file_path']}' not found in repository. "
                    "Cannot run git blame — check that the stack trace points to a repo file, "
                    "not a stdlib or virtualenv path."
                ),
            }

        blame_info = get_blame(repo_dir, trace_info["file_path"], trace_info["line_number"])
        commit_diff = get_commit_diff(repo_dir, blame_info["commit_hash"])

        # Dry-run: skip Claude + PR, print ROI analysis and return
        if dry_run:
            _print_roi_analysis(trace_info, blame_info)
            return {"success": True, "dry_run": True, "pr_url": None}

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
                    logger.error(
                        "All %d attempts exhausted — human intervention required", max_attempts
                    )
                    return {
                        "success": False,
                        "pr_url": None,
                        "error": f"Max fix attempts ({max_attempts}) reached. Human intervention required.",
                    }

        # Phase 4: PR creation (push + PR are atomic — branch is deleted on PR failure)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"hotfix/hermes-{timestamp}-{secrets.token_hex(4)}"
        if not _commit_workspace_changes(repo_dir, branch_name):
            logger.info("No changes detected — exiting without PR")
            return {"success": True, "pr_url": None, "error": None}

        push_branch(repo_dir, branch_name)
        try:
            pr_url = create_github_pr(
                repo_url=repo_url,
                branch_name=branch_name,
                base_branch=base_branch,
                root_cause=root_cause,
                author=f"{blame_info['author']} <{blame_info['email']}>",
                test_output=last_test_output,
            )
        except Exception as e:
            logger.error(
                "PR creation failed (%s: %s), deleting remote branch %s to avoid zombie",
                type(e).__name__, e, branch_name,
            )
            delete_remote_branch(repo_dir, branch_name)
            raise

        logger.info("=== Hermes complete. PR: %s ===", pr_url)
        return {"success": True, "pr_url": pr_url, "error": None}

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        logger.info("Workspace cleaned up: %s", workspace)
