# Architecture

## Overview

`spec-agent` is a lightweight CLI daemon that hooks into git's `post-push` event and uses Claude's tool-use API to auto-generate structured markdown specs in an Obsidian vault. There is no server, no database — only a config file, a git hook, and a flat file vault.

## End-to-End Flow

```
git push
  └─► ~/.git-hooks/post-push  (bash script, installed by spec-agent install-hook)
        └─► spec-agent run --repo ... --branch ... --messages ... --diff-file ...
              └─► agent.py: run_agent()
                    └─► Claude API (tool-use loop)
                          ├─► classify_commit   (reasoning only, no I/O)
                          ├─► search_wiki       → grep across vault
                          ├─► read_wiki_file    → read existing .md + frontmatter
                          ├─► write_wiki_file   → create or update .md
                          └─► update_index      → append row to index.md
```

The hook script passes the git diff via a temp file (not via shell args) to safely handle special characters and large diffs. The diff is truncated to 50,000 characters before being sent to the API.

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Click group: `init`, `install-hook`, `run`, `config-get`. Entry point for the `spec-agent` binary. |
| `config.py` | `Config` dataclass + YAML load/save at `~/.spec-agent/config.yaml`. Handles repo/branch ignore patterns (fnmatch glob). |
| `agent.py` | Anthropic tool-use loop. Builds the user message, dispatches tool calls, iterates until `end_turn`. |
| `tools/wiki_read.py` | Read a vault `.md` file; parses YAML frontmatter via `python-frontmatter`. |
| `tools/wiki_write.py` | Create (overwrite) or update (append changelog section) a vault `.md` file. |
| `tools/wiki_search.py` | Full-text search via `grep -r -i -n --include=*.md`. Returns path, title (first heading), excerpt. |
| `tools/wiki_index.py` | Append a `| date | type | title | project | [[link]] |` row to `index.md`. |

## Agent Tool Protocol

The agent is given five tools. Claude decides the call order; the expected pattern is:

1. `classify_commit` — a no-op that triggers Claude's internal reasoning about commit type. Returns early if type is `chore`.
2. `search_wiki` — finds related pages before writing to avoid duplicates and populate `[[wikilinks]]`.
3. `read_wiki_file` — reads a specific page when the agent wants to update it rather than create a new one.
4. `write_wiki_file` — writes the spec. Mode `create` overwrites; mode `update` appends to the `## Changelog` section.
5. `update_index` — appends to `index.md` after the spec is written.

## Vault Structure

```
<vault>/
├── index.md           # Master log — one row per pushed spec
├── features/          # Feature specs
├── bugs/              # Bug fix specs
├── refactors/         # Refactor specs
├── concepts/          # Architecture / concept notes
└── projects/          # Per-project overview pages
```

`spec-agent init --vault <path>` creates this layout and writes `~/.spec-agent/config.yaml`.

## Configuration

`~/.spec-agent/config.yaml`:

```yaml
vault_path: ~/Documents/dev-wiki
model: claude-sonnet-4-6
ignored_repos: []
ignored_branches:
  - dependabot/*
  - renovate/*
min_commit_chars: 50   # Skip push if total commit message length < this
```

`is_branch_ignored` uses `fnmatch`, so glob patterns like `dependabot/*` work correctly.

## Hook Firing Conditions

The bash hook exits early (no API call) when:
- No commits exist ahead of the upstream (`@{u}..HEAD` is empty)
- Total commit message length is below `min_commit_chars`
- The repo or branch matches an ignore pattern (checked in `cli.py:run`)
- The vault directory does not exist

## Key Dependencies

| Package | Role |
|---------|------|
| `anthropic` | Claude API client + tool-use response parsing |
| `click` | CLI argument parsing |
| `pyyaml` | Config file serialization |
| `python-frontmatter` | Parse YAML frontmatter from vault `.md` files |
| `rich` | Terminal output formatting |
