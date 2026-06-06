"""The dashboard's view model — pure, frozen, fully derived.

These types are the shape the renderer projects to HTML. They carry *already
computed* numbers (the aggregates live in :mod:`~froot.dashboard.read_model`),
so the renderer is a dumb projection and every figure on the page is
unit-tested apart from any I/O. Nothing here is persisted: a
:class:`DashboardModel` is built fresh per request and discarded after the
response (derive, never store).
"""

from __future__ import annotations

from datetime import datetime

from froot.domain.base import Frozen


class SourceHealth(Frozen):
    """Whether one external truth answered this request.

    Attributes:
        name: The source label (``github`` / ``temporal`` / ``clickhouse``).
        ok: True when the source returned data; False when it errored or is off.
        detail: A short human note — the row count, ``off``, or the error.
    """

    name: str
    ok: bool
    detail: str


class ScanLoop(Frozen):
    """The liveness of one repo's durable scan schedule (the signal stage).

    Attributes:
        repo: The ``owner/name`` slug this loop watches.
        loop: Which maintenance loop this row is for (``dependency-patch`` /
            ``security-patch``), so the two loops' scans show distinctly.
        status: The current scan workflow status (``running`` /
            ``continued_as_new`` / ``terminated`` / ``none`` / ...), lowercased.
        live: True when the loop is actively self-scheduling (running / CAN).
        last_tick: When the current scan execution started (≈ the last tick),
            or ``None`` if no scan workflow exists for the repo.
    """

    repo: str
    loop: str = "dependency-patch"
    status: str
    live: bool
    last_tick: datetime | None


class BumpRow(Frozen):
    """One proposed dependency bump, joined across GitHub and Temporal.

    GitHub is authoritative for the outcome (state / timestamps / PR); Temporal
    enriches with the model verdict and the CI reading while it is still in the
    7-day window, with the PR body as the durable fallback for the verdict.

    Attributes:
        repo: The ``owner/name`` slug.
        loop: Which loop proposed it (``dependency-patch`` /
            ``security-patch``), from the PR's loop label — so the two loops'
            records never mix.
        package: The bumped dependency.
        from_version: The version bumped from, if known.
        to_version: The version bumped to.
        state: The GitHub PR state — ``open`` / ``merged`` / ``closed``.
        verdict: The changelog verdict (``clean`` / ``risky`` / ``unknown``), or
            ``None`` when neither Temporal nor the PR body yields one.
        ci: The terminal CI reading (``passed`` / ``failed`` / ``absent`` /
            ``timed_out``), or ``None`` when only durable GitHub data remains.
        pr_number: The PR number, if a PR exists.
        pr_url: The PR URL, if a PR exists.
        opened_at: When the PR was opened.
        merged_at: When the PR was merged, if it was.
        ttm_minutes: Time-to-merge in minutes (merged - opened), if merged.
        age_hours: Age in hours for a still-open PR (now - opened), or ``None``.
        would_auto_merge: For an open PR, whether it would auto-merge under the
            advisory earned-autonomy grant (the shadow gate; nothing acts).
        held_reason: Why an open PR would *not* auto-merge, the first blocker.
        post_merge: For a merged PR, whether the merge *held* — ``held`` (the
            branch's CI stayed green after the merge), ``broke`` (it went red),
            ``reverted`` (a later commit reverted it), or ``None`` when no
            post-merge signal is recoverable (the outcome leg, coarse).
    """

    repo: str
    loop: str = "dependency-patch"
    package: str
    from_version: str | None
    to_version: str
    state: str
    verdict: str | None
    ci: str | None
    pr_number: int | None
    pr_url: str | None
    opened_at: datetime | None
    merged_at: datetime | None
    ttm_minutes: float | None
    age_hours: float | None
    would_auto_merge: bool = False
    held_reason: str | None = None
    post_merge: str | None = None


class ClassGate(Frozen):
    """The earned-autonomy standing of one (repo, loop) class — advisory only.

    The MHE economics of approval (§3.6) made legible: a class earns its gate
    move with a high enough approval rate over enough recently-decided PRs,
    and the budget framing shows what moving the gate would reclaim.

    Attributes:
        repo: The ``owner/name`` slug.
        loop: The loop this class is for.
        decided: PRs decided (merged or closed) in the recent window.
        merged: How many of those were merged.
        merge_rate: ``merged / decided``, or ``None`` if none decided.
        earned: Whether the class has earned its gate move under the policy.
        blocker: Why it has not, if it has not (else ``None``).
        approvals_per_week: The steward approvals this class costs now
            (merges per week over the window) — the current budget draw.
        reclaim_per_week: How many of those a gate move would auto-merge
            (the clean-and-green ones), i.e. the budget reclaimed — ``0`` until
            the class is ``earned``, since an un-earned class reclaims nothing.
        window_days: The look-back window the figures cover.
    """

    repo: str
    loop: str
    decided: int
    merged: int
    merge_rate: float | None
    earned: bool
    blocker: str | None
    approvals_per_week: float
    reclaim_per_week: float
    window_days: int


class Failure(Frozen):
    """A bump loop that did not close — the honest friction signal.

    Attributes:
        workflow_id: The Temporal workflow id (encodes repo/package/target).
        kind: ``terminated`` or ``failed``.
        reason: The human-readable termination/failure reason, if recovered.
        when: When the workflow closed, if known.
    """

    workflow_id: str
    kind: str
    reason: str | None
    when: datetime | None


class ActivityStat(Frozen):
    """Latency of one activity stage, from traces (run-telemetry enrichment).

    Attributes:
        name: The activity name (``scan_candidates``, ``open_pull_request``).
        count: How many executions in the window.
        avg_ms: Mean duration in milliseconds.
        max_ms: Max duration in milliseconds.
    """

    name: str
    count: int
    avg_ms: float
    max_ms: float


class RunTelemetry(Frozen):
    """Trace-derived run telemetry from ClickHouse, or an unavailable marker.

    Attributes:
        available: True when ClickHouse answered with froot traces.
        total_spans: Total froot spans in the window.
        error_spans: Spans that ended in an error.
        last_activity: The most recent froot span timestamp.
        window_days: The look-back window the figures cover.
        activities: Per-stage latency rows.
    """

    available: bool
    total_spans: int
    error_spans: int
    last_activity: datetime | None
    window_days: int
    activities: tuple[ActivityStat, ...]


class TrackRecord(Frozen):
    """The reputation headline, derived from GitHub PR outcomes.

    Attributes:
        opened: Total bumps froot has proposed.
        merged: How many a human merged.
        closed_unmerged: How many were closed without merging.
        open_now: How many are still awaiting a decision.
        merge_rate: ``merged / (merged + closed_unmerged)``, or ``None`` if none
            have been decided yet.
        median_ttm_minutes: Median time-to-merge across merged PRs, or ``None``.
    """

    opened: int
    merged: int
    closed_unmerged: int
    open_now: int
    merge_rate: float | None
    median_ttm_minutes: float | None


class Verification(Frozen):
    """The CI-oracle breakdown — kept honest about whether an oracle existed.

    Attributes:
        passed: Bumps whose CI went green.
        failed: Bumps whose CI went red.
        absent: Bumps where no CI check existed (no oracle).
        timed_out: Bumps where froot stopped waiting on CI.
        unknown: Bumps with no recoverable CI reading (aged out of Temporal).
        oracle_existed: Bumps where a real oracle reported (passed + failed).
        with_reading: Bumps with any CI reading at all (excludes ``unknown``).
    """

    passed: int
    failed: int
    absent: int
    timed_out: int
    unknown: int
    oracle_existed: int
    with_reading: int


class Reliability(Frozen):
    """Did the merges *hold*? — the post-merge outcome leg (coarse, low-recall).

    A merge is not the same as a success: the success leg is whether the merge
    *held* once it landed. This breaks recent merges into held / broke /
    reverted, with the honest caveat that it sees only what the default branch's
    CI and git-reverts reveal — a manual or bundled revert is invisible, so the
    defect rate is a *floor*, not the truth. It is the natural-traffic bearing
    the adversarial canary leg exercises.

    Attributes:
        held: Merges whose branch CI stayed green after the merge.
        broke: Merges whose branch CI went red after the merge.
        reverted: Merges a later commit git-reverted (the minority that are).
        unverified: Merges with no recoverable post-merge signal (no branch
            oracle, or aged past the commit window) — never counted as held.
        determined: ``held + broke + reverted`` — merges actually classified.
        defect_rate: ``(broke + reverted) / determined``, or ``None`` if none
            were determined. A floor on the true defect rate, by construction.
        window_days: The look-back window over merges considered.
    """

    held: int
    broke: int
    reverted: int
    unverified: int
    determined: int
    defect_rate: float | None
    window_days: int


class Probes(Frozen):
    """Adversarial canary probes — does the guardrail still bite? (§2.11).

    A canary is a deliberately-bad bump planted to test the guardrail; a healthy
    loop must refuse to merge it. These counts are kept **strictly apart** from
    the genuine track record and defect rate — a synthetic failure must never
    pollute the real bearings — and shown on their own. ``escaped > 0`` is the
    alarm: a known-bad bump that landed means the guardrail has a hole.

    Attributes:
        caught: Probes the guardrail refused (closed, or never landed).
        escaped: Probes that merged anyway — a guardrail hole (should be 0).
        pending: Probes still in flight (open, no verdict yet).
        total: All canary probes seen.
    """

    caught: int
    escaped: int
    pending: int
    total: int


class Judgment(Frozen):
    """The model's changelog-verdict mix and its calibration against CI.

    Attributes:
        clean: Verdicts of ``clean``.
        risky: Verdicts of ``risky``.
        unknown: Verdicts of ``unknown``.
        none: Bumps with no recoverable verdict.
        clean_but_failed: ``clean`` verdicts whose CI failed (mis-judged).
        flagged_but_passed: ``risky``/``unknown`` verdicts whose CI passed.
    """

    clean: int
    risky: int
    unknown: int
    none: int
    clean_but_failed: int
    flagged_but_passed: int


class ReviewLoop(Frozen):
    """Liveness of one repo's determinism-review loop (the transitive ring).

    Attributes:
        repo: The ``owner/name`` slug this loop reviews.
        status: The review workflow status (``running`` /
            ``continued_as_new`` / ``terminated`` / ...), lowercased.
        live: True when the loop is actively self-scheduling.
        last_tick: When the current review execution started (≈ the last tick),
            or ``None`` if no review workflow exists for the repo.
    """

    repo: str
    status: str
    live: bool
    last_tick: datetime | None


class ReviewRow(Frozen):
    """One per-PR determinism review, from its ``PrReviewWorkflow`` result.

    Attributes:
        repo: The ``owner/name`` slug the PR belongs to.
        pr_number: The reviewed PR number, if known.
        pr_url: The PR's web URL, if it can be formed.
        head_sha: The head commit the review ran against.
        findings: How many transitive hazards the review surfaced.
        rules: The distinct banned calls flagged (``datetime.datetime.now``…).
        comment_url: The advisory comment's URL, if one was posted.
        status: The review workflow status (``completed`` / ``running`` / ...).
        reviewed_at: When the review closed, or started if still running.
    """

    repo: str
    pr_number: int | None
    pr_url: str | None
    head_sha: str | None
    findings: int
    rules: tuple[str, ...]
    comment_url: str | None
    status: str
    reviewed_at: datetime | None


class ReviewRecord(Frozen):
    """The determinism reviewer's headline, derived from completed reviews.

    The hazard-resolved rate (was a flagged hazard gone on a later commit?) is
    a later addition — it needs accumulated cross-commit history, so it is not
    here yet.

    Attributes:
        reviewed: Completed per-PR reviews in the recent window.
        flagged: Reviews that surfaced at least one hazard.
        clean: Reviews that surfaced none.
        hazards: Total hazards surfaced across all reviews.
        repos_covered: Distinct repos with a live review loop.
    """

    reviewed: int
    flagged: int
    clean: int
    hazards: int
    repos_covered: int


class DashboardModel(Frozen):
    """The whole 10,000ft view, fully derived and ready to render.

    Attributes:
        generated_at: When this view was assembled (UTC).
        repos_configured: The repos froot is pointed at (``FROOT_REPOS``).
        scan_interval_seconds: The configured gap between scan ticks.
        sources: Per-source health for this request.
        scan_loops: Liveness of each repo's scan schedule.
        track_record: The reputation headline.
        class_gates: The earned-autonomy standing per (repo, loop) — advisory.
        verification: The CI-oracle breakdown.
        reliability: Did the merges hold post-merge (the outcome leg, coarse).
        probes: Adversarial canary results, kept apart from the real bearings.
        judgment: The model-verdict mix and calibration.
        gate: Open PRs awaiting a human, the freshest last.
        bumps: Every proposed bump, newest first (the detail behind the stats).
        failures: Bump loops that did not close.
        review_interval_seconds: The configured gap between review poll ticks.
        review_loops: Liveness of each Temporal repo's determinism-review loop.
        review_record: The determinism reviewer's headline.
        reviews: Every per-PR determinism review, newest first.
        telemetry: Trace-derived run telemetry (best-effort).
    """

    generated_at: datetime
    repos_configured: tuple[str, ...]
    scan_interval_seconds: int
    sources: tuple[SourceHealth, ...]
    scan_loops: tuple[ScanLoop, ...]
    track_record: TrackRecord
    class_gates: tuple[ClassGate, ...]
    verification: Verification
    reliability: Reliability
    probes: Probes
    judgment: Judgment
    gate: tuple[BumpRow, ...]
    bumps: tuple[BumpRow, ...]
    failures: tuple[Failure, ...]
    review_interval_seconds: int
    review_loops: tuple[ReviewLoop, ...]
    review_record: ReviewRecord
    reviews: tuple[ReviewRow, ...]
    telemetry: RunTelemetry
