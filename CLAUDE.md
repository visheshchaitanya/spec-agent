# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

`spec-agent` is a CLI tool that automatically generates Obsidian wiki specs from git commits. It installs a global `post-push` git hook that fires after every `git push`, reads the diff + commit messages, and calls Claude (via the Anthropic API) to write structured markdown specs into an Obsidian vault.

## Commands

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_agent.py

# Run with coverage
pytest --cov=spec_agent --cov-report=term-missing

# Install the CLI locally
pip install -e .

# Initialize vault and config
spec-agent init --vault ~/Documents/dev-wiki

# Install the global git hook
spec-agent install-hook
```

## Architecture

```
spec_agent/
├── cli.py          # Click CLI entry point: init, install-hook, run, config-get
├── config.py       # Config dataclass + load/save from ~/.spec-agent/config.yaml
├── agent.py        # Anthropic tool-use agent loop (the core LLM logic)
└── tools/
    ├── wiki_read.py    # Read a vault markdown file (parses YAML frontmatter)
    ├── wiki_write.py   # Write/update a vault markdown file
    ├── wiki_search.py  # Full-text grep search across the vault
    └── wiki_index.py   # Append entry to index.md
```

**Flow:** git push → `~/.git-hooks/post-push` → `spec-agent run` → `agent.py:run_agent()` → tool-use loop with Claude → vault markdown files written.

**Agent tools** (defined in `agent.py`): `classify_commit` (no-op, LLM reasons internally), `search_wiki`, `read_wiki_file`, `write_wiki_file`, `update_index`. The agent is prompted to skip chores, search before writing, and use `[[wikilink]]` syntax.

**Config** lives at `~/.spec-agent/config.yaml`. Key fields: `vault_path`, `model` (default `claude-sonnet-4-6`), `ignored_repos`, `ignored_branches` (glob patterns), `min_commit_chars`.

**Vault structure**: `features/`, `bugs/`, `refactors/`, `concepts/`, `projects/` subdirectories + `index.md` master log.

## Tests

Tests use `pytest` with a `vault_dir` fixture (in `conftest.py`) that creates a temp vault with standard folders. The agent's `_force_type` parameter allows bypassing API calls in tests.

`ANTHROPIC_API_KEY` must be set in the environment for any test or CLI run that calls the real API.
