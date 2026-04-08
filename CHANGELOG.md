# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
