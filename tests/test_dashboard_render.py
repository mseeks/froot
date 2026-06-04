from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from froot.dashboard import read_model, render
from froot.dashboard.github_source import GithubPr
from froot.dashboard.model import ActivityStat, DashboardModel, RunTelemetry
from froot.dashboard.temporal_source import (
    PrReviewExecution,
    ReviewExecution,
    ScanExecution,
)

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
REPO = "mseeks/revisionist"


def _model(
    prs: Sequence[GithubPr] = (),
    scans: Sequence[ScanExecution] = (),
    telemetry: tuple[RunTelemetry, str | None] | None = None,
    reviews: Sequence[ReviewExecution] = (),
    pr_reviews: Sequence[PrReviewExecution] = (),
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
        review_interval_seconds=300,
        github=(tuple(prs), None),
        temporal=((tuple(scans), (), tuple(reviews), tuple(pr_reviews)), None),
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


def test_page_is_a_self_contained_html_document():
    html = render.page(_model())
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "http://" not in html and "https://" not in html  # no links
    assert "<script" not in html.lower()  # no JavaScript at all


def test_page_shows_the_headline_sections_and_authority_footer():
    html = render.page(_model())
    for needle in (
        "froot",
        "Dependency-patch",  # the loop-group header
        "Is it alive?",
        "Track record",
        "Verification",
        "Model judgment",
        "Approval gate",
        "Determinism review",  # the second loop-group header
        "Authority envelope",
        "derived live",
    ):
        assert needle in html


def test_page_renders_track_record_numbers():
    prs = [
        _pr(1, "a", "merged", opened=NOW, merged=NOW),
        _pr(2, "b", "merged", opened=NOW, merged=NOW),
    ]
    html = render.page(_model(prs=prs))
    assert "100%" in html  # 2/2 merge rate
    assert ">2<" in html  # the merged count appears as a stat


def test_page_links_open_prs_and_lists_bumps():
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


def test_empty_state_is_explicit_not_blank():
    html = render.page(_model())
    assert "No bumps proposed yet" in html
    assert "Queue empty" in html


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
    assert "75 spans" in html


def test_live_scan_loop_shows_a_repo_row():
    scans = [
        ScanExecution(
            workflow_id="froot-scan-mseeks-revisionist",
            status="running",
            start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
        )
    ]
    html = render.page(_model(scans=scans))
    assert REPO in html
    assert "next" in html  # the next-due hint for a live loop


# ── Determinism review sections ──────────────────────────────────────────────
def _review(status: str = "running") -> ReviewExecution:
    return ReviewExecution(
        workflow_id="froot-review-mseeks-revisionist",
        status=status,
        start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
    )


def _pr_review(
    pr: int,
    findings: int,
    rules: tuple[str, ...],
    comment: str | None = None,
) -> PrReviewExecution:
    return PrReviewExecution(
        workflow_id=f"froot-pr-review-mseeks-revisionist-{pr}-abc1234def56",
        status="completed",
        start=datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
        close=datetime(2026, 6, 3, 6, 1, tzinfo=UTC),
        pr_number=pr,
        head_sha="abc1234def56",
        findings=findings,
        rules=rules,
        comment_url=comment,
    )


def test_page_shows_determinism_sections_with_empty_states():
    html = render.page(_model())
    assert "Determinism review" in html
    assert "transitive ring" in html
    assert "No determinism-review loops running" in html
    assert "No PRs reviewed yet" in html


def test_review_heartbeat_clears_empty_note_when_a_loop_is_live():
    live = render.page(_model(reviews=[_review("running")]))
    assert "No determinism-review loops running" not in live
    assert "next" in live  # the next-due hint for the live review loop


def test_flagged_review_renders_rule_count_and_comment_link():
    comment = f"https://github.com/{REPO}/pull/7#issuecomment-1"
    pr_reviews = [_pr_review(7, 1, ("datetime.datetime.now",), comment=comment)]
    html = render.page(_model(pr_reviews=pr_reviews))
    assert "datetime.datetime.now" in html
    assert "1 hazard" in html
    assert "#7" in html
    assert comment in html  # the one-click comment link


def test_clean_review_renders_clean_not_a_hazard():
    html = render.page(_model(pr_reviews=[_pr_review(8, 0, ())]))
    assert ">clean<" in html


# ── Hierarchy: two loop groups, at-a-glance, foldable framing ─────────────────
def test_sections_are_grouped_into_collapsible_loops():
    html = render.page(_model())
    # two loops, each a collapsible <details> collapsed by default (no `open`)
    assert html.count('<details class="loop">') == 2
    # telemetry is its own differentiated "shared" group, not part of a loop
    assert html.count('<details class="loop shared">') == 1
    assert html.count('class="loophead"') == 3
    for title in ("Dependency-patch", "Determinism review", "Run telemetry"):
        assert title in html


def test_loop_header_carries_an_at_a_glance():
    prs = [_pr(1, "a", "merged", opened=NOW, merged=NOW)]
    html = render.page(_model(prs=prs, reviews=[_review("running")]))
    assert 'class="glance"' in html
    assert "proposed" in html  # dependency-patch glance
    assert "reviewed" in html  # determinism glance


def test_framing_notes_fold_behind_details():
    html = render.page(_model())
    assert 'details class="why"' in html
