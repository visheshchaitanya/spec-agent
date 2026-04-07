import pytest
from spec_agent.tools.wiki_search import search_wiki


def test_finds_matching_files(vault_dir):
    """Returns files containing the query term."""
    (vault_dir / "concepts" / "clickhouse.md").write_text("# ClickHouse\nA columnar database for analytics.")
    (vault_dir / "concepts" / "postgres.md").write_text("# PostgreSQL\nA relational database.")
    (vault_dir / "features" / "ingestion.md").write_text("# Ingestion\nUses ClickHouse for storage.")

    results = search_wiki(str(vault_dir), "clickhouse")
    paths = [r["path"] for r in results]
    assert "concepts/clickhouse.md" in paths
    assert "features/ingestion.md" in paths
    assert "concepts/postgres.md" not in paths


def test_returns_excerpt(vault_dir):
    """Each result includes a short excerpt of the matching line."""
    (vault_dir / "bugs" / "fix-auth.md").write_text("# Fix Auth\nThe JWT token was expiring too early.")
    results = search_wiki(str(vault_dir), "JWT")
    assert len(results) == 1
    assert "JWT" in results[0]["excerpt"]


def test_case_insensitive(vault_dir):
    """Search is case-insensitive."""
    (vault_dir / "concepts" / "kafka.md").write_text("# Kafka\nA distributed event streaming platform.")
    results = search_wiki(str(vault_dir), "KAFKA")
    assert len(results) == 1


def test_no_results(vault_dir):
    """Returns empty list when nothing matches."""
    results = search_wiki(str(vault_dir), "unicorn-technology-xyz")
    assert results == []


def test_respects_limit(vault_dir):
    """Respects the limit parameter."""
    for i in range(10):
        (vault_dir / "features" / f"feature-{i}.md").write_text(f"# Feature {i}\nUses kafka.")
    results = search_wiki(str(vault_dir), "kafka", limit=3)
    assert len(results) <= 3
