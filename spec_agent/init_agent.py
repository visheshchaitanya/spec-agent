"""Init-repo agent: builds a knowledge base from an existing codebase."""
from __future__ import annotations
import json
import logging
from typing import Optional

from spec_agent.config import Config
from spec_agent.backends.factory import get_backend
from spec_agent.tools.fs_read import list_directory, read_source_file
from spec_agent.tools.wiki_read import read_wiki_file
from spec_agent.tools.wiki_write import write_wiki_file
from spec_agent.tools.wiki_search import search_wiki
from spec_agent.tools.wiki_index import update_index

try:
    from spec_agent.ast_extractor import extract_repo_structure as _extract_repo_structure
    _AST_AVAILABLE = True
except ImportError:
    _AST_AVAILABLE = False

logger = logging.getLogger(__name__)

_MAX_ITERATIONS_AST = 15      # when AST data is injected — LLM needs fewer iterations
_MAX_ITERATIONS_FALLBACK = 30  # when falling back to LLM-reads-files
_MAX_ITERATIONS = _MAX_ITERATIONS_FALLBACK  # backward-compat alias used by tests

INIT_TOOL_DEFINITIONS = [
    {
        "name": "list_directory",
        "description": (
            "List the directory tree of the repository. "
            "Skips .git, node_modules, __pycache__, build artifacts. "
            "Use this first to understand the repo structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path relative to repo root. Use '.' for root.",
                    "default": ".",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max directory depth to traverse.",
                    "default": 3,
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_source_file",
        "description": (
            "Read a source file from the repository. "
            "Content is capped at 8,000 characters. "
            "Do not read binary, lock, or generated files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root, e.g. src/main/java/UserService.java",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_wiki",
        "description": "Search the Obsidian vault for existing pages before writing a new one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (3-5 keywords)"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_wiki_file",
        "description": "Read an existing KB doc before updating it (only needed on --force re-run).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to vault root, e.g. projects/my-service/overview.md",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_wiki_file",
        "description": (
            "Write a KB doc to the vault under projects/<service-name>/. "
            "Use mode='create' for new docs. "
            "Use mode='update' only if read_wiki_file confirmed the file exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to vault root, e.g. projects/my-service/UserService.md",
                },
                "content": {"type": "string", "description": "Full markdown content"},
                "mode": {"type": "string", "enum": ["create", "update"], "default": "create"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "update_index",
        "description": "Register the overview doc in index.md after all component docs are written. Call once per init run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO date, e.g. 2026-04-10"},
                "type": {
                    "type": "string",
                    "enum": ["feature", "bug", "refactor", "arch", "chore", "concept", "project"],
                },
                "title": {"type": "string"},
                "project": {"type": "string"},
                "path": {"type": "string", "description": "Vault path without .md"},
            },
            "required": ["date", "type", "title", "project", "path"],
        },
    },
]

_SHALLOW_SYSTEM_PROMPT = """\
You are an architecture-documentation agent. Your job is to build a knowledge base (KB) \
for an existing codebase in an Obsidian vault.

**Step 1 — Understand the repo (shallow scan):**
- Call list_directory with relative_path="." to see the top-level structure.
- Read these files first, in order of priority, if they exist:
  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md
  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod
  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py
- Based on what you have read, identify the 3-6 most architecturally significant components.

**Step 2 — Write the KB:**
- First write `projects/<service-name>/overview.md` — an anchor doc describing the service's purpose,
  tech stack, architecture, and linking to all components with [[wikilink]] syntax.
- Then write `projects/<service-name>/<ComponentName>.md` for each important component.
- Finally call update_index once for the overview doc (type: "project").

**Component doc template:**
```
---
type: kb-component
project: <service-name>
date: <today's date>
---
# <ComponentName>

## Purpose

## Key responsibilities

## Dependencies / interactions
<!-- [[wikilink]] to related components -->

## Important methods / endpoints

## Keywords
<!-- ALL relevant class names, method names, function names, synonyms — one per line.
     This section is critical: the search tool is a keyword grep, so include every
     identifier and synonym that could appear in a future diff related to this component. -->

## Related
```

**Rules:**
- Stay grounded in what you actually read — do not invent features.
- The Keywords section MUST include every class name, method name, package name, and synonym.
- Use [[wikilink]] syntax when referencing other KB docs.
- Call search_wiki before writing any doc to check if it already exists.
"""

_DEEP_SYSTEM_PROMPT = """\
You are an architecture-documentation agent. Your job is to build a knowledge base (KB) \
for an existing codebase in an Obsidian vault.

**Step 1 — Deep-dive the repo (--deep mode):**
- Call list_directory with relative_path="." to see the top-level structure.
- Call list_directory on subdirectories that look important.
- Read these files first, in order of priority:
  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md
  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod
  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py
- Then read source files for all significant components (up to 40 files total).
- Include test files to understand expected behaviour.
- Based on what you have read, identify ALL architecturally significant components.

**Step 2 — Write the KB:**
- First write `projects/<service-name>/overview.md` — an anchor doc describing the service's purpose,
  tech stack, architecture, and linking to all components with [[wikilink]] syntax.
- Then write `projects/<service-name>/<ComponentName>.md` for each component.
- Finally call update_index once for the overview doc (type: "project").

**Component doc template:**
```
---
type: kb-component
project: <service-name>
date: <today's date>
---
# <ComponentName>

## Purpose

## Key responsibilities

## Dependencies / interactions
<!-- [[wikilink]] to related components -->

## Important methods / endpoints

## Keywords
<!-- ALL relevant class names, method names, function names, synonyms — one per line.
     This section is critical: the search tool is a keyword grep, so include every
     identifier and synonym that could appear in a future diff related to this component. -->

## Related
```

**Rules:**
- Stay grounded in what you actually read — do not invent features.
- The Keywords section MUST include every class name, method name, package name, and synonym.
- Use [[wikilink]] syntax when referencing other KB docs.
- Call search_wiki before writing any doc to check if it already exists.
"""

_SHALLOW_SYSTEM_PROMPT_AST = _SHALLOW_SYSTEM_PROMPT.replace(
    "**Step 1 — Understand the repo (shallow scan):**\n"
    "- Call list_directory with relative_path=\".\" to see the top-level structure.\n"
    "- Read these files first, in order of priority, if they exist:\n"
    "  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md\n"
    "  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod\n"
    "  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py\n"
    "- Based on what you have read, identify the 3-6 most architecturally significant components.",
    "**Step 1 — Use pre-extracted structure (AST mode):**\n"
    "- The user message contains a `<repo-structure>` block with pre-extracted AST data "
    "(classes, functions, imports) for all recognized source files.\n"
    "- Use it as your primary structural reference. You do NOT need to call "
    "`list_directory` or `read_source_file` for the main scan.\n"
    "- Call `list_directory` or `read_source_file` ONLY if you need specific "
    "implementation details not present in the structure block.\n"
    "- Based on the structure block, identify the 3-6 most architecturally significant components.",
)

assert "pre-extracted" in _SHALLOW_SYSTEM_PROMPT_AST, (
    "AST replacement failed for _SHALLOW_SYSTEM_PROMPT_AST — check that the Step 1 text matches exactly."
)

_DEEP_SYSTEM_PROMPT_AST = _DEEP_SYSTEM_PROMPT.replace(
    "**Step 1 — Deep-dive the repo (--deep mode):**\n"
    "- Call list_directory with relative_path=\".\" to see the top-level structure.\n"
    "- Call list_directory on subdirectories that look important.\n"
    "- Read these files first, in order of priority:\n"
    "  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md\n"
    "  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod\n"
    "  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py\n"
    "- Then read source files for all significant components (up to 40 files total).\n"
    "- Include test files to understand expected behaviour.\n"
    "- Based on what you have read, identify ALL architecturally significant components.",
    "**Step 1 — Use pre-extracted structure (AST mode, --deep):**\n"
    "- The user message contains a `<repo-structure>` block with pre-extracted AST data "
    "(classes, functions, imports) for all recognized source files.\n"
    "- Use it as your primary structural reference. You may still call `read_source_file` "
    "for implementation details of the most important components (up to 10 files).\n"
    "- Based on the structure block, identify ALL architecturally significant components.",
)

assert "pre-extracted" in _DEEP_SYSTEM_PROMPT_AST, (
    "AST replacement failed for _DEEP_SYSTEM_PROMPT_AST — check that the Step 1 text matches exactly."
)


def _dispatch_tool(
    name: str, tool_input: dict, repo_path: str, vault_path: str
) -> str:
    if name == "list_directory":
        return json.dumps(list_directory(
            repo_path,
            tool_input.get("relative_path", "."),
            tool_input.get("max_depth", 3),
        ))
    elif name == "read_source_file":
        return json.dumps(read_source_file(repo_path, tool_input["path"]))
    elif name == "search_wiki":
        results = search_wiki(vault_path, tool_input["query"], tool_input.get("limit", 5))
        return json.dumps(results)
    elif name == "read_wiki_file":
        return json.dumps(read_wiki_file(vault_path, tool_input["path"]))
    elif name == "write_wiki_file":
        return json.dumps(write_wiki_file(
            vault_path, tool_input["path"], tool_input["content"],
            mode=tool_input.get("mode", "create"),
        ))
    elif name == "update_index":
        return json.dumps(update_index(vault_path, tool_input))
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def run_init_agent(
    repo_path: str,
    repo_name: str,
    cfg: Config,
    deep: bool = False,
    changed_files: Optional[list[str]] = None,
) -> None:
    """Run the KB initialisation agent for a repository."""
    vault_path = str(cfg.vault_path)
    backend = get_backend(cfg)

    mode_note = "deep scan (--deep)" if deep else "shallow scan"
    changed_note = ""
    if changed_files:
        listed = "\n".join(f"- {f}" for f in changed_files[:20])
        suffix = f"\n... and {len(changed_files) - 20} more" if len(changed_files) > 20 else ""
        changed_note = f"\n\nFiles changed since last init:\n{listed}{suffix}"

    # Attempt AST pre-extraction
    has_ast = False
    ast_block = ""
    if _AST_AVAILABLE:
        try:
            ast_summary = _extract_repo_structure(
                repo_path,
                files=changed_files if changed_files else None,
            )
            if ast_summary.get("files"):
                has_ast = True
                compact_json = json.dumps(ast_summary, separators=(",", ":"))
                ast_block = (
                    f"\n\n<repo-structure>\n{compact_json}\n</repo-structure>\n\n"
                    "The repo-structure block above contains pre-extracted AST data (classes, "
                    "functions, imports) for all recognized source files. Use it as your primary "
                    "structural reference. You do NOT need to call list_directory or "
                    "read_source_file for the main scan — proceed directly to writing KB docs. "
                    "Those tools remain available if you need specific implementation details."
                )
        except Exception:
            logger.warning("spec-agent init: AST extraction failed, falling back to LLM-reads-files")

    user_message = (
        f"Build a knowledge base for this repository.\n\n"
        f"Repository name: {repo_name}\n"
        f"Repo root: {repo_path}\n"
        f"Mode: {mode_note}\n"
        f"Vault KB path: projects/{repo_name}/\n"
        f"{changed_note}"
        f"{ast_block}\n\n"
        "Follow the steps in your instructions to explore the repo and write the KB docs."
    )

    if has_ast:
        system_prompt = _DEEP_SYSTEM_PROMPT_AST if deep else _SHALLOW_SYSTEM_PROMPT_AST
        max_iterations = _MAX_ITERATIONS_AST
    else:
        system_prompt = _DEEP_SYSTEM_PROMPT if deep else _SHALLOW_SYSTEM_PROMPT
        max_iterations = _MAX_ITERATIONS_FALLBACK

    messages = [backend.make_user_message(user_message)]
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        response = backend.chat(
            system=system_prompt,
            messages=messages,
            tools=INIT_TOOL_DEFINITIONS,
            max_tokens=4096,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            results = [
                _dispatch_tool(tc.name, tc.arguments, repo_path, vault_path)
                for tc in response.tool_calls
            ]
            messages.append(response.raw_assistant_turn)
            messages.extend(backend.make_tool_results_messages(response.tool_calls, results))
        else:
            logger.warning(
                "spec-agent init: unexpected stop_reason=%r at iteration %d, aborting",
                response.stop_reason, iteration,
            )
            break

    if iteration >= max_iterations:
        logger.error(
            "spec-agent init: hit max iteration cap (%d) — possible runaway loop, aborting",
            max_iterations,
        )
