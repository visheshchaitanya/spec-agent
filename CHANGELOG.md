# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] — 2026-05-03

### Added
- SHA-based deduplication: `spec-agent run` now accepts `--sha` and skips processing if that commit SHA was already handled (cache at `~/.spec-agent/cache/processed_shas.txt`, capped at 500 entries)
- Chore pre-filter: pushes where all commit messages match `chore|docs|ci|test|style` are skipped before any LLM call
- `update_index` is now automatic: `write_wiki_file` (mode=create) parses frontmatter and updates `index.md` without a separate LLM tool call

### Changed
- Agent tool-use loop cap reduced from 20 → 6 iterations
- System prompt now instructs the agent to call `search_wiki` exactly once (was "as many queries as needed")
- `update_index` removed from agent `TOOL_DEFINITIONS` — LLM no longer needs to call it explicitly
- Hook script passes `--sha "$LOCAL_SHA"` to `spec-agent run`

## [0.5.1] — 2026-05-02

### Fixed
- Hook no longer exits silently when `~/.zshrc` contains `exec` or `exit` calls (common in zsh configs). Shell profiles are now sourced in a bash subprocess so exec/exit cannot kill the hook process; exported vars are imported back via `eval "$(bash -c '...; export -p')"`. Previously, sourcing `.zshrc` inline caused the entire pre-push hook to terminate before calling `spec-agent run`.

## [0.5.0] — 2026-05-02

### Added
- Groq LLM backend (`llm_backend: groq`) — free-tier cloud inference via `GROQ_API_KEY`, default model `llama-3.3-70b-versatile` (128k context); free tier: 1 000 req/day, 30 req/min, 12 000 TPM
- Interactive arrow-key `configure` menu via `questionary` (replaces text prompt)
- Groq is now the default backend (`llm_backend: groq`)

### Fixed
- Groq: inject format guard into system prompt to prevent Llama XML tool call format
- Groq: recover from `tool_use_failed` 400 errors via XML fallback parser (handles `<function=name{...}` with no separator)
- Groq: retry with backoff on 429 rate limit errors
- Groq: cap diff size per backend to avoid 413 token limit errors
- Agent: force tool use in system prompt to prevent text-only responses

## [0.4.2] — 2026-04-18

### Added
- AST pre-processing via tree-sitter: `spec_agent/ast_extractor.py` extracts classes, functions, and imports from Python, Go, JavaScript, TypeScript, TSX, Rust, and Java source files without LLM calls
- `init-repo` now injects a `<repo-structure>` block of pre-extracted AST data into the user message, reducing API calls from 15–30 down to 2–4 per run
- AST-aware system prompts for both shallow and deep init modes
- `init-repo` iteration cap is now dynamic: 15 when AST data is available, 30 when falling back to LLM-reads-files mode
- `git push` agent enriches the diff user message with changed symbols (classes and functions) extracted via regex from `@@` hunk headers

### Changed
- tree-sitter and all language grammar packages are now bundled in the base install (`pip install spec-agent`) — AST extraction is a first-class feature used by `init-repo`

### Fixed
- `tree-sitter-tsx` does not exist on PyPI — removed from dependencies; TSX grammar is bundled inside `tree-sitter-typescript`
- `.ts` and `.tsx` files would silently fail to parse: `tree_sitter_typescript` exposes `language_typescript()` / `language_tsx()`, not a generic `language()` — fixed `_get_parser()` to call the correct function

## [0.4.0] — 2026-04-18

### Added
- GitHub Models LLM backend (`llm_backend: github`) — OpenAI-compatible endpoint (`https://models.inference.ai.azure.com`) via `GITHUB_TOKEN`, free tier (150 req/day), default model `gpt-4o-mini`; no new dependencies (`requests` already required)

### Fixed
- `GeminiBackend` now raises a clear `ValueError` at construction time when a Gemma model is selected (Gemma does not support function calling, which spec-agent requires)
- Pre-push hook script: added `|| true` to the `git diff | head -c` pipe so the hook no longer exits with an error on empty diffs
- `spec-agent init` "Next steps" hint now shows both `configure` and `install-hook` steps in order
- `spec-agent configure` Gemini menu: removed Gemma from suggested models and added a check for missing `google-genai` package with install instructions

## [0.3.0] — 2026-04-10

### Added
- `spec-agent init-repo` — bootstraps a knowledge base (KB) from an existing codebase into the Obsidian vault, solving the cold-start problem for repos with existing history
  - Shallow mode (default): reads README, config files, and entry points; writes an `overview.md` + per-component docs under `projects/<repo-name>/`
  - `--deep` flag: breadth-first scan of up to 40 files for richer KB coverage
  - `--force` flag: update an existing KB; a file-timestamp cache (`~/.spec-agent/cache/<repo>.json`) surfaces only changed/new files to the LLM on re-runs
  - Hard cap of 30 iterations guards against runaway LLM loops
- `spec-agent opt-out` — exclude the current repo from the global pre-push hook (auto-detects repo name from git)
- `spec-agent opt-in` — re-include a previously excluded repo
- `spec_agent/tools/fs_read.py` — `list_directory` + `read_source_file` tools for the init agent; includes gitignore-aware filtering and a 8,000-character file cap
- `spec_agent/tools/init_cache.py` — file-timestamp cache for efficient `--force` re-runs
- `spec_agent/init_agent.py` — tool-use agent loop for KB generation (mirrors `agent.py`); supports shallow and deep system prompts

### Fixed
- `spec_agent/tools/fs_read.py`: added path traversal protection to `list_directory` and `read_source_file` — resolves paths and rejects any `relative_path` that escapes the repo root, matching the guard already present in `wiki_read.py` and `wiki_write.py`

## [0.2.0] — 2026-04-08

### Added
- Pluggable LLM backends: `anthropic` (default), `ollama` (local/free), `gemini` (free tier)
- `spec-agent configure` — interactive setup wizard; no YAML editing required
- `spec-agent uninstall-hook` — remove the global pre-push hook
- `spec-agent opt-out` / `spec-agent opt-in` stubs in config (ignored_repos field)
- `spec_agent/backends/` package: `AnthropicBackend`, `OllamaBackend`, `GeminiBackend`, common `ChatResponse` normalisation, `get_backend()` factory

### Changed
- `spec_agent/agent.py`: removed the `classify_commit` no-op tool — commit type is now determined entirely from the message prefix inside the system prompt, saving one API round-trip per invocation
- `spec_agent/agent.py`: system prompt now embeds explicit markdown templates for all four spec types (`feature`, `bug`, `refactor`, `arch`) to produce consistent, well-structured output
- `spec_agent/agent.py`: `write_wiki_file` tool description clarified to distinguish `create` vs `update` mode; `update_index` type enum extended with `"concept"` and `"project"` to match vault folder structure
- `spec_agent/agent.py`: user message now prepends commit-type classification instruction so the model has the signal at the top of context
- `spec_agent/agent.py`: `_call_api_with_retry()` — exponential-backoff retry (up to 3 attempts, 2 s base delay) for transient API errors; hard cap of 20 tool-use loop iterations

## [0.1.0] — 2026-04-07

Initial release.

### Added
- `spec_agent/config.py` — `Config` dataclass with YAML load/save at `~/.spec-agent/config.yaml`; repo and branch ignore patterns (fnmatch glob); `min_commit_chars` threshold
- `spec_agent/tools/wiki_read.py` — reads vault `.md` files and parses YAML frontmatter
- `spec_agent/tools/wiki_write.py` — creates or appends to vault `.md` files; auto-manages `## Changelog` sections
- `spec_agent/tools/wiki_search.py` — full-text grep search across the vault
- `spec_agent/tools/wiki_index.py` — appends rows to `index.md` master log
- `spec_agent/agent.py` — Anthropic tool-use agent loop: `classify_commit`, `search_wiki`, `read_wiki_file`, `write_wiki_file`, `update_index`
- `spec_agent/cli.py` — Click CLI with `init`, `install-hook`, `run`, and `config-get` commands
- Global `post-push` git hook installed to `~/.git-hooks/post-push`; passes diff via temp file to handle special characters safely
- README, LICENSE (MIT), CI/CD workflows, and full PyPI packaging metadata

[Unreleased]: https://github.com/visheshchaitanya/spec-agent/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/visheshchaitanya/spec-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/visheshchaitanya/spec-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/visheshchaitanya/spec-agent/releases/tag/v0.1.0
