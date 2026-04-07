from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from spec_agent.agent import run_agent
from spec_agent.config import Config, DEFAULT_CONFIG_PATH, load_config, save_config

console = Console()

_HOOK_SCRIPT = """\
#!/usr/bin/env bash
# spec-agent post-push hook
# Fires after every git push. Passes diff via temp file to avoid shell escaping issues.

set -euo pipefail

REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Get commit range pushed
RANGE=$(git log @{u}..HEAD --format="%H" 2>/dev/null | tail -1)
if [ -z "$RANGE" ]; then
    exit 0
fi

COMMITS=$(git log @{u}..HEAD --format="%s" 2>/dev/null)
MSG_LEN=$(echo "$COMMITS" | wc -c)
MIN_CHARS=$(spec-agent config-get min_commit_chars 2>/dev/null || echo "50")

if [ "$MSG_LEN" -lt "$MIN_CHARS" ]; then
    exit 0
fi

# Write diff to a temp file to safely handle special characters
DIFF_FILE=$(mktemp /tmp/spec-agent-diff.XXXXXX)
git diff @{u}..HEAD 2>/dev/null | head -c 50000 > "$DIFF_FILE"

spec-agent run \\
    --repo "$REPO_NAME" \\
    --branch "$BRANCH" \\
    --messages "$COMMITS" \\
    --diff-file "$DIFF_FILE" &

exit 0
"""


@click.group()
def cli():
    """spec-agent: Auto-generate wiki specs from git commits."""


@cli.command()
@click.option("--repo", required=True, help="Repository name")
@click.option("--branch", required=True, help="Branch that was pushed")
@click.option("--messages", required=True, help="Newline-separated commit messages")
@click.option("--diff-file", required=True, help="Path to temp file containing the git diff")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def run(repo, branch, messages, diff_file, config):
    """Run the spec agent (called by git hook)."""
    cfg = load_config(Path(config))

    if cfg.is_repo_ignored(repo):
        console.print(f"[dim]spec-agent: skipping ignored repo {repo}[/dim]")
        return

    if cfg.is_branch_ignored(branch):
        console.print(f"[dim]spec-agent: skipping ignored branch {branch}[/dim]")
        return

    commit_messages = [m.strip() for m in messages.strip().splitlines() if m.strip()]

    if not cfg.vault_path.exists():
        console.print(f"[yellow]spec-agent: vault not found at {cfg.vault_path}. Run: spec-agent init[/yellow]")
        return

    # Read diff from temp file then clean up
    diff_path = Path(diff_file)
    diff = diff_path.read_text(encoding="utf-8", errors="replace") if diff_path.exists() else ""
    try:
        diff_path.unlink(missing_ok=True)
    except Exception:
        pass

    console.print(f"[cyan]spec-agent:[/cyan] processing push to {repo}/{branch}")
    run_agent(
        diff=diff,
        commit_messages=commit_messages,
        repo_name=repo,
        branch=branch,
        cfg=cfg,
    )
    console.print(f"[green]spec-agent:[/green] done — check {cfg.vault_path}")


@cli.command()
@click.option("--vault", required=True, help="Path to Obsidian vault directory")
def init(vault):
    """Initialize vault and write config file."""
    vault_path = Path(vault).expanduser().resolve()
    vault_path.mkdir(parents=True, exist_ok=True)

    for folder in ["features", "bugs", "refactors", "concepts", "projects"]:
        (vault_path / folder).mkdir(exist_ok=True)

    index = vault_path / "index.md"
    if not index.exists():
        index.write_text(
            "# Dev Wiki — Index\n\n"
            "| Date | Type | Title | Project | Link |\n"
            "|------|------|-------|---------|------|\n"
        )

    cfg = Config(vault_path=vault_path)
    save_config(cfg)

    console.print(f"[green]✓[/green] Vault created at {vault_path}")
    console.print(f"[green]✓[/green] Config saved to {DEFAULT_CONFIG_PATH}")
    console.print("\nNext step: [bold]spec-agent install-hook[/bold]")


@cli.command("install-hook")
def install_hook():
    """Install global git post-push hook."""
    hooks_dir = Path.home() / ".git-hooks"
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "post-push"
    hook_path.write_text(_HOOK_SCRIPT)
    hook_path.chmod(0o755)

    subprocess.run(
        ["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
        check=True
    )

    console.print(f"[green]✓[/green] Hook installed at {hook_path}")
    console.print(f"[green]✓[/green] Global git hooksPath set to {hooks_dir}")
    console.print("\n[bold]Done.[/bold] Every git push will now trigger spec-agent.")


@cli.command("config-get")
@click.argument("key")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH))
def config_get(key, config):
    """Get a config value (used by the hook script)."""
    cfg = load_config(Path(config))
    value = getattr(cfg, key, None)
    if value is not None:
        click.echo(str(value))
    else:
        sys.exit(1)
