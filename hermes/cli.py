import json
import logging
import sys
import click
import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

from hermes.orchestrator import run as orchestrator_run
from hermes.test_runner import validate_test_command

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def validate_repo_url(url: str) -> None:
    if not url.startswith("https://github.com/"):
        raise ValueError(
            "Hermes only supports public GitHub repositories over HTTPS for security (SSRF protection). "
            "URL must start with https://github.com/"
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
@click.option(
    "--error-file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON error payload (Sentry format)",
)
@click.option("--repo", required=True, help="Target repository URL")
@click.option("--base-branch", default="main", show_default=True)
@click.option("--test-command", default=None, help="Test command (default: from config.yaml)")
@click.option("--max-attempts", default=None, type=int, help="Max fix attempts (default: from config.yaml)")
@click.option("--dry-run", is_flag=True, help="Simulate the fix and show ROI without running Claude or creating a PR.")
def fix(error, error_file, repo, base_branch, test_command, max_attempts, dry_run):
    """Diagnose a production error and create an automated fix PR."""
    if not error and not error_file:
        raise click.UsageError("Provide either --error or --error-file")

    try:
        validate_repo_url(repo)
    except ValueError as e:
        raise click.UsageError(str(e))

    config = _load_config()
    effective_test_command = test_command or config.get("default_test_command", "pytest")
    effective_max_attempts = max_attempts or config.get("max_fix_attempts", 3)
    effective_workspace_base = config.get("workspace_base") or None

    try:
        validate_test_command(effective_test_command)
    except ValueError as e:
        raise click.UsageError(str(e))

    stack_trace = _parse_sentry_json(error_file) if error_file else error
    click.echo("Hermes is analyzing the error...")

    result = orchestrator_run(
        stack_trace=stack_trace,
        repo_url=repo,
        base_branch=base_branch,
        test_command=effective_test_command,
        max_attempts=effective_max_attempts,
        workspace_base=effective_workspace_base,
        dry_run=dry_run,
    )

    if result["success"]:
        if not result.get("dry_run") and result["pr_url"]:
            click.echo(f"PR: {result['pr_url']}")
        elif not result.get("dry_run"):
            click.echo("Tests already passing — no fix needed.")
        sys.exit(0)
    else:
        click.echo(f"Failed: {result['error']}", err=True)
        sys.exit(1)


def main():
    cli()
