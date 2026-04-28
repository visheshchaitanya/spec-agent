import pytest
import yaml
from pathlib import Path
from spec_agent.config import Config, load_config, save_config, DEFAULT_CONFIG_PATH


def test_load_config_defaults(tmp_path):
    """When no config file exists, returns defaults."""
    cfg = load_config(config_path=tmp_path / "config.yaml")
    assert cfg.vault_path == Path.home() / "Documents" / "dev-wiki"
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.ignored_repos == []
    assert cfg.ignored_branches == ["dependabot/*", "renovate/*"]
    assert cfg.min_commit_chars == 50
    assert cfg.llm_backend == "anthropic"
    assert cfg.ollama_url == "http://localhost:11434"
    assert cfg.ollama_model == "qwen2.5:7b"
    assert cfg.gemini_model == "gemini-2.0-flash"


def test_load_config_from_file(tmp_path):
    """Values from config file override defaults."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "vault_path": str(tmp_path / "my-vault"),
        "model": "claude-haiku-4-5-20251001",
        "min_commit_chars": 100,
    }))
    cfg = load_config(config_path=config_file)
    assert cfg.vault_path == tmp_path / "my-vault"
    assert cfg.model == "claude-haiku-4-5-20251001"
    assert cfg.min_commit_chars == 100
    assert cfg.ignored_repos == []  # default preserved


def test_save_config(tmp_path):
    """save_config writes a valid YAML file that load_config can read back."""
    config_file = tmp_path / "config.yaml"
    cfg = Config(
        vault_path=tmp_path / "vault",
        model="claude-sonnet-4-6",
        ignored_repos=["my-private-repo"],
        ignored_branches=["dependabot/*"],
        min_commit_chars=75,
        llm_backend="ollama",
        ollama_url="http://192.168.1.10:11434",
        ollama_model="qwen2.5:14b",
        gemini_model="gemini-2.0-flash",
    )
    save_config(cfg, config_path=config_file)
    reloaded = load_config(config_path=config_file)
    assert reloaded.vault_path == tmp_path / "vault"
    assert reloaded.ignored_repos == ["my-private-repo"]
    assert reloaded.min_commit_chars == 75
    assert reloaded.llm_backend == "ollama"
    assert reloaded.ollama_url == "http://192.168.1.10:11434"
    assert reloaded.ollama_model == "qwen2.5:14b"


def test_is_repo_ignored(tmp_path):
    cfg = Config(
        vault_path=tmp_path,
        ignored_repos=["secret-project"],
    )
    assert cfg.is_repo_ignored("secret-project") is True
    assert cfg.is_repo_ignored("public-project") is False


def test_is_branch_ignored(tmp_path):
    cfg = Config(
        vault_path=tmp_path,
        ignored_branches=["dependabot/*", "renovate/*"],
    )
    assert cfg.is_branch_ignored("dependabot/bump-requests") is True
    assert cfg.is_branch_ignored("renovate/update-deps") is True
    assert cfg.is_branch_ignored("main") is False
    assert cfg.is_branch_ignored("feature/my-work") is False


def test_groq_model_defaults_to_llama():
    cfg = Config(vault_path=Path("/tmp/vault"))
    assert cfg.groq_model == "llama-3.3-70b-versatile"
