from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from froot.dashboard import read_model, render
from froot.dashboard.github_source import GithubPr
from froot.dashboard.model import ActivityStat, DashboardModel, RunTelemetry
from froot.dashboard.temporal_source import ScanExecution

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
REPO = "mseeks/revisionist"


def _model(
    prs: Sequence[GithubPr] = (),
    scans: Sequence[ScanExecution] = (),
    telemetry: tuple[RunTelemetry, str | None] | None = None,
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
        github=(tuple(prs), None),
        temporal=((tuple(scans), ()), None),
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
        "Is the loop alive?",
        "Track record",
        "Verification",
        "Model judgment",
        "Approval gate",
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
