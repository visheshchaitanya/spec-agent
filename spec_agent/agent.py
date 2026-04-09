from __future__ import annotations
import json
from typing import Optional
from spec_agent.config import Config
from spec_agent.backends.factory import get_backend
from spec_agent.tools.wiki_read import read_wiki_file
from spec_agent.tools.wiki_write import write_wiki_file
from spec_agent.tools.wiki_search import search_wiki
from spec_agent.tools.wiki_index import update_index

TOOL_DEFINITIONS = [
    {
        "name": "classify_commit",
        "description": (
            "Classify the git commit(s) to determine what type of change was made "
            "and extract key concepts for wiki linking. Call this first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "The git diff content"},
                "messages": {"type": "array", "items": {"type": "string"}, "description": "Commit messages"},
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["diff", "messages", "repo"],
        },
    },
    {
        "name": "search_wiki",
        "description": "Full-text search across the Obsidian vault to find related existing pages before writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
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
            "Write a markdown file to the vault. Use mode='create' for new specs, "
            "mode='update' to append a changelog entry to an existing spec."
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
                "type": {"type": "string", "enum": ["feature", "bug", "refactor", "arch", "chore"]},
                "title": {"type": "string"},
                "project": {"type": "string"},
                "path": {"type": "string", "description": "Vault path without .md, e.g. features/auth"},
            },
            "required": ["date", "type", "title", "project", "path"],
        },
    },
]

_SYSTEM_PROMPT = """You are a spec-writing agent. When given a git diff and commit messages, you:
1. Call classify_commit to understand what changed.
2. If type is "chore", stop — no spec needed.
3. Search the wiki for related pages to understand existing context and find pages to link to.
4. Read any highly relevant existing pages (especially if you might be updating them).
5. Write or update the appropriate spec file using the right template:
   - feature: Summary, Problem it solves, Implementation details, Files touched, Related [[wikilinks]], Open questions, Changelog
   - bug: Root cause, Fix applied, Related [[wikilinks]], Changelog
   - refactor: What changed, Why, Before/After key diff, Related [[wikilinks]]
   - arch: Context, Decision, Consequences, Alternatives considered, Related [[wikilinks]]
6. Call update_index with the new entry.

Use [[wikilink]] syntax for related pages you found via search_wiki. Keep specs factual and grounded in the diff.
"""


def _dispatch_tool(name: str, tool_input: dict, vault_path: str) -> str:
    if name == "classify_commit":
        # The agent classifies via its own reasoning — this tool is a no-op
        return json.dumps({"status": "classified", "note": "Use your reasoning to determine type and concepts"})
    elif name == "search_wiki":
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


def run_agent(
    diff: str,
    commit_messages: list[str],
    repo_name: str,
    branch: str,
    cfg: Config,
    _force_type: Optional[str] = None,  # test hook
) -> None:
    """Run the tool-using agent loop using the configured LLM backend."""
    # Test hook: skip API calls for known chore commits
    if _force_type == "chore":
        return

    vault_path = str(cfg.vault_path)
    backend = get_backend(cfg)

    user_content = (
        f"Repository: {repo_name}\n"
        f"Branch: {branch}\n"
        f"Commit messages:\n" + "\n".join(f"- {m}" for m in commit_messages) +
        f"\n\nGit diff (truncated to 50,000 chars):\n```\n{diff[:50_000]}\n```"
    )

    messages = [backend.make_user_message(user_content)]

    while True:
        response = backend.chat(
            system=_SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            max_tokens=4096,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            results = [
                _dispatch_tool(tc.name, tc.arguments, vault_path)
                for tc in response.tool_calls
            ]
            messages.append(response.raw_assistant_turn)
            messages.extend(backend.make_tool_results_messages(response.tool_calls, results))
        else:
            break
