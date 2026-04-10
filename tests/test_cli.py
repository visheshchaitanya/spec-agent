"""Tests for CLI commands."""
from __future__ import annotations
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from click.testing import CliRunner

from spec_agent.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def home(tmp_path: Path):
    """Isolated HOME so config writes go to tmp_path instead of the real home."""
    return tmp_path


# ---------------------------------------------------------------------------
# spec-agent init
# ---------------------------------------------------------------------------

class TestInit:
    def _config_path(self, home: Path) -> Path:
        return home / ".spec-agent" / "config.yaml"

    def test_creates_vault_structure(self, runner: CliRunner, home: Path) -> None:
        vault = home / "my-vault"
        config = self._config_path(home)
        result = runner.invoke(cli, ["init", "--vault", str(vault), "--config", str(config)])
        assert result.exit_code == 0, result.output
        for folder in ["features", "bugs", "refactors", "concepts", "projects"]:
            assert (vault / folder).is_dir()
        assert (vault / "index.md").exists()

    def test_creates_config(self, runner: CliRunner, home: Path) -> None:
        vault = home / "vault"
        config = self._config_path(home)
        runner.invoke(cli, ["init", "--vault", str(vault), "--config", str(config)])
        assert config.exists()
        data = yaml.safe_load(config.read_text())
        assert data["vault_path"] == str(vault)

    def test_does_not_overwrite_existing_index(self, runner: CliRunner, home: Path) -> None:
        vault = home / "vault"
        vault.mkdir(parents=True)
        existing = vault / "index.md"
        existing.write_text("# My existing index\n")
        config = self._config_path(home)
        runner.invoke(cli, ["init", "--vault", str(vault), "--config", str(config)])
        assert existing.read_text() == "# My existing index\n"

    def test_output_mentions_next_step(self, runner: CliRunner, home: Path) -> None:
        vault = home / "vault"
        config = self._config_path(home)
        result = runner.invoke(cli, ["init", "--vault", str(vault), "--config", str(config)])
        assert "install-hook" in result.output


# ---------------------------------------------------------------------------
# spec-agent configure
# ---------------------------------------------------------------------------

class TestConfigure:
    def _cfg_file(self, home: Path) -> Path:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\n")
        return cfg

    def test_configure_anthropic(self, runner: CliRunner, home: Path) -> None:
        cfg = self._cfg_file(home)
        result = runner.invoke(
            cli, ["configure", "--config", str(cfg)],
            input="anthropic\nclaude-haiku-4-5-20251001\n",
        )
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(cfg.read_text())
        assert data["llm_backend"] == "anthropic"
        assert data["model"] == "claude-haiku-4-5-20251001"

    def test_configure_ollama(self, runner: CliRunner, home: Path) -> None:
        cfg = self._cfg_file(home)
        result = runner.invoke(
            cli, ["configure", "--config", str(cfg)],
            input="ollama\nhttp://192.168.1.10:11434\ngemma3\n",
        )
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(cfg.read_text())
        assert data["llm_backend"] == "ollama"
        assert data["ollama_url"] == "http://192.168.1.10:11434"
        assert data["ollama_model"] == "gemma3"

    def test_configure_gemini(self, runner: CliRunner, home: Path) -> None:
        cfg = self._cfg_file(home)
        result = runner.invoke(
            cli, ["configure", "--config", str(cfg)],
            input="gemini\ngemini-2.0-flash\n",
        )
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(cfg.read_text())
        assert data["llm_backend"] == "gemini"
        assert data["gemini_model"] == "gemini-2.0-flash"

    def test_configure_invalid_backend_reprompts(self, runner: CliRunner, home: Path) -> None:
        cfg = self._cfg_file(home)
        # "invalid" is not a valid choice; click reprompts; then "ollama" succeeds
        result = runner.invoke(
            cli, ["configure", "--config", str(cfg)],
            input="invalid\nollama\nhttp://localhost:11434\nqwen2.5:7b\n",
        )
        assert result.exit_code == 0, result.output

    def test_configure_shows_ollama_model_list(self, runner: CliRunner, home: Path) -> None:
        cfg = self._cfg_file(home)
        result = runner.invoke(
            cli, ["configure", "--config", str(cfg)],
            input="ollama\n\n\n",
        )
        assert "qwen2.5" in result.output
        assert "gemma3" in result.output


# ---------------------------------------------------------------------------
# spec-agent config-get
# ---------------------------------------------------------------------------

class TestConfigGet:
    def test_returns_vault_path(self, runner: CliRunner, home: Path) -> None:
        config_file = home / "config.yaml"
        config_file.write_text(f"vault_path: {home}/vault\n")
        result = runner.invoke(cli, ["config-get", "vault_path", "--config", str(config_file)])
        assert result.exit_code == 0
        assert str(home / "vault") in result.output

    def test_returns_model(self, runner: CliRunner, home: Path) -> None:
        config_file = home / "config.yaml"
        config_file.write_text("vault_path: /tmp/v\nmodel: claude-haiku-4-5-20251001\n")
        result = runner.invoke(cli, ["config-get", "model", "--config", str(config_file)])
        assert result.exit_code == 0
        assert "claude-haiku-4-5-20251001" in result.output

    def test_exits_nonzero_for_unknown_key(self, runner: CliRunner, home: Path) -> None:
        config_file = home / "config.yaml"
        config_file.write_text("vault_path: /tmp/v\n")
        result = runner.invoke(cli, ["config-get", "nonexistent_key", "--config", str(config_file)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# spec-agent run (error paths — no API calls)
# ---------------------------------------------------------------------------

class TestRun:
    def _config_file(self, home: Path, vault: Path) -> Path:
        f = home / "config.yaml"
        f.write_text(f"vault_path: {vault}\n")
        return f

    def test_skips_ignored_repo(self, runner: CliRunner, home: Path) -> None:
        vault = home / "vault"
        vault.mkdir()
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {vault}\nignored_repos:\n  - secret-repo\n")
        result = runner.invoke(cli, [
            "run", "--repo", "secret-repo", "--branch", "main",
            "--messages", "feat: something", "--diff-file", "/nonexistent",
            "--config", str(cfg),
        ])
        assert result.exit_code == 0
        assert "skipping ignored repo" in result.output

    def test_skips_ignored_branch(self, runner: CliRunner, home: Path) -> None:
        vault = home / "vault"
        vault.mkdir()
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {vault}\nignored_branches:\n  - dependabot/*\n")
        result = runner.invoke(cli, [
            "run", "--repo", "my-repo", "--branch", "dependabot/bump-foo",
            "--messages", "chore: bump", "--diff-file", "/nonexistent",
            "--config", str(cfg),
        ])
        assert result.exit_code == 0
        assert "skipping ignored branch" in result.output

    def test_warns_when_vault_missing(self, runner: CliRunner, home: Path) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/nonexistent-vault\n")
        result = runner.invoke(cli, [
            "run", "--repo", "my-repo", "--branch", "main",
            "--messages", "feat: x", "--diff-file", "/nonexistent",
            "--config", str(cfg),
        ])
        assert result.exit_code == 0
        assert "vault not found" in result.output

    def test_calls_agent_with_parsed_args(self, runner: CliRunner, home: Path, vault_dir) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {vault_dir}\n")
        diff_file = home / "diff.txt"
        diff_file.write_text("some diff content")

        with patch("spec_agent.cli.run_agent") as mock_agent:
            result = runner.invoke(cli, [
                "run",
                "--repo", "my-app",
                "--branch", "main",
                "--messages", "feat: new feature\nfix: bug fix",
                "--diff-file", str(diff_file),
                "--config", str(cfg),
            ])

        assert result.exit_code == 0, result.output
        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args.kwargs
        assert call_kwargs["repo_name"] == "my-app"
        assert call_kwargs["branch"] == "main"
        assert call_kwargs["diff"] == "some diff content"


# ---------------------------------------------------------------------------
# spec-agent install-hook / uninstall-hook
# ---------------------------------------------------------------------------

class TestHooks:
    def test_install_hook_creates_file(self, runner: CliRunner, home: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(cli, ["install-hook"], env={"HOME": str(home)})
        assert result.exit_code == 0
        hook = home / ".git-hooks" / "pre-push"
        assert hook.exists()
        assert hook.stat().st_mode & 0o111  # executable

    def test_uninstall_hook_removes_file(self, runner: CliRunner, home: Path) -> None:
        hook_dir = home / ".git-hooks"
        hook_dir.mkdir()
        (hook_dir / "pre-push").write_text("#!/bin/bash\n")
        result = runner.invoke(cli, ["uninstall-hook"], env={"HOME": str(home)})
        assert result.exit_code == 0
        assert not (hook_dir / "pre-push").exists()

    def test_uninstall_hook_missing_is_graceful(self, runner: CliRunner, home: Path) -> None:
        result = runner.invoke(cli, ["uninstall-hook"], env={"HOME": str(home)})
        assert result.exit_code == 0
        assert "nothing to remove" in result.output


# ---------------------------------------------------------------------------
# spec-agent opt-out / opt-in
# ---------------------------------------------------------------------------

class TestOptOut:
    def _cfg_with_vault(self, home: Path) -> Path:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        return cfg

    def test_adds_repo_to_ignored_list(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert "my-service" in data["ignored_repos"]

    def test_output_confirms_opt_out(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert "my-service" in result.output
        assert "ignored" in result.output

    def test_no_op_when_already_ignored(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos:\n  - my-service\n")
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert data["ignored_repos"].count("my-service") == 1  # not duplicated

    def test_errors_when_not_in_git_repo(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "Not a git repository" in result.output


class TestOptIn:
    def _cfg_with_ignored(self, home: Path) -> Path:
        cfg = home / "config.yaml"
        cfg.write_text(
            f"vault_path: {home}/vault\nignored_repos:\n  - my-service\n  - other-repo\n"
        )
        return cfg

    def test_removes_repo_from_ignored_list(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_ignored(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert "my-service" not in data["ignored_repos"]
        assert "other-repo" in data["ignored_repos"]  # other repo unaffected

    def test_output_confirms_opt_in(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_ignored(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert "my-service" in result.output

    def test_no_op_when_not_ignored(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code == 0
        assert "not currently ignored" in result.output

    def test_errors_when_not_in_git_repo(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "Not a git repository" in result.output
