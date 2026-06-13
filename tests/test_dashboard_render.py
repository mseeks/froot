from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from froot.dashboard import read_model, render
from froot.dashboard.github_source import GithubPr
from froot.dashboard.model import ActivityStat, DashboardModel, RunTelemetry
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


def _model(
    prs: Sequence[GithubPr] = (),
    scans: Sequence[ScanExecution] = (),
    telemetry: tuple[RunTelemetry, str | None] | None = None,
    advisory: Sequence[AdvisoryExecution] = (),
    pr_advisory: Sequence[PrAdvisoryExecution] = (),
) -> DashboardModel:
    if telemetry is None:
        telemetry = (
            RunTelemetry(
                available=False,
                total_spans=0,
                error_spans=0,
                last_activity=None,
                window_days=3,
                activities=(),
            ),
            "off",
        )
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
            (tuple(scans), (), tuple(advisory), tuple(pr_advisory)),
            None,
        ),
        telemetry=telemetry,
    )


def _pr(number: int, package: str, state: str, **kw) -> GithubPr:
    return GithubPr(
        repo=REPO,
        number=number,
        url=f"https://github.com/{REPO}/pull/{number}",
        package=package,
        from_version=kw.get("from_version"),
        to_version=kw.get("to_version", "1.0.0"),
        verdict=kw.get("verdict"),
        state=state,
        opened_at=kw.get("opened", NOW),
        merged_at=kw.get("merged"),
    )


# ── the page shell: self-contained, no JS, tabbed ────────────────────────────
def test_page_is_a_self_contained_html_document():
    html = render.page(_model())
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "http://" not in html and "https://" not in html  # no links
    assert "<script src" not in html.lower()  # no external JS; theme is inline


def test_page_is_tabbed_one_per_loop_plus_determinism_and_telemetry():
    html = render.page(_model())
    assert '<nav class="tabbar">' in html
    # CSS-only tabs: hidden radio inputs drive the panels (no external JS).
    assert 'type="radio"' in html and "<script src" not in html.lower()
    for label in (
        "Dependency-patch",
        "Determinism review",
        "A11y review",
        "Telemetry",
    ):
        assert label in html
    # the footer's authority envelope, trimmed of the word-bomb
    assert "Authority envelope" in html
    assert "froot" in html


def test_dead_code_loop_renders_with_scissors_and_unused():
    # The dead-code tab gets the scissors icon and its removal rows read
    # "<pkg> -> unused", not the bump-shaped "<pkg> -> <version>".
    rm = GithubPr(
        repo=REPO,
        number=5,
        url=f"https://github.com/{REPO}/pull/5",
        package="left-pad",
        from_version=None,
        to_version=None,
        verdict=None,
        state="open",
        opened_at=NOW,
        merged_at=None,
        loop="dead-code",
    )
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
        telemetry=(
            RunTelemetry(
                available=False,
                total_spans=0,
                error_spans=0,
                last_activity=None,
                window_days=3,
                activities=(),
            ),
            "off",
        ),
    )
    html = render.page(model)
    assert "Dead-code" in html  # the tab label
    assert "M20 4 8.12 15.88" in html  # the scissors icon path
    assert "unused" in html  # the removal's target column, not a version


def test_loop_tab_icon_is_spec_driven_not_a_hardcoded_map() -> None:
    # The dashboard-from-registry milestone: a loop's tab presentation flows
    # from its registered spec, so changing the spec's icon changes the rendered
    # tab with NO renderer edit (the renderer no longer keys icons by loop).
    from dataclasses import replace

    from froot.dashboard.render import _ICONS
    from froot.loops import registry

    original = registry.get(Loop.DEPENDENCY_PATCH)
    assert original.dashboard_icon == "package"
    try:
        registry.register(replace(original, dashboard_icon="layers"))
        html = render.page(_model())
        assert _ICONS["layers"] in html  # the spec's new icon is rendered
        assert _ICONS["package"] not in html  # the old one is gone
    finally:
        registry.register(original)  # restore for the other tests


def test_theme_toggle_is_present_and_light_is_the_default():
    html = render.page(_model())
    # Light is the :root default; dark applies via system pref or the toggle.
    assert "--fg:#1b1f24" in html  # the light palette is the base
    assert "[data-theme=dark]" in html  # the forced-dark override exists
    assert "__toggleTheme" in html and 'class="themetgl"' in html


def test_gate_hero_shows_the_four_bearings_and_a_decision():
    html = render.page(_model())
    assert "Earned autonomy" in html and "the gate" in html
    for bearing in ("approval rate", "defect rate", "probe", "deep review"):
        assert bearing in html
    assert "HOLD" in html  # no record yet -> the gate holds


def test_page_renders_track_record_numbers():
    prs = [
        _pr(1, "a", "merged", opened=NOW, merged=NOW),
        _pr(2, "b", "merged", opened=NOW, merged=NOW),
    ]
    html = render.page(_model(prs=prs))
    assert "100%" in html  # 2/2 approval rate
    assert ">2<" in html  # the proposed count as a card stat
    assert "2 merged" in html


def test_page_links_open_prs_and_lists_them_in_the_queue():
    prs = [_pr(23, "vitest", "open", to_version="3.2.6")]
    html = render.page(_model(prs=prs))
    assert f"https://github.com/{REPO}/pull/23" in html
    assert "vitest" in html
    assert "#23" in html


def test_page_escapes_dynamic_content():
    evil = "<script>alert(1)</script>"
    prs = [_pr(1, evil, "merged", opened=NOW, merged=NOW)]
    html = render.page(_model(prs=prs))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_queue_is_explicit_not_blank():
    html = render.page(_model())
    assert "Nothing awaiting you" in html


# ── telemetry tab ────────────────────────────────────────────────────────────
def test_telemetry_panel_reports_unavailable_when_off():
    html = render.page(_model())
    assert "Unavailable" in html


def test_telemetry_panel_renders_activity_rows_when_available():
    telemetry = (
        RunTelemetry(
            available=True,
            total_spans=75,
            error_spans=10,
            last_activity=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
            window_days=3,
            activities=(
                ActivityStat(
                    name="open_pull_request",
                    count=14,
                    avg_ms=14162.0,
                    max_ms=55828.0,
                ),
            ),
        ),
        None,
    )
    html = render.page(_model(telemetry=telemetry))
    assert "open_pull_request" in html
    assert ">75<" in html and "spans" in html


def test_scan_cadence_shows_liveness_and_next_due():
    scans = [
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="running",
            start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
        )
    ]
    html = render.page(_model(scans=scans))
    assert REPO in html  # the class row carries the repo
    assert "next" in html  # the next-due hint for the live loop


# ── the advisory family tabs (determinism-review, a11y-review) ───────────────
# Both advisory loops render through one generic, registry-driven tab. These
# exercise that tab via the determinism loop, plus the a11y loop where the two
# must stay distinct (no cross-attribution through the shared renderer).
def _adv_loop(
    loop: Loop, slug: str, status: str = "running"
) -> AdvisoryExecution:
    return AdvisoryExecution(
        loop=loop,
        workflow_id=f"froot-{slug}-mseeks-revisionist",
        status=status,
        start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
    )


def _pr_adv(
    loop: Loop,
    slug: str,
    pr: int,
    findings: int,
    detail: tuple[str, ...],
    comment: str | None = None,
) -> PrAdvisoryExecution:
    return PrAdvisoryExecution(
        loop=loop,
        workflow_id=f"froot-pr-{slug}-mseeks-revisionist-{pr}-abc1234def56",
        status="completed",
        start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
        close=datetime(2026, 6, 3, 6, 1, tzinfo=UTC),
        pr_number=pr,
        head_sha="abc1234def56",
        findings=findings,
        detail=detail,
        comment_url=comment,
    )


def _review(status: str = "running") -> AdvisoryExecution:
    return _adv_loop(Loop.DETERMINISM_REVIEW, "review", status)


def _pr_review(
    pr: int, findings: int, detail: tuple[str, ...], comment: str | None = None
) -> PrAdvisoryExecution:
    return _pr_adv(
        Loop.DETERMINISM_REVIEW, "review", pr, findings, detail, comment
    )


def _pr_a11y(
    pr: int, findings: int, detail: tuple[str, ...], comment: str | None = None
) -> PrAdvisoryExecution:
    return _pr_adv(Loop.A11Y_REVIEW, "a11y", pr, findings, detail, comment)


def test_advisory_tabs_are_registry_driven_one_per_emit_signal_loop():
    # Both advisory loops surface as their own tab, titled from the registered
    # spec — the dashboard derives the *set* of advisory tabs from the
    # registry, never a hard-coded determinism+a11y pair.
    html = render.page(_model())
    assert "Determinism review" in html  # determinism-review's panel_title
    assert "A11y review" in html  # a11y-review's panel_title
    assert "No PRs reviewed yet" in html


def test_advisory_tab_presentation_is_spec_driven_not_hardcoded() -> None:
    # The cut-#2 milestone for the advisory family: a tab's icon flows from its
    # spec, so changing the spec's icon changes the rendered tab with NO
    # renderer edit (mirroring the acting family's spec-driven tabs).
    from dataclasses import replace

    from froot.dashboard.render import _ICONS
    from froot.loops import registry

    original = registry.get(Loop.A11Y_REVIEW)
    assert original.dashboard_icon == "accessibility"
    try:
        registry.register(replace(original, dashboard_icon="layers"))
        html = render.page(_model())
        assert _ICONS["layers"] in html  # the spec's new icon is rendered
    finally:
        registry.register(original)  # restore for the other tests


def test_advisory_tab_counts_a_live_loop():
    html = render.page(_model(advisory=[_review("running")]))
    assert "loops live" in html  # the liveness card
    assert ">1<" in html  # one repo covered / one loop live


def test_flagged_advisory_renders_finding_count_and_comment_link():
    comment = f"https://github.com/{REPO}/pull/7#issuecomment-1"
    pr_advisory = [
        _pr_review(7, 1, ("datetime.datetime.now",), comment=comment)
    ]
    html = render.page(_model(pr_advisory=pr_advisory))
    assert "datetime.datetime.now" in html  # the kind, in the detail column
    assert "1 finding" in html
    assert "#7" in html
    assert comment in html  # the one-click comment link


def test_clean_advisory_renders_clean_not_a_finding():
    html = render.page(_model(pr_advisory=[_pr_review(8, 0, ())]))
    assert ">clean<" in html


def test_a11y_loop_does_not_cross_attribute_to_determinism():
    # The two advisory loops share one renderer but a per-PR a11y review must
    # land on the a11y tab with its own gap kind, not the determinism tab.
    html = render.page(_model(pr_advisory=[_pr_a11y(7, 1, ("missing-alt",))]))
    assert "missing-alt" in html  # only the a11y loop surfaces this kind
    assert "1 finding" in html


# ── the gate: per-class standing + queue badge ───────────────────────────────
def _model_p(
    prs: Sequence[GithubPr],
    bumps: Sequence[BumpExecution],
    policy: AutonomyPolicy,
    outcomes: dict[tuple[str, int], str] | None = None,
) -> DashboardModel:
    telemetry = (
        RunTelemetry(
            available=False,
            total_spans=0,
            error_spans=0,
            last_activity=None,
            window_days=3,
            activities=(),
        ),
        "off",
    )
    return read_model.assemble(
        now=NOW,
        repos=(REPO,),
        policy=policy,
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=(tuple(prs), None),
        temporal=(((), tuple(bumps), (), ()), None),
        telemetry=telemetry,
        outcomes=outcomes,
    )


def _clean_green(number: int, package: str) -> tuple[GithubPr, BumpExecution]:
    opened = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    merged = datetime(2026, 5, 20, 12, 15, tzinfo=UTC)
    pr = _pr(
        number, package, "merged", verdict="clean", opened=opened, merged=merged
    )
    bump = BumpExecution(
        workflow_id=f"froot-bump-mseeks-revisionist-{package}",
        status="completed",
        start=opened,
        close=merged,
        verdict="clean",
        ci="passed",
        pr_number=number,
        repo=REPO,
        reason=None,
    )
    return pr, bump


def test_class_table_shows_the_unearned_blocker_with_no_history():
    html = render.page(_model())
    assert "Per-class standing" in html
    assert "only 0/5 decided recently" in html  # the honest blocker


def test_hero_says_no_classes_when_no_repos_configured():
    model = read_model.assemble(
        now=NOW,
        repos=(),
        scan_interval_seconds=86_400,
        advisory_intervals={
            Loop.DETERMINISM_REVIEW: 300,
            Loop.A11Y_REVIEW: 300,
        },
        github=((), None),
        temporal=(((), (), (), ()), None),
        telemetry=(
            RunTelemetry(
                available=False,
                total_spans=0,
                error_spans=0,
                last_activity=None,
                window_days=3,
                activities=(),
            ),
            "off",
        ),
    )
    assert "No classes yet" in render.page(model)


def test_queue_badge_holds_open_pr_with_substantive_reason():
    prs = [_pr(23, "vitest", "open", verdict="clean", opened=NOW)]
    html = render.page(_model_p(prs, [], AutonomyPolicy()))
    assert "held" in html
    assert "class not earned" in html


def test_class_earned_pill_and_budget():
    pairs = [_clean_green(n, f"pkg{n}") for n in (1, 2, 3, 4, 5)]
    prs = [p for p, _ in pairs]
    bumps = [b for _, b in pairs]
    policy = AutonomyPolicy(min_decided=3, allowlisted_repos=frozenset({REPO}))
    held = {(REPO, n): "held" for n in (1, 2, 3, 4, 5)}  # defect bearing clean
    html = render.page(_model_p(prs, bumps, policy, outcomes=held))
    assert ">earned<" in html  # the class cleared its gate (the pill)
    assert "budget/wk" in html  # the budget column


def test_queue_badge_would_auto_merge_on_earned_allowlisted_class():
    pairs = [_clean_green(n, f"pkg{n}") for n in (1, 2, 3)]
    prs = [p for p, _ in pairs]
    bumps = [b for _, b in pairs]
    _, open_bump = _clean_green(9, "axios")
    prs.append(_pr(9, "axios", "open", verdict="clean", opened=NOW))
    bumps.append(open_bump)
    policy = AutonomyPolicy(min_decided=3, allowlisted_repos=frozenset({REPO}))
    held = {(REPO, n): "held" for n in (1, 2, 3)}  # clear the defect bearing
    html = render.page(_model_p(prs, bumps, policy, outcomes=held))
    assert "would auto-merge" in html


# ── reliability + probes surface in the loop's cards / detail ────────────────
def _model_outcomes(
    prs: Sequence[GithubPr], outcomes: dict[tuple[str, int], str]
) -> DashboardModel:
    telemetry = (
        RunTelemetry(
            available=False,
            total_spans=0,
            error_spans=0,
            last_activity=None,
            window_days=3,
            activities=(),
        ),
        "off",
    )
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
        telemetry=telemetry,
        outcomes=outcomes,
        reliability_window_days=90,
    )


def test_defect_rate_card_and_post_merge_tags():
    prs = [
        _pr(1, "a", "merged", opened=NOW, merged=NOW),
        _pr(2, "b", "merged", opened=NOW, merged=NOW),
    ]
    outcomes = {(REPO, 1): "held", (REPO, 2): "broke"}
    html = render.page(_model_outcomes(prs, outcomes))
    assert "defect rate" in html
    assert "50%" in html  # 1 of 2 determined was a defect
    assert ">held<" in html and ">broke<" in html  # the post-merge tags


def test_canary_escape_shows_in_probes_card_and_segregated():
    # A merged canary (to 99.99.99) is a guardrail hole: the probes card counts
    # the escape, and the canary stays out of the genuine bumps.
    prs = [
        _pr(7, "evil", "merged", to_version="99.99.99", opened=NOW, merged=NOW)
    ]
    html = render.page(_model_outcomes(prs, {}))
    assert "probes escaped" in html
    # the canary is not a real bump -> the track record stays at zero proposed
    assert "evil" not in html


def test_bumps_fold_lists_bumps_with_post_merge_column():
    prs = [_pr(1, "a", "merged", opened=NOW, merged=NOW)]
    html = render.page(_model_outcomes(prs, {(REPO, 1): "reverted"}))
    assert "post-merge" in html  # the bumps-table column
    assert "reverted" in html  # the per-row post-merge tag


def test_header_shows_flapping_badge_when_a_loop_keeps_failing():
    scans = [
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="failed",
            start=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="failed",
            start=datetime(2026, 6, 2, tzinfo=UTC),
        ),
    ]
    html = render.page(_model(scans=scans))
    assert "1 flapping" in html
    assert "mseeks/revisionist (2x)" in html  # the tooltip detail


def test_header_has_no_flapping_badge_when_every_loop_is_healthy():
    assert "flapping" not in render.page(_model())
