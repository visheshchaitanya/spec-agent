from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from spec_agent.agent import run_agent
from spec_agent.config import Config, DEFAULT_CONFIG_PATH, load_config, save_config
from spec_agent.init_agent import run_init_agent
from spec_agent.tools.init_cache import get_changed_files, save_cache

console = Console()

_HOOK_SCRIPT = """\
#!/usr/bin/env bash
# spec-agent pre-push hook
# Fires before every git push. Git passes the commit range via stdin.

set -euo pipefail

REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Git passes push info via stdin: <local ref> <local sha1> <remote ref> <remote sha1>
LOCAL_SHA=""
REMOTE_SHA=""
while IFS=' ' read -r local_ref local_sha remote_ref remote_sha; do
    LOCAL_SHA="$local_sha"
    REMOTE_SHA="$remote_sha"
    break
done

if [ -z "$LOCAL_SHA" ]; then
    exit 0
fi

# When pushing a new branch, remote sha is all zeros — use the initial commit as base
if [[ "$REMOTE_SHA" =~ ^0+$ ]]; then
    REMOTE_SHA=$(git rev-list --max-parents=0 HEAD)
fi

COMMITS=$(git log "${REMOTE_SHA}..${LOCAL_SHA}" --format="%s" 2>/dev/null)

# Write diff to a temp file to safely handle special characters
DIFF_FILE=$(mktemp /tmp/spec-agent-diff.XXXXXX)
git diff "${REMOTE_SHA}..${LOCAL_SHA}" 2>/dev/null | head -c 50000 > "$DIFF_FILE"

# Skip if no actual file changes
if [ ! -s "$DIFF_FILE" ]; then
    rm -f "$DIFF_FILE"
    exit 0
fi

spec-agent run \\
    --repo "$REPO_NAME" \\
    --branch "$BRANCH" \\
    --messages "$COMMITS" \\
    --diff-file "$DIFF_FILE" &

exit 0
"""


def _detect_repo_name() -> str:
    """Auto-detect repo name from the current directory via git."""
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return Path(repo_root).name
    except subprocess.CalledProcessError:
        return ""


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
    except OSError as e:
        console.print(f"[yellow]spec-agent: could not remove temp file {diff_path}: {e}[/yellow]")

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
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def init(vault, config):
    """Initialize vault and write config file."""
    vault_path = Path(vault).expanduser().resolve()
    config_path = Path(config)
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
    save_config(cfg, config_path)

    console.print(f"[green]✓[/green] Vault created at {vault_path}")
    console.print(f"[green]✓[/green] Config saved to {config_path}")
    console.print("\nNext step: [bold]spec-agent install-hook[/bold]")


@cli.command("install-hook")
def install_hook():
    """Install global git post-push hook."""
    hooks_dir = Path.home() / ".git-hooks"
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "pre-push"
    hook_path.write_text(_HOOK_SCRIPT)
    hook_path.chmod(0o755)

    subprocess.run(
        ["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
        check=True
    )

    console.print(f"[green]✓[/green] Hook installed at {hook_path}")
    console.print(f"[green]✓[/green] Global git hooksPath set to {hooks_dir}")
    console.print("\n[bold]Done.[/bold] Every git push will now trigger spec-agent.")


@cli.command("uninstall-hook")
def uninstall_hook():
    """Remove the global git pre-push hook."""
    hooks_dir = Path.home() / ".git-hooks"
    hook_path = hooks_dir / "pre-push"

    if not hook_path.exists():
        console.print("[yellow]spec-agent: hook not found — nothing to remove.[/yellow]")
        return

    hook_path.unlink()
    console.print(f"[green]✓[/green] Hook removed from {hook_path}")
    console.print("\n[bold]Done.[/bold] spec-agent will no longer run on git push.")
    console.print("To re-enable: [bold]spec-agent install-hook[/bold]")


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


@cli.command("configure")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def configure(config):
    """Interactively set up your LLM backend (no YAML editing required)."""
    config_path = Path(config)
    cfg = load_config(config_path)

    console.print("[bold cyan]spec-agent configure[/bold cyan]\n")
    console.print("Choose an LLM backend:\n")
    console.print("  [bold]anthropic[/bold]  Cloud — best quality, requires [yellow]ANTHROPIC_API_KEY[/yellow]")
    console.print("  [bold]ollama[/bold]     Local — free, runs on your machine (no API key)")
    console.print("  [bold]gemini[/bold]     Cloud — free tier available, requires [yellow]GEMINI_API_KEY[/yellow]\n")

    backend = click.prompt(
        "Backend",
        type=click.Choice(["anthropic", "ollama", "gemini"]),
        default=cfg.llm_backend,
    )

    if backend == "anthropic":
        model = click.prompt("Model", default=cfg.model)
        cfg.llm_backend = "anthropic"
        cfg.model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: anthropic, model: {model}")
        console.print("\n[bold]Set your API key (add to ~/.zshrc or ~/.bashrc to make it permanent):[/bold]")
        console.print('[dim]  export ANTHROPIC_API_KEY="sk-ant-..."[/dim]')

    elif backend == "ollama":
        console.print("\n[bold]Popular Ollama models:[/bold]")
        console.print("  qwen2.5:7b   — fast, good reasoning, ~4 GB")
        console.print("  qwen2.5:14b  — better quality, ~8 GB")
        console.print("  gemma3       — Google Gemma 3 (12B), ~7 GB")
        console.print("  llama3.2     — Meta Llama 3.2, ~2 GB")
        console.print("  mistral      — Mistral 7B, ~4 GB\n")
        url = click.prompt("Ollama server URL", default=cfg.ollama_url)
        model = click.prompt("Model name", default=cfg.ollama_model)
        cfg.llm_backend = "ollama"
        cfg.ollama_url = url
        cfg.ollama_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: ollama, model: {model}, url: {url}")
        console.print("\n[bold]To install Ollama and pull the model:[/bold]")
        console.print(f"[dim]  # 1. Install Ollama: https://ollama.com/download[/dim]")
        console.print(f"[dim]  # 2. Pull your chosen model:  ollama pull {model}[/dim]")
        console.print("\n[dim]Ollama starts automatically after install. To verify: ollama list[/dim]")

    elif backend == "gemini":
        console.print("\n[bold]Available Gemini models:[/bold]")
        console.print("  gemini-2.0-flash   — fast, free tier, recommended")
        console.print("  gemini-2.5-pro     — best quality, paid")
        console.print("  gemma-3-27b-it     — open Gemma 3 model via Google API\n")
        model = click.prompt("Model", default=cfg.gemini_model)
        cfg.llm_backend = "gemini"
        cfg.gemini_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: gemini, model: {model}")
        console.print("\n[bold]Set your API key — get one free at https://aistudio.google.com:[/bold]")
        console.print('[dim]  export GEMINI_API_KEY="AIza..."[/dim]')
        console.print('[dim]  echo \'export GEMINI_API_KEY="AIza..."\' >> ~/.zshrc[/dim]')

    console.print(
        f"\n[bold]Done.[/bold] Config lives at [dim]{config_path}[/dim] — "
        "run [bold]spec-agent configure[/bold] again to change it."
    )


@cli.command("opt-out")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def opt_out(config: str) -> None:
    """Exclude the current repo from spec-agent's global hook."""
    repo_name = _detect_repo_name()
    if not repo_name:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    config_path = Path(config)
    cfg = load_config(config_path)
    if repo_name in cfg.ignored_repos:
        console.print(f"[dim]{repo_name} is already ignored.[/dim]")
        return

    cfg.ignored_repos.append(repo_name)
    save_config(cfg, config_path)
    console.print(
        f"[green]✓[/green] [bold]{repo_name}[/bold] added to ignored repos — "
        f"spec-agent will skip future pushes"
    )


@cli.command("opt-in")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def opt_in(config: str) -> None:
    """Re-include the current repo in spec-agent's global hook."""
    repo_name = _detect_repo_name()
    if not repo_name:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    config_path = Path(config)
    cfg = load_config(config_path)
    if repo_name not in cfg.ignored_repos:
        console.print(f"[dim]{repo_name} is not currently ignored.[/dim]")
        return

    cfg.ignored_repos = [r for r in cfg.ignored_repos if r != repo_name]
    save_config(cfg, config_path)
    console.print(
        f"[green]✓[/green] [bold]{repo_name}[/bold] removed from ignored repos — "
        f"spec-agent is now active"
    )


@cli.command("init-repo")
@click.option("--deep", is_flag=True, default=False, help="Full breadth-first scan (reads up to 40 files)")
@click.option("--force", is_flag=True, default=False, help="Update existing KB without prompting")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def init_repo(deep: bool, force: bool, config: str) -> None:
    """Bootstrap a knowledge base for the current repo in the Obsidian vault."""
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
        repo_name = Path(repo_root).name
    except subprocess.CalledProcessError:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    cfg = load_config(Path(config))
    if not cfg.vault_path.exists():
        console.print(
            f"[yellow]spec-agent: vault not found at {cfg.vault_path}. Run: spec-agent init[/yellow]"
        )
        raise SystemExit(1)

    kb_path = cfg.vault_path / "projects" / repo_name
    if kb_path.exists() and not force:
        console.print(
            f"[yellow]⚠[/yellow]  KB already exists for [bold]{repo_name}[/bold]. "
            f"Run with [bold]--force[/bold] to update."
        )
        return

    changed_files = get_changed_files(repo_root, repo_name) if force else None

    mode = "[deep]" if deep else "[shallow]"
    console.print(f"[cyan]spec-agent init-repo:[/cyan] scanning {repo_name} {mode}...")

    run_init_agent(
        repo_path=repo_root,
        repo_name=repo_name,
        cfg=cfg,
        deep=deep,
        changed_files=changed_files,
    )

    save_cache(repo_name, repo_root)
    console.print(f"[green]✓[/green] KB written to {kb_path}")
    console.print(
        f"[green]✓[/green] Cache saved — future [bold]--force[/bold] runs will focus on changed files"
    )
