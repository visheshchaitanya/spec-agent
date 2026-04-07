import pytest
from spec_agent.tools.wiki_read import read_wiki_file


def test_read_existing_file(vault_dir):
    """Reads content and parses frontmatter."""
    path = vault_dir / "features" / "auth.md"
    path.write_text(
        "---\ntype: feature\nproject: my-app\ndate: 2026-04-01\n---\n\n# Auth System\n\nSome content."
    )
    result = read_wiki_file(str(vault_dir), "features/auth.md")
    assert result["content"] == "# Auth System\n\nSome content."
    assert result["frontmatter"]["type"] == "feature"
    assert result["frontmatter"]["project"] == "my-app"
    assert result["exists"] is True


def test_read_missing_file(vault_dir):
    """Returns exists=False for files that don't exist."""
    result = read_wiki_file(str(vault_dir), "features/nonexistent.md")
    assert result["exists"] is False
    assert result["content"] == ""
    assert result["frontmatter"] == {}


def test_read_file_no_frontmatter(vault_dir):
    """Files without frontmatter return empty frontmatter dict."""
    path = vault_dir / "concepts" / "clickhouse.md"
    path.write_text("# ClickHouse\n\nA columnar database.")
    result = read_wiki_file(str(vault_dir), "concepts/clickhouse.md")
    assert result["exists"] is True
    assert result["content"] == "# ClickHouse\n\nA columnar database."
    assert result["frontmatter"] == {}
