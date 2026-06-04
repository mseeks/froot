"""Assemble the dashboard view — pure, from the three readers' output.

This is the reputation read-model proper: it joins GitHub (authoritative
outcomes) to Temporal (recent verdict + CI reading) by PR number, derives the
MHE-framed aggregates (track record, verification, judgment, the approval
queue), and returns a fully-computed
:class:`~froot.dashboard.model.DashboardModel` the renderer just projects. No
I/O and no clock of its own — ``now`` is passed in — so every figure on the
page is unit-tested apart from the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.dashboard.model import (
    BumpRow,
    DashboardModel,
    Failure,
    Judgment,
    ReviewLoop,
    ReviewRecord,
    ReviewRow,
    RunTelemetry,
    ScanLoop,
    SourceHealth,
    TrackRecord,
    Verification,
)
from froot.domain.repo import RepoRef, TargetRepo
from froot.policy.naming import review_workflow_id, scan_workflow_id
from froot.result import Ok

if TYPE_CHECKING:
    from datetime import datetime

    from froot.dashboard.github_source import GithubPr
    from froot.dashboard.temporal_source import (
        BumpExecution,
        PrReviewExecution,
        ReviewExecution,
        ScanExecution,
    )

_LIVE_STATUSES = frozenset({"running", "continued_as_new"})
# Every way a bump can end without closing cleanly — all belong in the honest
# Failures panel, not silently dropped.
_FAILURE_STATUSES = frozenset({"terminated", "failed", "canceled", "timed_out"})


def _median(values: list[float]) -> float | None:
    """The median of ``values``, or ``None`` if empty (pure)."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _scan_id(repo: str) -> str | None:
    """The deterministic scan-loop id for an ``owner/name`` slug, if valid."""
    match RepoRef.parse(repo):
        case Ok(ref):
            return scan_workflow_id(TargetRepo(repo=ref))
        case _:
            return None


def _scan_loops(
    repos: tuple[str, ...], scans: tuple[ScanExecution, ...]
) -> tuple[ScanLoop, ...]:
    """One liveness row per configured repo (latest execution wins)."""
    by_id: dict[str, ScanExecution] = {}
    for scan in scans:
        current = by_id.get(scan.workflow_id)
        if current is None or _newer(scan.start, current.start):
            by_id[scan.workflow_id] = scan
    loops: list[ScanLoop] = []
    for repo in repos:
        scan_id = _scan_id(repo)
        execution = by_id.get(scan_id) if scan_id is not None else None
        if execution is None:
            loops.append(
                ScanLoop(repo=repo, status="none", live=False, last_tick=None)
            )
        else:
            loops.append(
                ScanLoop(
                    repo=repo,
                    status=execution.status,
                    live=execution.status in _LIVE_STATUSES,
                    last_tick=execution.start,
                )
            )
    return tuple(loops)


def _newer(a: datetime | None, b: datetime | None) -> bool:
    """True if ``a`` is a later instant than ``b`` (``None`` is oldest)."""
    if a is None:
        return False
    if b is None:
        return True
    return a > b


def _bump_rows(
    now: datetime,
    prs: tuple[GithubPr, ...],
    bumps: tuple[BumpExecution, ...],
) -> tuple[BumpRow, ...]:
    """Join GitHub PRs (authoritative) to Temporal outcomes by PR number."""
    # Keyed on (repo, PR number), not the bare number: Temporal lists every
    # repo's bumps in the namespace, so two repos that each have a PR #N would
    # otherwise cross-attribute one's verdict/CI onto the other's row.
    by_pr: dict[tuple[str, int], BumpExecution] = {
        (bump.repo, bump.pr_number): bump
        for bump in bumps
        if bump.repo is not None and bump.pr_number is not None
    }
    rows: list[BumpRow] = []
    for pr in prs:
        execution = by_pr.get((pr.repo, pr.number))
        verdict = (execution.verdict if execution else None) or pr.verdict
        ci = execution.ci if execution else None
        ttm = _minutes_between(pr.opened_at, pr.merged_at)
        age = _hours_between(pr.opened_at, now) if pr.state == "open" else None
        rows.append(
            BumpRow(
                repo=pr.repo,
                package=pr.package or "?",
                from_version=pr.from_version,
                to_version=pr.to_version or "?",
                state=pr.state,
                verdict=verdict,
                ci=ci,
                pr_number=pr.number,
                pr_url=pr.url,
                opened_at=pr.opened_at,
                merged_at=pr.merged_at,
                ttm_minutes=ttm,
                age_hours=age,
            )
        )
    rows.sort(key=_opened_sort_key, reverse=True)
    return tuple(rows)


def _opened_sort_key(row: BumpRow) -> float:
    """Sort key putting the most recently opened PR first (unknown last)."""
    return row.opened_at.timestamp() if row.opened_at is not None else 0.0


def _minutes_between(
    start: datetime | None, end: datetime | None
) -> float | None:
    """Whole-ish minutes from ``start`` to ``end``, or ``None``."""
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60, 1)


def _hours_between(
    start: datetime | None, end: datetime | None
) -> float | None:
    """Hours from ``start`` to ``end``, or ``None``."""
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600, 1)


def _track_record(rows: tuple[BumpRow, ...]) -> TrackRecord:
    """Counts, merge rate, and median time-to-merge from the bump rows."""
    merged = [r for r in rows if r.state == "merged"]
    closed = sum(1 for r in rows if r.state == "closed")
    open_now = sum(1 for r in rows if r.state == "open")
    decided = len(merged) + closed
    ttms = [r.ttm_minutes for r in merged if r.ttm_minutes is not None]
    return TrackRecord(
        opened=len(rows),
        merged=len(merged),
        closed_unmerged=closed,
        open_now=open_now,
        merge_rate=(len(merged) / decided) if decided else None,
        median_ttm_minutes=_median(ttms),
    )


def _verification(rows: tuple[BumpRow, ...]) -> Verification:
    """The CI-oracle breakdown, keeping ``absent`` distinct from a failure."""
    passed = sum(1 for r in rows if r.ci == "passed")
    failed = sum(1 for r in rows if r.ci == "failed")
    absent = sum(1 for r in rows if r.ci == "absent")
    timed_out = sum(1 for r in rows if r.ci == "timed_out")
    unknown = sum(1 for r in rows if r.ci is None)
    return Verification(
        passed=passed,
        failed=failed,
        absent=absent,
        timed_out=timed_out,
        unknown=unknown,
        oracle_existed=passed + failed,
        with_reading=passed + failed + absent + timed_out,
    )


def _judgment(rows: tuple[BumpRow, ...]) -> Judgment:
    """The verdict mix plus the two calibration cells worth flagging."""
    clean = sum(1 for r in rows if r.verdict == "clean")
    risky = sum(1 for r in rows if r.verdict == "risky")
    unknown = sum(1 for r in rows if r.verdict == "unknown")
    none = sum(1 for r in rows if r.verdict is None)
    clean_but_failed = sum(
        1 for r in rows if r.verdict == "clean" and r.ci == "failed"
    )
    flagged_but_passed = sum(
        1
        for r in rows
        if r.verdict in ("risky", "unknown") and r.ci == "passed"
    )
    return Judgment(
        clean=clean,
        risky=risky,
        unknown=unknown,
        none=none,
        clean_but_failed=clean_but_failed,
        flagged_but_passed=flagged_but_passed,
    )


def _gate(rows: tuple[BumpRow, ...]) -> tuple[BumpRow, ...]:
    """Open PRs awaiting a human, the most-aged first (the freshest last)."""
    open_rows = [r for r in rows if r.state == "open"]
    open_rows.sort(
        key=lambda r: r.age_hours if r.age_hours is not None else 0.0,
        reverse=True,
    )
    return tuple(open_rows)


def _failures(bumps: tuple[BumpExecution, ...]) -> tuple[Failure, ...]:
    """Bump loops that did not close, newest first."""
    failures = [
        Failure(
            workflow_id=bump.workflow_id,
            kind=bump.status,
            reason=bump.reason,
            when=bump.close,
        )
        for bump in bumps
        if bump.status in _FAILURE_STATUSES
    ]
    failures.sort(
        key=lambda f: f.when.timestamp() if f.when is not None else 0.0,
        reverse=True,
    )
    return tuple(failures)


def _review_id(repo: str) -> str | None:
    """The deterministic review-loop id for an ``owner/name`` slug, if valid."""
    match RepoRef.parse(repo):
        case Ok(ref):
            return review_workflow_id(TargetRepo(repo=ref))
        case _:
            return None


def _pr_review_prefix(repo: str) -> str | None:
    """The id prefix every per-PR review of ``repo`` shares (the join key)."""
    review_id = _review_id(repo)
    if review_id is None:
        return None
    # froot-review-<slug> -> froot-pr-review-<slug>- ; the pr/sha tail follows.
    return "froot-pr-review-" + review_id.removeprefix("froot-review-") + "-"


def _attribute_repo(workflow_id: str, repos: tuple[str, ...]) -> str | None:
    """The configured repo a per-PR-review id belongs to (longest prefix)."""
    best: str | None = None
    best_len = -1
    for repo in repos:
        prefix = _pr_review_prefix(repo)
        if prefix and workflow_id.startswith(prefix) and len(prefix) > best_len:
            best, best_len = repo, len(prefix)
    return best


def _review_loops(
    repos: tuple[str, ...], reviews: tuple[ReviewExecution, ...]
) -> tuple[ReviewLoop, ...]:
    """One liveness row per repo that actually has a review loop.

    Reviews are scoped to the Temporal repos, so a configured npm repo with no
    review loop is omitted rather than shown as a dead one.
    """
    by_id: dict[str, ReviewExecution] = {}
    for review in reviews:
        current = by_id.get(review.workflow_id)
        if current is None or _newer(review.start, current.start):
            by_id[review.workflow_id] = review
    loops: list[ReviewLoop] = []
    for repo in repos:
        review_id = _review_id(repo)
        execution = by_id.get(review_id) if review_id is not None else None
        if execution is None:
            continue
        loops.append(
            ReviewLoop(
                repo=repo,
                status=execution.status,
                live=execution.status in _LIVE_STATUSES,
                last_tick=execution.start,
            )
        )
    return tuple(loops)


def _review_rows(
    pr_reviews: tuple[PrReviewExecution, ...], repos: tuple[str, ...]
) -> tuple[ReviewRow, ...]:
    """Project each per-PR review into a row, newest review first."""
    rows: list[ReviewRow] = []
    for execution in pr_reviews:
        repo = _attribute_repo(execution.workflow_id, repos)
        pr_url = (
            f"https://github.com/{repo}/pull/{execution.pr_number}"
            if repo is not None and execution.pr_number is not None
            else None
        )
        rows.append(
            ReviewRow(
                repo=repo or "?",
                pr_number=execution.pr_number,
                pr_url=pr_url,
                head_sha=execution.head_sha,
                findings=execution.findings,
                rules=execution.rules,
                comment_url=execution.comment_url,
                status=execution.status,
                reviewed_at=execution.close or execution.start,
            )
        )
    rows.sort(
        key=lambda r: r.reviewed_at.timestamp() if r.reviewed_at else 0.0,
        reverse=True,
    )
    return tuple(rows)


def _review_record(
    loops: tuple[ReviewLoop, ...], rows: tuple[ReviewRow, ...]
) -> ReviewRecord:
    """Counts over the completed reviews (resolved-rate is a later loop)."""
    completed = [r for r in rows if r.status == "completed"]
    flagged = sum(1 for r in completed if r.findings > 0)
    hazards = sum(r.findings for r in completed)
    return ReviewRecord(
        reviewed=len(completed),
        flagged=flagged,
        clean=len(completed) - flagged,
        hazards=hazards,
        repos_covered=len(loops),
    )


def _sources(
    github_error: str | None,
    github_count: int,
    temporal_error: str | None,
    temporal_count: int,
    telemetry: RunTelemetry,
    clickhouse_error: str | None,
) -> tuple[SourceHealth, ...]:
    """Per-source health for the header strip."""
    clickhouse_ok = clickhouse_error is None
    if clickhouse_error == "off":
        clickhouse_detail = "off"
    elif clickhouse_error is not None:
        clickhouse_detail = clickhouse_error
    else:
        spans = telemetry.total_spans
        clickhouse_detail = f"{spans} spans / {telemetry.window_days}d"
    return (
        SourceHealth(
            name="github",
            ok=github_error is None,
            detail=github_error or f"{github_count} PRs",
        ),
        SourceHealth(
            name="temporal",
            ok=temporal_error is None,
            detail=temporal_error or f"{temporal_count} workflows",
        ),
        SourceHealth(
            name="clickhouse", ok=clickhouse_ok, detail=clickhouse_detail
        ),
    )


def assemble(
    *,
    now: datetime,
    repos: tuple[str, ...],
    scan_interval_seconds: int,
    review_interval_seconds: int,
    github: tuple[tuple[GithubPr, ...], str | None],
    temporal: tuple[
        tuple[
            tuple[ScanExecution, ...],
            tuple[BumpExecution, ...],
            tuple[ReviewExecution, ...],
            tuple[PrReviewExecution, ...],
        ],
        str | None,
    ],
    telemetry: tuple[RunTelemetry, str | None],
) -> DashboardModel:
    """Build the whole view from the readers' ``(data, error)`` outputs."""
    prs, github_error = github
    (scans, bumps, reviews, pr_reviews), temporal_error = temporal
    run_telemetry, clickhouse_error = telemetry

    rows = _bump_rows(now, prs, bumps)
    review_loops = _review_loops(repos, reviews)
    review_rows = _review_rows(pr_reviews, repos)
    return DashboardModel(
        generated_at=now,
        repos_configured=repos,
        scan_interval_seconds=scan_interval_seconds,
        sources=_sources(
            github_error,
            len(prs),
            temporal_error,
            len(scans) + len(bumps) + len(reviews) + len(pr_reviews),
            run_telemetry,
            clickhouse_error,
        ),
        scan_loops=_scan_loops(repos, scans),
        track_record=_track_record(rows),
        verification=_verification(rows),
        judgment=_judgment(rows),
        gate=_gate(rows),
        bumps=rows,
        failures=_failures(bumps),
        review_interval_seconds=review_interval_seconds,
        review_loops=review_loops,
        review_record=_review_record(review_loops, review_rows),
        reviews=review_rows,
        telemetry=run_telemetry,
    )
