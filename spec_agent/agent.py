from __future__ import annotations
import json
import logging
import os
import time
import anthropic
from typing import Optional
from spec_agent.config import Config
from spec_agent.tools.wiki_read import read_wiki_file
from spec_agent.tools.wiki_write import write_wiki_file
from spec_agent.tools.wiki_search import search_wiki
from spec_agent.tools.wiki_index import update_index

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "search_wiki",
        "description": "Full-text search across the Obsidian vault to find related existing pages before writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (3–5 keywords)"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_wiki_file",
        "description": "Read an existing wiki file to understand its content before updating it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to vault root, e.g. features/auth.md"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_wiki_file",
        "description": (
            "Write a markdown file to the vault. "
            "Use mode='create' for new specs (path does not yet exist). "
            "Use mode='update' only if read_wiki_file confirmed the file exists — "
            "it appends a changelog entry without overwriting the full spec."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to vault root, e.g. features/auth.md"},
                "content": {"type": "string", "description": "Full markdown content (create) or changelog line(s) (update)"},
                "mode": {"type": "string", "enum": ["create", "update"], "default": "create"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "update_index",
        "description": "Append an entry to index.md — the master log. Call this after writing the spec file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO date, e.g. 2026-04-07"},
                "type": {"type": "string", "enum": ["feature", "bug", "refactor", "arch", "chore", "concept", "project"]},
                "title": {"type": "string"},
                "project": {"type": "string"},
                "path": {"type": "string", "description": "Vault path without .md, e.g. features/auth"},
            },
            "required": ["date", "type", "title", "project", "path"],
        },
    },
]

_SYSTEM_PROMPT = """You are a spec-writing agent that documents git changes in an Obsidian vault.
Given a git diff and commit messages, follow these steps precisely:

1. Determine the commit type from the message prefix:
   - feat / feature  →  feature
   - fix             →  bug
   - refactor        →  refactor
   - arch / adr      →  arch
   - chore / docs / ci / test / style  →  STOP immediately, no spec needed.
   - Unknown prefix  →  infer from the diff content.

2. Search the wiki for related pages. Run as many queries as needed to find
   relevant existing pages and concepts to link to.

3. Read at most 1 existing page if you intend to update it (skip if creating new).

4. Write or update the spec using the exact template for the type below.
   For mode='update', only append a changelog line — do not rewrite the full spec.
   For mode='create', use the full template.

**feature template:**
```markdown
---
type: feature
project: {{project}}
date: {{date}}
---
# {{title}}

## Summary

## Problem it solves

## Implementation

## Files touched

## Related
<!-- use [[wikilink]] syntax for pages found via search_wiki -->

## Open questions

## Changelog
- {{date}}: initial spec
```

**bug template:**
```markdown
---
type: bug
project: {{project}}
date: {{date}}
---
# {{title}}

## Root cause

## Fix applied

## Related

## Changelog
- {{date}}: initial spec
```

**refactor template:**
```markdown
---
type: refactor
project: {{project}}
date: {{date}}
---
# {{title}}

## What changed

## Why

## Before/After

## Related

## Changelog
- {{date}}: initial spec
```

**arch template:**
```markdown
---
type: arch
project: {{project}}
date: {{date}}
---
# {{title}}

## Context

## Decision

## Consequences

## Alternatives considered

## Related

## Changelog
- {{date}}: initial spec
```

5. Call update_index after writing the spec. Use the vault path without the .md extension.

Rules:
- Use [[wikilink]] syntax for pages found via search_wiki.
- Stay grounded in the diff — do not invent features not present in the code.
- Be thorough: specs should be detailed enough to be useful for future developers.
"""

# Retryable HTTP status codes and exception types
_RETRYABLE_STATUS = {429, 500, 502, 503, 529}
_MAX_RETRIES = 3
_MAX_ITERATIONS = 20  # hard cap on tool-use loop iterations to prevent runaway loops
_RETRY_BASE_DELAY = 2.0  # seconds


def _dispatch_tool(name: str, tool_input: dict, vault_path: str) -> str:
    if name == "search_wiki":
        results = search_wiki(vault_path, tool_input["query"], tool_input.get("limit", 5))
        return json.dumps(results)
    elif name == "read_wiki_file":
        return json.dumps(read_wiki_file(vault_path, tool_input["path"]))
    elif name == "write_wiki_file":
        return json.dumps(write_wiki_file(
            vault_path, tool_input["path"], tool_input["content"],
            mode=tool_input.get("mode", "create")
        ))
    elif name == "update_index":
        return json.dumps(update_index(vault_path, tool_input))
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def _call_api_with_retry(client: anthropic.Anthropic, **kwargs) -> anthropic.types.Message:
    """Call the Anthropic API with exponential-backoff retry on transient errors."""
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("spec-agent: rate limited (attempt %d/%d), retrying in %.1fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code in _RETRYABLE_STATUS:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "spec-agent: API error %d (attempt %d/%d), retrying in %.1fs",
                    exc.status_code, attempt + 1, _MAX_RETRIES, delay,
                )
                time.sleep(delay)
            else:
                # Non-retryable (e.g. 400 Bad Request, 401 Unauthorized)
                logger.error("spec-agent: non-retryable API error %d: %s", exc.status_code, exc.message)
                raise
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("spec-agent: connection/timeout error (attempt %d/%d), retrying in %.1fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)

    raise RuntimeError(f"spec-agent: API call failed after {_MAX_RETRIES} retries — aborting.")


def run_agent(
    diff: str,
    commit_messages: list[str],
    repo_name: str,
    branch: str,
    cfg: Config,
    _force_type: Optional[str] = None,  # test hook
) -> None:
    """Run the tool-using agent loop."""
    # Test hook: skip API calls for known chore commits
    if _force_type == "chore":
        return

    vault_path = str(cfg.vault_path)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    user_message = (
        "Classify this push as one of: feature | bug | refactor | arch | chore.\n"
        "Use the commit message prefix as the primary signal "
        "(feat→feature, fix→bug, refactor→refactor, chore→stop).\n\n"
        f"Repository: {repo_name}\n"
        f"Branch: {branch}\n"
        "Commit messages:\n" + "\n".join(f"- {m}" for m in commit_messages) +
        f"\n\nGit diff (truncated to 50,000 chars):\n```\n{diff[:50_000]}\n```"
    )

    messages = [{"role": "user", "content": user_message}]
    iteration = 0

    while iteration < _MAX_ITERATIONS:
        iteration += 1

        try:
            response = _call_api_with_retry(
                client,
                model=cfg.model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except RuntimeError as exc:
            # All retries exhausted — log and exit cleanly
            logger.error("%s", exc)
            return
        except anthropic.APIError as exc:
            # Non-retryable error surfaced from _call_api_with_retry
            logger.error("spec-agent: unrecoverable API error, aborting: %s", exc)
            return

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _dispatch_tool(block.name, block.input, vault_path)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop reason (e.g. "max_tokens") — exit cleanly
            logger.warning("spec-agent: unexpected stop_reason=%r at iteration %d, aborting", response.stop_reason, iteration)
            break

    if iteration >= _MAX_ITERATIONS:
        logger.error("spec-agent: hit max iteration cap (%d) — possible runaway loop, aborting", _MAX_ITERATIONS)
