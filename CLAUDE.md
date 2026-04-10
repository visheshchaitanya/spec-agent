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
├── cli.py           # Click CLI: init, init-repo, install-hook, run, configure, opt-out, opt-in, config-get
├── config.py        # Config dataclass + load/save from ~/.spec-agent/config.yaml
├── agent.py         # Push agent: tool-use loop for spec generation on git push
├── init_agent.py    # Init-repo agent: tool-use loop for KB generation from codebase
└── tools/
    ├── wiki_read.py     # Read a vault markdown file (parses YAML frontmatter)
    ├── wiki_write.py    # Write/update a vault markdown file
    ├── wiki_search.py   # Full-text grep search across the vault
    ├── wiki_index.py    # Append entry to index.md
    ├── fs_read.py       # list_directory + read_source_file for init-repo agent
    └── init_cache.py    # File-timestamp cache for efficient init-repo --force re-runs
```

**Push flow:** git push → `~/.git-hooks/pre-push` → `spec-agent run` → `agent.py:run_agent()` → tool-use loop → vault markdown files written.

**Init flow:** `spec-agent init-repo` → `init_agent.py:run_init_agent()` → tool-use loop → KB docs written under `projects/<repo-name>/`.

**Agent tools** (defined in `agent.py`): `search_wiki`, `read_wiki_file`, `write_wiki_file`, `update_index`. The agent is prompted to skip chores, search before writing, and use `[[wikilink]]` syntax.

**Config** lives at `~/.spec-agent/config.yaml`. Key fields: `vault_path`, `model` (default `claude-sonnet-4-6`), `ignored_repos`, `ignored_branches` (glob patterns), `min_commit_chars`.

**Vault structure**: `features/`, `bugs/`, `refactors/`, `concepts/`, `projects/` subdirectories + `index.md` master log.

## Tests

Tests use `pytest` with a `vault_dir` fixture (in `conftest.py`) that creates a temp vault with standard folders. The agent's `_force_type` parameter allows bypassing API calls in tests.

`ANTHROPIC_API_KEY` must be set in the environment for any test or CLI run that calls the real API.

## Release checklist

**Every PR that adds features, fixes bugs, or changes behaviour must include:**

1. `CHANGELOG.md` — add an entry under the appropriate version section (`[Unreleased]` while in development, or a new `[x.y.z]` section when releasing). Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format: `### Added`, `### Changed`, `### Fixed`, `### Removed`.
2. `README.md` — update the Features list, CLI Reference, and any relevant usage sections to reflect the change. New commands must be documented under "CLI Reference".
3. `pyproject.toml` — bump `version` when cutting a release (semantic versioning: patch for fixes, minor for new features, major for breaking changes).
