# Configuration Reference

Config file location: `~/.spec-agent/config.yaml`

Created automatically by `spec-agent init`. Edit it manually to customize behavior.

---

## Fields

### `vault_path`

**Type:** string (path)  
**Default:** `~/Documents/dev-wiki`

Absolute path to the Obsidian vault directory. Tilde (`~`) is expanded. Must exist before running — created by `spec-agent init`.

```yaml
vault_path: ~/Documents/dev-wiki
```

---

### `model`

**Type:** string  
**Default:** `claude-sonnet-4-6`

Anthropic model used for spec generation. Any model that supports tool use works.

```yaml
model: claude-sonnet-4-6     # default — best quality/cost tradeoff
model: claude-haiku-4-5-20251001  # faster and cheaper, lower quality
model: claude-opus-4-6       # highest quality, slowest and most expensive
```

---

### `ignored_repos`

**Type:** list of strings  
**Default:** `[]`

Exact repository names to skip entirely. Matched against the basename of the repo (e.g. `my-app`, not a full path or URL).

```yaml
ignored_repos:
  - dotfiles
  - scratch
  - private-journal
```

To find your repo's name as seen by the hook: `basename $(git rev-parse --show-toplevel)`.

---

### `ignored_branches`

**Type:** list of strings (fnmatch glob patterns)  
**Default:** `["dependabot/*", "renovate/*"]`

Branch name patterns to skip. Uses Python's `fnmatch` — `*` matches any sequence of characters, `?` matches a single character. Useful for bot branches and short-lived scratch branches.

```yaml
ignored_branches:
  - dependabot/*
  - renovate/*
  - wip/*          # skip all branches starting with wip/
  - temp-*         # skip all branches starting with temp-
```

To skip only a specific branch, use its exact name without a wildcard.

---

### `min_commit_chars`

**Type:** integer  
**Default:** `50`

Minimum total character length of all commit messages combined for a push to be processed. Pushes where the combined commit messages are shorter than this are silently skipped.

This filters out noise commits like `"fix"`, `"wip"`, `"typo"` that would produce low-quality specs.

```yaml
min_commit_chars: 50    # default — skips very short messages
min_commit_chars: 0     # process every push regardless of message length
min_commit_chars: 100   # stricter — requires more descriptive messages
```

---

## Example: Full Config

```yaml
vault_path: ~/Documents/dev-wiki
model: claude-sonnet-4-6
ignored_repos:
  - dotfiles
  - scratch
ignored_branches:
  - dependabot/*
  - renovate/*
  - wip/*
min_commit_chars: 50
```

---

## Reading Config Values

The hook script reads config values at runtime via `spec-agent config-get <key>`:

```bash
spec-agent config-get min_commit_chars   # prints: 50
spec-agent config-get vault_path         # prints: /Users/you/Documents/dev-wiki
```

This is used internally by the `post-push` hook — you typically won't need to call it directly.

---

## Resetting to Defaults

Delete the config file and re-run `init`:

```bash
rm ~/.spec-agent/config.yaml
spec-agent init --vault ~/Documents/dev-wiki
```
