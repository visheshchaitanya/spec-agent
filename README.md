# spec-agent

> Auto-generate an Obsidian knowledge wiki from every `git push` — powered by Claude.

Every time you push code, **spec-agent** reads the diff, classifies the change, and writes a structured spec document into your [Obsidian](https://obsidian.md) vault. Over time, your vault becomes a living, visually-navigable graph of everything you've ever built.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): the LLM acts as a compiler (raw commits → structured wiki), not a retrieval engine. No RAG, no embeddings — just well-organized markdown with `[[wikilinks]]` that Obsidian renders as a knowledge graph.

---

## How It Works

```
git push
  └── ~/.git-hooks/pre-push         ← global hook, fires on every repo
        └── spec-agent run           ← Python CLI
              └── Claude (tool-use)  ← agentic loop
                    ├── classify_commit
                    ├── search_wiki       ← finds related existing pages
                    ├── read_wiki_file    ← reads context before updating
                    ├── write_wiki_file   ← creates or updates spec
                    └── update_index      ← appends row to index.md
```

The agent:
1. Classifies the commit type (`feature`, `bug`, `refactor`, `arch`, `chore`)
2. Searches your vault for related pages to link to
3. Writes an adaptive spec using the appropriate template
4. Updates `index.md` — the master log that Claude reads at session start

**Chore commits are skipped.** Bot branches (`dependabot/*`, `renovate/*`) are skipped. Tiny commits (below a configurable character threshold) are skipped.

---

## Features

- **Zero friction** — fires automatically on every `git push`, no developer action needed
- **Adaptive templates** — selects the right format based on commit type
  - `feature` → full spec (summary, problem, implementation, files, open questions)
  - `bug` → short report (root cause, fix applied)
  - `refactor` → brief note (what changed, why, before/after)
  - `arch` → ADR format (context, decision, consequences, alternatives)
- **Accurate `[[wikilinks]]`** — searches vault for existing pages before writing, so links are real
- **Living index** — `index.md` is a table of every spec ever written; share it with Claude at session start to give it full project memory
- **Obsidian graph** — concepts referenced by many specs become visual hubs after 10+ specs
- **Works on every repo** — one global hook installation covers all your projects

---

## Prerequisites

- **Python 3.11+**
- **An Anthropic API key** — [get one here](https://console.anthropic.com)
- **Obsidian** — [download here](https://obsidian.md) (free)
- **Git 2.9+** (for `core.hooksPath` support)

---

## Installation

### From PyPI (recommended)

```bash
pip install spec-agent
```

### From source

```bash
git clone https://github.com/visheshchaitanya/spec-agent.git ~/.spec-agent
pip install -e ~/.spec-agent
```

---

## Setup

### 1. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.zshrc`, `~/.bashrc`, or `~/.zshenv`) to make it permanent:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
```

### 2. Initialize your vault

```bash
spec-agent init --vault ~/Documents/dev-wiki
```

This creates the vault directory structure and writes a default `~/.spec-agent/config.yaml`.

Then open `~/Documents/dev-wiki` as a vault in Obsidian (**File → Open vault as folder**).

### 3. Install the global git hook

```bash
spec-agent install-hook
```

This creates `~/.git-hooks/pre-push` and sets `git config --global core.hooksPath ~/.git-hooks`. The hook fires on every push in every repository on your machine.

To disable at any time:

```bash
spec-agent uninstall-hook
```

### 4. Push anything to test

```bash
cd ~/any-repo
git push
# → spec-agent fires in the background
# → spec appears in ~/Documents/dev-wiki
```

---

## Configuration

Config lives at `~/.spec-agent/config.yaml`:

```yaml
vault_path: ~/Documents/dev-wiki
model: claude-sonnet-4-6
ignored_repos: []           # list of repo names to skip entirely
ignored_branches:
  - dependabot/*
  - renovate/*
min_commit_chars: 50        # skip pushes where total commit message length is below this
```

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/dev-wiki` | Absolute path to your Obsidian vault |
| `model` | `claude-sonnet-4-6` | Anthropic model to use |
| `ignored_repos` | `[]` | Exact repo names to never process |
| `ignored_branches` | `[dependabot/*, renovate/*]` | Glob patterns — matching branches are skipped |
| `min_commit_chars` | `50` | Skip pushes where total commit message length is below this (filters "wip", "fix typo") |

---

## Vault Structure

```
~/Documents/dev-wiki/
├── index.md                    ← master log — give this to Claude at session start
├── features/
│   ├── alert-ingestion.md
│   └── auth-system.md
├── bugs/
│   ├── fix-status-migration.md
│   └── fix-null-pointer.md
├── refactors/
│   └── extract-auth-middleware.md
├── concepts/                   ← auto-created graph hubs when first referenced
│   ├── clickhouse.md
│   └── jwt.md
└── projects/
    └── my-app.md
```

### index.md — your project memory

`index.md` is a markdown table of every spec ever written:

```markdown
# Dev Wiki — Index

| Date | Type | Title | Project | Link |
|------|------|-------|---------|------|
| 2026-04-07 | bug | Fix status migration | my-app | [[bugs/fix-status-migration]] |
| 2026-04-05 | feature | Alert ingestion pipeline | my-app | [[features/alert-ingestion]] |
```

Paste the contents of `index.md` at the start of any Claude session — Claude immediately knows everything you've built across all projects.

### Spec frontmatter

Every generated spec has YAML frontmatter:

```yaml
---
type: feature
project: my-app
date: 2026-04-07
commit: a3f9c12
status: shipped
---
```

---

## Giving Claude context at session start

Paste this into your Claude session to give it full project memory:

```
Here is my dev wiki index — everything I've built:

<paste contents of ~/Documents/dev-wiki/index.md>

I'm working on <task>. Based on the index, what related specs should I look at?
```

Claude can then ask you to paste specific spec files for deeper context.

---

## CLI Reference

```
spec-agent [COMMAND] [OPTIONS]

Commands:
  run              Run the agent (called automatically by git hook)
  init             Initialize vault directory and write config
  install-hook     Install global git pre-push hook
  uninstall-hook   Remove the global git pre-push hook
  config-get       Read a config value (used internally by hook)
```

### `spec-agent run`

```
Options:
  --repo TEXT        Repository name (required)
  --branch TEXT      Branch that was pushed (required)
  --messages TEXT    Newline-separated commit messages (required)
  --diff-file TEXT   Path to temp file containing the git diff (required)
  --config TEXT      Path to config.yaml [default: ~/.spec-agent/config.yaml]
```

### `spec-agent init`

```
Options:
  --vault TEXT  Path to Obsidian vault directory (required)
```

### `spec-agent install-hook`

No options. Installs `~/.git-hooks/pre-push` and sets the global git hooks path.

### `spec-agent uninstall-hook`

No options. Removes `~/.git-hooks/pre-push`, disabling automatic spec generation on push.

---

## Manual run (without pushing)

You can run the agent manually against any repo:

```bash
DIFF_FILE=$(mktemp /tmp/spec-agent-diff.XXXXXX)
git diff HEAD~1..HEAD | head -c 50000 > "$DIFF_FILE"

spec-agent run \
  --repo "$(basename $(pwd))" \
  --branch "$(git rev-parse --abbrev-ref HEAD)" \
  --messages "$(git log HEAD~1..HEAD --format='%s')" \
  --diff-file "$DIFF_FILE"
```

---

## Per-repo opt-out

To exclude a specific repo from spec generation, add its name to `ignored_repos` in `~/.spec-agent/config.yaml`:

```yaml
ignored_repos:
  - my-private-repo
  - dotfiles
```

---

## Development

### Requirements

```bash
git clone https://github.com/visheshchaitanya/spec-agent.git
cd spec-agent
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Run tests with coverage

```bash
pytest --cov=spec_agent --cov-report=term-missing
```

All tests use temporary directories — no vault or API key required.

---

## Architecture

### Tool-using agent loop

The agent runs an Anthropic `messages.create` loop until `stop_reason == "end_turn"`:

```
client.messages.create(tools=TOOL_DEFINITIONS, ...)
  → stop_reason == "tool_use"
      → dispatch tool, collect results
      → append assistant + user messages
      → loop
  → stop_reason == "end_turn"
      → done
```

### Tools

| Tool | Purpose |
|------|---------|
| `classify_commit` | Agent classifies diff type and extracts concepts (no-op server-side — agent reasons internally) |
| `search_wiki` | Full-text search across vault using `grep -r` — finds related pages for wikilinks |
| `read_wiki_file` | Reads existing spec file — enables update mode instead of duplicate creation |
| `write_wiki_file` | Writes markdown to vault; `mode=update` appends a dated changelog section |
| `update_index` | Appends row to `index.md` master log |

### Diff safety

Git diffs larger than 50,000 characters are truncated before being passed to the agent. The diff is passed via a temp file (not shell arguments) to avoid escaping issues with special characters.

---

## Roadmap

- [ ] GitHub webhook / cloud daemon (replace local hook with HTTP POST)
- [ ] Multi-agent parallel processing (Classifier + Writer + Linker)
- [ ] Obsidian Dataview dashboards
- [ ] Per-project vault paths
- [ ] Slack/email notifications on spec creation

---

## Contributing

Pull requests welcome. Please:

1. Fork the repo and create a branch from `main`
2. Add tests for any new behavior
3. Ensure `pytest` passes
4. Open a pull request

---

## License

[MIT](LICENSE) — © 2026 Vishesh Chaitanya
