"""Tests for spec_agent.ollama_setup helpers."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

from spec_agent.ollama_setup import (
    get_pulled_models,
    is_ollama_installed,
    is_ollama_running,
    pull_model,
)


# ---------------------------------------------------------------------------
# is_ollama_installed
# ---------------------------------------------------------------------------

class TestIsOllamaInstalled:
    def test_returns_true_when_binary_found(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/ollama"):
            assert is_ollama_installed() is True

    def test_returns_false_when_binary_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            assert is_ollama_installed() is False


# ---------------------------------------------------------------------------
# is_ollama_running
# ---------------------------------------------------------------------------

class TestIsOllamaRunning:
    def test_returns_true_on_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            assert is_ollama_running() is True

    def test_returns_false_on_non_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp):
            assert is_ollama_running() is False

    def test_returns_false_on_connection_error(self) -> None:
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
            assert is_ollama_running() is False

    def test_returns_false_on_timeout(self) -> None:
        with patch("requests.get", side_effect=requests.exceptions.Timeout):
            assert is_ollama_running() is False

    def test_uses_provided_base_url(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp) as mock_get:
            is_ollama_running("http://192.168.1.5:11434")
            mock_get.assert_called_once_with(
                "http://192.168.1.5:11434/api/tags", timeout=3
            )

    def test_strips_trailing_slash_from_url(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp) as mock_get:
            is_ollama_running("http://localhost:11434/")
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags", timeout=3
            )


# ---------------------------------------------------------------------------
# get_pulled_models
# ---------------------------------------------------------------------------

class TestGetPulledModels:
    def test_returns_model_names(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2"}]
        }
        with patch("requests.get", return_value=mock_resp):
            models = get_pulled_models()
        assert "qwen2.5:7b" in models
        assert "llama3.2" in models

    def test_returns_empty_list_on_connection_error(self) -> None:
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
            assert get_pulled_models() == []

    def test_returns_empty_list_on_non_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            assert get_pulled_models() == []

    def test_returns_empty_list_when_models_key_missing(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        with patch("requests.get", return_value=mock_resp):
            assert get_pulled_models() == []


# ---------------------------------------------------------------------------
# pull_model
# ---------------------------------------------------------------------------

class TestPullModel:
    def test_calls_subprocess_run_with_correct_args(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pull_model("qwen2.5:7b")
            mock_run.assert_called_once_with(
                ["ollama", "pull", "qwen2.5:7b"], check=True
            )

    def test_raises_on_nonzero_exit(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["ollama", "pull", "bad-model"]),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                pull_model("bad-model")
