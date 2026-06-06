"""Render the view model to one self-contained HTML page (pure).

All CSS is inline, there is no JavaScript, and the page makes no network
request of its own — it is a static projection of an already-computed
:class:`~froot.dashboard.model.DashboardModel`. Every dynamic value is
HTML-escaped at the boundary. The ordering is trust-first (is it alive → track
record → oracle → judgment → the human's queue), so it reads top to bottom.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from froot.dashboard.model import (
        BumpRow,
        ClassGate,
        DashboardModel,
        ReviewLoop,
        ReviewRow,
        RunTelemetry,
        ScanLoop,
    )

_CSS = """
:root{--fg:#1a1a1a;--mut:#6b6b6b;--line:#e4e4e4;--bg:#fff;--ok:#1a7f37;
--warn:#9a6700;--bad:#cf222e;--accent:#0969da;--card:#fafafa}
@media(prefers-color-scheme:dark){:root{--fg:#e6e6e6;--mut:#9a9a9a;
--line:#262626;--bg:#0d0d0d;--ok:#3fb950;--warn:#d29922;--bad:#f85149;
--accent:#58a6ff;--card:#141414}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:820px;margin:0 auto;padding:34px 20px 72px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
.tag{color:var(--mut);margin:3px 0 0;font-size:13px}
.meta{color:var(--mut);font-size:12px;margin:12px 0 0}
.sources{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 0;font-size:12px}
section{margin:30px 0 0}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
color:var(--mut);margin:0 0 12px;font-weight:600;
border-bottom:1px solid var(--line);padding-bottom:6px}
.stats{display:flex;flex-wrap:wrap;gap:26px}
.stat .n{font-size:26px;font-weight:600;line-height:1.1}
.stat .l{color:var(--mut);font-size:12px;margin-top:2px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;
margin-right:7px}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}
.dot.bad{background:var(--bad)}.dot.mute{background:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 12px 6px 0;
border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.04em}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.row{display:flex;align-items:baseline;gap:8px;padding:4px 0}
.mut{color:var(--mut)}.ok{color:var(--ok)}.warn{color:var(--warn)}
.bad{color:var(--bad)}
.note{color:var(--mut);font-size:12px;margin:10px 0 0}
footer{margin:44px 0 0;padding-top:16px;border-top:1px solid var(--line);
color:var(--mut);font-size:12px;line-height:1.7}
footer b{color:var(--fg);font-weight:600}
/* loop groups — collapsible (collapsed by default), two-level hierarchy */
details.loop{margin:24px 0 0}
summary.loophead{display:flex;align-items:baseline;gap:6px 12px;flex-wrap:wrap;
cursor:pointer;list-style:none;margin:0;padding:0 0 7px;
border-bottom:2px solid var(--fg)}
summary.loophead::-webkit-details-marker{display:none}
summary.loophead::before{content:"\\25B8";color:var(--mut);margin-right:5px;
font-size:11px;position:relative;top:-1px}
details.loop[open]>summary.loophead::before{content:"\\25BE"}
summary.loophead h2{font-size:16px;text-transform:none;letter-spacing:-.01em;
color:var(--fg);border:0;margin:0;padding:0;font-weight:700}
summary.loophead .sub{color:var(--mut);font-size:12px}
summary.loophead .glance{margin-left:auto;display:flex;flex-wrap:wrap;
align-items:baseline;gap:3px 14px;font-size:12px;color:var(--mut)}
summary.loophead .glance b{color:var(--fg);font-weight:600}
/* the shared-infra group reads as not-a-loop: lighter, dashed, muted */
details.loop.shared>summary.loophead{border-bottom:1px dashed var(--line)}
details.loop.shared>summary.loophead h2{font-size:13px;color:var(--mut);
font-weight:600;text-transform:uppercase;letter-spacing:.06em}
/* subsections sit tighter inside a loop; the loop rule carries the weight */
details.loop section{margin:18px 0 0}
details.loop section>h2{border-bottom:0;padding-bottom:0;margin-bottom:9px}
/* foldable framing — the MHE notes, one click away, so the page scans clean */
details.why{margin:9px 0 0}
details.why>summary{color:var(--accent);font-size:12px;cursor:pointer;
list-style:none}
details.why>summary::-webkit-details-marker{display:none}
details.why>summary::before{content:"\\002b  why";font-weight:600}
details.why[open]>summary::before{content:"\\2212  why"}
details.why .note{margin:6px 0 0}
"""

_CI_CLASS = {
    "passed": "ok",
    "failed": "bad",
    "absent": "mut",
    "timed_out": "warn",
}
_VERDICT_CLASS = {"clean": "ok", "risky": "warn", "unknown": "mut"}
_POST_MERGE_CLASS = {
    "held": "ok",
    "broke": "bad",
    "reverted": "bad",
    "unknown": "mut",
}


def _aware(when: datetime) -> datetime:
    """Treat a stray naive timestamp as UTC so arithmetic never raises."""
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _ago(when: datetime | None, now: datetime) -> str:
    """A compact 'time since' label (``6h ago``)."""
    if when is None:
        return "—"
    secs = (now - _aware(when)).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{int(secs // 60)}m ago"
    if secs < 129600:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def _until(when: datetime | None, now: datetime) -> str:
    """A compact 'time until' label (``in 18h`` / ``due now``)."""
    if when is None:
        return "—"
    secs = (_aware(when) - now).total_seconds()
    if secs <= 0:
        return "due now"
    if secs < 5400:
        return f"in {int(secs // 60)}m"
    if secs < 129600:
        return f"in {int(secs // 3600)}h"
    return f"in {int(secs // 86400)}d"


def _dot(kind: str) -> str:
    """A status dot span (``ok`` / ``warn`` / ``bad`` / ``mute``)."""
    return f'<span class="dot {kind}"></span>'


def _tag(value: str | None, classes: dict[str, str]) -> str:
    """A small coloured label for a verdict/CI value, or an em-dash."""
    if value is None:
        return '<span class="mut">—</span>'
    cls = classes.get(value, "mut")
    return f'<span class="{cls}">{escape(value)}</span>'


def _stat(n: object, label: str) -> str:
    return (
        f'<div class="stat"><div class="n">{escape(str(n))}</div>'
        f'<div class="l">{escape(label)}</div></div>'
    )


def _why(note_html: str) -> str:
    """Fold a framing note behind a native ``<details>`` so the page scans."""
    return f'<details class="why"><summary></summary>{note_html}</details>'


def _glance(n: object, label: str) -> str:
    """One at-a-glance item for a loop header (``<b>12</b> proposed``)."""
    return f"<span><b>{escape(str(n))}</b> {escape(label)}</span>"


def _header(model: DashboardModel) -> str:
    now = model.generated_at
    repos = ", ".join(model.repos_configured) or "none configured"
    dots = "".join(
        f"<span>{_dot('ok' if s.ok else 'bad')}"
        f'{escape(s.name)} <span class="mut">{escape(s.detail)}</span></span>'
        for s in model.sources
    )
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    return (
        "<header>"
        "<h1>froot</h1>"
        '<p class="tag">durable maintenance loops &middot; '
        "reputation read-model</p>"
        f'<p class="meta">watching <span class="mono">{escape(repos)}</span>'
        f" &middot; generated {escape(stamp)} &middot; "
        "derived live, stored nowhere</p>"
        f'<div class="sources">{dots}</div>'
        "</header>"
    )


def _heartbeat(model: DashboardModel) -> str:
    now = model.generated_at
    interval = model.scan_interval_seconds

    def line(loop: ScanLoop) -> str:
        if loop.live:
            dot, tail = "ok", ""
            if loop.last_tick is not None:
                nxt = _aware(loop.last_tick) + timedelta(seconds=interval)
                last = _ago(loop.last_tick, now)
                tail = (
                    f' <span class="mut">&middot; last {last}'
                    f" &middot; next {_until(nxt, now)}</span>"
                )
        else:
            dot = "bad" if loop.status in ("terminated", "none") else "warn"
            tail = f' <span class="mut">&middot; {escape(loop.status)}</span>'
        return (
            f'<div class="row">{_dot(dot)}'
            f'<span class="mono">{escape(loop.repo)}</span>'
            f' <span class="mut">{escape(loop.loop)}</span>{tail}</div>'
        )

    if not model.scan_loops:
        body = '<p class="note">No repos configured (FROOT_REPOS unset).</p>'
    else:
        body = "".join(line(loop) for loop in model.scan_loops)
    return f"<section><h2>Is it alive?</h2>{body}</section>"


def _track_record(model: DashboardModel) -> str:
    t = model.track_record
    rate = "—" if t.merge_rate is None else f"{t.merge_rate * 100:.0f}%"
    ttm = (
        "—"
        if t.median_ttm_minutes is None
        else f"{t.median_ttm_minutes:.0f} min"
    )
    stats = "".join(
        (
            _stat(t.opened, "proposed"),
            _stat(t.merged, "merged"),
            _stat(t.open_now, "awaiting"),
            _stat(t.closed_unmerged, "closed"),
            _stat(rate, "merge rate"),
            _stat(ttm, "median time-to-merge"),
        )
    )
    note = (
        '<p class="note">Merge rate is the Stage-1 signal &mdash; narrow to '
        "npm patch bumps by construction. It counts a human merge, not a "
        "confirmed good outcome: revert tracking is a later loop, so merge is "
        "not yet proof of success.</p>"
    )
    return (
        "<section><h2>Track record &middot; the reputation</h2>"
        f'<div class="stats">{stats}</div>{_why(note)}</section>'
    )


def _rate_cell(rate: float | None) -> str:
    """A class's approval rate as a percent, or an em-dash if none decided."""
    if rate is None:
        return '<span class="mut">—</span>'
    return f"{rate * 100:.0f}%"


def _earned_cell(g: ClassGate) -> str:
    """A class's gate standing: a green 'earned', else the muted blocker."""
    if g.earned:
        return f'{_dot("ok")}<span class="ok">earned</span>'
    blocker = escape(g.blocker or "not earned")
    return f'{_dot("mut")}<span class="mut">{blocker}</span>'


def _budget_cell(g: ClassGate) -> str:
    """The gate in steward-time: approvals/week now &rarr; reclaimable/week."""
    return (
        f'<span class="mono">{g.approvals_per_week:.1f}</span> appr'
        f' <span class="mut">&rarr; {g.reclaim_per_week:.1f} reclaimable</span>'
    )


def _defect_cell(g: ClassGate) -> str:
    """The post-merge defect bearing: rate over confirmed-held outcomes."""
    if g.determined == 0:
        return '<span class="mut">— (0 confirmed)</span>'
    rate = g.defect_rate if g.defect_rate is not None else 0.0
    cls = "ok" if g.defects == 0 else "bad"
    return (
        f'<span class="{cls}">{rate * 100:.0f}%</span>'
        f' <span class="mut">({g.defects}/{g.determined})</span>'
    )


def _class_gates(model: DashboardModel) -> str:
    """The earned-autonomy panel — the shadow gate's per-class standing.

    Read-only: it renders whether each (repo, loop) class *would* have earned a
    gate move, and the steward-budget that move would reclaim. Nothing acts.
    """
    gates = model.class_gates
    if not gates:
        body = (
            '<p class="note">No classes yet &mdash; a (repo, loop) earns a '
            "gate move from its own track record.</p>"
        )
    else:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(g.repo)}</td>'
            f'<td class="mut">{escape(g.loop)}</td>'
            f"<td>{g.decided} in {g.window_days}d</td>"
            f"<td>{_rate_cell(g.merge_rate)}</td>"
            f"<td>{_defect_cell(g)}</td>"
            f"<td>{_earned_cell(g)}</td>"
            f"<td>{_budget_cell(g)}</td>"
            "</tr>"
            for g in gates
        )
        body = (
            "<table><thead><tr><th>repo</th><th>loop</th><th>decided</th>"
            "<th>rate</th><th>defect</th><th>gate</th><th>budget / week</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    note = (
        '<p class="note">Each <b>class</b> is one loop on one repo &mdash; a '
        "distinct trust unit (a security patch is not a version bump, and they "
        "never share a record). A class earns its gate by <b>triangulation</b> "
        "(&sect;3.8): a high enough <b>approval rate</b> over enough "
        "recently-<b>decided</b> PRs <i>and</i> a low <b>defect rate</b> over "
        "enough confirmed-held merges &mdash; two bearings that fail "
        "differently (the rate to rubber-stamping, the defect rate to a weak "
        "oracle), so they can&rsquo;t both lie at once. The window keeps trust "
        "recent. <b>Budget</b> reads the gate in steward-time: approvals/week "
        "the class costs now &rarr; the reclaimable slice a move hands back. "
        "<b>Advisory only</b>: auto-merge is allowlist-gated and off; sampled "
        "review and adversarial probing are the next legs.</p>"
    )
    return (
        "<section><h2>Earned autonomy &middot; the shadow gate</h2>"
        f"{body}{_why(note)}</section>"
    )


def _verification(model: DashboardModel) -> str:
    v = model.verification
    stats = "".join(
        (
            _stat(v.passed, "CI passed"),
            _stat(v.failed, "CI failed"),
            _stat(v.absent, "no checks"),
            _stat(v.timed_out, "timed out"),
            _stat(v.unknown, "unknown"),
        )
    )
    if v.with_reading == 0:
        note = '<p class="note">No CI readings yet.</p>'
    else:
        note = _why(
            f'<p class="note">A real oracle reported on '
            f"<b>{v.oracle_existed}</b> of {v.with_reading} bumps with a "
            'reading. <span class="mut">&lsquo;no checks&rsquo; means CI was '
            "absent &mdash; not a pass; never conflated.</span>"
            "</p>"
        )
    return (
        "<section><h2>Verification &middot; CI is the oracle</h2>"
        f'<div class="stats">{stats}</div>{note}</section>'
    )


def _reliability(model: DashboardModel) -> str:
    r = model.reliability
    rate = "—" if r.defect_rate is None else f"{r.defect_rate * 100:.0f}%"
    stats = "".join(
        (
            _stat(r.held, "held"),
            _stat(r.broke, "broke"),
            _stat(r.reverted, "reverted"),
            _stat(r.unverified, "unverified"),
            _stat(rate, "defect rate"),
        )
    )
    if r.determined == 0:
        note = (
            '<p class="note">No post-merge outcomes determined yet '
            f"(last {r.window_days}d). A merge is only a *success* once it "
            "holds; until then it&rsquo;s just merged.</p>"
        )
    else:
        note = _why(
            '<p class="note">Did the merge <b>hold</b>? &mdash; the outcome '
            "leg, the only bearing that watches what actually shipped. "
            f"<b>{r.determined}</b> of the recent merges were classifiable; "
            "the defect rate is a <b>floor</b>, not the truth: it sees the "
            "branch&rsquo;s CI and git-reverts, but a <i>manual</i> or "
            "<i>bundled</i> revert (most of them) is invisible. "
            '<span class="mut">&lsquo;unverified&rsquo; means no branch '
            "oracle &mdash; never counted as held.</span></p>"
        )
    return (
        "<section><h2>Reliability &middot; did the merge hold?</h2>"
        f'<div class="stats">{stats}</div>{note}</section>'
    )


def _probes(model: DashboardModel) -> str:
    p = model.probes
    stats = "".join(
        (
            _stat(p.caught, "caught"),
            _stat(p.escaped, "escaped"),
            _stat(p.pending, "pending"),
        )
    )
    if p.total == 0:
        note = (
            '<p class="note">No adversarial probes yet. A <b>canary</b> '
            "&mdash; a deliberately-bad bump &mdash; tests whether the "
            "guardrail still bites; it needs no volume to be informative, so "
            "it carries weight while the rate-based bearings are thin "
            "(&sect;2.11).</p>"
        )
    elif p.escaped:
        note = (
            f'<p class="note"><span class="bad">&#9888; <b>{p.escaped}</b> '
            "canary(s) <b>escaped</b> &mdash; a known-bad bump landed, so the "
            "guardrail has a hole.</span> This is the alarm the probe exists "
            "to raise.</p>"
        )
    else:
        note = _why(
            '<p class="note">Every canary was <b>caught</b> &mdash; the '
            "guardrail refused the planted bad bumps. Probes are scored on a "
            "strict bar (a canary must never merge) and kept <b>out</b> of the "
            "track record and defect rate, so a synthetic failure never "
            "pollutes the real bearings.</p>"
        )
    return (
        "<section><h2>Adversarial probes &middot; does the guardrail bite?</h2>"
        f'<div class="stats">{stats}</div>{note}</section>'
    )


def _judgment(model: DashboardModel) -> str:
    j = model.judgment
    stats = "".join(
        (
            _stat(j.clean, "clean"),
            _stat(j.risky, "risky"),
            _stat(j.unknown, "unknown"),
            _stat(j.none, "no verdict"),
        )
    )
    if j.clean_but_failed or j.flagged_but_passed:
        note = (
            f'<p class="note">Calibration: <b>{j.clean_but_failed}</b> '
            "&lsquo;clean&rsquo; bumps whose CI failed, "
            f"<b>{j.flagged_but_passed}</b> flagged bumps whose CI passed.</p>"
        )
    else:
        note = (
            '<p class="note">The model&rsquo;s only job is the changelog '
            "verdict; the spine proposes the bump either way.</p>"
        )
    return (
        "<section><h2>Model judgment &middot; the one model call</h2>"
        f'<div class="stats">{stats}</div>{_why(note)}</section>'
    )


def _shadow_badge(row: BumpRow) -> str:
    """Whether this open PR *would* auto-merge under its class's grant.

    Advisory: a green 'would auto-merge' means every condition is met and the
    human approval is the only thing still in the way; otherwise the first
    blocker, muted, so the held reason is the thing to fix.
    """
    if row.would_auto_merge:
        return '<span class="ok">would auto-merge</span>'
    reason = row.held_reason or "held"
    return f'<span class="mut">held &middot; {escape(reason)}</span>'


def _gate(model: DashboardModel) -> str:
    now = model.generated_at
    if not model.gate:
        body = '<p class="note">Queue empty &mdash; nothing awaiting you.</p>'
    else:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(row.package)}</td>'
            f"<td>{escape(_ago(row.opened_at, now))}</td>"
            f"<td>{_shadow_badge(row)}</td>"
            f"<td>{_pr_link(row)}</td>"
            "</tr>"
            for row in model.gate
        )
        note = _why(
            '<p class="note">The <b>shadow gate</b> column is advisory &mdash; '
            "froot acts on nothing. A green &lsquo;would auto-merge&rsquo; "
            "means this PR met its class&rsquo;s grant and the human approval "
            "is the only remaining step; it rests on the single CI oracle and "
            "a merge-rate record, which (esp. for a security patch) is not the "
            "same as a confirmed-good or security-reviewed outcome. You still "
            "own every merge.</p>"
        )
        body = (
            "<table><thead><tr><th>package</th><th>waiting</th>"
            "<th>shadow gate</th><th>pr</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>{note}"
        )
    return (
        "<section><h2>Approval gate &middot; what a human owns</h2>"
        f"{body}</section>"
    )


def _bumps(model: DashboardModel) -> str:
    now = model.generated_at
    if not model.bumps:
        body = '<p class="note">No bumps proposed yet.</p>'
    else:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(row.package)}</td>'
            f'<td class="mono mut">{escape(row.from_version or "?")} &rarr; '
            f"{escape(row.to_version)}</td>"
            f"<td>{_tag(row.verdict, _VERDICT_CLASS)}</td>"
            f"<td>{_tag(row.ci, _CI_CLASS)}</td>"
            f"<td>{_state_tag(row.state)}</td>"
            f"<td>{_tag(row.post_merge, _POST_MERGE_CLASS)}</td>"
            f'<td class="mut">{escape(_ago(row.opened_at, now))}</td>'
            f"<td>{_pr_link(row)}</td>"
            "</tr>"
            for row in model.bumps
        )
        body = (
            "<table><thead><tr><th>package</th><th>bump</th><th>verdict</th>"
            "<th>ci</th><th>state</th><th>held?</th><th>opened</th><th>pr</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    return f"<section><h2>Bumps &middot; the detail</h2>{body}</section>"


def _failures(model: DashboardModel) -> str:
    if not model.failures:
        return ""
    now = model.generated_at
    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(_short_id(f.workflow_id))}</td>'
        f"<td>{_state_tag(f.kind)}</td>"
        f'<td class="mut">{escape(f.reason or "—")}</td>'
        f'<td class="mut">{escape(_ago(f.when, now))}</td>'
        "</tr>"
        for f in model.failures
    )
    return (
        "<section><h2>Failures &middot; where the loop did not close</h2>"
        "<table><thead><tr><th>bump</th><th>kind</th><th>reason</th>"
        f"<th>when</th></tr></thead><tbody>{rows}</tbody></table></section>"
    )


def _telem_glance(model: DashboardModel) -> str:
    """The telemetry group's at-a-glance (or an ``unavailable`` marker)."""
    t = model.telemetry
    if not t.available:
        return '<span class="mut">unavailable</span>'
    return _glance(t.total_spans, f"spans / {t.window_days}d")


def _telemetry(model: DashboardModel) -> str:
    """The telemetry body — header lives in the shared loop group above it."""
    t: RunTelemetry = model.telemetry
    if not t.available:
        return (
            "<section>"
            '<p class="note">Unavailable (not configured or unreachable). '
            "GitHub + Temporal carry the dashboard regardless.</p></section>"
        )
    now = model.generated_at
    if t.activities:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(a.name)}</td>'
            f"<td>{a.count}</td>"
            f'<td class="mut">{a.avg_ms:.0f} ms</td>'
            f'<td class="mut">{a.max_ms:.0f} ms</td>'
            "</tr>"
            for a in t.activities
        )
        table = (
            "<table><thead><tr><th>activity</th><th>runs</th><th>avg</th>"
            f"<th>max</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = '<p class="note">No froot spans in the window.</p>'
    summary = (
        f'<p class="note">{t.total_spans} spans &middot; '
        f"{t.error_spans} errored &middot; last activity "
        f"{escape(_ago(t.last_activity, now))} &middot; "
        f"{t.window_days}-day window.</p>"
    )
    return f"<section>{summary}{table}</section>"


def _review_heartbeat(model: DashboardModel) -> str:
    now = model.generated_at
    interval = model.review_interval_seconds

    def line(loop: ReviewLoop) -> str:
        if loop.live:
            dot, tail = "ok", ""
            if loop.last_tick is not None:
                nxt = _aware(loop.last_tick) + timedelta(seconds=interval)
                last = _ago(loop.last_tick, now)
                tail = (
                    f' <span class="mut">&middot; last {last}'
                    f" &middot; next {_until(nxt, now)}</span>"
                )
        else:
            dot = "bad" if loop.status in ("terminated", "none") else "warn"
            tail = f' <span class="mut">&middot; {escape(loop.status)}</span>'
        return (
            f'<div class="row">{_dot(dot)}'
            f'<span class="mono">{escape(loop.repo)}</span>{tail}</div>'
        )

    if not model.review_loops:
        body = (
            '<p class="note">No determinism-review loops running '
            "(the transitive ring watches the @workflow.defn repos).</p>"
        )
    else:
        body = "".join(line(loop) for loop in model.review_loops)
    return f"<section><h2>Is it alive?</h2>{body}</section>"


def _review_record(model: DashboardModel) -> str:
    r = model.review_record
    stats = "".join(
        (
            _stat(r.reviewed, "reviewed"),
            _stat(r.flagged, "flagged"),
            _stat(r.clean, "clean"),
            _stat(r.hazards, "hazards"),
            _stat(r.repos_covered, "repos covered"),
        )
    )
    note = (
        '<p class="note">The transitive ring: it chases first-party helper '
        "calls out of each workflow to catch a hazard the lexical CI kernel "
        "can&rsquo;t see. <b>Advisory</b> &mdash; the blocking gate stays the "
        "kernel&rsquo;s CI check. The hazard-resolved rate (was a flag gone on "
        "a later commit?) is a later loop; it needs accumulated history.</p>"
    )
    return (
        "<section><h2>Track record &middot; the reputation</h2>"
        f'<div class="stats">{stats}</div>{_why(note)}</section>'
    )


def _reviews(model: DashboardModel) -> str:
    now = model.generated_at
    if not model.reviews:
        body = '<p class="note">No PRs reviewed yet.</p>'
    else:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(row.repo)}</td>'
            f"<td>{_review_pr_link(row)}</td>"
            f'<td class="mono mut">{escape((row.head_sha or "")[:7]) or "—"}'
            "</td>"
            f"<td>{_findings_cell(row)}</td>"
            f'<td class="mut">{escape(_ago(row.reviewed_at, now))}</td>'
            "</tr>"
            for row in model.reviews
        )
        body = (
            "<table><thead><tr><th>repo</th><th>pr</th><th>head</th>"
            "<th>findings</th><th>reviewed</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    return f"<section><h2>Reviews &middot; the detail</h2>{body}</section>"


def _footer() -> str:
    return (
        "<footer>"
        "<b>Authority envelope.</b> Stage 1 &mdash; froot holds "
        "<b>write authority</b> only: it opens PRs, a human approves every "
        "merge (commit authority = none). Trust, when any is granted, is "
        "earned, narrow to a single loop on a single repo (a version bump is "
        "not a security patch; they never share a record), conditional on its "
        'environment (judge <span class="mono">gemma4:26b</span>, '
        "lockfile-only regen), revocable, and time-expiring. Today it records "
        "the track "
        "record and renders a <b>shadow gate</b> &mdash; a dry run of the "
        "auto-merge decision that still acts on nothing.<br>"
        "Everything above is derived on this request from GitHub (outcomes) + "
        "Temporal (runs) + ClickHouse (telemetry). froot keeps no database; "
        "reload to recompute."
        "</footer>"
    )


def _pr_link(row: BumpRow) -> str:
    if row.pr_url is None or row.pr_number is None:
        return '<span class="mut">—</span>'
    return f'<a href="{escape(row.pr_url, quote=True)}">#{row.pr_number}</a>'


def _review_pr_link(row: ReviewRow) -> str:
    if row.pr_url is None or row.pr_number is None:
        return '<span class="mut">—</span>'
    return f'<a href="{escape(row.pr_url, quote=True)}">#{row.pr_number}</a>'


def _findings_cell(row: ReviewRow) -> str:
    """A review's findings: 'clean', or the hazard count + rules + comment."""
    if row.findings == 0:
        return '<span class="ok">clean</span>'
    rules = (
        f' <span class="mono mut">{escape(", ".join(row.rules))}</span>'
        if row.rules
        else ""
    )
    comment = (
        f' <a href="{escape(row.comment_url, quote=True)}">comment</a>'
        if row.comment_url
        else ""
    )
    noun = "hazard" if row.findings == 1 else "hazards"
    return f'<span class="bad">{row.findings} {noun}</span>{rules}{comment}'


def _state_tag(state: str) -> str:
    cls = {
        "merged": "ok",
        "open": "warn",
        "closed": "mut",
        "terminated": "bad",
        "failed": "bad",
        "timed_out": "bad",
        "canceled": "warn",
    }.get(state, "mut")
    return f'<span class="{cls}">{escape(state)}</span>'


def _short_id(workflow_id: str) -> str:
    """Drop the ``froot-bump-`` prefix for a readable failures row."""
    return workflow_id.removeprefix("froot-bump-")


def _dep_glance(model: DashboardModel) -> str:
    """The dependency-patch loop's at-a-glance, shown in its header."""
    t = model.track_record
    live = sum(1 for loop in model.scan_loops if loop.live)
    total = len(model.scan_loops)
    rate = "—" if t.merge_rate is None else f"{t.merge_rate * 100:.0f}%"
    items = [
        _glance(f"{live}/{total}", "live"),
        _glance(t.opened, "proposed"),
        _glance(rate, "merged"),
    ]
    if model.class_gates:
        earned = sum(1 for g in model.class_gates if g.earned)
        items.append(_glance(f"{earned}/{len(model.class_gates)}", "earned"))
    if t.open_now:
        items.append(_glance(t.open_now, "awaiting you"))
    return "".join(items)


def _det_glance(model: DashboardModel) -> str:
    """The determinism-review loop's at-a-glance, shown in its header."""
    r = model.review_record
    return "".join(
        (
            _glance(r.repos_covered, "repos"),
            _glance(r.reviewed, "reviewed"),
            _glance(r.hazards, "hazards"),
        )
    )


def _loop(
    title: str,
    sub: str,
    glance: str,
    sections: tuple[str, ...],
    *,
    shared: bool = False,
) -> str:
    """A collapsible group: a prominent header + at-a-glance, collapsed.

    The header (with its at-a-glance) is the ``<summary>``, so a collapsed group
    still shows the headline; expanding reveals the subsections. ``shared`` is a
    non-loop infra group (telemetry) with a lighter, distinct header.
    """
    cls = "loop shared" if shared else "loop"
    head = (
        '<summary class="loophead">'
        f"<h2>{escape(title)}</h2>"
        f'<span class="sub">{sub}</span>'
        f'<span class="glance">{glance}</span>'
        "</summary>"
    )
    return f'<details class="{cls}">{head}{"".join(sections)}</details>'


def page(model: DashboardModel) -> str:
    """Render the whole dashboard as one self-contained HTML document."""
    parts = (
        _header(model),
        _loop(
            "Dependency-patch",
            "npm + uv &middot; scan &rarr; bump &rarr; CI &rarr; merge",
            _dep_glance(model),
            (
                _heartbeat(model),
                _track_record(model),
                _class_gates(model),
                _verification(model),
                _reliability(model),
                _probes(model),
                _judgment(model),
                _gate(model),
                _bumps(model),
                _failures(model),
            ),
        ),
        _loop(
            "Determinism review",
            "the transitive ring &middot; advisory",
            _det_glance(model),
            (
                _review_heartbeat(model),
                _review_record(model),
                _reviews(model),
            ),
        ),
        _loop(
            "Run telemetry",
            "ClickHouse &middot; trace-derived, best-effort",
            _telem_glance(model),
            (_telemetry(model),),
            shared=True,
        ),
        _footer(),
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>froot &middot; read-model</title>"
        f"<style>{_CSS}</style></head><body><main>"
        + "".join(parts)
        + "</main></body></html>"
    )
