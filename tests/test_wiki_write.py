import pytest
from pathlib import Path
from spec_agent.tools.wiki_write import write_wiki_file


def test_create_new_file(vault_dir):
    """Creates a new markdown file in the vault."""
    content = "---\ntype: feature\nproject: myapp\ndate: 2026-04-07\ncommit: abc123\nstatus: shipped\n---\n\n# My Feature\n\nDoes stuff."
    result = write_wiki_file(str(vault_dir), "features/my-feature.md", content, mode="create")
    assert result["success"] is True
    assert result["path"] == "features/my-feature.md"
    assert (vault_dir / "features" / "my-feature.md").read_text() == content


def test_create_makes_parent_dirs(vault_dir):
    """Creates intermediate directories if needed."""
    content = "# New concept"
    write_wiki_file(str(vault_dir), "concepts/new-tech.md", content, mode="create")
    assert (vault_dir / "concepts" / "new-tech.md").exists()


def test_update_appends_changelog(vault_dir):
    """Update mode appends a changelog section, not overwrite."""
    path = vault_dir / "features" / "auth.md"
    original = "---\ntype: feature\n---\n\n# Auth\n\nOriginal content.\n\n## Changelog\n\n- 2026-04-01: Initial"
    path.write_text(original)
    write_wiki_file(
        str(vault_dir),
        "features/auth.md",
        "- 2026-04-07: Added OAuth support",
        mode="update",
    )
    updated = path.read_text()
    assert "Original content." in updated
    assert "Added OAuth support" in updated


def test_create_overwrites_existing(vault_dir):
    """Create mode replaces existing file content."""
    path = vault_dir / "bugs" / "old-bug.md"
    path.write_text("# Old content")
    write_wiki_file(str(vault_dir), "bugs/old-bug.md", "# New content", mode="create")
    assert path.read_text() == "# New content"
