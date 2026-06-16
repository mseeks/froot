from __future__ import annotations

import pytest
from pydantic import ValidationError

from froot.config.settings import (
    AutonomySettings,
    BehaviorSettings,
    GitHubSettings,
    ModelSettings,
    Settings,
    TelemetrySettings,
    TemporalSettings,
    WorkerSettings,
)
from froot.domain.ecosystem import Ecosystem


def test_behavior_defaults_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_CLOSE_ON_RED", raising=False)
    monkeypatch.delenv("FROOT_RECONCILE", raising=False)
    behavior = BehaviorSettings()
    assert behavior.close_on_red is True
    assert behavior.reconcile is True


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("on", True), ("", True), ("0", False)],
)
def test_behavior_close_on_red_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
):
    # Blank defaults on (the _blank_is_on validator); explicit 0 turns it off.
    monkeypatch.setenv("FROOT_CLOSE_ON_RED", value)
    assert BehaviorSettings().close_on_red is expected


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


def test_loops_default_to_dependency_patch_only(
    monkeypatch: pytest.MonkeyPatch,
):
    from froot.domain.loop import Loop

    monkeypatch.setenv("FROOT_REPOS", "acme/widgets")
    monkeypatch.delenv("FROOT_LOOPS", raising=False)
    assert Settings().loops == (Loop.DEPENDENCY_PATCH,)


def test_parses_loops_list(monkeypatch: pytest.MonkeyPatch):
    from froot.domain.loop import Loop

    monkeypatch.setenv("FROOT_REPOS", "acme/widgets")
    monkeypatch.setenv(
        "FROOT_LOOPS", "dependency-patch, security-patch, dead-code"
    )
    assert Settings().loops == (
        Loop.DEPENDENCY_PATCH,
        Loop.SECURITY_PATCH,
        Loop.DEAD_CODE,
    )


def test_unknown_loop_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "acme/widgets")
    monkeypatch.setenv("FROOT_LOOPS", "bogus-loop")
    with pytest.raises(ValidationError):
        Settings()


def test_parses_ecosystem_suffix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "acme/widgets, acme/pylib@uv")
    repos = Settings().repos
    assert repos[0].repo.slug == "acme/widgets"
    assert repos[0].ecosystem is Ecosystem.NPM  # default when no suffix
    assert repos[1].repo.slug == "acme/pylib"
    assert repos[1].ecosystem is Ecosystem.UV


def test_unknown_ecosystem_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_REPOS", "acme/pylib@cargo")
    with pytest.raises(ValidationError):
        Settings()


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


def test_pr_assignees_default_empty(monkeypatch: pytest.MonkeyPatch):
    # Unset → no one is assigned, so an existing deployment is unchanged.
    monkeypatch.delenv("FROOT_PR_ASSIGNEES", raising=False)
    assert GitHubSettings().pr_assignees == ()


def test_pr_assignees_parsed_stripped_and_at_tolerated(
    monkeypatch: pytest.MonkeyPatch,
):
    # Comma-separated, surrounding space trimmed, a leading @ tolerated, and
    # blank entries dropped — so "@mseeks, bot ," yields the two bare logins.
    monkeypatch.setenv("FROOT_PR_ASSIGNEES", "@mseeks, bot ,")
    assert GitHubSettings().pr_assignees == ("mseeks", "bot")


def test_model_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("FROOT_OLLAMA_URL", raising=False)
    defaults = ModelSettings()
    assert defaults.ollama_model == "gemma4:12b"
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


def _clear_automerge(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "FROOT_AUTOMERGE_MIN_RATE",
        "FROOT_AUTOMERGE_MIN_DECIDED",
        "FROOT_AUTOMERGE_WINDOW_DAYS",
        "FROOT_AUTOMERGE_ALLOWLIST",
    ):
        monkeypatch.delenv(var, raising=False)


def test_autonomy_defaults_are_conservative(monkeypatch: pytest.MonkeyPatch):
    _clear_automerge(monkeypatch)
    policy = AutonomySettings().policy()
    assert policy.min_rate == 0.95
    assert policy.min_decided == 5
    assert policy.window_days == 90
    # The post-merge defect bearing: needs evidence, zero-tolerance by default.
    assert policy.min_determined == 3
    assert policy.max_defect_rate == 0.0
    # The revocable switch is off by default: no repo can ride the grant.
    assert policy.allowlisted_repos == frozenset()


def test_autonomy_reads_env_and_parses_allowlist(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("FROOT_AUTOMERGE_MIN_RATE", "0.9")
    monkeypatch.setenv("FROOT_AUTOMERGE_MIN_DECIDED", "10")
    monkeypatch.setenv("FROOT_AUTOMERGE_WINDOW_DAYS", "30")
    monkeypatch.setenv(
        "FROOT_AUTOMERGE_ALLOWLIST", "acme/widgets, acme/gadgets"
    )
    policy = AutonomySettings().policy()
    assert policy.min_rate == 0.9
    assert policy.min_decided == 10
    assert policy.window_days == 30
    assert policy.allowlisted_repos == frozenset(
        {"acme/widgets", "acme/gadgets"}
    )


def test_autonomy_allowlist_blank_is_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_AUTOMERGE_ALLOWLIST", "  ")
    assert AutonomySettings().policy().allowlisted_repos == frozenset()


def test_autonomy_rejects_rate_above_one(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_AUTOMERGE_MIN_RATE", "1.5")
    with pytest.raises(ValidationError):
        AutonomySettings()


def test_worker_concurrency_defaults_to_four(monkeypatch: pytest.MonkeyPatch):
    # Matches Ollama's 4 concurrent calls, so independent loops adjudicate in
    # parallel rather than serializing behind one in-flight model call.
    monkeypatch.delenv("FROOT_MAX_CONCURRENT_ACTIVITIES", raising=False)
    assert WorkerSettings().max_concurrent_activities == 4


def test_worker_concurrency_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_MAX_CONCURRENT_ACTIVITIES", "2")
    assert WorkerSettings().max_concurrent_activities == 2


def test_worker_concurrency_rejects_below_one(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FROOT_MAX_CONCURRENT_ACTIVITIES", "0")
    with pytest.raises(ValidationError):
        WorkerSettings()
