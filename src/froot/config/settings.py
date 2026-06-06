"""All deployment config, as pydantic-settings models (env or ``.env``), frozen.

* :class:`Settings` (``FROOT_*``) — loop config: repositories, scan interval,
  and which maintenance loops (``FROOT_LOOPS``) to run on them.
* :class:`TemporalSettings` (``TEMPORAL_*``) — connection: host / namespace /
  task queue, shared by the worker, the scan starter, and the activity client.
* :class:`GitHubSettings` — the API token (``FROOT_GITHUB_TOKEN``) as a
  :class:`~pydantic.SecretStr`, so it is masked in ``repr``, logs, and
  tracebacks and cannot leak accidentally.
* :class:`ModelSettings` (``FROOT_OLLAMA_MODEL`` / ``FROOT_OLLAMA_URL``) — the
  changelog-judge model endpoint.
* :class:`TelemetrySettings` (``FROOT_OTEL``) — observability toggle.

Each consumer builds the small model it needs at its point of use; nothing
secret lives in the repo. ``repos`` is ``NoDecode`` so ``FROOT_REPOS`` is a
comma-separated list of ``owner/name`` slugs rather than JSON; a slug may carry
an optional ``@<ecosystem>`` suffix (e.g. ``acme/pylib@uv``), defaulting to npm.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from froot.domain.ecosystem import Ecosystem
from froot.domain.loop import Loop
from froot.domain.repo import RepoRef, TargetRepo
from froot.result import Ok

_DEFAULT_SCAN_INTERVAL_SECONDS = 86_400


class Settings(BaseSettings):
    """Non-secret worker config from ``FROOT_*`` (env or ``.env``)."""

    model_config = SettingsConfigDict(
        env_prefix="FROOT_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    repos: Annotated[tuple[TargetRepo, ...], NoDecode] = Field(min_length=1)
    scan_interval_seconds: int = Field(
        default=_DEFAULT_SCAN_INTERVAL_SECONDS, gt=0
    )
    # Which maintenance loops to run on each repo. ``FROOT_LOOPS`` is a
    # comma-separated list of loop names; it defaults to dependency-patch alone,
    # so an existing deployment keeps running exactly the loop it did before.
    loops: Annotated[tuple[Loop, ...], NoDecode] = Field(
        default=(Loop.DEPENDENCY_PATCH,), min_length=1
    )

    @field_validator("loops", mode="before")
    @classmethod
    def _parse_loops(cls, value: object) -> object:
        """Parse ``FROOT_LOOPS`` as a comma-separated loop-name list."""
        if not isinstance(value, str):
            return value
        loops: list[Loop] = []
        for raw in value.split(","):
            entry = raw.strip()
            if not entry:
                continue
            try:
                loops.append(Loop(entry))
            except ValueError:
                raise ValueError(f"unknown loop: {entry!r}") from None
        return tuple(loops)

    @field_validator("repos", mode="before")
    @classmethod
    def _parse_repos(cls, value: object) -> object:
        """Parse ``FROOT_REPOS`` as a comma-separated target list.

        Each entry is an ``owner/name`` slug, optionally suffixed with
        ``@<ecosystem>`` (e.g. ``acme/pylib@uv``); the suffix is omitted for the
        default ``npm``.
        """
        if not isinstance(value, str):
            return value
        targets: list[TargetRepo] = []
        for raw in value.split(","):
            entry = raw.strip()
            if not entry:
                continue
            slug, _, eco = entry.partition("@")
            match RepoRef.parse(slug):
                case Ok(ref):
                    pass
                case _:
                    raise ValueError(f"invalid repo slug: {slug!r}")
            try:
                ecosystem = Ecosystem(eco) if eco else Ecosystem.NPM
            except ValueError:
                raise ValueError(f"unknown ecosystem: {eco!r}") from None
            targets.append(TargetRepo(repo=ref, ecosystem=ecosystem))
        return tuple(targets)


class TemporalSettings(BaseSettings):
    """Temporal connection config from ``TEMPORAL_*`` (env or ``.env``).

    The same image runs anywhere by configuring these; the in-cluster
    deployment sets them to the cluster's frontend, namespace, and queue.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEMPORAL_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    host: str = Field(default="localhost:7233", min_length=1)
    namespace: str = Field(default="default", min_length=1)
    task_queue: str = Field(default="froot", min_length=1)


class GitHubSettings(BaseSettings):
    """GitHub credentials, from ``FROOT_GITHUB_TOKEN``.

    The token is a :class:`~pydantic.SecretStr`, so it is masked in ``repr``,
    logs, and tracebacks and cannot leak accidentally; call
    ``github_token.get_secret_value()`` only where the real value is sent.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    github_token: SecretStr | None = None


class ModelSettings(BaseSettings):
    """The changelog-judge model endpoint (a local Ollama by default)."""

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    ollama_model: str = Field(default="gemma4:e4b", min_length=1)
    ollama_url: str = Field(default="http://localhost:11434/v1", min_length=1)


class TelemetrySettings(BaseSettings):
    """OpenTelemetry toggle — off unless ``FROOT_OTEL`` is truthy."""

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    otel: bool = False

    @field_validator("otel", mode="before")
    @classmethod
    def _blank_is_off(cls, value: object) -> object:
        """Treat an empty/whitespace ``FROOT_OTEL`` as off, not an error."""
        if isinstance(value, str) and not value.strip():
            return False
        return value


class ClickHouseSettings(BaseSettings):
    """ClickHouse (the run ledger) connection for the dashboard read-model.

    Every field is optional: when ``FROOT_CLICKHOUSE_URL`` is unset the
    dashboard renders the run-telemetry panel as *unavailable* rather than
    failing. That panel is best-effort enrichment — GitHub (outcomes) and
    Temporal (live runs) are the dependable sources; ClickHouse only adds
    trace-derived run telemetry, on a 3-day TTL at that. The password is a
    :class:`~pydantic.SecretStr`.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_CLICKHOUSE_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    # Host only, e.g. ``http://clickhouse:8123`` — NEVER embed credentials as
    # userinfo (``http://user:pw@host``): they belong in ``user``/``password``
    # so they stay out of error strings the dashboard may surface.
    url: str | None = None
    user: str = Field(default="default", min_length=1)
    password: SecretStr | None = None
    database: str = Field(default="default", min_length=1)


class DashboardSettings(BaseSettings):
    """The read-model dashboard's HTTP surface, served by the worker.

    A read-only page the worker serves on ``FROOT_DASHBOARD_PORT``; reach it
    with ``kubectl port-forward``. It derives everything on request and stores
    nothing (froot's own derived-state invariant), so it is safe to leave on.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_DASHBOARD_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = True
    # Bind all interfaces so an in-cluster ``kubectl port-forward`` reaches it.
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8080, gt=0, le=65535)

    @field_validator("enabled", mode="before")
    @classmethod
    def _blank_is_on(cls, value: object) -> object:
        """Treat an empty/whitespace value as the default (on), not an error."""
        if isinstance(value, str) and not value.strip():
            return True
        return value


class ReviewSettings(BaseSettings):
    """The determinism-reviewer loop (``FROOT_REVIEW_*``).

    The transitive ring: a per-repo loop that polls open PRs and leaves an
    advisory comment when a workflow reaches a determinism hazard through a
    first-party helper (``depth`` call levels) or a risky third-party import.
    Advisory only — the blocking gate is the kernel's ``Determinism`` CI check.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_REVIEW_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = True
    # PRs merge fast, but this loop is advisory (not a gate), so a little
    # latency is fine — it never needs to win the merge race.
    poll_interval_seconds: int = Field(default=300, gt=0)
    # How many first-party call levels to chase out of each workflow method.
    depth: int = Field(default=2, ge=1, le=4)

    @field_validator("enabled", mode="before")
    @classmethod
    def _blank_is_on(cls, value: object) -> object:
        """Treat an empty/whitespace value as the default (on), not an error."""
        if isinstance(value, str) and not value.strip():
            return True
        return value


class BehaviorSettings(BaseSettings):
    """Loop-hygiene toggles (``FROOT_*``), both defaulting on.

    * ``close_on_red`` — close a bump's PR (and delete its branch) when its CI
      comes back red, so no rotting red proposal is left for the human. The
      outcome is still recorded either way. Read at dispatch and pinned onto the
      bump's params, so an in-flight bump keeps the value it started with.
    * ``reconcile`` — each scan tick, close froot PRs a newer patch has
      superseded or the base has already satisfied. Read by the reconcile
      activity, which no-ops when it is off.

    Both close-then-delete a branch, so they are the destructive knobs; default
    on (the SPEC's behavior), but here to disable for cautious adoption on a
    flaky-CI repo.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    close_on_red: bool = True
    reconcile: bool = True

    @field_validator("close_on_red", "reconcile", mode="before")
    @classmethod
    def _blank_is_on(cls, value: object) -> object:
        """Treat an empty/whitespace value as the default (on), not an error."""
        if isinstance(value, str) and not value.strip():
            return True
        return value
