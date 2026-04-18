# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Models LLM backend (`llm_backend: github`) — OpenAI-compatible endpoint via `GITHUB_TOKEN`, free tier (150 req/day), default model `gpt-4o-mini`

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
