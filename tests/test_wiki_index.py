import pytest
from spec_agent.tools.wiki_index import update_index


def test_appends_entry_to_index(vault_dir):
    """Adds a new row to the index table."""
    update_index(str(vault_dir), {
        "date": "2026-04-07",
        "type": "feature",
        "title": "Alert Ingestion Pipeline",
        "project": "quilr-ingestion-service",
        "path": "features/alert-ingestion",
    })
    index = (vault_dir / "index.md").read_text()
    assert "Alert Ingestion Pipeline" in index
    assert "quilr-ingestion-service" in index
    assert "[[features/alert-ingestion]]" in index


def test_creates_index_if_missing(tmp_path):
    """Creates index.md from scratch if it doesn't exist."""
    update_index(str(tmp_path), {
        "date": "2026-04-07",
        "type": "bug",
        "title": "Fix login",
        "project": "my-app",
        "path": "bugs/fix-login",
    })
    assert (tmp_path / "index.md").exists()
    content = (tmp_path / "index.md").read_text()
    assert "Fix login" in content


def test_multiple_entries(vault_dir):
    """Multiple calls append multiple rows."""
    for i in range(3):
        update_index(str(vault_dir), {
            "date": f"2026-04-0{i+1}",
            "type": "feature",
            "title": f"Feature {i}",
            "project": "app",
            "path": f"features/feature-{i}",
        })
    index = (vault_dir / "index.md").read_text()
    assert "Feature 0" in index
    assert "Feature 1" in index
    assert "Feature 2" in index
