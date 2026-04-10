# spec-agent: init-repo & opt-out/opt-in Design

**Date:** 2026-04-10
**Status:** Approved

---

## Overview

Two independent features that solve the "cold start" problem and give users control over which repos trigger the global hook.

- **Req 1 — `spec-agent init-repo`**: Bootstraps a knowledge base (KB) for an existing codebase in the Obsidian vault, so the push agent has rich context from day one.
- **Req 2 — `spec-agent opt-out` / `spec-agent opt-in`**: Lets users exclude specific repos from the global pre-push hook to avoid unwanted API costs.

---

## Context & Problem

The current push flow fires on every `git push`, generates specs from the diff/commit messages, and writes them to the vault. This works well for ongoing development but has two gaps:

1. **Cold start**: A freshly installed spec-agent has an empty vault. The first several pushes on any existing codebase produce specs with no links to prior context — the LLM doesn't know the architecture, key classes, or patterns in the repo.
2. **No opt-out**: The global hook fires on all repos. There's no way to say "don't run spec-agent for this repo" without uninstalling the hook entirely.

---

## Requirement 1: `spec-agent init-repo`

### Command Interface

```bash
spec-agent init-repo          # shallow scan, warns if KB already exists
spec-agent init-repo --deep   # breadth-first full scan
spec-agent init-repo --force  # skip warning, update existing KB
```

Run from inside the repo directory. Repo name is auto-detected via:
```bash
git rev-parse --show-toplevel | xargs basename
```

### How the Push Agent Benefits

The push agent (`agent.py`) is **unchanged**. It already calls `search_wiki` before writing any spec. Once KB docs exist in `projects/<service-name>/`, `search_wiki` finds them naturally via keyword grep. KB docs are designed to be keyword-rich (class names, method names, domain vocabulary) so grep matches are reliable.

This is the "passive context" approach — no token injection on every push, no changes to the push flow, full discoverability through the existing search mechanism.

### New Files

| File | Purpose |
|------|---------|
| `spec_agent/init_agent.py` | New agent module for init-repo (mirrors agent.py structure) |
| `spec_agent/tools/fs_read.py` | Two new tools: `list_directory`, `read_source_file` |
| `spec_agent/tools/init_cache.py` | Lightweight file-timestamp cache |

### New Tools (init agent only)

| Tool | Description | Guardrail |
|------|-------------|-----------|
| `list_directory(path, max_depth)` | Returns directory tree. Skips: `.git`, `node_modules`, `__pycache__`, `target/`, `build/`, `dist/`, `.venv`, `*.lock`, `*.min.js` | max depth: 3 |
| `read_source_file(path)` | Reads a source file relative to repo root | 8,000 char cap per file |
| `write_wiki_file` | Write KB docs to vault | reused from existing tools |
| `search_wiki` | Check if a component doc already exists | reused from existing tools |
| `update_index` | Log new docs in index.md | reused from existing tools |

### Agent Guardrails

- **Max iterations**: 30 (vs 20 for push agent — init does more exploration)
- **Max files read**: 15 (shallow) / 40 (deep)
- **Respects `.gitignore`**: parsed at startup, skip patterns added to `list_directory` exclusions
- **Binary/generated file skip**: `.class`, `.pyc`, `.jar`, `.min.js`, `*.lock` never read

### System Prompt — File Priority Order

The init agent system prompt instructs the LLM to explore in this order:
1. `README.md`, `CLAUDE.md`, `.cursorrules`, `pyproject.toml` / `pom.xml` / `package.json` / `build.gradle`
2. Entry points: `main.py`, `Application.java`, `app.py`, `index.ts`, `server.py`
3. Core source files the LLM deems architecturally significant (based on dir structure + step 1 context)
4. Tests only if `--deep`

The prompt also instructs the LLM to write KB docs that are **keyword-rich**: include all class names, method names, package names, and domain synonyms so `search_wiki` (keyword grep) can find them reliably.

### Vault Output Structure

```
projects/
  <service-name>/
    overview.md          ← anchor doc, links to all components via [[wikilink]]
    UserService.md
    PaymentProcessor.md
    AuthController.md
    ...
```

After writing all docs, the agent calls `update_index` once for the overview doc (type: `project`) to register the KB in `index.md`.

Each component doc uses a dedicated template:

```markdown
---
type: kb-component
project: <service-name>
date: <date>
---
# <ComponentName>

## Purpose

## Key responsibilities

## Dependencies / interactions
<!-- [[wikilink]] to related components -->

## Important methods / endpoints

## Keywords
<!-- all relevant class names, method names, synonyms for grep discoverability -->

## Related
```

### Re-run Detection & Update Behaviour

1. Check if `projects/<service-name>/` exists in vault
2. If exists and no `--force`: print warning and exit:
   ```
   ⚠ KB already exists for <service-name>. Run with --force to update.
   ```
3. With `--force`: Python diffs current file timestamps against the cache (see Caching), passes LLM a summary of changed files so it focuses its iterations on what actually changed. LLM calls `search_wiki` + `read_wiki_file` on existing docs before rewriting them.

### Caching

Cache file: `~/.spec-agent/cache/<repo-name>.json`

Format:
```json
{
  "last_run": "2026-04-10T12:00:00",
  "files": {
    "src/main/java/UserService.java": 1712750400.0,
    "src/main/java/PaymentProcessor.java": 1712750400.0
  }
}
```

- Written only after a successful `init-repo` run (aborted runs don't corrupt state)
- On `--force` re-run: files with changed `mtime` are listed in the LLM prompt as "changed since last init"
- Keeps re-runs cheap: LLM focuses on changed files rather than re-reading everything

---

## Requirement 2: `spec-agent opt-out` / `spec-agent opt-in`

### Command Interface

```bash
# From inside a git repo:
spec-agent opt-out     # exclude this repo from the global hook
spec-agent opt-in      # re-include this repo
```

### Implementation

Both commands:
1. Detect repo name: `git rev-parse --show-toplevel | xargs basename`
2. Load `~/.spec-agent/config.yaml`
3. Mutate `Config.ignored_repos` (add or remove)
4. Save config
5. Print confirmation

```
✓ my-service added to ignored repos — spec-agent will skip future pushes
✓ my-service removed from ignored repos — spec-agent is now active
```

Error if not inside a git repo:
```
✗ Not a git repository. Run this command from inside a repo.
```

### What Already Exists

No new config fields or logic needed in the push flow:
- `Config.ignored_repos: list[str]` — already in `config.py`
- `Config.is_repo_ignored(repo_name)` — already implemented
- `run` command already calls `cfg.is_repo_ignored(repo)` before processing

Only addition: the two CLI commands in `cli.py`.

---

## Future Work (GitHub Issue)

**Chunked Phase 2 optimization**: Instead of the tool-use loop reading files one at a time into a growing context, Phase 2 could process one component per LLM call — each call receives only the files relevant to that component. This caps per-call token cost and makes `--deep` more predictable. Tracked as a separate issue.

---

## Out of Scope

- Semantic/vector search (future upgrade path if keyword grep proves insufficient)
- Per-repo `.spec-agent-ignore` files (global config is sufficient; team-wide opt-out can be added later)
- `spec-agent list-ignored` command (can read the YAML directly for now)
- Auto-triggering `init-repo` on `spec-agent install-hook`
