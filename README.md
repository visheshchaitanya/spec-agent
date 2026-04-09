# spec-agent

> Auto-generate an Obsidian knowledge wiki from every `git push` — powered by Claude, Ollama, or Gemini.

Every time you push code, **spec-agent** reads the diff, classifies the change, and writes a structured spec document into your [Obsidian](https://obsidian.md) vault. Over time, your vault becomes a living, visually-navigable graph of everything you've ever built.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): the LLM acts as a compiler (raw commits → structured wiki), not a retrieval engine. No RAG, no embeddings — just well-organized markdown with `[[wikilinks]]` that Obsidian renders as a knowledge graph.

---

## How It Works

```
git push
  └── ~/.git-hooks/pre-push         ← global hook, fires on every repo
        └── spec-agent run           ← Python CLI
              └── LLM (tool-use)     ← agentic loop (Anthropic / Ollama / Gemini)
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
- **Pluggable LLM backends** — use Anthropic (cloud), Ollama (local/free), or Gemini (free tier)
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
- **Obsidian** — [download here](https://obsidian.md) (free)
- **Git 2.9+** (for `core.hooksPath` support)
- **One of the following LLM backends** (you choose during setup):
  - **Anthropic** — [API key](https://console.anthropic.com) required
  - **Ollama** — free, runs locally; [download here](https://ollama.com/download)
  - **Gemini** — free tier available; [API key](https://aistudio.google.com) required

---

## Installation

### From PyPI (recommended)

```bash
pip install spec-agent
```

### From source

```bash
git clone https://github.com/visheshchaitanya/spec-agent.git
cd spec-agent
pip install -e .
```

For Gemini backend support, install the extra:

```bash
pip install "spec-agent[gemini]"
```

---

## Setup

### 1. Initialize your vault

```bash
spec-agent init --vault ~/Documents/dev-wiki
```

This creates the vault directory structure and writes a default `~/.spec-agent/config.yaml`.

Then open `~/Documents/dev-wiki` as a vault in Obsidian (**File → Open vault as folder**).

### 2. Choose your LLM backend

```bash
spec-agent configure
```

This interactive command walks you through picking a backend and saves your settings — no YAML editing needed:

```
spec-agent configure

Choose an LLM backend:

  anthropic  Cloud — best quality, requires ANTHROPIC_API_KEY
  ollama     Local — free, runs on your machine (no API key)
  gemini     Cloud — free tier available, requires GEMINI_API_KEY

Backend [anthropic]: ollama

Popular Ollama models:
  qwen2.5:7b   — fast, good reasoning, ~4 GB
  qwen2.5:14b  — better quality, ~8 GB
  gemma3       — Google Gemma 3 (12B), ~7 GB
  llama3.2     — Meta Llama 3.2, ~2 GB

Ollama server URL [http://localhost:11434]:
Model name [qwen2.5:7b]:

✓ Config saved → backend: ollama, model: qwen2.5:7b

To install Ollama and pull the model:
  # 1. Install Ollama: https://ollama.com/download
  # 2. Pull your chosen model:
  ollama pull qwen2.5:7b
```

#### Setting API keys (Anthropic / Gemini)

API keys are read from environment variables — they are never written to disk.

**Anthropic:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Add to ~/.zshrc or ~/.bashrc to make permanent
```

**Gemini** (free tier at [aistudio.google.com](https://aistudio.google.com)):
```bash
export GEMINI_API_KEY="AIza..."
# Add to ~/.zshrc or ~/.bashrc to make permanent
```

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

## LLM Backends

| Backend | Cost | Quality | Setup |
|---------|------|---------|-------|
| `anthropic` | ~$0.003–0.015 / push | Best | `ANTHROPIC_API_KEY` |
| `ollama` | Free (local compute) | Good (model-dependent) | Install Ollama + pull model |
| `gemini` | Free tier / ~$0.001 | Good | `GEMINI_API_KEY` |

### Running with Ollama (local, zero cost)

1. [Install Ollama](https://ollama.com/download)
2. Pull a model:
   ```bash
   ollama pull qwen2.5:7b   # fast, good reasoning
   # or
   ollama pull gemma3        # Google Gemma 3
   ```
3. Configure spec-agent:
   ```bash
   spec-agent configure     # choose "ollama", set model name
   ```

Ollama runs the model locally on your GPU/CPU — no data leaves your machine.

### Running with Gemini (cheap cloud alternative)

1. Get a free API key at [aistudio.google.com](https://aistudio.google.com)
2. Install the extra dependency:
   ```bash
   pip install "spec-agent[gemini]"
   ```
3. Configure:
   ```bash
   export GEMINI_API_KEY="AIza..."
   spec-agent configure     # choose "gemini"
   ```

---

## Configuration

Config lives at `~/.spec-agent/config.yaml`. Run `spec-agent configure` to update it interactively, or edit it directly:

```yaml
vault_path: ~/Documents/dev-wiki
model: claude-sonnet-4-6
ignored_repos: []
ignored_branches:
  - dependabot/*
  - renovate/*
min_commit_chars: 50
# LLM backend
llm_backend: anthropic        # anthropic | ollama | gemini
ollama_url: http://localhost:11434
ollama_model: qwen2.5:7b
gemini_model: gemini-2.0-flash
```

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/dev-wiki` | Absolute path to your Obsidian vault |
| `model` | `claude-sonnet-4-6` | Anthropic model (used when `llm_backend: anthropic`) |
| `ignored_repos` | `[]` | Exact repo names to never process |
| `ignored_branches` | `[dependabot/*, renovate/*]` | Glob patterns — matching branches are skipped |
| `min_commit_chars` | `50` | Skip pushes where total commit message length is below this |
| `llm_backend` | `anthropic` | Which backend to use: `anthropic`, `ollama`, or `gemini` |
| `ollama_url` | `http://localhost:11434` | Ollama server URL (change if running on a remote machine) |
| `ollama_model` | `qwen2.5:7b` | Ollama model name (must be pulled first via `ollama pull`) |
| `gemini_model` | `gemini-2.0-flash` | Gemini model name |

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
  configure        Interactively set up your LLM backend (recommended)
  init             Initialize vault directory and write config
  install-hook     Install global git pre-push hook
  uninstall-hook   Remove the global git pre-push hook
  run              Run the agent (called automatically by git hook)
  config-get       Read a config value (used internally by hook)
```

### `spec-agent configure`

Interactive setup wizard. Prompts for backend choice and backend-specific settings, then saves to `~/.spec-agent/config.yaml`. No options required.

### `spec-agent init`

```
Options:
  --vault TEXT  Path to Obsidian vault directory (required)
```

### `spec-agent install-hook`

No options. Installs `~/.git-hooks/pre-push` and sets the global git hooks path.

### `spec-agent uninstall-hook`

No options. Removes `~/.git-hooks/pre-push`, disabling automatic spec generation on push.

### `spec-agent run`

```
Options:
  --repo TEXT        Repository name (required)
  --branch TEXT      Branch that was pushed (required)
  --messages TEXT    Newline-separated commit messages (required)
  --diff-file TEXT   Path to temp file containing the git diff (required)
  --config TEXT      Path to config.yaml [default: ~/.spec-agent/config.yaml]
```

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

To exclude a specific repo from spec generation, add its name to `ignored_repos` via `spec-agent configure` or directly in `~/.spec-agent/config.yaml`:

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

### Pluggable LLM backends

The agent loop in `agent.py` is backend-agnostic. A backend is selected via `get_backend(cfg)` and implements a common interface:

```
LLMBackend
  ├── AnthropicBackend   uses anthropic SDK, native tool-use
  ├── OllamaBackend      HTTP POST to /api/chat, OpenAI-compatible tool format
  └── GeminiBackend      uses google-genai SDK, function declarations
```

Each backend normalizes its response to a `ChatResponse(stop_reason, text, tool_calls)` so the agent loop is identical regardless of which LLM is running.

### Tool-using agent loop

```
backend.chat(system, messages, tools)
  → stop_reason == "tool_use"
      → dispatch tool, collect results
      → backend.make_tool_results_messages(tool_calls, results)
      → append to messages, loop
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

- [ ] Auto-detect Ollama installation and pull model during `spec-agent configure` ([#enhancement](https://github.com/visheshchaitanya/spec-agent/issues))
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
