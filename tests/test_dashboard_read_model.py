from __future__ import annotations

from datetime import UTC, datetime

from froot.dashboard import read_model
from froot.dashboard.github_source import GithubPr
from froot.dashboard.model import AdvisoryView, DashboardModel, RunTelemetry
from froot.dashboard.temporal_source import (
    AdvisoryExecution,
    BumpExecution,
    PrAdvisoryExecution,
    ScanExecution,
)
from froot.domain.loop import Loop
from froot.policy.autonomy import AutonomyPolicy

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
REPO = "mseeks/revisionist"


def _pr(
    number: int,
    package: str,
    state: str,
    *,
    to_version: str | None = "1.0.0",
    from_version: str | None = None,
    verdict: str | None = None,
    opened: datetime | None = None,
    merged: datetime | None = None,
    env: str | None = None,
    loop: str = "dependency-patch",
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
        env=env,
        loop=loop,
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
    advisory: list[AdvisoryExecution] | None = None,
    pr_advisory: list[PrAdvisoryExecution] | None = None,
) -> DashboardModel:
    return read_model.assemble(
        now=NOW,
        repos=(REPO,),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=(tuple(prs), None),
        temporal=(
            (
                tuple(scans),
                tuple(bumps),
                tuple(advisory or ()),
                tuple(pr_advisory or ()),
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
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=((), "boom"),
        temporal=(((), (), (), ()), None),
        telemetry=_telemetry_off(),
    )
    health = {s.name: s for s in model.sources}
    assert health["github"].ok is False
    assert health["github"].detail == "boom"
    assert health["temporal"].ok is True
    assert health["clickhouse"].ok is False  # "off"


# ── The advisory family (determinism-review + a11y-review) ───────────────────
# Both advisory loops flow through one generic read-model path, partitioned by
# their loop tag. These exercise it per loop and assert the two never
# cross-attribute through the shared code.
def _review(status: str = "running") -> AdvisoryExecution:
    return AdvisoryExecution(
        loop=Loop.DETERMINISM_REVIEW,
        workflow_id="froot-review-mseeks-revisionist",
        status=status,
        start=datetime(2026, 6, 3, 11, 55, tzinfo=UTC),
    )


def _pr_review(
    pr: int,
    *,
    status: str = "completed",
    findings: int = 0,
    detail: tuple[str, ...] = (),
    head: str = "abc1234def56",
) -> PrAdvisoryExecution:
    return PrAdvisoryExecution(
        loop=Loop.DETERMINISM_REVIEW,
        workflow_id=f"froot-pr-review-mseeks-revisionist-{pr}-{head}",
        status=status,
        start=datetime(2026, 6, 3, 11, 50, tzinfo=UTC),
        close=datetime(2026, 6, 3, 11, 51, tzinfo=UTC),
        pr_number=pr,
        head_sha=head,
        findings=findings,
        detail=detail,
        comment_url=None,
    )


def _a11y(status: str = "running") -> AdvisoryExecution:
    return AdvisoryExecution(
        loop=Loop.A11Y_REVIEW,
        workflow_id="froot-a11y-mseeks-revisionist",
        status=status,
        start=datetime(2026, 6, 3, 11, 55, tzinfo=UTC),
    )


def _pr_a11y(
    pr: int,
    *,
    status: str = "completed",
    findings: int = 0,
    detail: tuple[str, ...] = (),
    head: str = "abc1234def56",
) -> PrAdvisoryExecution:
    return PrAdvisoryExecution(
        loop=Loop.A11Y_REVIEW,
        workflow_id=f"froot-pr-a11y-mseeks-revisionist-{pr}-{head}",
        status=status,
        start=datetime(2026, 6, 3, 11, 50, tzinfo=UTC),
        close=datetime(2026, 6, 3, 11, 51, tzinfo=UTC),
        pr_number=pr,
        head_sha=head,
        findings=findings,
        detail=detail,
        comment_url=None,
    )


def _view(model: DashboardModel, loop: Loop) -> AdvisoryView:
    (view,) = [v for v in model.advisory if v.loop == loop]
    return view


def test_advisory_views_one_per_registered_emit_signal_loop():
    # The advisory tabs are derived from the registry's emit-signal specs, with
    # each view's presentation (title, icon) read straight from its spec.
    model = _assemble([], [], [])
    loops = {v.loop for v in model.advisory}
    assert Loop.DETERMINISM_REVIEW in loops
    assert Loop.A11Y_REVIEW in loops
    det = _view(model, Loop.DETERMINISM_REVIEW)
    assert det.title == "Determinism review"  # from the spec's panel_title
    assert det.icon == "search"  # from the spec's dashboard_icon


def test_review_loop_live_when_running():
    model = _assemble([], [], [], advisory=[_review("running")])
    det = _view(model, Loop.DETERMINISM_REVIEW)
    assert len(det.loops) == 1
    assert det.loops[0].repo == REPO
    assert det.loops[0].live is True


def test_review_loop_omitted_when_no_execution():
    # Reviews are scoped to the Temporal repos; a repo with no review loop is
    # left out, not shown as a dead one (unlike the scan heartbeat).
    assert _view(_assemble([], [], []), Loop.DETERMINISM_REVIEW).loops == ()


def test_review_record_counts_findings_clean_and_total():
    pr_reviews = [
        _pr_review(
            1, findings=2, detail=("datetime.datetime.now", "random.random")
        ),
        _pr_review(2, findings=0),
        _pr_review(3, findings=1, detail=("time.time",)),
    ]
    model = _assemble([], [], [], advisory=[_review()], pr_advisory=pr_reviews)
    r = _view(model, Loop.DETERMINISM_REVIEW).record
    assert (r.reviewed, r.flagged, r.clean, r.findings) == (3, 2, 1, 3)
    assert r.repos_covered == 1


def test_review_row_attributes_repo_and_pr_url():
    model = _assemble(
        [],
        [],
        [],
        pr_advisory=[_pr_review(7, findings=1, detail=("time.time",))],
    )
    row = _view(model, Loop.DETERMINISM_REVIEW).rows[0]
    assert row.repo == REPO
    assert row.pr_url == f"https://github.com/{REPO}/pull/7"
    assert row.pr_number == 7
    assert row.detail == ("time.time",)


def test_review_record_ignores_incomplete_reviews():
    pr_reviews = [
        _pr_review(1, status="running", findings=0),
        _pr_review(2, status="completed", findings=1, detail=("time.time",)),
    ]
    model = _assemble([], [], [], pr_advisory=pr_reviews)
    r = _view(model, Loop.DETERMINISM_REVIEW).record
    assert r.reviewed == 1  # only the completed one
    assert r.flagged == 1


def test_a11y_loop_live_when_running():
    model = _assemble([], [], [], advisory=[_a11y("running")])
    a11y = _view(model, Loop.A11Y_REVIEW)
    assert len(a11y.loops) == 1
    assert a11y.loops[0].repo == REPO
    assert a11y.loops[0].live is True


def test_a11y_loop_omitted_when_no_execution():
    # Like the review loop: a11y is scoped to the Temporal repos, so a repo
    # with no a11y loop is left out, not shown as a dead one.
    assert _view(_assemble([], [], []), Loop.A11Y_REVIEW).loops == ()


def test_a11y_record_counts_findings_clean_and_total():
    pr_a11y = [
        _pr_a11y(1, findings=2, detail=("missing-alt", "unlabeled-control")),
        _pr_a11y(2, findings=0),
        _pr_a11y(3, findings=1, detail=("missing-alt",)),
    ]
    model = _assemble([], [], [], advisory=[_a11y()], pr_advisory=pr_a11y)
    r = _view(model, Loop.A11Y_REVIEW).record
    assert (r.reviewed, r.flagged, r.clean, r.findings) == (3, 2, 1, 3)
    assert r.repos_covered == 1


def test_a11y_row_attributes_repo_and_pr_url():
    model = _assemble(
        [],
        [],
        [],
        pr_advisory=[_pr_a11y(7, findings=1, detail=("missing-alt",))],
    )
    row = _view(model, Loop.A11Y_REVIEW).rows[0]
    assert row.repo == REPO
    assert row.pr_url == f"https://github.com/{REPO}/pull/7"
    assert row.pr_number == 7
    assert row.detail == ("missing-alt",)


def test_a11y_record_ignores_incomplete_reviews():
    pr_a11y = [
        _pr_a11y(1, status="running", findings=0),
        _pr_a11y(2, status="completed", findings=1, detail=("missing-alt",)),
    ]
    model = _assemble([], [], [], pr_advisory=pr_a11y)
    r = _view(model, Loop.A11Y_REVIEW).record
    assert r.reviewed == 1  # only the completed one
    assert r.flagged == 1


def test_advisory_loops_do_not_cross_attribute():
    # The two loops share the generic read-model path but are partitioned by
    # their loop tag: a determinism review never lands on the a11y view, and
    # each carries only its own findings.
    model = _assemble(
        [],
        [],
        [],
        advisory=[_review(), _a11y()],
        pr_advisory=[
            _pr_review(1, findings=1, detail=("time.time",)),
            _pr_a11y(2, findings=1, detail=("missing-alt",)),
        ],
    )
    det = _view(model, Loop.DETERMINISM_REVIEW)
    a11y = _view(model, Loop.A11Y_REVIEW)
    assert [r.pr_number for r in det.rows] == [1]
    assert det.rows[0].detail == ("time.time",)
    assert [r.pr_number for r in a11y.rows] == [2]
    assert a11y.rows[0].detail == ("missing-alt",)


# ── Earned-autonomy class gates (the shadow gate) ────────────────────────────
def _allow(**overrides: object) -> AutonomyPolicy:
    base = {
        "min_rate": 0.95,
        "min_decided": 3,
        "window_days": 90,
        "allowlisted_repos": frozenset({REPO}),
    }
    base.update(overrides)
    return AutonomyPolicy(**base)  # type: ignore[arg-type]


def _assemble_p(
    prs: list[GithubPr],
    bumps: list[BumpExecution],
    policy: AutonomyPolicy,
    outcomes: dict[tuple[str, int], str] | None = None,
    environment: str = "",
) -> DashboardModel:
    return read_model.assemble(
        now=NOW,
        repos=(REPO,),
        loops=(Loop.DEPENDENCY_PATCH,),
        policy=policy,
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=(tuple(prs), None),
        temporal=(((), tuple(bumps), (), ()), None),
        telemetry=_telemetry_off(),
        outcomes=outcomes,
        environment=environment,
    )


def _held(numbers: tuple[int, ...]) -> dict[tuple[str, int], str]:
    """Post-merge outcomes marking each PR number held (the defect bearing)."""
    return {(REPO, n): "held" for n in numbers}


def _clean_green_merge(
    number: int, package: str
) -> tuple[GithubPr, BumpExecution]:
    """A merged PR plus the Temporal bump giving it a clean+green reading."""
    opened = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    merged = datetime(2026, 5, 20, 12, 15, tzinfo=UTC)
    pr = _pr(
        number, package, "merged", verdict="clean", opened=opened, merged=merged
    )
    bump = _bump(
        f"{package}-1.0.0",
        "completed",
        pr_number=number,
        verdict="clean",
        ci="passed",
    )
    return pr, bump


def test_class_gate_earned_for_clean_green_history():
    pairs = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2, 3, 4)]
    prs = [p for p, _ in pairs]
    bumps = [b for _, b in pairs]
    # All four held post-merge -> the defect bearing has evidence and is clean.
    model = _assemble_p(prs, bumps, _allow(), outcomes=_held((1, 2, 3, 4)))
    assert len(model.class_gates) == 1
    g = model.class_gates[0]
    assert (g.repo, g.loop) == (REPO, "dependency-patch")
    assert g.decided == 4
    assert g.merged == 4
    assert g.merge_rate == 1.0
    assert g.determined == 4
    assert g.defects == 0
    assert g.defect_rate == 0.0
    assert g.earned is True
    assert g.blocker is None
    # 4 merges over a 90d window (~12.86 weeks); all clean+green -> reclaimable.
    assert g.approvals_per_week > 0
    assert g.reclaim_per_week == g.approvals_per_week


def test_class_gate_not_earned_with_a_post_merge_defect():
    # Perfect rate and enough confirmed, but one merge broke -> the second
    # bearing fails (zero-tolerance default), so the gate stays shut.
    pairs = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2, 3, 4)]
    outcomes = {(REPO, 1): "held", (REPO, 2): "held", (REPO, 3): "held"}
    outcomes[(REPO, 4)] = "broke"
    model = _assemble_p(
        [p for p, _ in pairs], [b for _, b in pairs], _allow(), outcomes
    )
    g = model.class_gates[0]
    assert g.defects == 1
    assert g.earned is False
    assert g.blocker is not None and "defect rate" in g.blocker


def test_class_gate_not_earned_below_min_decided():
    pairs = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2)]
    model = _assemble_p(
        [p for p, _ in pairs], [b for _, b in pairs], _allow(min_decided=3)
    )
    g = model.class_gates[0]
    assert g.decided == 2
    assert g.earned is False
    assert g.blocker == "only 2/3 decided recently"


def test_class_gate_windows_out_old_decisions():
    # One recent merge, one merged before the 90-day window opened.
    recent = _pr(
        1,
        "fresh",
        "merged",
        verdict="clean",
        opened=datetime(2026, 5, 1, tzinfo=UTC),
        merged=datetime(2026, 5, 1, 0, 10, tzinfo=UTC),
    )
    old = _pr(
        2,
        "stale",
        "merged",
        verdict="clean",
        opened=datetime(2026, 1, 1, tzinfo=UTC),
        merged=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )
    model = _assemble_p([recent, old], [], _allow())
    g = model.class_gates[0]
    assert g.decided == 1  # the old merge fell out of the window


def test_class_gate_reclaim_excludes_unverified_merges():
    # A merged PR with a clean body verdict but NO CI reading is not counted as
    # reclaimable: without a green oracle we cannot claim it would auto-merge.
    pr = _pr(
        1,
        "lodash",
        "merged",
        verdict="clean",
        opened=datetime(2026, 5, 25, tzinfo=UTC),
        merged=datetime(2026, 5, 25, 0, 10, tzinfo=UTC),
    )
    model = _assemble_p([pr], [], _allow(min_decided=1))
    g = model.class_gates[0]
    assert g.merged == 1
    assert g.reclaim_per_week == 0.0


def test_class_gate_counts_only_current_environment():
    # Two merges under the prior env (e4b) and three under the current (26b).
    # Only the current-env merges count; the prior ones are reset but surfaced.
    prior = [
        _pr(
            n,
            f"old{n}",
            "merged",
            verdict="clean",
            opened=datetime(2026, 5, 10, tzinfo=UTC),
            merged=datetime(2026, 5, 10, 0, 5, tzinfo=UTC),
            env="gemma4-e4b",
        )
        for n in (1, 2)
    ]
    current = [
        _pr(
            n,
            f"new{n}",
            "merged",
            verdict="clean",
            opened=datetime(2026, 5, 20, tzinfo=UTC),
            merged=datetime(2026, 5, 20, 0, 5, tzinfo=UTC),
            env="gemma4-26b",
        )
        for n in (3, 4, 5)
    ]
    held = {(REPO, n): "held" for n in (3, 4, 5)}
    model = _assemble_p(
        prior + current,
        [],
        _allow(),
        outcomes=held,
        environment="gemma4-26b",
    )
    g = model.class_gates[0]
    assert g.decided == 3  # only the current-environment merges
    assert g.prior_env_decided == 2  # the e4b record, reset but legible
    assert g.earned is True  # 3 current, all held, 0 defects


def test_class_gate_resets_when_only_prior_environment_history_exists():
    # Everything was earned under e4b; the current env is 26b -> reset to zero.
    prior = [
        _pr(
            n,
            f"old{n}",
            "merged",
            verdict="clean",
            opened=datetime(2026, 5, 10, tzinfo=UTC),
            merged=datetime(2026, 5, 10, 0, 5, tzinfo=UTC),
            env="gemma4-e4b",
        )
        for n in (1, 2, 3, 4)
    ]
    held = {(REPO, n): "held" for n in (1, 2, 3, 4)}
    model = _assemble_p(
        prior, [], _allow(), outcomes=held, environment="gemma4-26b"
    )
    g = model.class_gates[0]
    assert g.decided == 0
    assert g.prior_env_decided == 4
    assert g.earned is False


# ── Adversarial canary probes (segregation) ──────────────────────────────────
def test_canary_rows_excluded_from_bearings_and_tallied_in_probes():
    # A real merged bump plus two canaries (to 99.99.99): one closed (caught),
    # one merged (escaped). The canaries must NOT touch the genuine bearings.
    prs = [
        _pr(1, "real", "merged", to_version="1.0.1", opened=NOW, merged=NOW),
        _pr(2, "canary-closed", "closed", to_version="99.99.99", opened=NOW),
        _pr(
            3,
            "canary-merged",
            "merged",
            to_version="99.99.99",
            opened=NOW,
            merged=NOW,
        ),
    ]
    model = _assemble(prs, [], [])
    # genuine bearings see only the one real bump
    assert model.track_record.opened == 1
    assert model.track_record.merged == 1
    assert [r.package for r in model.bumps] == ["real"]
    # the canaries are tallied apart
    assert model.probes.total == 2
    assert model.probes.caught == 1  # the closed one
    assert model.probes.escaped == 1  # the merged one — a guardrail hole
    assert model.probes.pending == 0


def test_no_canaries_means_empty_probes():
    prs = [_pr(1, "real", "merged", to_version="1.0.1", opened=NOW, merged=NOW)]
    p = _assemble(prs, [], []).probes
    assert (p.total, p.caught, p.escaped, p.pending) == (0, 0, 0, 0)


# ── Reliability (post-merge outcome leg) ─────────────────────────────────────
def _assemble_outcomes(
    prs: list[GithubPr], outcomes: dict[tuple[str, int], str]
) -> DashboardModel:
    return read_model.assemble(
        now=NOW,
        repos=(REPO,),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=(tuple(prs), None),
        temporal=(((), (), (), ()), None),
        telemetry=_telemetry_off(),
        outcomes=outcomes,
        reliability_window_days=90,
    )


def test_reliability_counts_and_defect_rate():
    prs = [
        _pr(1, "a", "merged", opened=NOW, merged=NOW),
        _pr(2, "b", "merged", opened=NOW, merged=NOW),
        _pr(3, "c", "merged", opened=NOW, merged=NOW),
        _pr(4, "d", "merged", opened=NOW, merged=NOW),
    ]
    outcomes = {
        (REPO, 1): "held",
        (REPO, 2): "held",
        (REPO, 3): "broke",
        (REPO, 4): "reverted",
    }
    r = _assemble_outcomes(prs, outcomes).reliability
    assert (r.held, r.broke, r.reverted) == (2, 1, 1)
    assert r.determined == 4
    assert r.unverified == 0
    assert r.defect_rate == 0.5  # (1 broke + 1 reverted) / 4


def test_reliability_unknown_is_unverified_not_held():
    prs = [_pr(1, "a", "merged", opened=NOW, merged=NOW)]
    r = _assemble_outcomes(prs, {(REPO, 1): "unknown"}).reliability
    assert r.unverified == 1
    assert r.held == 0
    assert r.determined == 0
    assert r.defect_rate is None  # nothing determined -> no rate, not 0%


def test_post_merge_none_when_outcome_absent():
    # A merged PR with no outcome entry (older than the window) carries no
    # post_merge tag and is not counted in reliability.
    prs = [_pr(9, "old", "merged", opened=NOW, merged=NOW)]
    model = _assemble_outcomes(prs, {})
    assert model.bumps[0].post_merge is None
    rel = model.reliability
    assert (rel.held, rel.broke, rel.reverted, rel.unverified) == (0, 0, 0, 0)


def test_post_merge_tag_attaches_to_the_right_row():
    prs = [
        _pr(1, "a", "merged", opened=NOW, merged=NOW),
        _pr(2, "b", "merged", opened=NOW, merged=NOW),
    ]
    model = _assemble_outcomes(prs, {(REPO, 1): "broke"})
    by_num = {r.pr_number: r.post_merge for r in model.bumps}
    assert by_num[1] == "broke"
    assert by_num[2] is None


def test_class_gate_reclaim_is_zero_until_earned():
    # Two clean+green merges, but min_decided=5 -> the class is NOT earned, so
    # reclaim is zero: an un-earned class's gate would not move, hence reclaims
    # nothing, even though clean-and-green merges exist.
    pairs = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2)]
    model = _assemble_p(
        [p for p, _ in pairs], [b for _, b in pairs], _allow(min_decided=5)
    )
    g = model.class_gates[0]
    assert g.earned is False
    assert g.merged == 2
    assert g.reclaim_per_week == 0.0
    assert g.approvals_per_week > 0  # the cost is still real


def test_gate_marks_open_pr_would_auto_merge_on_earned_class():
    history = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2, 3)]
    prs = [p for p, _ in history]
    bumps = [b for _, b in history]
    # An open, clean PR with a green CI reading on the earned allowlisted class.
    prs.append(_pr(9, "axios", "open", verdict="clean", opened=NOW))
    bumps.append(
        _bump(
            "axios-1.0.0",
            "completed",
            pr_number=9,
            verdict="clean",
            ci="passed",
        )
    )
    model = _assemble_p(prs, bumps, _allow(), outcomes=_held((1, 2, 3)))
    open_row = next(r for r in model.gate if r.pr_number == 9)
    assert open_row.would_auto_merge is True
    assert open_row.held_reason is None


def test_gate_holds_open_pr_with_reason_when_not_allowlisted():
    history = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2, 3)]
    prs = [p for p, _ in history]
    bumps = [b for _, b in history]
    prs.append(_pr(9, "axios", "open", verdict="clean", opened=NOW))
    bumps.append(
        _bump(
            "axios-1.0.0",
            "completed",
            pr_number=9,
            verdict="clean",
            ci="passed",
        )
    )
    # Earned history, but the repo is NOT allowlisted -> held on the switch.
    model = _assemble_p(
        prs,
        bumps,
        _allow(allowlisted_repos=frozenset()),
        outcomes=_held((1, 2, 3)),
    )
    open_row = next(r for r in model.gate if r.pr_number == 9)
    assert open_row.would_auto_merge is False
    assert open_row.held_reason == "auto-merge not enabled for this repo"


def test_gate_holds_open_pr_on_pending_ci():
    history = [_clean_green_merge(n, f"pkg{n}") for n in (1, 2, 3)]
    prs = [p for p, _ in history]
    bumps = [b for _, b in history]
    # Open, clean, but no CI reading yet -> held on CI even though earned.
    prs.append(_pr(9, "axios", "open", verdict="clean", opened=NOW))
    model = _assemble_p(prs, bumps, _allow(), outcomes=_held((1, 2, 3)))
    open_row = next(r for r in model.gate if r.pr_number == 9)
    assert open_row.would_auto_merge is False
    assert open_row.held_reason == "CI pending"


def test_bump_loops_partition_each_loop_into_its_own_view():
    # Two loops, one merged PR each: every loop gets its own self-contained view
    # (its own bumps + track record), and a PR never crosses loops.
    dep = _pr(1, "left-pad", "merged", verdict="clean", loop="dependency-patch")
    sec = _pr(2, "left-pad", "merged", verdict="clean", loop="security-patch")
    model = read_model.assemble(
        now=NOW,
        repos=(REPO,),
        loops=(Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=((dep, sec), None),
        temporal=(((), (), (), ()), None),
        telemetry=_telemetry_off(),
    )
    by_loop = {v.loop: v for v in model.bump_loops}
    assert set(by_loop) == {"dependency-patch", "security-patch"}
    assert by_loop["dependency-patch"].title == "Dependency-patch"
    assert [r.pr_number for r in by_loop["dependency-patch"].bumps] == [1]
    assert [r.pr_number for r in by_loop["security-patch"].bumps] == [2]
    # Each per-loop track record counts only its own merge.
    assert by_loop["dependency-patch"].track_record.merged == 1
    assert by_loop["security-patch"].track_record.merged == 1
    # The combined top-level view still sees both.
    assert model.track_record.merged == 2


def test_dead_code_loop_renders_removal_shape():
    # A removal carries no version: its row reads "left-pad -> unused" with no
    # from-version, and it lands in its own dead-code view.
    rm = _pr(3, "left-pad", "open", to_version=None, loop="dead-code")
    model = read_model.assemble(
        now=NOW,
        repos=(REPO,),
        loops=(Loop.DEAD_CODE,),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=((rm,), None),
        temporal=(((), (), (), ()), None),
        telemetry=_telemetry_off(),
    )
    by_loop = {v.loop: v for v in model.bump_loops}
    assert by_loop["dead-code"].title == "Dead-code"
    row = by_loop["dead-code"].bumps[0]
    assert row.package == "left-pad"
    assert row.to_version == "unused"
    assert row.from_version is None


def test_bump_loops_attribute_failures_by_workflow_id():
    # A segmentless id is dependency-patch; a security-patch-segmented id is
    # security-patch — failures land in the right loop's view.
    dep_fail = _bump("left-pad-1.0.0", "failed", reason="boom")
    sec_fail = BumpExecution(
        workflow_id="froot-bump-security-patch-mseeks-revisionist-x-1.0.0",
        status="failed",
        start=datetime(2026, 6, 2, 19, 45, tzinfo=UTC),
        close=None,
        verdict=None,
        ci=None,
        pr_number=None,
        repo=REPO,
        reason="boom",
    )
    model = read_model.assemble(
        now=NOW,
        repos=(REPO,),
        loops=(Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=((), None),
        temporal=(((), (dep_fail, sec_fail), (), ()), None),
        telemetry=_telemetry_off(),
    )
    by_loop = {v.loop: v for v in model.bump_loops}
    assert len(by_loop["dependency-patch"].failures) == 1
    assert len(by_loop["security-patch"].failures) == 1
    assert "security-patch" in by_loop["security-patch"].failures[0].workflow_id
