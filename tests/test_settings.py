from __future__ import annotations

import pytest
from pydantic import ValidationError

from froot.config.settings import (
    GitHubSettings,
    ModelSettings,
    Settings,
    TelemetrySettings,
    TemporalSettings,
)


def test_parses_repo_slugs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "acme/widgets, acme/gadgets")
    monkeypatch.setenv("FROOT_SCAN_INTERVAL_SECONDS", "3600")
    settings = Settings()
    assert [t.repo.slug for t in settings.repos] == [
        "acme/widgets",
        "acme/gadgets",
    ]
    assert settings.repos[0].default_branch == "main"
    assert settings.scan_interval_seconds == 3600


def test_default_interval(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "a/b")
    monkeypatch.delenv("FROOT_SCAN_INTERVAL_SECONDS", raising=False)
    assert Settings().scan_interval_seconds == 86_400


def test_invalid_slug_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "not-a-slug")
    with pytest.raises(ValidationError):
        Settings()


def test_temporal_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    for var in ("TEMPORAL_HOST", "TEMPORAL_NAMESPACE", "TEMPORAL_TASK_QUEUE"):
        monkeypatch.delenv(var, raising=False)
    settings = TemporalSettings()
    assert settings.host == "localhost:7233"
    assert settings.namespace == "default"
    assert settings.task_queue == "froot"


def test_temporal_settings_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEMPORAL_HOST", "temporal-frontend:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "froot")
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "froot-q")
    settings = TemporalSettings()
    assert settings.host == "temporal-frontend:7233"
    assert settings.namespace == "froot"
    assert settings.task_queue == "froot-q"


def test_github_token_is_secret_and_masked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_GITHUB_TOKEN", "ghp_supersecret123")
    settings = GitHubSettings()
    assert settings.github_token is not None
    # The real value is available only via the explicit accessor...
    assert settings.github_token.get_secret_value() == "ghp_supersecret123"
    # ...and is masked everywhere else, so it can't leak into logs.
    assert "ghp_supersecret123" not in repr(settings)
    assert "ghp_supersecret123" not in str(settings.github_token)


def test_github_token_absent_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_GITHUB_TOKEN", raising=False)
    assert GitHubSettings().github_token is None


def test_model_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("FROOT_OLLAMA_URL", raising=False)
    defaults = ModelSettings()
    assert defaults.ollama_model == "gemma4:e4b"
    assert defaults.ollama_url.endswith("/v1")
    monkeypatch.setenv("FROOT_OLLAMA_MODEL", "gemma4:e2b")
    monkeypatch.setenv("FROOT_OLLAMA_URL", "http://ollama.llm:11434/v1")
    overridden = ModelSettings()
    assert overridden.ollama_model == "gemma4:e2b"
    assert overridden.ollama_url == "http://ollama.llm:11434/v1"


def test_telemetry_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_OTEL", raising=False)
    assert TelemetrySettings().otel is False


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("on", True), ("", False), ("no", False)],
)
def test_telemetry_otel_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
):
    monkeypatch.setenv("FROOT_OTEL", value)
    assert TelemetrySettings().otel is expected
