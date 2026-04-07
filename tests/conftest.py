import pytest
from pathlib import Path


@pytest.fixture
def vault_dir(tmp_path):
    """A temporary Obsidian vault directory with standard folders."""
    for folder in ["features", "bugs", "refactors", "concepts", "projects"]:
        (tmp_path / folder).mkdir()
    (tmp_path / "index.md").write_text(
        "# Dev Wiki — Index\n\n| Date | Type | Title | Project | Link |\n|------|------|-------|---------|------|\n"
    )
    return tmp_path
