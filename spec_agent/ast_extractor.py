from __future__ import annotations
import importlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LANG_MAP: dict[str, str] = {
    ".py":   "tree_sitter_python",
    ".go":   "tree_sitter_go",
    ".js":   "tree_sitter_javascript",
    ".jsx":  "tree_sitter_javascript",
    ".ts":   "tree_sitter_typescript",
    ".tsx":  "tree_sitter_tsx",        # Note: tsx has its own grammar, NOT typescript
    ".rs":   "tree_sitter_rust",
    ".java": "tree_sitter_java",
}

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target"}
_MAX_FILE_BYTES = 100_000   # 100 KB cap per file
_MAX_TOTAL_FILES = 200      # cap on number of files included in output JSON
_MAX_OUTPUT_CHARS = 60_000  # cap on total serialized JSON chars (~15k tokens)


@lru_cache(maxsize=None)
def _get_parser(ext: str) -> Any:
    """Return a tree_sitter.Parser for the given extension. Cached."""
    import tree_sitter
    module_name = LANG_MAP[ext]
    lang_module = importlib.import_module(module_name)
    language = tree_sitter.Language(lang_module.language())
    parser = tree_sitter.Parser(language)
    return parser


def _get_node_name(node: Any) -> str | None:
    """Extract the name from a node's 'name' field child or first identifier child."""
    # Try named field first
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode("utf-8", errors="replace")
    # Fall back to first identifier child
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8", errors="replace")
    return None


def _extract_class_methods(class_node: Any, lang: str) -> list[str]:
    """Walk a class body and return method names."""
    method_types: set[str]
    if lang == "python":
        method_types = {"function_definition"}
    elif lang in ("javascript", "typescript", "tsx"):
        method_types = {"method_definition", "function_declaration"}
    elif lang == "java":
        method_types = {"method_declaration"}
    elif lang == "rust":
        method_types = {"function_item"}
    else:
        method_types = set()

    methods: list[str] = []

    def _walk(node: Any) -> None:
        for child in node.children:
            if child.type in method_types:
                name = _get_node_name(child)
                if name:
                    methods.append(name)
            else:
                _walk(child)

    _walk(class_node)
    return methods


def _extract_file(abs_path: Path, ext: str, repo_root: Path) -> dict:
    """
    Parse a source file with tree-sitter and return extracted symbols.

    Returns:
        {
            "path": str,       # relative to repo root
            "language": str,
            "classes": [{"name": str, "line": int, "methods": list[str]}],
            "functions": [{"name": str, "line": int}],
            "imports": [str],
        }
    """
    raw = abs_path.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError(f"File too large: {len(raw)} bytes")

    parser = _get_parser(ext)
    tree = parser.parse(raw)
    root = tree.root_node

    module_name = LANG_MAP[ext]
    # e.g. "tree_sitter_python" -> "python", "tree_sitter_tsx" -> "tsx"
    language = module_name.replace("tree_sitter_", "")

    classes: list[dict] = []
    functions: list[dict] = []
    imports: list[str] = []

    # Node types per language
    if language == "python":
        class_types = {"class_definition"}
        func_types = {"function_definition"}
        import_types = {"import_statement", "import_from_statement"}
    elif language == "go":
        class_types = {"type_declaration"}
        func_types = {"function_declaration", "method_declaration"}
        import_types = {"import_declaration"}
    elif language in ("javascript", "typescript"):
        class_types = {"class_declaration"}
        func_types = {"function_declaration"}
        import_types = {"import_statement"}
    elif language == "tsx":
        class_types = {"class_declaration"}
        func_types = {"function_declaration"}
        import_types = {"import_statement"}
    elif language == "rust":
        class_types = {"struct_item", "impl_item"}
        func_types = {"function_item"}
        import_types = {"use_declaration"}
    elif language == "java":
        class_types = {"class_declaration"}
        func_types = {"method_declaration"}
        import_types = {"import_declaration"}
    else:
        class_types = set()
        func_types = set()
        import_types = set()

    def _walk(node: Any) -> None:
        for child in node.children:
            if child.type in class_types:
                name = _get_node_name(child)
                line = child.start_point[0] + 1
                methods = _extract_class_methods(child, language)
                classes.append({"name": name or "<anonymous>", "line": line, "methods": methods})
            elif child.type in func_types:
                name = _get_node_name(child)
                line = child.start_point[0] + 1
                functions.append({"name": name or "<anonymous>", "line": line})
            elif child.type in import_types:
                imports.append(child.text.decode("utf-8", errors="replace").strip())
            # Recurse into children for nested definitions
            _walk(child)

    _walk(root)

    return {
        "path": str(abs_path.relative_to(repo_root)),
        "language": language,
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }


def _walk_repo(repo_path: str) -> list[str]:
    """Return absolute path strings for all non-skipped source files in the repo."""
    root = Path(repo_path)
    results: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Skip symlinks that resolve outside the repo root
        if p.is_symlink():
            try:
                p.resolve().relative_to(root.resolve())
            except ValueError:
                continue
        # Skip hidden segments and skip dirs
        parts = p.relative_to(root).parts
        skip = False
        for part in parts:
            if part in _SKIP_DIRS or part.startswith("."):
                skip = True
                break
        if skip:
            continue
        results.append(str(p))
    return results


def extract_repo_structure(
    repo_path: str,
    files: list[str] | None = None,
) -> dict:
    """
    Extract structural symbols from a repository using tree-sitter.

    Args:
        repo_path: Absolute path to the repository root.
        files: Optional list of specific file paths to process. Each may be
               absolute or relative to repo_path. If None, the full repo is walked.

    Returns:
        {
            "files": [<extracted file dicts>],
            "skipped": [<relative path strings>],
            "truncated": bool,   # present only when truncated
            "error": str,        # present only on fatal error
        }
    """
    # Graceful degradation when tree-sitter is not installed
    try:
        importlib.import_module("tree_sitter")
    except ImportError:
        return {"files": [], "skipped": [], "error": "tree-sitter not installed"}

    repo_root = Path(repo_path)

    extracted: list[dict] = []
    skipped: list[str] = []

    if files is not None:
        abs_files: list[str] = []
        for f in files:
            p = Path(f)
            if not p.is_absolute():
                p = repo_root / p
            # Reject paths that escape the repo root
            try:
                p.resolve().relative_to(repo_root.resolve())
            except ValueError:
                logger.warning("ast_extractor: skipping out-of-root path: %s", f)
                skipped.append(str(f))
                continue
            abs_files.append(str(p))
    else:
        abs_files = _walk_repo(repo_path)

    for abs_path_str in abs_files:
        if len(extracted) >= _MAX_TOTAL_FILES:
            abs_path = Path(abs_path_str)
            try:
                skipped.append(str(abs_path.relative_to(repo_root)))
            except ValueError:
                skipped.append(abs_path_str)
            continue

        abs_path = Path(abs_path_str)
        ext = abs_path.suffix.lower()

        if ext not in LANG_MAP:
            try:
                rel = str(abs_path.relative_to(repo_root))
            except ValueError:
                rel = abs_path_str
            skipped.append(rel)
            continue

        try:
            info = _extract_file(abs_path, ext, repo_root)
            extracted.append(info)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ast_extractor: skipping %s — %s", abs_path_str, exc)
            try:
                rel = str(abs_path.relative_to(repo_root))
            except ValueError:
                rel = abs_path_str
            skipped.append(rel)

    result: dict = {"files": extracted, "skipped": skipped}

    # Enforce output size cap
    serialized = json.dumps(result)
    if len(serialized) > _MAX_OUTPUT_CHARS:
        while result["files"] and len(json.dumps(result)) > _MAX_OUTPUT_CHARS:
            result["files"].pop()
        result["truncated"] = True

    return result


# ---------------------------------------------------------------------------
# Diff symbol extraction (regex-based — no tree-sitter)
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE = re.compile(r"^@@ .+?@@ (.+)$", re.MULTILINE)

# Patterns to detect symbol names in hunk context lines and changed lines
_SYMBOL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bclass\s+([A-Za-z_]\w*)"), "class"),
    (re.compile(r"\bdef\s+([A-Za-z_]\w*)"), "function"),
    (re.compile(r"\bfn\s+([A-Za-z_]\w*)"), "function"),
    (re.compile(r"\bfunc\s+([A-Za-z_]\w*)"), "function"),
    (re.compile(r"\bpublic\s+(?:static\s+)?(?:\w+\s+)+([A-Za-z_]\w*)\s*\("), "function"),
    (re.compile(r"\bprivate\s+(?:static\s+)?(?:\w+\s+)+([A-Za-z_]\w*)\s*\("), "function"),
    (re.compile(r"\bprotected\s+(?:static\s+)?(?:\w+\s+)+([A-Za-z_]\w*)\s*\("), "function"),
]

_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)*$")


def _categorize_name(name: str, hint: str) -> str:
    """Return 'class' or 'function' for a symbol name."""
    if hint == "class":
        return "class"
    if _PASCAL_CASE_RE.match(name):
        return "class"
    return "function"


def _parse_symbols_from_text(text: str) -> tuple[list[str], list[str]]:
    """Extract class and function names from a fragment of source text."""
    classes: list[str] = []
    functions: list[str] = []
    for pattern, kind in _SYMBOL_PATTERNS:
        for m in pattern.finditer(text):
            name = m.group(1)
            category = _categorize_name(name, kind)
            if category == "class":
                classes.append(name)
            else:
                functions.append(name)
    return classes, functions


def extract_diff_symbols(diff: str) -> dict[str, dict]:
    """
    Parse a unified diff and return modified classes/functions per file.

    Uses regex on @@ hunk headers and changed lines — does NOT invoke tree-sitter,
    because hunk content is fragmented and cannot be parsed as a full AST.

    Returns:
        {
            "path/to/file.py": {
                "modified_classes": [...],
                "modified_functions": [...],
            },
            ...
        }
    """
    if not diff:
        return {}

    result: dict[str, dict] = {}

    # Split diff into per-file sections by scanning for "+++ b/" lines
    # We accumulate lines per file section
    current_file: str | None = None
    current_lines: list[str] = []
    file_sections: list[tuple[str, list[str]]] = []

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            if current_file is not None:
                file_sections.append((current_file, current_lines))
            current_file = line[6:]  # strip "+++ b/"
            current_lines = []
        elif current_file is not None:
            current_lines.append(line)

    if current_file is not None:
        file_sections.append((current_file, current_lines))

    for filename, lines in file_sections:
        ext = Path(filename).suffix.lower()
        if ext not in LANG_MAP:
            continue

        classes: set[str] = set()
        functions: set[str] = set()

        section_text = "\n".join(lines)

        # Extract from @@ hunk header context strings
        for m in _HUNK_HEADER_RE.finditer(section_text):
            context = m.group(1)
            cls, fns = _parse_symbols_from_text(context)
            classes.update(cls)
            functions.update(fns)

        # Extract from changed lines (lines starting with + or -)
        for line in lines:
            if line.startswith("+") or line.startswith("-"):
                changed = line[1:501]  # cap at 500 chars to prevent ReDoS
                cls, fns = _parse_symbols_from_text(changed)
                classes.update(cls)
                functions.update(fns)

        # Remove class names that leaked into functions
        functions -= classes

        result[filename] = {
            "modified_classes": sorted(classes),
            "modified_functions": sorted(functions),
        }

    return result
