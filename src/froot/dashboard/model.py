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
        would_auto_merge: For an open PR, whether it meets the earned-autonomy
            grant — the loop's actual merge decision on an allowlisted repo, the
            advisory shadow-gate verdict everywhere else (the default).
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
    # The judgment environment (judge-model slug) the PR was opened under, or
    # ``None`` if unstamped; the gate counts only the current env (§3.7).
    env: str | None = None


class ClassGate(Frozen):
    """The earned-autonomy standing of one (repo, loop) class.

    The MHE economics of approval (§3.6) made legible: a class earns its gate
    move with a high enough approval rate over enough recently-decided PRs,
    and the budget framing shows what moving the gate would reclaim.

    Attributes:
        repo: The ``owner/name`` slug.
        loop: The loop this class is for.
        decided: PRs decided (merged or closed) in the recent window.
        merged: How many of those were merged.
        merge_rate: ``merged / decided``, or ``None`` if none decided.
        determined: Merges with a confirmed post-merge outcome in the window
            (held / broke / reverted) — the defect bearing's evidence.
        defects: Of those, how many broke the branch or were reverted.
        defect_rate: ``defects / determined``, or ``None`` if none determined —
            the second, independent bearing the gate triangulates against.
        prior_env_decided: Decided PRs in the window earned under a *different*
            (or no) environment — they no longer count, so this figure makes a
            model-change reset legible rather than a mysterious drop to zero.
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
    determined: int
    defects: int
    defect_rate: float | None
    prior_env_decided: int
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


class AdvisoryLoop(Frozen):
    """Liveness of one repo's advisory loop (the emit-signal family).

    The advisory family (determinism-review, a11y-review) scans open PRs and
    leaves one decaying comment; this is the per-repo loop's heartbeat, the
    same shape every advisory loop reports.

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


class AdvisoryRow(Frozen):
    """One per-PR advisory review, from its per-PR workflow's result.

    Attributes:
        repo: The ``owner/name`` slug the PR belongs to.
        pr_number: The reviewed PR number, if known.
        pr_url: The PR's web URL, if it can be formed.
        head_sha: The head commit the review ran against.
        findings: How many findings the review surfaced.
        detail: The distinct finding kinds flagged — banned calls for the
            determinism loop (``datetime.datetime.now``…), gap kinds for a11y
            (``missing-alt``…).
        comment_url: The advisory comment's URL, if one was posted.
        status: The review workflow status (``completed`` / ``running`` / ...).
        reviewed_at: When the review closed, or started if still running.
    """

    repo: str
    pr_number: int | None
    pr_url: str | None
    head_sha: str | None
    findings: int
    detail: tuple[str, ...]
    comment_url: str | None
    status: str
    reviewed_at: datetime | None


class AdvisoryRecord(Frozen):
    """One advisory loop's headline, derived from its completed reviews.

    Attributes:
        reviewed: Completed per-PR reviews in the recent window.
        flagged: Reviews that surfaced at least one finding.
        clean: Reviews that surfaced none.
        findings: Total findings surfaced across all reviews.
        repos_covered: Distinct repos with a live loop.
    """

    reviewed: int
    flagged: int
    clean: int
    findings: int
    repos_covered: int


class AdvisoryView(Frozen):
    """One advisory loop's complete tab — the same treatment for every loop.

    The acting family's :class:`LoopView`, mirrored for the emit-signal family.
    The presentation (icon, title) is the loop's registered spec, derived once
    in the read-model, so a new advisory loop's tab appears with no renderer
    change. Built by partitioning the advisory executions by loop and running
    the same aggregates for each.

    Attributes:
        loop: The loop key (``determinism-review`` / ``a11y-review``).
        icon: The tab's icon key, from the loop's registered spec.
        title: The tab/panel title, from the loop's registered spec.
        interval_seconds: This loop's poll cadence (telemetry-in-context).
        loops: Liveness of this loop's per-repo review schedules.
        record: This loop's headline over completed reviews.
        rows: This loop's per-PR reviews, newest first.
    """

    loop: str
    icon: str
    title: str
    interval_seconds: int
    loops: tuple[AdvisoryLoop, ...]
    record: AdvisoryRecord
    rows: tuple[AdvisoryRow, ...]


class LoopView(Frozen):
    """One bump loop's complete standing — the same treatment for every loop.

    dependency-patch and security-patch are distinct trust classes (§3.9) that
    never share a record, so each gets its own self-contained view: its gate and
    four bearings, its queue, its detail. Built by partitioning the bump rows by
    loop and running the same aggregates the combined view uses, so a loop's tab
    is exactly the combined dashboard scoped to that one loop.

    Attributes:
        loop: The loop key (``dependency-patch`` / ``security-patch``).
        title: The human title for the tab.
        icon: The tab's icon key, from the loop's registered spec.
        scan_loops: Liveness of this loop's per-repo scan schedules.
        scan_interval_seconds: This loop's scan cadence (telemetry-in-context).
        track_record: This loop's reputation headline.
        class_gates: This loop's per-repo earned-autonomy standing (the gate).
        verification: This loop's CI-oracle breakdown.
        reliability: This loop's post-merge outcome leg.
        probes: This loop's adversarial canary tally.
        judgment: This loop's model-verdict mix and calibration.
        gate: This loop's open PRs awaiting a human, freshest last.
        bumps: This loop's proposed bumps, newest first.
        failures: This loop's bump loops that did not close.
    """

    loop: str
    title: str
    icon: str
    scan_loops: tuple[ScanLoop, ...]
    scan_interval_seconds: int
    track_record: TrackRecord
    class_gates: tuple[ClassGate, ...]
    verification: Verification
    reliability: Reliability
    probes: Probes
    judgment: Judgment
    gate: tuple[BumpRow, ...]
    bumps: tuple[BumpRow, ...]
    failures: tuple[Failure, ...]


class DashboardModel(Frozen):
    """The whole 10,000ft view, fully derived and ready to render.

    Attributes:
        generated_at: When this view was assembled (UTC).
        repos_configured: The repos froot is pointed at (``FROOT_REPOS``).
        scan_interval_seconds: The configured gap between scan ticks.
        sources: Per-source health for this request.
        scan_loops: Liveness of each repo's scan schedule.
        track_record: The reputation headline.
        class_gates: The earned-autonomy standing per (repo, loop) — the gate.
        verification: The CI-oracle breakdown.
        reliability: Did the merges hold post-merge (the outcome leg, coarse).
        probes: Adversarial canary results, kept apart from the real bearings.
        judgment: The model-verdict mix and calibration.
        gate: Open PRs awaiting a human, the freshest last.
        bumps: Every proposed bump, newest first (the detail behind the stats).
        failures: Bump loops that did not close.
        advisory: One self-contained view per advisory loop — the emit-signal
            tabs (determinism-review, a11y-review), each with its own
            heartbeat, headline, and per-PR reviews. Derived from the registry,
            so a new advisory loop is one more view here.
        telemetry: Trace-derived run telemetry (best-effort).
        bump_loops: One self-contained view per bump loop — the per-loop tabs.
            The top-level bump aggregates above are the combined ("all loops")
            view; these split it per trust class.
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
    advisory: tuple[AdvisoryView, ...]
    telemetry: RunTelemetry
    bump_loops: tuple[LoopView, ...] = ()
