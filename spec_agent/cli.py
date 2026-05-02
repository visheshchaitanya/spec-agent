from __future__ import annotations
import logging
import logging.handlers
import os
import subprocess
import sys
from pathlib import Path

import click
import questionary
from rich.console import Console

from spec_agent.agent import run_agent
from spec_agent.config import Config, DEFAULT_CONFIG_PATH, load_config, save_config
from spec_agent.init_agent import run_init_agent
from spec_agent.tools.init_cache import get_changed_files, save_cache

console = Console()

LOG_PATH = Path.home() / ".spec-agent" / "spec-agent.log"


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

_HOOK_SCRIPT = """\
#!/usr/bin/env bash
# spec-agent pre-push hook
# Fires before every git push. Git passes the commit range via stdin.

set -euo pipefail

# Load API keys from shell profiles safely.
# Each profile is sourced inside a bash subprocess so that exec/exit calls
# (common in zsh configs) cannot terminate this hook script.
# export -p dumps the resulting env; eval imports it into the current shell.
_import_env() {
    local _f="$1"
    [ -f "$_f" ] || return 0
    # shellcheck disable=SC1090
    eval "$(bash --norc --noprofile -c "source '$_f' 2>/dev/null; export -p" 2>/dev/null)" 2>/dev/null || true
}
_import_env "$HOME/.profile"
_import_env "$HOME/.bashrc"
_import_env "$HOME/.zshrc"
unset -f _import_env

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
git diff "${REMOTE_SHA}..${LOCAL_SHA}" 2>/dev/null | head -c 50000 > "$DIFF_FILE" || true

# Skip if no actual file changes
if [ ! -s "$DIFF_FILE" ]; then
    rm -f "$DIFF_FILE"
    exit 0
fi

spec-agent run \\
    --repo "$REPO_NAME" \\
    --branch "$BRANCH" \\
    --messages "$COMMITS" \\
    --diff-file "$DIFF_FILE" >> /tmp/spec-agent-hook.log 2>&1 &
disown $!

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
    _setup_logging()


@cli.command()
@click.option("--repo", required=True, help="Repository name")
@click.option("--branch", required=True, help="Branch that was pushed")
@click.option("--messages", required=True, help="Newline-separated commit messages")
@click.option("--diff-file", required=True, help="Path to temp file containing the git diff")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def run(repo, branch, messages, diff_file, config):
    """Run the spec agent (called by git hook)."""
    logger = logging.getLogger(__name__)
    logger.info("run started — repo=%s branch=%s", repo, branch)
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
    try:
        run_agent(
            diff=diff,
            commit_messages=commit_messages,
            repo_name=repo,
            branch=branch,
            cfg=cfg,
        )
    except Exception:
        logger.exception("run failed for %s/%s", repo, branch)
        raise
    logger.info("run finished — repo=%s branch=%s", repo, branch)
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
    console.print("\nNext steps:")
    console.print("  1. [bold]spec-agent configure[/bold]   — choose your LLM backend (Anthropic, Ollama, or Gemini)")
    console.print("  2. [bold]spec-agent install-hook[/bold] — install the global git hook")


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

    backend = questionary.select(
        "Choose an LLM backend:",
        choices=[
            questionary.Choice("groq       — Cloud, free tier (1 000 req/day), recommended", value="groq"),
            questionary.Choice("ollama     — Local, free, runs on your machine (no API key)", value="ollama"),
            questionary.Choice("gemini     — Cloud, free tier available, requires GEMINI_API_KEY", value="gemini"),
            questionary.Choice("github     — Cloud, free tier (150 req/day), requires GITHUB_TOKEN", value="github"),
            questionary.Choice("anthropic  — Cloud, best quality, requires ANTHROPIC_API_KEY", value="anthropic"),
        ],
        default=cfg.llm_backend,
    ).ask()

    if backend is None:
        return

    if backend == "anthropic":
        model = questionary.select(
            "Choose a model:",
            choices=[
                questionary.Choice("claude-sonnet-4-6  — best quality, recommended", value="claude-sonnet-4-6"),
                questionary.Choice("claude-haiku-4-5   — faster, lower cost", value="claude-haiku-4-5-20251001"),
            ],
            default=cfg.model if cfg.model in ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"] else "claude-sonnet-4-6",
        ).ask()
        if model is None:
            return
        cfg.llm_backend = "anthropic"
        cfg.model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: anthropic, model: {model}")
        console.print("\n[bold]Set your API key (add to ~/.zshrc or ~/.bashrc to make it permanent):[/bold]")
        console.print('[dim]  export ANTHROPIC_API_KEY="sk-ant-..."[/dim]')

    elif backend == "ollama":
        model = questionary.select(
            "Choose a model:",
            choices=[
                questionary.Choice("qwen2.5:7b   — fast, good reasoning, ~4 GB", value="qwen2.5:7b"),
                questionary.Choice("qwen2.5:14b  — better quality, ~8 GB", value="qwen2.5:14b"),
                questionary.Choice("gemma3       — Google Gemma 3 (12B), ~7 GB", value="gemma3"),
                questionary.Choice("llama3.2     — Meta Llama 3.2, ~2 GB", value="llama3.2"),
                questionary.Choice("mistral      — Mistral 7B, ~4 GB", value="mistral"),
            ],
            default=cfg.ollama_model if cfg.ollama_model in ["qwen2.5:7b", "qwen2.5:14b", "gemma3", "llama3.2", "mistral"] else "qwen2.5:7b",
        ).ask()
        if model is None:
            return
        cfg.llm_backend = "ollama"
        cfg.ollama_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: ollama, model: {model}")
        console.print("\n[bold]To install Ollama and pull the model:[/bold]")
        console.print("[dim]  # 1. Install Ollama: https://ollama.com/download[/dim]")
        console.print(f"[dim]  # 2. Pull your chosen model:  ollama pull {model}[/dim]")
        console.print("\n[dim]Ollama starts automatically after install. To verify: ollama list[/dim]")

    elif backend == "gemini":
        model = questionary.select(
            "Choose a model:",
            choices=[
                questionary.Choice("gemini-2.0-flash  — fast, free tier, recommended", value="gemini-2.0-flash"),
                questionary.Choice("gemini-2.5-pro    — best quality, paid", value="gemini-2.5-pro"),
            ],
            default=cfg.gemini_model if cfg.gemini_model in ["gemini-2.0-flash", "gemini-2.5-pro"] else "gemini-2.0-flash",
        ).ask()
        if model is None:
            return
        cfg.llm_backend = "gemini"
        cfg.gemini_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: gemini, model: {model}")
        try:
            from google import genai as _genai  # noqa: F401
        except ImportError:
            console.print(
                "\n[yellow]⚠[/yellow]  The [bold]google-genai[/bold] package is not installed. "
                "Install it before running spec-agent:\n"
                "  [bold]pip install google-genai[/bold]"
            )
        console.print("\n[bold]Set your API key — get one free at https://aistudio.google.com:[/bold]")
        console.print('[dim]  export GEMINI_API_KEY="AIza..."[/dim]')
        console.print('[dim]  echo \'export GEMINI_API_KEY="AIza..."\' >> ~/.zshrc[/dim]')

    elif backend == "github":
        model = questionary.select(
            "Choose a model:",
            choices=[
                questionary.Choice("gpt-4o-mini  — fast, free tier, recommended", value="gpt-4o-mini"),
                questionary.Choice("gpt-4o       — higher quality, still free tier", value="gpt-4o"),
            ],
            default=cfg.github_model if cfg.github_model in ["gpt-4o-mini", "gpt-4o"] else "gpt-4o-mini",
        ).ask()
        if model is None:
            return
        cfg.llm_backend = "github"
        cfg.github_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: github, model: {model}")
        console.print(
            "\n[yellow]Rate limit:[/yellow] 150 requests/day on the free tier.\n"
            "  Each git push uses ~4-5 requests. [bold]init-repo --deep[/bold] uses ~30.\n"
        )
        console.print("\n[bold]Set GITHUB_TOKEN — generate at https://github.com/settings/tokens:[/bold]")
        console.print('[dim]  export GITHUB_TOKEN="github_pat_..."[/dim]')
        console.print('[dim]  echo \'export GITHUB_TOKEN="github_pat_..."\' >> ~/.zshrc[/dim]')
        console.print('\n[dim]A classic PAT with no scopes (or a fine-grained token with "Models" access) is sufficient.[/dim]')

    elif backend == "groq":
        model = questionary.select(
            "Choose a model:",
            choices=[
                questionary.Choice("llama-3.3-70b-versatile  — best quality, recommended", value="llama-3.3-70b-versatile"),
                questionary.Choice("llama-3.1-8b-instant     — faster, higher daily limits", value="llama-3.1-8b-instant"),
            ],
            default=cfg.groq_model if cfg.groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"] else "llama-3.3-70b-versatile",
        ).ask()
        if model is None:
            return
        cfg.llm_backend = "groq"
        cfg.groq_model = model
        save_config(cfg, config_path)
        console.print(f"\n[green]✓[/green] Config saved → backend: groq, model: {model}")
        console.print(
            "\n[yellow]Free tier limits (llama-3.3-70b-versatile):[/yellow] 1 000 req/day, 30 req/min, 12 000 TPM.\n"
            "  Each git push uses ~4-6 requests (~200 pushes/day free).\n"
        )
        console.print("\n[bold]Get your free GROQ_API_KEY (no credit card required):[/bold]")
        console.print("[dim]  1. Sign up at https://console.groq.com (free account)[/dim]")
        console.print("[dim]  2. Go to https://console.groq.com/keys → click Create API Key[/dim]")
        console.print('[dim]  3. export GROQ_API_KEY="gsk_..."[/dim]')
        console.print('[dim]     echo \'export GROQ_API_KEY="gsk_..."\' >> ~/.zshrc[/dim]')
        console.print('\n[dim]Free tier is permanent — no trial period, no credit card.[/dim]')

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

    logger = logging.getLogger(__name__)
    mode = "[deep]" if deep else "[shallow]"
    logger.info("init-repo started — repo=%s mode=%s", repo_name, mode.strip("[]"))
    console.print(f"[cyan]spec-agent init-repo:[/cyan] scanning {repo_name} {mode}...")

    try:
        run_init_agent(
            repo_path=repo_root,
            repo_name=repo_name,
            cfg=cfg,
            deep=deep,
            changed_files=changed_files,
        )
    except Exception:
        logger.exception("init-repo failed for %s", repo_name)
        raise

    save_cache(repo_name, repo_root)
    logger.info("init-repo finished — repo=%s kb_path=%s", repo_name, kb_path)
    console.print(f"[green]✓[/green] KB written to {kb_path}")
    console.print(
        f"[green]✓[/green] Cache saved — future [bold]--force[/bold] runs will focus on changed files"
    )


@cli.command("logs")
@click.option("-n", default=50, help="Number of lines to show (default: 50)")
@click.option("--errors", is_flag=True, default=False, help="Show only ERROR and above")
def logs(n: int, errors: bool) -> None:
    """Show recent spec-agent log entries."""
    if not LOG_PATH.exists():
        console.print(f"[yellow]No log file found at {LOG_PATH}[/yellow]")
        return

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    if errors:
        lines = [l for l in lines if " ERROR    " in l or " CRITICAL " in l]

    for line in lines[-n:]:
        if " ERROR    " in line or " CRITICAL " in line:
            console.print(f"[red]{line}[/red]")
        elif " WARNING  " in line:
            console.print(f"[yellow]{line}[/yellow]")
        else:
            console.print(f"[dim]{line}[/dim]")
