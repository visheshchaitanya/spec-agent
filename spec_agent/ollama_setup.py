"""Helpers to detect, validate, and set up a local Ollama installation."""
from __future__ import annotations

import shutil
import subprocess

import requests


def is_ollama_installed() -> bool:
    """Return True if the `ollama` binary is on PATH."""
    return shutil.which("ollama") is not None


def is_ollama_running(base_url: str = "http://localhost:11434") -> bool:
    """Return True if Ollama is reachable at *base_url*."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        return resp.status_code == 200
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False


def get_pulled_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return the names of models already pulled in Ollama.

    Returns an empty list on any error (not installed, not running, etc.).
    """
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def pull_model(model: str) -> None:
    """Run ``ollama pull <model>``, streaming output to the terminal.

    Raises ``subprocess.CalledProcessError`` on non-zero exit.
    """
    subprocess.run(["ollama", "pull", model], check=True)
