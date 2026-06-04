from __future__ import annotations

from datetime import UTC, datetime

from froot.dashboard import read_model
from froot.dashboard.github_source import GithubPr
from froot.dashboard.model import DashboardModel, RunTelemetry
from froot.dashboard.temporal_source import (
    BumpExecution,
    PrReviewExecution,
    ReviewExecution,
    ScanExecution,
)

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
REPO = "mseeks/revisionist"


def _pr(
    number: int,
    package: str,
    state: str,
    *,
    to_version: str = "1.0.0",
    from_version: str | None = None,
    verdict: str | None = None,
    opened: datetime | None = None,
    merged: datetime | None = None,
) -> GithubPr:
    return GithubPr(
        repo=REPO,
        number=number,
        url=f"https://github.com/{REPO}/pull/{number}",
        package=package,
        from_version=from_version,
        to_version=to_version,
        verdict=verdict,
        state=state,
        opened_at=opened,
        merged_at=merged,
    )


def _bump(
    suffix: str,
    status: str,
    *,
    pr_number: int | None = None,
    repo: str | None = REPO,
    verdict: str | None = None,
    ci: str | None = None,
    reason: str | None = None,
    close: datetime | None = None,
) -> BumpExecution:
    return BumpExecution(
        workflow_id=f"froot-bump-mseeks-revisionist-{suffix}",
        status=status,
        start=datetime(2026, 6, 2, 19, 45, tzinfo=UTC),
        close=close,
        verdict=verdict,
        ci=ci,
        pr_number=pr_number,
        repo=repo,
        reason=reason,
    )


def _telemetry_off() -> tuple[RunTelemetry, str | None]:
    empty = RunTelemetry(
        available=False,
        total_spans=0,
        error_spans=0,
        last_activity=None,
        window_days=3,
        activities=(),
    )
    return empty, "off"


def _assemble(
    prs: list[GithubPr],
    scans: list[ScanExecution],
    bumps: list[BumpExecution],
    reviews: list[ReviewExecution] | None = None,
    pr_reviews: list[PrReviewExecution] | None = None,
) -> DashboardModel:
    return read_model.assemble(
        now=NOW,
        repos=(REPO,),
        scan_interval_seconds=86_400,
        review_interval_seconds=300,
        github=(tuple(prs), None),
        temporal=(
            (
                tuple(scans),
                tuple(bumps),
                tuple(reviews or ()),
                tuple(pr_reviews or ()),
            ),
            None,
        ),
        telemetry=_telemetry_off(),
    )


def _rich_model() -> DashboardModel:
    opened1 = datetime(2026, 6, 2, 19, 45, tzinfo=UTC)
    opened2 = datetime(2026, 6, 2, 19, 46, tzinfo=UTC)
    opened3 = datetime(2026, 6, 2, 19, 47, tzinfo=UTC)
    merged_at = datetime(2026, 6, 2, 20, 0, tzinfo=UTC)
    prs = [
        _pr(21, "@nuxt/test-utils", "merged", opened=opened1, merged=merged_at),
        _pr(22, "nuxt", "merged", opened=opened2, merged=merged_at),
        _pr(23, "vitest", "open", opened=opened3),
    ]
    scans = [
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="running",
            start=opened1,
        )
    ]
    bumps = [
        _bump(
            "nuxt-test-utils-3.19.2",
            "completed",
            pr_number=21,
            verdict="clean",
            ci="absent",
        ),
        _bump(
            "nuxt-3.21.7",
            "completed",
            pr_number=22,
            verdict="risky",
            ci="passed",
        ),
        _bump(
            "broken-1.0.0",
            "terminated",
            reason="ERESOLVE",
            close=datetime(2026, 6, 2, 19, 50, tzinfo=UTC),
        ),
    ]
    return _assemble(prs, scans, bumps)


def test_track_record_counts_and_merge_rate():
    model = _rich_model()
    t = model.track_record
    assert t.opened == 3
    assert t.merged == 2
    assert t.open_now == 1
    assert t.closed_unmerged == 0
    assert t.merge_rate == 1.0  # 2 merged / 2 decided
    # ttm: pr21 = 15min, pr22 = 14min -> median 14.5
    assert t.median_ttm_minutes == 14.5


def test_verification_keeps_absent_distinct_from_failure():
    v = _rich_model().verification
    assert v.passed == 1  # pr22
    assert v.absent == 1  # pr21
    assert v.failed == 0
    assert v.unknown == 1  # pr23 open, no temporal outcome
    assert v.with_reading == 2
    assert v.oracle_existed == 1


def test_judgment_mix_and_calibration():
    j = _rich_model().judgment
    assert (j.clean, j.risky, j.unknown, j.none) == (1, 1, 0, 1)
    assert j.flagged_but_passed == 1  # pr22 risky verdict, CI passed
    assert j.clean_but_failed == 0


def test_gate_holds_only_open_prs():
    gate = _rich_model().gate
    assert [row.pr_number for row in gate] == [23]
    assert gate[0].age_hours is not None


def test_failures_surface_terminated_bumps():
    failures = _rich_model().failures
    assert len(failures) == 1
    assert failures[0].kind == "terminated"
    assert failures[0].reason == "ERESOLVE"


def test_scan_loop_is_live_when_a_running_execution_exists():
    loops = _rich_model().scan_loops
    assert len(loops) == 1
    assert loops[0].repo == REPO
    assert loops[0].live is True
    assert loops[0].status == "running"


def test_scan_loop_reports_none_when_no_execution():
    model = _assemble([], [], [])
    assert model.scan_loops[0].status == "none"
    assert model.scan_loops[0].live is False


def test_scan_loop_not_live_when_terminated():
    scans = [
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="terminated",
            start=NOW,
        )
    ]
    model = _assemble([], scans, [])
    assert model.scan_loops[0].live is False
    assert model.scan_loops[0].status == "terminated"


def test_latest_scan_execution_wins():
    older = ScanExecution(
        workflow_id="froot-scan-mseeks-revisionist",
        status="continued_as_new",
        start=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
    )
    newer = ScanExecution(
        workflow_id="froot-scan-mseeks-revisionist",
        status="running",
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
    )
    model = _assemble([], [older, newer], [])
    assert model.scan_loops[0].status == "running"


def test_verdict_falls_back_to_pr_body_when_temporal_is_gone():
    # An old PR whose bump aged out of Temporal: verdict comes from the body.
    prs = [_pr(5, "lodash", "merged", verdict="clean")]
    model = _assemble(prs, [], [])
    assert model.bumps[0].verdict == "clean"
    assert model.bumps[0].ci is None  # no durable CI reading


def test_temporal_outcome_overrides_body_verdict():
    prs = [_pr(6, "lodash", "merged", verdict="clean")]
    bumps = [
        _bump(
            "lodash-1.0.0",
            "completed",
            pr_number=6,
            verdict="risky",
            ci="failed",
        )
    ]
    model = _assemble(prs, [], bumps)
    assert model.bumps[0].verdict == "risky"
    assert model.bumps[0].ci == "failed"


def test_median_helper_handles_odd_and_empty():
    assert read_model._median([3.0, 1.0, 2.0]) == 2.0
    assert read_model._median([]) is None


def test_cross_repo_pr_number_does_not_collide():
    # Temporal lists every repo's bumps; a bump from another repo with the same
    # PR number must NOT attach its verdict/CI to this repo's PR #1.
    prs = [_pr(1, "left-pad", "merged", verdict="clean")]
    other = _bump(
        "x",
        "completed",
        pr_number=1,
        repo="other/repo",
        verdict="risky",
        ci="failed",
    )
    model = _assemble(prs, [], [other])
    row = model.bumps[0]
    assert row.verdict == "clean"  # from the PR body, not the other repo
    assert row.ci is None  # no same-repo Temporal outcome to attach


def test_same_repo_pr_number_attaches_outcome():
    prs = [_pr(1, "left-pad", "merged", verdict="clean")]
    same = _bump(
        "x", "completed", pr_number=1, repo=REPO, verdict="risky", ci="failed"
    )
    model = _assemble(prs, [], [same])
    assert model.bumps[0].verdict == "risky"
    assert model.bumps[0].ci == "failed"


def test_canceled_and_timed_out_appear_in_failures():
    bumps = [
        _bump("a", "canceled", close=datetime(2026, 6, 2, 19, 50, tzinfo=UTC)),
        _bump("b", "timed_out", close=datetime(2026, 6, 2, 19, 51, tzinfo=UTC)),
    ]
    model = _assemble([], [], bumps)
    assert {f.kind for f in model.failures} == {"canceled", "timed_out"}


def test_source_health_reflects_errors():
    model = read_model.assemble(
        now=NOW,
        repos=(REPO,),
        scan_interval_seconds=86_400,
        review_interval_seconds=300,
        github=((), "boom"),
        temporal=(((), (), (), ()), None),
        telemetry=_telemetry_off(),
    )
    health = {s.name: s for s in model.sources}
    assert health["github"].ok is False
    assert health["github"].detail == "boom"
    assert health["temporal"].ok is True
    assert health["clickhouse"].ok is False  # "off"


# ── Determinism review loop ──────────────────────────────────────────────────
def _review(status: str = "running") -> ReviewExecution:
    return ReviewExecution(
        workflow_id="froot-review-mseeks-revisionist",
        status=status,
        start=datetime(2026, 6, 3, 11, 55, tzinfo=UTC),
    )


def _pr_review(
    pr: int,
    *,
    status: str = "completed",
    findings: int = 0,
    rules: tuple[str, ...] = (),
    head: str = "abc1234def56",
) -> PrReviewExecution:
    return PrReviewExecution(
        workflow_id=f"froot-pr-review-mseeks-revisionist-{pr}-{head}",
        status=status,
        start=datetime(2026, 6, 3, 11, 50, tzinfo=UTC),
        close=datetime(2026, 6, 3, 11, 51, tzinfo=UTC),
        pr_number=pr,
        head_sha=head,
        findings=findings,
        rules=rules,
        comment_url=None,
    )


def test_review_loop_live_when_running():
    model = _assemble([], [], [], reviews=[_review("running")])
    assert len(model.review_loops) == 1
    assert model.review_loops[0].repo == REPO
    assert model.review_loops[0].live is True


def test_review_loop_omitted_when_no_execution():
    # Reviews are scoped to the Temporal repos; a repo with no review loop is
    # left out, not shown as a dead one (unlike the scan heartbeat).
    assert _assemble([], [], []).review_loops == ()


def test_review_record_counts_findings_clean_and_hazards():
    pr_reviews = [
        _pr_review(
            1, findings=2, rules=("datetime.datetime.now", "random.random")
        ),
        _pr_review(2, findings=0),
        _pr_review(3, findings=1, rules=("time.time",)),
    ]
    model = _assemble([], [], [], reviews=[_review()], pr_reviews=pr_reviews)
    r = model.review_record
    assert (r.reviewed, r.flagged, r.clean, r.hazards) == (3, 2, 1, 3)
    assert r.repos_covered == 1


def test_review_row_attributes_repo_and_pr_url():
    model = _assemble(
        [], [], [], pr_reviews=[_pr_review(7, findings=1, rules=("time.time",))]
    )
    row = model.reviews[0]
    assert row.repo == REPO
    assert row.pr_url == f"https://github.com/{REPO}/pull/7"
    assert row.pr_number == 7
    assert row.rules == ("time.time",)


def test_review_record_ignores_incomplete_reviews():
    pr_reviews = [
        _pr_review(1, status="running", findings=0),
        _pr_review(2, status="completed", findings=1, rules=("time.time",)),
    ]
    model = _assemble([], [], [], pr_reviews=pr_reviews)
    assert model.review_record.reviewed == 1  # only the completed one
    assert model.review_record.flagged == 1
