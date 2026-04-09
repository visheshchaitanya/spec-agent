# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `spec_agent/agent.py`: removed the `classify_commit` no-op tool — commit type is now determined entirely from the message prefix inside the system prompt, saving one API round-trip per invocation
- `spec_agent/agent.py`: system prompt now embeds explicit markdown templates for all four spec types (`feature`, `bug`, `refactor`, `arch`) to produce consistent, well-structured output
- `spec_agent/agent.py`: `write_wiki_file` tool description clarified to distinguish `create` vs `update` mode; `update_index` type enum extended with `"concept"` and `"project"` to match vault folder structure
- `spec_agent/agent.py`: user message now prepends commit-type classification instruction so the model has the signal at the top of context

### Added
- `spec_agent/agent.py`: `_call_api_with_retry()` — exponential-backoff retry (up to 3 attempts, 2 s base delay) for transient Anthropic API errors: rate-limits (429), server errors (500/502/503/529), connection errors, and timeouts
- `spec_agent/agent.py`: hard cap of 20 tool-use loop iterations to prevent runaway agent loops
- `spec_agent/agent.py`: graceful exit on unexpected `stop_reason` values (e.g. `"max_tokens"`) with a warning log

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

[Unreleased]: https://github.com/visheshchaitanya/spec-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/visheshchaitanya/spec-agent/releases/tag/v0.1.0
