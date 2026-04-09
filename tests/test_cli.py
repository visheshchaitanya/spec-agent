import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from spec_agent.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def test_init_creates_vault_structure(runner, tmp_path):
    vault = tmp_path / "my-wiki"
    config_path = tmp_path / "config.yaml"

    with patch("spec_agent.cli.DEFAULT_CONFIG_PATH", config_path):
        result = runner.invoke(cli, ["init", "--vault", str(vault)])

    assert result.exit_code == 0, result.output
    for folder in ["features", "bugs", "refactors", "concepts", "projects"]:
        assert (vault / folder).is_dir()
    assert (vault / "index.md").exists()


def test_init_does_not_overwrite_existing_index(runner, tmp_path):
    vault = tmp_path / "wiki"
    vault.mkdir()
    index = vault / "index.md"
    index.write_text("existing content")
    config_path = tmp_path / "config.yaml"

    with patch("spec_agent.cli.DEFAULT_CONFIG_PATH", config_path):
        result = runner.invoke(cli, ["init", "--vault", str(vault)])

    assert result.exit_code == 0
    assert index.read_text() == "existing content"


# ---------------------------------------------------------------------------
# install-hook / uninstall-hook
# ---------------------------------------------------------------------------

def test_install_hook_writes_script_and_sets_git_config(runner, tmp_path):
    hooks_dir = tmp_path / ".git-hooks"

    with patch("spec_agent.cli.Path.home", return_value=tmp_path), \
         patch("spec_agent.cli.subprocess.run") as mock_run:
        result = runner.invoke(cli, ["install-hook"])

    assert result.exit_code == 0, result.output
    hook = hooks_dir / "pre-push"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111  # executable
    assert "spec-agent run" in hook.read_text()
    mock_run.assert_called_once()


def test_uninstall_hook_removes_file(runner, tmp_path):
    hooks_dir = tmp_path / ".git-hooks"
    hooks_dir.mkdir()
    hook = hooks_dir / "pre-push"
    hook.write_text("#!/bin/bash\n")

    with patch("spec_agent.cli.Path.home", return_value=tmp_path):
        result = runner.invoke(cli, ["uninstall-hook"])

    assert result.exit_code == 0, result.output
    assert not hook.exists()
    assert "Done" in result.output


def test_uninstall_hook_when_not_installed(runner, tmp_path):
    with patch("spec_agent.cli.Path.home", return_value=tmp_path):
        result = runner.invoke(cli, ["uninstall-hook"])

    assert result.exit_code == 0
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def test_run_skips_ignored_repo(runner, tmp_path, vault_dir):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"vault_path: {vault_dir}\n"
        "ignored_repos:\n  - secret-repo\n"
    )
    diff_file = tmp_path / "diff.txt"
    diff_file.write_text("diff content")

    with patch("spec_agent.cli.run_agent") as mock_agent:
        result = runner.invoke(cli, [
            "run",
            "--repo", "secret-repo",
            "--branch", "main",
            "--messages", "feat: stuff",
            "--diff-file", str(diff_file),
            "--config", str(config_path),
        ])

    assert result.exit_code == 0
    mock_agent.assert_not_called()


def test_run_skips_ignored_branch(runner, tmp_path, vault_dir):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"vault_path: {vault_dir}\n"
        "ignored_branches:\n  - dependabot/*\n"
    )
    diff_file = tmp_path / "diff.txt"
    diff_file.write_text("diff content")

    with patch("spec_agent.cli.run_agent") as mock_agent:
        result = runner.invoke(cli, [
            "run",
            "--repo", "my-app",
            "--branch", "dependabot/npm-updates",
            "--messages", "chore: bump deps",
            "--diff-file", str(diff_file),
            "--config", str(config_path),
        ])

    assert result.exit_code == 0
    mock_agent.assert_not_called()


def test_run_warns_when_vault_missing(runner, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"vault_path: {tmp_path / 'nonexistent-vault'}\n")
    diff_file = tmp_path / "diff.txt"
    diff_file.write_text("diff content")

    with patch("spec_agent.cli.run_agent") as mock_agent:
        result = runner.invoke(cli, [
            "run",
            "--repo", "my-app",
            "--branch", "main",
            "--messages", "feat: thing",
            "--diff-file", str(diff_file),
            "--config", str(config_path),
        ])

    assert result.exit_code == 0
    assert "vault not found" in result.output
    mock_agent.assert_not_called()


def test_run_calls_agent_with_parsed_args(runner, tmp_path, vault_dir):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"vault_path: {vault_dir}\n")
    diff_file = tmp_path / "diff.txt"
    diff_file.write_text("some diff content")

    with patch("spec_agent.cli.run_agent") as mock_agent:
        result = runner.invoke(cli, [
            "run",
            "--repo", "my-app",
            "--branch", "main",
            "--messages", "feat: new feature\nfix: bug fix",
            "--diff-file", str(diff_file),
            "--config", str(config_path),
        ])

    assert result.exit_code == 0, result.output
    mock_agent.assert_called_once()
    call_kwargs = mock_agent.call_args.kwargs
    assert call_kwargs["repo_name"] == "my-app"
    assert call_kwargs["branch"] == "main"
    assert "new feature" in call_kwargs["commit_messages"][0]
    assert call_kwargs["diff"] == "some diff content"
    # diff file should be cleaned up
    assert not diff_file.exists()


# ---------------------------------------------------------------------------
# config-get
# ---------------------------------------------------------------------------

def test_config_get_existing_key(runner, tmp_path, vault_dir):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"vault_path: {vault_dir}\n")

    result = runner.invoke(cli, ["config-get", "vault_path", "--config", str(config_path)])

    assert result.exit_code == 0
    assert str(vault_dir) in result.output


def test_config_get_missing_key_exits_nonzero(runner, tmp_path, vault_dir):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"vault_path: {vault_dir}\n")

    result = runner.invoke(cli, ["config-get", "nonexistent_key", "--config", str(config_path)])

    assert result.exit_code == 1
