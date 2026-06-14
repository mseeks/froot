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
from froot.policy.autonomy import AutonomyPolicy
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


class WorkerSettings(BaseSettings):
    """Worker runtime tuning (``FROOT_*``).

    ``max_concurrent_activities`` caps how many activities the worker runs at
    once. The model judge calls a local Ollama; matching this to Ollama's own
    concurrency lets independent loops adjudicate in parallel instead of
    serializing behind a single in-flight call. The durable CI wait is a
    workflow timer, so it never holds an activity slot.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    max_concurrent_activities: int = Field(default=4, ge=1)


class NtfySettings(BaseSettings):
    """ntfy alert channel for loop-health notifications (``FROOT_*``).

    The liveness watchdog posts here when it revives a dead loop. An empty topic
    (the default) disables alerts — the watchdog still restarts, it just stays
    quiet. The topic is a capability: anyone who knows it can read and post, so
    treat it like a secret in the deployment.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_", env_file=".env", extra="ignore", frozen=True
    )

    ntfy_topic: str = ""
    ntfy_url: str = Field(default="https://ntfy.sh", min_length=1)


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

    ollama_model: str = Field(default="gemma4:12b", min_length=1)
    ollama_url: str = Field(default="http://localhost:11434/v1", min_length=1)
    # The independent gate reviewer (the fourth trust leg, §3.7). Empty means
    # "reuse ``ollama_model``" — so by default it is the same model run a second
    # time with an adversarial prompt; point it at a stronger model to make the
    # deep review genuinely independent in capability, not just in framing.
    gate_review_model: str = ""


class E2bSettings(BaseSettings):
    """The e2b sandbox backend's config (``FROOT_E2B_*``).

    The signal sandbox for loops whose analysis needs the target's deps
    installed (uv's ``deptry``). The API key is a :class:`~pydantic.SecretStr`,
    so it is masked in ``repr``/logs; it is passed explicitly to the e2b SDK
    rather than read from its default ``E2B_API_KEY`` env, so the credential is
    namespaced under ``FROOT_`` like every other froot secret. ``template`` is
    an optional e2b template id (a prebuilt image with the toolchain baked);
    empty means the e2b base image, with the toolchain installed at run time.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_E2B_", env_file=".env", extra="ignore", frozen=True
    )

    api_key: SecretStr | None = None
    template: str = ""
    # Kept under the 10-minute scan activity timeout (with margin) so a slow
    # ``uv sync`` is capped by the sandbox, not by the activity timing out.
    timeout_seconds: int = Field(default=480, gt=0)


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


class A11yReviewSettings(BaseSettings):
    """The source-level a11y-reviewer loop (``FROOT_A11Y_*``).

    A per-repo loop that polls open PRs and leaves an advisory comment when a
    changed Vue/JSX template has a source-level accessibility gap (an unnamed
    ``role="img"``/``<svg>``, an unlabeled control, a click on a non-interactive
    element with no keyboard path, an ``<img>`` with no alt). Advisory only — it
    never merges; it is the source-level complement to the runtime axe checks an
    app's e2e suite runs.

    Off by default: a new loop opts in deliberately (MHE's observe-then-act
    staging), and it only matters for UI repos — a repo with no templates yields
    nothing, so enabling it cluster-wide is harmless.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_A11Y_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    # Advisory, so a little latency is fine — it never races a merge.
    poll_interval_seconds: int = Field(default=300, gt=0)

    @field_validator("enabled", mode="before")
    @classmethod
    def _blank_is_off(cls, value: object) -> object:
        """Treat a blank value as the default (off), not an error."""
        if isinstance(value, str) and not value.strip():
            return False
        return value


class DocRefsReviewSettings(BaseSettings):
    """The documentation-reference reviewer loop (``FROOT_DOC_REFS_*``).

    A per-repo loop that polls open PRs and leaves an advisory comment when a
    changed Markdown doc references something missing at the head — a dead link
    or file path, or a removed ``make`` target — flagging hardest the references
    a PR's own deletions broke. Advisory only; a human fixes the doc.

    Off by default: a new loop opts in deliberately (MHE's observe-then-act
    staging). It only fires when a doc actually dangles, so enabling it
    cluster-wide is low-noise.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_DOC_REFS_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    # Advisory, so a little latency is fine — it never races a merge.
    poll_interval_seconds: int = Field(default=300, gt=0)

    @field_validator("enabled", mode="before")
    @classmethod
    def _blank_is_off(cls, value: object) -> object:
        """Treat a blank value as the default (off), not an error."""
        if isinstance(value, str) and not value.strip():
            return False
        return value


class AgenticSettings(BaseSettings):
    """The agentic executor's bounds (``FROOT_AGENTIC_*``).

    The heavier, tool-using model run behind a fabrication/mapper loop's action
    slot — the doc-coherence reviewer is froot's first. ``max_requests`` is a
    hard ceiling on model turns so a runaway reasoning loop can't burn the
    worker; the model itself is the configured Ollama (shared with the thin
    judges, swappable by config later).
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_AGENTIC_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    max_requests: int = Field(default=40, gt=0)


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


class AutonomySettings(BaseSettings):
    """The earned-autonomy thresholds (``FROOT_AUTOMERGE_*``) for the gate.

    These tune the gate the loop now acts on: whether a (repo, loop) class has
    earned its move, and whether each clean+green PR merges under that grant. On
    an allowlisted repo the loop auto-merges; everywhere else the same verdict
    is the dashboard's advisory *shadow gate*. The defaults are deliberately
    conservative and the allowlist is empty — the revocable switch left off
    until a steward opts a repo in.

    * ``min_rate`` / ``min_decided`` / ``window_days`` — the track-record bar a
      class must clear, measured over a recent window (trust is recent, §2.11).
    * ``allowlist`` (``FROOT_AUTOMERGE_ALLOWLIST``) — a comma-separated list of
      ``owner/name`` slugs a steward has opted into; ``NoDecode`` so it is a
      plain list, not JSON. Empty by default: no class can ride the grant.
    """

    model_config = SettingsConfigDict(
        env_prefix="FROOT_AUTOMERGE_",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    min_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    min_decided: int = Field(default=5, ge=1)
    window_days: int = Field(default=90, gt=0)
    # The post-merge defect bearing (the second, independent leg, §3.8):
    # how many confirmed-held outcomes are needed before it counts, and the
    # ceiling on the defect rate (zero-tolerance by default).
    min_determined: int = Field(default=3, ge=1)
    max_defect_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    allowlist: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("allowlist", mode="before")
    @classmethod
    def _parse_allowlist(cls, value: object) -> object:
        """Parse the allowlist as a comma-separated ``owner/name`` list."""
        if not isinstance(value, str):
            return value
        return tuple(
            entry.strip() for entry in value.split(",") if entry.strip()
        )

    def policy(self) -> AutonomyPolicy:
        """Build the pure :class:`AutonomyPolicy` the read-model consumes."""
        return AutonomyPolicy(
            min_rate=self.min_rate,
            min_decided=self.min_decided,
            window_days=self.window_days,
            min_determined=self.min_determined,
            max_defect_rate=self.max_defect_rate,
            allowlisted_repos=frozenset(self.allowlist),
        )
