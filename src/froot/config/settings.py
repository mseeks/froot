"""All deployment config, as pydantic-settings models (env or ``.env``), frozen.

* :class:`Settings` (``FROOT_*``) — loop config: repositories and scan interval.
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
comma-separated list of ``owner/name`` slugs rather than JSON.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    @field_validator("repos", mode="before")
    @classmethod
    def _parse_repos(cls, value: object) -> object:
        """Accept ``FROOT_REPOS`` as a comma-separated ``owner/name`` list."""
        if not isinstance(value, str):
            return value
        targets: list[TargetRepo] = []
        for raw in value.split(","):
            slug = raw.strip()
            if not slug:
                continue
            match RepoRef.parse(slug):
                case Ok(ref):
                    targets.append(TargetRepo(repo=ref))
                case _:
                    raise ValueError(f"invalid repo slug: {slug!r}")
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
