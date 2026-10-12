"""Offline checks for environment loading, validation, and secret handling."""

import pytest
from pydantic import ValidationError

from paper_research_agent.config import PROJECT_ROOT, Settings, load_settings


@pytest.fixture(autouse=True)
def clear_config_environment(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_allow_initialization_without_api_key(tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    assert settings.data_dir == PROJECT_ROOT / "data"
    assert settings.arxiv_max_results == 5
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        settings.require_openai_api_key()


def test_environment_overrides_file_and_secret_is_masked(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=test-secret\nARXIV_MAX_RESULTS=3\nDATA_DIR=data/custom\n", encoding="utf-8")
    monkeypatch.setenv("ARXIV_MAX_RESULTS", "7")
    settings = load_settings(env_file)
    assert settings.arxiv_max_results == 7
    assert settings.data_dir == PROJECT_ROOT / "data" / "custom"
    assert settings.require_openai_api_key() == "test-secret"
    assert "test-secret" not in repr(settings)
    assert "test-secret" not in settings.model_dump_json()


@pytest.mark.parametrize("content", ["ARXIV_MAX_RESULTS=0", "PDF_MAX_PAGES=abc", "REQUEST_TIMEOUT_SECONDS=-1", "AGENT_MAX_TOOL_ROUNDS=0", "OPENAI_MODEL=   ", "DATA_DIR="])
def test_invalid_configuration_fails_early(tmp_path, content):
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(env_file)


def test_blank_key_is_optional_and_loading_does_not_change_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=\nARXIV_MAX_RESULTS=9\n", encoding="utf-8")
    settings = load_settings(env_file)
    assert settings.openai_api_key is None
    monkeypatch.setenv("ARXIV_MAX_RESULTS", "2")
    assert load_settings(env_file).arxiv_max_results == 2
