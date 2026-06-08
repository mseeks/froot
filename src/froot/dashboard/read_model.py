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
    A11yLoop,
    A11yRecord,
    A11yRow,
    BumpRow,
    ClassGate,
    DashboardModel,
    Failure,
    Judgment,
    LoopView,
    Probes,
    Reliability,
    ReviewLoop,
    ReviewRecord,
    ReviewRow,
    RunTelemetry,
    ScanLoop,
    SourceHealth,
    TrackRecord,
    Verification,
)
from froot.domain.loop import Loop
from froot.domain.repo import RepoRef, TargetRepo
from froot.loops import registry
from froot.policy.autonomy import AutonomyPolicy, class_earned, pr_autonomy
from froot.policy.canary import is_canary, score_probe
from froot.policy.naming import (
    a11y_review_workflow_id,
    review_workflow_id,
    scan_workflow_id,
)
from froot.result import Ok

if TYPE_CHECKING:
    from datetime import datetime

    from froot.dashboard.github_source import GithubPr
    from froot.dashboard.temporal_source import (
        A11yExecution,
        BumpExecution,
        PrA11yExecution,
        PrReviewExecution,
        ReviewExecution,
        ScanExecution,
    )

# The conservative fallback policy: empty allowlist, so the shadow gate holds
# everything until a caller passes a real one (built from FROOT_AUTOMERGE_*).
_DEFAULT_POLICY = AutonomyPolicy()

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


def _scan_id(repo: str, loop: Loop) -> str | None:
    """The deterministic scan-loop id for an ``owner/name`` slug + loop."""
    match RepoRef.parse(repo):
        case Ok(ref):
            return scan_workflow_id(TargetRepo(repo=ref), loop)
        case _:
            return None


def _scan_loops(
    repos: tuple[str, ...],
    loops: tuple[Loop, ...],
    scans: tuple[ScanExecution, ...],
) -> tuple[ScanLoop, ...]:
    """One liveness row per configured (repo, loop) (latest execution wins)."""
    by_id: dict[str, ScanExecution] = {}
    for scan in scans:
        current = by_id.get(scan.workflow_id)
        if current is None or _newer(scan.start, current.start):
            by_id[scan.workflow_id] = scan
    rows: list[ScanLoop] = []
    for loop in loops:
        for repo in repos:
            scan_id = _scan_id(repo, loop)
            execution = by_id.get(scan_id) if scan_id is not None else None
            if execution is None:
                rows.append(
                    ScanLoop(
                        repo=repo,
                        loop=loop.value,
                        status="none",
                        live=False,
                        last_tick=None,
                    )
                )
            else:
                rows.append(
                    ScanLoop(
                        repo=repo,
                        loop=loop.value,
                        status=execution.status,
                        live=execution.status in _LIVE_STATUSES,
                        last_tick=execution.start,
                    )
                )
    return tuple(rows)


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
    outcomes: dict[tuple[str, int], str],
) -> tuple[BumpRow, ...]:
    """Join GitHub PRs (authoritative) to Temporal outcomes by PR number.

    ``outcomes`` carries the post-merge signal (``held`` / ``broke`` /
    ``reverted`` / ``unknown``) per recently-merged ``(repo, number)``; it is
    absent for older or non-merged PRs, which leaves ``post_merge`` ``None``.
    """
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
        # A removal carries no version: show "unused" in the target column and
        # no from-version, so a dead-code row reads "left-pad -> unused" rather
        # than the bump-shaped "left-pad -> ?".
        is_removal = pr.loop == Loop.DEAD_CODE.value
        rows.append(
            BumpRow(
                repo=pr.repo,
                loop=pr.loop,
                package=pr.package or "?",
                from_version=None if is_removal else pr.from_version,
                to_version="unused" if is_removal else (pr.to_version or "?"),
                state=pr.state,
                verdict=verdict,
                ci=ci,
                pr_number=pr.number,
                pr_url=pr.url,
                opened_at=pr.opened_at,
                merged_at=pr.merged_at,
                ttm_minutes=ttm,
                age_hours=age,
                post_merge=outcomes.get((pr.repo, pr.number)),
                env=pr.env,
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


def _reliability(rows: tuple[BumpRow, ...], window_days: int) -> Reliability:
    """The post-merge outcome breakdown — did the merges hold? (coarse).

    Reads only the ``post_merge`` tag the outcome reader set: ``unknown`` means
    an in-window merge we could not classify (no branch oracle / aged out), kept
    distinct from a held one; ``None`` (older / non-merged) is not counted here.
    The defect rate is a floor — manual and bundled reverts are invisible.
    """
    held = sum(1 for r in rows if r.post_merge == "held")
    broke = sum(1 for r in rows if r.post_merge == "broke")
    reverted = sum(1 for r in rows if r.post_merge == "reverted")
    unverified = sum(1 for r in rows if r.post_merge == "unknown")
    determined = held + broke + reverted
    return Reliability(
        held=held,
        broke=broke,
        reverted=reverted,
        unverified=unverified,
        determined=determined,
        defect_rate=((broke + reverted) / determined) if determined else None,
        window_days=window_days,
    )


def _probes(canary_rows: tuple[BumpRow, ...]) -> Probes:
    """Tally the adversarial canary probes — caught / escaped / pending.

    These rows are the synthetic bad bumps; they are scored on the strict bar
    (a canary must never merge) and kept out of every genuine bearing.
    """
    scored = [score_probe(r.state) for r in canary_rows]
    return Probes(
        caught=sum(1 for s in scored if s == "caught"),
        escaped=sum(1 for s in scored if s == "escaped"),
        pending=sum(1 for s in scored if s == "pending"),
        total=len(scored),
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


def _decided_at(row: BumpRow) -> datetime | None:
    """When a decided PR was decided — merge time, else open time as a proxy.

    A merged PR has an exact merge instant; a closed-unmerged one does not (the
    issues list froot reads carries no close timestamp), so it is windowed by
    when it opened. The proxy only nudges a closed PR's window membership by its
    own lifetime — close enough for a recency window measured in months.
    """
    return row.merged_at or row.opened_at


def _within(when: datetime | None, now: datetime, window_days: int) -> bool:
    """Whether ``when`` falls within ``window_days`` before ``now`` (pure)."""
    if when is None:
        return False
    return (now - when).total_seconds() <= window_days * 86400.0


def _class_gates(
    now: datetime,
    rows: tuple[BumpRow, ...],
    repos: tuple[str, ...],
    loops: tuple[Loop, ...],
    policy: AutonomyPolicy,
    environment: str,
) -> tuple[ClassGate, ...]:
    """The earned-autonomy standing of each (repo, loop) class.

    Counts only PRs *decided within the window* — trust is recent, not lifetime
    (§2.11) — *and* earned under the current ``environment`` (§3.7's conditional
    property): a PR opened under a different judge model no longer counts, so a
    model swap resets the class. ``prior_env_decided`` keeps that reset legible.
    The budget figures (approvals / reclaim per week) translate the record into
    the steward-time MHE meters (§3.6): what the class costs now, and what
    moving its gate would hand back.
    """
    weeks = max(policy.window_days / 7.0, 1.0)
    gates: list[ClassGate] = []
    for loop in loops:
        for repo in repos:
            in_window = [
                r
                for r in rows
                if r.repo == repo
                and r.loop == loop.value
                and r.state in ("merged", "closed")
                and _within(_decided_at(r), now, policy.window_days)
            ]
            # An empty ``environment`` means "don't filter" (none configured);
            # otherwise only PRs stamped with the current one count.
            decided_rows = [
                r for r in in_window if not environment or r.env == environment
            ]
            prior_env_decided = len(in_window) - len(decided_rows)
            merged_rows = [r for r in decided_rows if r.state == "merged"]
            decided = len(decided_rows)
            merged = len(merged_rows)
            # The post-merge defect bearing, per class (§3.8): confirmed-held
            # outcomes and how many of those went bad. Independent of the rate.
            determined = sum(
                1
                for r in merged_rows
                if r.post_merge in ("held", "broke", "reverted")
            )
            defects = sum(
                1 for r in merged_rows if r.post_merge in ("broke", "reverted")
            )
            earned, blocker = class_earned(
                decided=decided,
                merged=merged,
                determined=determined,
                defects=defects,
                policy=policy,
            )
            # Reclaim is the budget a gate *move* hands back — so it is zero
            # until the class has actually earned the move. Counting the
            # clean-and-green merges of an un-earned class would imply savings
            # the gate would refuse (every PR stays held at "class not earned").
            reclaimable = (
                sum(
                    1
                    for r in merged_rows
                    if r.verdict == "clean" and r.ci == "passed"
                )
                if earned
                else 0
            )
            gates.append(
                ClassGate(
                    repo=repo,
                    loop=loop.value,
                    decided=decided,
                    merged=merged,
                    merge_rate=(merged / decided) if decided else None,
                    determined=determined,
                    defects=defects,
                    defect_rate=(
                        (defects / determined) if determined else None
                    ),
                    prior_env_decided=prior_env_decided,
                    earned=earned,
                    blocker=blocker,
                    approvals_per_week=round(merged / weeks, 2),
                    reclaim_per_week=round(reclaimable / weeks, 2),
                    window_days=policy.window_days,
                )
            )
    return tuple(gates)


def earned_now(
    now: datetime,
    prs: tuple[GithubPr, ...],
    outcomes: dict[tuple[str, int], str],
    repo: str,
    loop: Loop,
    policy: AutonomyPolicy,
    environment: str,
) -> bool:
    """Whether one (repo, loop) class has earned its gate, from live data.

    The exact computation the dashboard's class-gate panel shows, exposed so the
    acting gate (the loop) reuses it rather than duplicating the windowing,
    environment filter, and triangulation. Pure over already-fetched data.
    """
    rows = _bump_rows(now, prs, (), outcomes)
    gates = _class_gates(now, rows, (repo,), (loop,), policy, environment)
    return any(g.earned for g in gates)


def _gate(
    rows: tuple[BumpRow, ...],
    gates: tuple[ClassGate, ...],
    policy: AutonomyPolicy,
) -> tuple[BumpRow, ...]:
    """Open PRs awaiting a human, most-aged first, each carrying a verdict.

    The verdict is the gate's: would this PR auto-merge under its class's grant
    — the loop's real decision where the repo is allowlisted, advisory (the
    shadow gate) where it is not. The reason is the grant met, or the first
    blocker to fix.
    """
    earned_by_class = {(g.repo, g.loop): (g.earned, g.blocker) for g in gates}
    open_rows = [r for r in rows if r.state == "open"]
    open_rows.sort(
        key=lambda r: r.age_hours if r.age_hours is not None else 0.0,
        reverse=True,
    )
    annotated: list[BumpRow] = []
    for row in open_rows:
        earned, blocker = earned_by_class.get(
            (row.repo, row.loop), (False, "no record for this class")
        )
        verdict = pr_autonomy(
            repo=row.repo,
            verdict=row.verdict,
            ci=row.ci,
            earned=earned,
            blocker=blocker,
            policy=policy,
        )
        annotated.append(
            row.model_copy(
                update={
                    "would_auto_merge": verdict.would_merge,
                    "held_reason": (
                        None if verdict.would_merge else verdict.reason
                    ),
                }
            )
        )
    return tuple(annotated)


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


def _loop_title(loop: Loop) -> str:
    """The human tab title for a loop key (``dependency-patch`` -> ...)."""
    return loop.value.capitalize()


def _failure_loop(workflow_id: str, loops: tuple[Loop, ...]) -> Loop | None:
    """Which loop a failed bump belongs to, from its workflow id.

    Non-default loops carry their name as an id segment
    (``froot-bump-security-patch-…``); dependency-patch is segmentless
    (``froot-bump-…``), so it is the fallback once the specific loops miss.
    """
    for loop in loops:
        if loop is not Loop.DEPENDENCY_PATCH and workflow_id.startswith(
            f"froot-bump-{loop.value}-"
        ):
            return loop
    if workflow_id.startswith("froot-bump-"):
        return next(
            (loop for loop in loops if loop is Loop.DEPENDENCY_PATCH), None
        )
    return None


def _bump_loops(
    now: datetime,
    rows: tuple[BumpRow, ...],
    canary_rows: tuple[BumpRow, ...],
    failures: tuple[Failure, ...],
    scans: tuple[ScanExecution, ...],
    repos: tuple[str, ...],
    loops: tuple[Loop, ...],
    policy: AutonomyPolicy,
    environment: str,
    scan_interval_seconds: int,
    reliability_window_days: int,
) -> tuple[LoopView, ...]:
    """One self-contained :class:`LoopView` per loop — the per-loop tabs.

    Partitions the already-computed bump rows by loop and runs the very same
    aggregates the combined view uses, so each loop's tab is the whole dashboard
    scoped to one trust class (§3.9). Failures are attributed by workflow id.
    """
    views: list[LoopView] = []
    for loop in loops:
        loop_rows = tuple(r for r in rows if r.loop == loop.value)
        loop_canary = tuple(r for r in canary_rows if r.loop == loop.value)
        loop_gates = _class_gates(
            now, loop_rows, repos, (loop,), policy, environment
        )
        loop_failures = tuple(
            f for f in failures if _failure_loop(f.workflow_id, loops) is loop
        )
        views.append(
            LoopView(
                loop=loop.value,
                title=_loop_title(loop),
                icon=registry.get(loop).dashboard_icon,
                scan_loops=_scan_loops(repos, (loop,), scans),
                scan_interval_seconds=scan_interval_seconds,
                track_record=_track_record(loop_rows),
                class_gates=loop_gates,
                verification=_verification(loop_rows),
                reliability=_reliability(loop_rows, reliability_window_days),
                probes=_probes(loop_canary),
                judgment=_judgment(loop_rows),
                gate=_gate(loop_rows, loop_gates, policy),
                bumps=loop_rows,
                failures=loop_failures,
            )
        )
    return tuple(views)


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


def _a11y_id(repo: str) -> str | None:
    """The deterministic a11y-loop id for an ``owner/name`` slug, if valid."""
    match RepoRef.parse(repo):
        case Ok(ref):
            return a11y_review_workflow_id(TargetRepo(repo=ref))
        case _:
            return None


def _pr_a11y_prefix(repo: str) -> str | None:
    """The id prefix every per-PR a11y review of ``repo`` shares (join key)."""
    a11y_id = _a11y_id(repo)
    if a11y_id is None:
        return None
    # froot-a11y-<slug> -> froot-pr-a11y-<slug>- ; the pr/sha tail follows.
    return "froot-pr-a11y-" + a11y_id.removeprefix("froot-a11y-") + "-"


def _attribute_a11y_repo(
    workflow_id: str, repos: tuple[str, ...]
) -> str | None:
    """The configured repo a per-PR-a11y id belongs to (longest prefix)."""
    best: str | None = None
    best_len = -1
    for repo in repos:
        prefix = _pr_a11y_prefix(repo)
        if prefix and workflow_id.startswith(prefix) and len(prefix) > best_len:
            best, best_len = repo, len(prefix)
    return best


def _a11y_loops(
    repos: tuple[str, ...], a11y_reviews: tuple[A11yExecution, ...]
) -> tuple[A11yLoop, ...]:
    """One liveness row per repo that actually has an a11y loop.

    Scoped to the Temporal repos, so a configured repo with no a11y loop is
    omitted rather than shown as a dead one.
    """
    by_id: dict[str, A11yExecution] = {}
    for review in a11y_reviews:
        current = by_id.get(review.workflow_id)
        if current is None or _newer(review.start, current.start):
            by_id[review.workflow_id] = review
    loops: list[A11yLoop] = []
    for repo in repos:
        a11y_id = _a11y_id(repo)
        execution = by_id.get(a11y_id) if a11y_id is not None else None
        if execution is None:
            continue
        loops.append(
            A11yLoop(
                repo=repo,
                status=execution.status,
                live=execution.status in _LIVE_STATUSES,
                last_tick=execution.start,
            )
        )
    return tuple(loops)


def _a11y_rows(
    pr_a11y_reviews: tuple[PrA11yExecution, ...], repos: tuple[str, ...]
) -> tuple[A11yRow, ...]:
    """Project each per-PR a11y review into a row, newest review first."""
    rows: list[A11yRow] = []
    for execution in pr_a11y_reviews:
        repo = _attribute_a11y_repo(execution.workflow_id, repos)
        pr_url = (
            f"https://github.com/{repo}/pull/{execution.pr_number}"
            if repo is not None and execution.pr_number is not None
            else None
        )
        rows.append(
            A11yRow(
                repo=repo or "?",
                pr_number=execution.pr_number,
                pr_url=pr_url,
                head_sha=execution.head_sha,
                findings=execution.findings,
                kinds=execution.kinds,
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


def _a11y_record(
    loops: tuple[A11yLoop, ...], rows: tuple[A11yRow, ...]
) -> A11yRecord:
    """Counts over the completed a11y reviews."""
    completed = [r for r in rows if r.status == "completed"]
    flagged = sum(1 for r in completed if r.findings > 0)
    issues = sum(r.findings for r in completed)
    return A11yRecord(
        reviewed=len(completed),
        flagged=flagged,
        clean=len(completed) - flagged,
        issues=issues,
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
    loops: tuple[Loop, ...] = (Loop.DEPENDENCY_PATCH,),
    policy: AutonomyPolicy = _DEFAULT_POLICY,
    scan_interval_seconds: int,
    review_interval_seconds: int,
    a11y_interval_seconds: int,
    github: tuple[tuple[GithubPr, ...], str | None],
    temporal: tuple[
        tuple[
            tuple[ScanExecution, ...],
            tuple[BumpExecution, ...],
            tuple[ReviewExecution, ...],
            tuple[PrReviewExecution, ...],
            tuple[A11yExecution, ...],
            tuple[PrA11yExecution, ...],
        ],
        str | None,
    ],
    telemetry: tuple[RunTelemetry, str | None],
    outcomes: dict[tuple[str, int], str] | None = None,
    reliability_window_days: int = 90,
    environment: str = "",
) -> DashboardModel:
    """Build the whole view from the readers' ``(data, error)`` outputs.

    ``outcomes`` is the post-merge signal per ``(repo, number)`` from the
    outcome reader (best-effort); absent for a merge older than the window.
    """
    prs, github_error = github
    (
        (
            scans,
            bumps,
            reviews,
            pr_reviews,
            a11y_reviews,
            pr_a11y_reviews,
        ),
        temporal_error,
    ) = temporal
    run_telemetry, clickhouse_error = telemetry

    all_rows = _bump_rows(now, prs, bumps, outcomes or {})
    # Canary probes are synthetic bad bumps — keep them out of every genuine
    # bearing (track record, defect rate, gates) so a planted failure can never
    # pollute the real reputation; they get their own tally.
    canary_rows = tuple(r for r in all_rows if is_canary(r.to_version))
    rows = tuple(r for r in all_rows if not is_canary(r.to_version))
    class_gates = _class_gates(now, rows, repos, loops, policy, environment)
    all_failures = _failures(bumps)
    bump_loops = _bump_loops(
        now,
        rows,
        canary_rows,
        all_failures,
        scans,
        repos,
        loops,
        policy,
        environment,
        scan_interval_seconds,
        reliability_window_days,
    )
    review_loops = _review_loops(repos, reviews)
    review_rows = _review_rows(pr_reviews, repos)
    a11y_loops = _a11y_loops(repos, a11y_reviews)
    a11y_rows = _a11y_rows(pr_a11y_reviews, repos)
    return DashboardModel(
        generated_at=now,
        repos_configured=repos,
        scan_interval_seconds=scan_interval_seconds,
        sources=_sources(
            github_error,
            len(prs),
            temporal_error,
            len(scans)
            + len(bumps)
            + len(reviews)
            + len(pr_reviews)
            + len(a11y_reviews)
            + len(pr_a11y_reviews),
            run_telemetry,
            clickhouse_error,
        ),
        scan_loops=_scan_loops(repos, loops, scans),
        track_record=_track_record(rows),
        class_gates=class_gates,
        verification=_verification(rows),
        reliability=_reliability(rows, reliability_window_days),
        probes=_probes(canary_rows),
        judgment=_judgment(rows),
        gate=_gate(rows, class_gates, policy),
        bumps=rows,
        failures=all_failures,
        review_interval_seconds=review_interval_seconds,
        review_loops=review_loops,
        review_record=_review_record(review_loops, review_rows),
        reviews=review_rows,
        a11y_interval_seconds=a11y_interval_seconds,
        a11y_loops=a11y_loops,
        a11y_record=_a11y_record(a11y_loops, a11y_rows),
        a11y_reviews=a11y_rows,
        telemetry=run_telemetry,
        bump_loops=bump_loops,
    )
