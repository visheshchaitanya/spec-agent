from __future__ import annotations
import json
import logging
import re
from spec_agent.config import Config
from spec_agent.backends.factory import get_backend
from spec_agent.tools.wiki_read import read_wiki_file
from spec_agent.tools.wiki_write import write_wiki_file
from spec_agent.tools.wiki_search import search_wiki
from spec_agent.tools.wiki_index import update_index

try:
    from spec_agent.ast_extractor import extract_diff_symbols as _extract_diff_symbols
    _DIFF_AST_AVAILABLE = True
except ImportError:
    _DIFF_AST_AVAILABLE = False

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

2. Call search_wiki exactly once to find related pages to link to.

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

Rules:
- Use [[wikilink]] syntax for pages found via search_wiki.
- Stay grounded in the diff — do not invent features not present in the code.
- Be concise but complete: fill every section with real content from the diff.
- Do not describe what you will do — call tools immediately.
- Your very first response MUST be a tool call to search_wiki, not a text classification.
- Optimal flow: search_wiki ONCE → write_wiki_file for each spec → stop. Maximum 2 searches total.
- After all write_wiki_file calls succeed, respond with plain text "Done." to end the session. No further tool calls.
"""

_MAX_ITERATIONS = 6  # hard cap on tool-use loop iterations to prevent runaway loops

_FM_KEY_RE = re.compile(r'^(\w+):\s*(.+)', re.MULTILINE)
_H1_RE = re.compile(r'^# (.+)', re.MULTILINE)


def _auto_update_index(vault_path: str, content: str, path: str) -> None:
    """Parse frontmatter from a newly-created spec and append a row to index.md."""
    fm_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return
    fm = {m.group(1): m.group(2).strip() for m in _FM_KEY_RE.finditer(fm_match.group(1))}
    h1 = _H1_RE.search(content)
    entry = {
        "date": fm.get("date", ""),
        "type": fm.get("type", ""),
        "title": h1.group(1).strip() if h1 else path.split("/")[-1],
        "project": fm.get("project", ""),
        "path": path.removesuffix(".md"),
    }
    if entry["date"] and entry["type"]:
        update_index(vault_path, entry)


def _dispatch_tool(name: str, tool_input: dict, vault_path: str) -> str:
    if name == "search_wiki":
        results = search_wiki(vault_path, tool_input["query"], tool_input.get("limit", 5))
        return json.dumps(results)
    elif name == "read_wiki_file":
        return json.dumps(read_wiki_file(vault_path, tool_input["path"]), default=str)
    elif name == "write_wiki_file":
        mode = tool_input.get("mode", "create")
        result = write_wiki_file(vault_path, tool_input["path"], tool_input["content"], mode=mode)
        if result["success"] and mode == "create":
            _auto_update_index(vault_path, tool_input["content"], tool_input["path"])
        return json.dumps(result)
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def run_agent(
    diff: str,
    commit_messages: list[str],
    repo_name: str,
    branch: str,
    cfg: Config,
    _force_type: str | None = None,  # test hook
) -> None:
    """Run the tool-using agent loop using the configured LLM backend."""
    # Test hook: skip API calls for known chore commits
    if _force_type == "chore":
        return

    vault_path = str(cfg.vault_path)
    backend = get_backend(cfg)

    # Extract changed symbols from diff for additional context
    symbols_note = ""
    _DIFF_SYMBOL_CAP = 500_000  # 500 KB — generous for symbol extraction
    if _DIFF_AST_AVAILABLE:
        try:
            changed_symbols = _extract_diff_symbols(diff[:_DIFF_SYMBOL_CAP])
            if changed_symbols:
                symbols_note = "\n\nChanged symbols (AST-extracted):\n" + json.dumps(
                    changed_symbols, indent=2
                )
        except Exception:
            logger.warning(
                "spec-agent: AST diff symbol extraction failed, skipping enrichment",
                exc_info=True,
            )

    diff_cap = backend.max_diff_chars
    today = __import__("datetime").date.today().isoformat()
    user_message = (
        "Classify this push as one of: feature | bug | refactor | arch | chore.\n"
        "Use the commit message prefix as the primary signal "
        "(feat→feature, fix→bug, refactor→refactor, chore→stop).\n\n"
        f"Today's date: {today}\n"
        f"Repository: {repo_name}\n"
        f"Branch: {branch}\n"
        "Commit messages:\n" + "\n".join(f"- {m}" for m in commit_messages) +
        f"{symbols_note}"
        f"\n\nGit diff (truncated to {diff_cap:,} chars):\n```\n{diff[:diff_cap]}\n```"
    )

    messages = [backend.make_user_message(user_message)]
    iteration = 0

    while iteration < _MAX_ITERATIONS:
        iteration += 1
        response = backend.chat(
            system=_SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            max_tokens=4096,
        )

        if response.stop_reason == "end_turn":
            logger.debug("agent end_turn at iteration %d, response text: %r", iteration, response.text)
            break

        if response.stop_reason == "tool_use":
            results = [
                _dispatch_tool(tc.name, tc.arguments, vault_path)
                for tc in response.tool_calls
            ]
            messages.append(response.raw_assistant_turn)
            messages.extend(backend.make_tool_results_messages(response.tool_calls, results))
        else:
            # Unexpected stop reason (e.g. "max_tokens") — exit cleanly
            logger.warning("spec-agent: unexpected stop_reason=%r at iteration %d, aborting", response.stop_reason, iteration)
            break

    if iteration >= _MAX_ITERATIONS:
        logger.error("spec-agent: hit max iteration cap (%d) — possible runaway loop, aborting", _MAX_ITERATIONS)
