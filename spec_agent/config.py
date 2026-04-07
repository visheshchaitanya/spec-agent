from __future__ import annotations
import fnmatch
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / ".spec-agent" / "config.yaml"


@dataclass
class Config:
    vault_path: Path
    model: str = "claude-sonnet-4-6"
    ignored_repos: list[str] = field(default_factory=list)
    ignored_branches: list[str] = field(default_factory=lambda: ["dependabot/*", "renovate/*"])
    min_commit_chars: int = 50

    def is_repo_ignored(self, repo_name: str) -> bool:
        return repo_name in self.ignored_repos

    def is_branch_ignored(self, branch: str) -> bool:
        return any(fnmatch.fnmatch(branch, pattern) for pattern in self.ignored_branches)


def _defaults() -> dict:
    return {
        "vault_path": str(Path.home() / "Documents" / "dev-wiki"),
        "model": "claude-sonnet-4-6",
        "ignored_repos": [],
        "ignored_branches": ["dependabot/*", "renovate/*"],
        "min_commit_chars": 50,
    }


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    data = _defaults()
    if config_path.exists():
        with open(config_path) as f:
            data.update(yaml.safe_load(f) or {})
    return Config(
        vault_path=Path(data["vault_path"]),
        model=data["model"],
        ignored_repos=data.get("ignored_repos", []),
        ignored_branches=data.get("ignored_branches", ["dependabot/*", "renovate/*"]),
        min_commit_chars=int(data.get("min_commit_chars", 50)),
    )


def save_config(cfg: Config, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump({
            "vault_path": str(cfg.vault_path),
            "model": cfg.model,
            "ignored_repos": cfg.ignored_repos,
            "ignored_branches": cfg.ignored_branches,
            "min_commit_chars": cfg.min_commit_chars,
        }, f, default_flow_style=False)
