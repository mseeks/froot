"""Render the view model to one self-contained HTML page (pure).

All CSS is inline, there is no JavaScript (tabs are CSS-only, via hidden radio
inputs), and the page makes no network request of its own — it is a static,
full-screen projection of an already-computed
:class:`~froot.dashboard.model.DashboardModel`. Every dynamic value is
HTML-escaped at the boundary.

The shape is gate-first: each loop is a tab whose hero is the *gate* — a small
flow of the four trust bearings into the earned/hold decision — over a compact
metric grid and foldable detail. Each loop is a distinct trust class (§3.9), so
each tab is the whole dashboard scoped to one loop; determinism-review and the
cross-cutting run-telemetry get their own tabs.
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
        LoopView,
        ReviewRow,
        RunTelemetry,
    )

_CSS = """
:root{--fg:#13151a;--mut:#6b7280;--faint:#9aa1ac;--line:#e7e9ee;--bg:#fbfbfc;
--panel:#fff;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--accent:#0969da;
--accentbg:#ddf0ff;--chip:#f2f4f7;--node:#eef6ff}
@media(prefers-color-scheme:dark){:root{--fg:#e8eaed;--mut:#9aa1ac;
--faint:#6b7280;--line:#23262d;--bg:#0a0b0d;--panel:#121419;--ok:#3fb950;
--warn:#d29922;--bad:#f85149;--accent:#58a6ff;--accentbg:#10263f;
--chip:#1a1d24;--node:#10263f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
main{padding:0 clamp(16px,3vw,44px) 64px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
.mut{color:var(--mut)}.ok{color:var(--ok)}.warn{color:var(--warn)}
.bad{color:var(--bad)}
/* header */
header{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 20px;
padding:22px 0 16px;border-bottom:1px solid var(--line)}
h1{font-size:19px;margin:0;letter-spacing:-.02em;font-weight:700}
h1 .v{color:var(--faint);font-weight:400;font-size:13px;margin-left:8px}
.hstatus{display:flex;align-items:center;gap:7px;font-size:13px}
.hmeta{margin-left:auto;display:flex;flex-wrap:wrap;gap:6px 16px;
color:var(--mut);font-size:12px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}
.dot.bad{background:var(--bad)}.dot.mute{background:var(--faint)}
/* tabs (CSS-only) */
.tabin{position:absolute;opacity:0;pointer-events:none}
nav.tabbar{display:flex;flex-wrap:wrap;gap:4px;margin:14px 0 0;
border-bottom:1px solid var(--line)}
nav.tabbar label{display:inline-flex;align-items:center;gap:8px;cursor:pointer;
padding:9px 15px;font-size:13px;font-weight:600;color:var(--mut);
border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
nav.tabbar label:hover{color:var(--fg)}
nav.tabbar label .badge{font-weight:600;font-size:11px;color:var(--faint);
background:var(--chip);border-radius:9px;padding:1px 7px}
.panel{display:none;padding:22px 0 0;animation:fade .15s ease}
@keyframes fade{from{opacity:.4}to{opacity:1}}
/* gate hero */
.hero{display:grid;grid-template-columns:minmax(320px,1.1fr) minmax(280px,1fr);
gap:18px 26px;align-items:start;margin:0 0 6px}
@media(max-width:760px){.hero{grid-template-columns:1fr}}
.heroh{font-size:11px;text-transform:uppercase;letter-spacing:.09em;
color:var(--mut);font-weight:700;margin:0 0 12px}
.gateflow{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bearings{display:flex;flex-direction:column;gap:6px;min-width:150px}
.bearing{display:flex;align-items:center;justify-content:space-between;gap:10px;
background:var(--chip);border-radius:7px;padding:6px 10px;font-size:12px}
.bearing .bl{color:var(--mut)}
.bearing .bv{font-weight:600;font-variant-numeric:tabular-nums}
.bearing.armed .bv{color:var(--faint);font-weight:500}
.flowarrow{color:var(--faint);font-size:18px;line-height:1}
.gatenode{flex:0 0 auto;text-align:center;border:2px solid var(--accent);
background:var(--node);border-radius:12px;padding:12px 16px;min-width:96px}
.gatenode .gl{font-size:10px;text-transform:uppercase;letter-spacing:.08em;
color:var(--accent);font-weight:700}
.gatenode .gv{font-size:22px;font-weight:700;line-height:1.15;
font-variant-numeric:tabular-nums}
.gatenode .gs{font-size:11px;color:var(--mut)}
.outcome{flex:0 0 auto;border-radius:10px;padding:11px 15px;text-align:center;
border:1px solid var(--line)}
.outcome .ot{font-size:15px;font-weight:700;letter-spacing:.01em}
.outcome .os{font-size:11px;color:var(--mut);margin-top:1px}
.outcome.act{background:color-mix(in srgb,var(--ok) 12%,transparent);
border-color:color-mix(in srgb,var(--ok) 40%,transparent)}
.outcome.act .ot{color:var(--ok)}
.outcome.hold .ot{color:var(--mut)}
.caption{color:var(--mut);font-size:12px;margin:8px 0 0;line-height:1.45}
/* class table inside the hero */
.classes{width:100%;border-collapse:collapse;font-size:12.5px}
.classes th,.classes td{text-align:left;padding:6px 10px 6px 0;
border-bottom:1px solid var(--line);vertical-align:baseline}
.classes th{color:var(--mut);font-weight:600;font-size:10.5px;
text-transform:uppercase;letter-spacing:.05em}
.classes td.r{font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:11px;font-weight:600;border-radius:20px;
padding:1px 9px}
.pill.ok{color:var(--ok);
background:color-mix(in srgb,var(--ok) 14%,transparent)}
.pill.hold{color:var(--mut);background:var(--chip)}
/* metric cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:10px;margin:22px 0 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:13px 15px}
.card .n{font-size:24px;font-weight:700;line-height:1.05;
font-variant-numeric:tabular-nums}
.card .l{color:var(--mut);font-size:11.5px;margin-top:3px}
.card .x{color:var(--faint);font-size:11px;margin-top:5px}
/* section + detail */
.sec{margin:26px 0 0}
.sech{font-size:11px;text-transform:uppercase;letter-spacing:.08em;
color:var(--mut);font-weight:700;margin:0 0 10px;display:flex;
align-items:baseline;gap:10px}
.sech .n{color:var(--faint);font-weight:600;letter-spacing:0}
details.fold{margin:18px 0 0;border:1px solid var(--line);border-radius:10px;
background:var(--panel)}
details.fold>summary{cursor:pointer;list-style:none;padding:11px 15px;
font-size:12px;font-weight:600;color:var(--fg);display:flex;
align-items:center;gap:9px}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"\\25B8";color:var(--faint);font-size:10px}
details.fold[open]>summary::before{content:"\\25BE"}
details.fold>summary .c{color:var(--faint);font-weight:600}
details.fold .body{padding:0 15px 14px}
table.data{width:100%;border-collapse:collapse;font-size:12.5px}
table.data th,table.data td{text-align:left;padding:6px 12px 6px 0;
border-bottom:1px solid var(--line);vertical-align:top}
table.data th{color:var(--mut);font-weight:600;font-size:10.5px;
text-transform:uppercase;letter-spacing:.04em}
table.data td.r{font-variant-numeric:tabular-nums;white-space:nowrap}
.empty{color:var(--mut);font-size:13px;padding:14px 0;border:1px dashed
var(--line);border-radius:9px;text-align:center;background:var(--panel)}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.t{font-size:11px;border-radius:6px;padding:1px 7px;background:var(--chip);
color:var(--mut)}
.t.ok{color:var(--ok)}.t.warn{color:var(--warn)}.t.bad{color:var(--bad)}
.cad{color:var(--mut);font-size:12px;margin:14px 0 0}
.cad b{color:var(--fg);font-weight:600}
footer{margin:40px 0 0;padding-top:16px;border-top:1px solid var(--line);
color:var(--mut);font-size:12px;line-height:1.65}
footer b{color:var(--fg);font-weight:600}
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
_STATE_CLASS = {"merged": "ok", "closed": "mut", "open": "warn"}
_FAIL_CLASS = {"failed": "bad", "terminated": "warn"}


# ── small formatters ─────────────────────────────────────────────────────────
def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "—"
    secs = (now - _aware(when)).total_seconds()
    if secs < 90:
        return "just now"
    mins = secs / 60
    if mins < 90:
        return f"{round(mins)}m ago"
    hours = mins / 60
    if hours < 36:
        return f"{round(hours)}h ago"
    return f"{round(hours / 24)}d ago"


def _until(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "—"
    secs = (_aware(when) - now).total_seconds()
    if secs <= 0:
        return "due"
    mins = secs / 60
    if mins < 90:
        return f"~{round(mins)}m"
    hours = mins / 60
    if hours < 36:
        return f"~{round(hours)}h"
    return f"~{round(hours / 24)}d"


def _pct(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:.0f}%"


def _dot(kind: str) -> str:
    return f'<span class="dot {kind}"></span>'


def _tag(value: str | None, classes: dict[str, str]) -> str:
    if value is None:
        return '<span class="t">—</span>'
    cls = classes.get(value, "")
    return f'<span class="t {cls}">{escape(value)}</span>'


def _pr_link(row: BumpRow) -> str:
    if row.pr_url is None or row.pr_number is None:
        return '<span class="mut">—</span>'
    return f'<a href="{escape(row.pr_url, quote=True)}">#{row.pr_number}</a>'


def _short_id(workflow_id: str) -> str:
    return escape(workflow_id.removeprefix("froot-bump-"))


# ── header ───────────────────────────────────────────────────────────────────
def _alive(model: DashboardModel) -> tuple[str, str]:
    """Global liveness dot + label across every loop."""
    live = sum(1 for x in model.scan_loops if x.live) + sum(
        1 for x in model.review_loops if x.live
    )
    total = len(model.scan_loops) + len(model.review_loops)
    if total == 0:
        return "mute", "no loops configured"
    kind = "ok" if live == total else ("warn" if live else "bad")
    return kind, f"{live}/{total} loops live"


def _header(model: DashboardModel) -> str:
    kind, label = _alive(model)
    sources = " ".join(
        f"{_dot('ok' if s.ok else 'bad')}{escape(s.name)}"
        for s in model.sources
    )
    return (
        "<header>"
        '<h1>froot<span class="v mono">gemma4:12b</span></h1>'
        f'<span class="hstatus">{_dot(kind)}{escape(label)}</span>'
        f'<span class="hmeta"><span>{sources}</span>'
        f"<span>{len(model.repos_configured)} repos</span>"
        f"<span>built {_ago(model.generated_at, model.generated_at)}"
        " · reload to recompute</span></span>"
        "</header>"
    )


# ── the gate hero (per loop) ─────────────────────────────────────────────────
def _bearing(label: str, value: str, kind: str, *, armed: bool = False) -> str:
    cls = "bearing armed" if armed else "bearing"
    return (
        f'<div class="{cls}"><span class="bl">{escape(label)}</span>'
        f'<span class="bv {kind}">{escape(value)}</span></div>'
    )


def _gate_hero(view: LoopView) -> str:
    t, rel, pr = view.track_record, view.reliability, view.probes
    earned = sum(1 for g in view.class_gates if g.earned)
    total = len(view.class_gates)
    acting = any(r.would_auto_merge for r in view.gate)
    # The four bearings: rate + defect come from the record; the adversarial
    # probe (canary) is the loop's escaped-count; the deep review runs per-PR at
    # the merge, so it is shown armed (always-on), not a record figure.
    rate_ok = "ok" if (t.merge_rate or 0) >= 0.95 else "warn"
    defect_ok = "ok" if not rel.defect_rate else "bad"
    probe_ok = "ok" if pr.escaped == 0 else "bad"
    bearings = "".join(
        (
            _bearing(
                "approval rate",
                _pct(t.merge_rate),
                rate_ok if t.merge_rate is not None else "mut",
            ),
            _bearing(
                "defect rate",
                _pct(rel.defect_rate),
                defect_ok if rel.defect_rate is not None else "mut",
            ),
            _bearing(
                "probe",
                f"{pr.escaped} escaped" if pr.total else "none",
                probe_ok if pr.total else "mut",
            ),
            _bearing("deep review", "armed", "mut", armed=True),
        )
    )
    if total == 0:
        node = (
            '<div class="gatenode"><div class="gl">gate</div>'
            '<div class="gv">—</div><div class="gs">no class yet</div></div>'
        )
    else:
        node = (
            f'<div class="gatenode"><div class="gl">earned</div>'
            f'<div class="gv">{earned}/{total}</div>'
            '<div class="gs">classes</div></div>'
        )
    if acting:
        out = (
            '<div class="outcome act"><div class="ot">AUTO-MERGE</div>'
            '<div class="os">a class is acting now</div></div>'
        )
    elif earned:
        out = (
            '<div class="outcome act"><div class="ot">EARNED</div>'
            '<div class="os">acts where allowlisted</div></div>'
        )
    else:
        out = (
            '<div class="outcome hold"><div class="ot">HOLD</div>'
            '<div class="os">building the record</div></div>'
        )
    flow = (
        '<div class="gateflow">'
        f'<div class="bearings">{bearings}</div>'
        '<div class="flowarrow">&rarr;</div>'
        f"{node}"
        '<div class="flowarrow">&rarr;</div>'
        f"{out}</div>"
    )
    caption = (
        '<p class="caption">A class earns the gate by triangulation: a high '
        "<b>approval rate</b> and a low <b>defect rate</b>, over enough "
        "evidence. Two further legs guard the live merge — an adversarial "
        "<b>probe</b> and an independent <b>deep review</b> at merge. "
        "Auto-merge is allowlist-gated (off by default).</p>"
    )
    return (
        '<div><div class="heroh">Earned autonomy &middot; the gate</div>'
        f"{flow}{caption}</div>"
    )


def _class_table(view: LoopView) -> str:
    if not view.class_gates:
        return (
            '<div><div class="heroh">Classes</div>'
            '<div class="empty">No classes yet &mdash; a (repo, loop) '
            "earns the gate from its own track record.</div></div>"
        )
    rows = "".join(_class_row(g) for g in view.class_gates)
    return (
        '<div><div class="heroh">Per-class standing</div>'
        '<table class="classes"><thead><tr><th>repo</th><th>rate</th>'
        "<th>defect</th><th>gate</th><th>budget/wk</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _class_row(g: ClassGate) -> str:
    if g.earned:
        gate = '<span class="pill ok">earned</span>'
    else:
        gate = (
            f'<span class="pill hold">hold</span> '
            f'<span class="mut">{escape(g.blocker or "")}</span>'
        )
    defect = "—" if g.defect_rate is None else _pct(g.defect_rate)
    budget = (
        f"{g.reclaim_per_week:.1f}/{g.approvals_per_week:.1f}"
        if g.approvals_per_week
        else "—"
    )
    return (
        f'<tr><td class="mono">{escape(g.repo)}</td>'
        f'<td class="r">{_pct(g.merge_rate)}</td>'
        f'<td class="r">{escape(defect)}</td>'
        f"<td>{gate}</td>"
        f'<td class="r mut">{escape(budget)}</td></tr>'
    )


# ── metric cards (per loop) ──────────────────────────────────────────────────
def _card(n: object, label: str, extra: str = "", kind: str = "") -> str:
    x = f'<div class="x">{extra}</div>' if extra else ""
    return (
        f'<div class="card"><div class="n {kind}">{escape(str(n))}</div>'
        f'<div class="l">{escape(label)}</div>{x}</div>'
    )


def _loop_cards(view: LoopView) -> str:
    t, v, rel, j, pr = (
        view.track_record,
        view.verification,
        view.reliability,
        view.judgment,
        view.probes,
    )
    defects = rel.broke + rel.reverted
    cards = [
        _card(
            t.opened,
            "proposed",
            f"{t.merged} merged · {t.closed_unmerged} closed",
        ),
        _card(_pct(t.merge_rate), "approval rate", "the first bearing"),
        _card(
            t.open_now,
            "awaiting you",
            "open, needs a human",
            "warn" if t.open_now else "",
        ),
        _card(
            _pct(rel.defect_rate) if rel.determined else "—",
            "defect rate",
            f"{rel.held} held · {defects} broke",
            "bad" if defects else "",
        ),
        _card(
            f"{v.passed}/{v.oracle_existed}" if v.oracle_existed else "—",
            "CI passed",
            "the oracle",
        ),
        _card(
            pr.escaped if pr.total else "0",
            "probes escaped",
            f"{pr.caught} caught" if pr.total else "no probes yet",
            "bad" if pr.escaped else "",
        ),
        _card(
            j.clean,
            "clean verdicts",
            f"{j.clean_but_failed} mis-judged"
            if j.clean_but_failed
            else "judge calibrated",
        ),
        _card(rel.held, "merges held", "post-merge, stayed green"),
    ]
    return f'<div class="cards">{"".join(cards)}</div>'


# ── detail tables ────────────────────────────────────────────────────────────
def _cadence(view: LoopView, now: datetime) -> str:
    live = sum(1 for s in view.scan_loops if s.live)
    total = len(view.scan_loops)
    nxt = ""
    last = max(
        (s.last_tick for s in view.scan_loops if s.last_tick is not None),
        default=None,
    )
    if last is not None:
        due = last + timedelta(seconds=view.scan_interval_seconds)
        nxt = f" &middot; next {escape(_until(due, now))}"
    every = round(view.scan_interval_seconds / 3600, 1)
    return (
        f'<p class="cad">Scan loop &middot; <b>{live}/{total}</b> live '
        f"&middot; every <b>{every}h</b>{nxt}</p>"
    )


def _bumps_fold(view: LoopView) -> str:
    if not view.bumps:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(r.package)}</td>'
        f'<td class="mono mut">{escape(r.to_version)}</td>'
        f"<td>{_tag(r.state, _STATE_CLASS)}</td>"
        f"<td>{_tag(r.verdict, _VERDICT_CLASS)}</td>"
        f"<td>{_tag(r.ci, _CI_CLASS)}</td>"
        f"<td>{_tag(r.post_merge, _POST_MERGE_CLASS)}</td>"
        f"<td>{_pr_link(r)}</td>"
        "</tr>"
        for r in view.bumps
    )
    return (
        '<details class="fold"><summary>Bumps '
        f'<span class="c">{len(view.bumps)}</span></summary><div class="body">'
        '<table class="data"><thead><tr><th>package</th><th>&rarr;</th>'
        "<th>state</th><th>verdict</th><th>ci</th><th>post-merge</th>"
        "<th>pr</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


def _failures_fold(view: LoopView) -> str:
    if not view.failures:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="mono">{_short_id(f.workflow_id)}</td>'
        f"<td>{_tag(f.kind, _FAIL_CLASS)}</td>"
        f'<td class="mut">{escape(f.reason or "—")}</td>'
        "</tr>"
        for f in view.failures
    )
    return (
        '<details class="fold"><summary class="bad">Failures '
        f'<span class="c">{len(view.failures)}</span></summary>'
        '<div class="body"><table class="data"><thead><tr><th>bump</th>'
        "<th>kind</th><th>reason</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


# ── panels ───────────────────────────────────────────────────────────────────
def _loop_panel(view: LoopView, pid: str, now: datetime) -> str:
    queue = _queue_sec(view)
    return (
        f'<section class="panel" id="{pid}">'
        f'<div class="hero">{_gate_hero(view)}{_class_table(view)}</div>'
        f"{_loop_cards(view)}"
        f"{queue}"
        f"{_cadence(view, now)}"
        f"{_bumps_fold(view)}{_failures_fold(view)}"
        "</section>"
    )


def _queue_sec(view: LoopView) -> str:
    if not view.gate:
        return (
            '<div class="sec"><div class="sech">Approval queue '
            '<span class="n">empty</span></div>'
            '<div class="empty">Nothing awaiting you.</div></div>'
        )
    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(r.package)}</td>'
        f'<td class="mono mut">{escape(r.to_version)}</td>'
        f"<td>{_queue_badge(r)}</td>"
        f"<td>{_pr_link(r)}</td>"
        "</tr>"
        for r in view.gate
    )
    return (
        '<div class="sec"><div class="sech">Approval queue '
        f'<span class="n">{len(view.gate)} yours</span></div>'
        '<table class="data"><thead><tr><th>package</th><th>&rarr;</th>'
        "<th>gate</th><th>pr</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _queue_badge(row: BumpRow) -> str:
    if row.would_auto_merge:
        return '<span class="pill ok">would auto-merge</span>'
    reason = row.held_reason or "held"
    return f'<span class="mut">held &middot; {escape(reason)}</span>'


def _review_panel(model: DashboardModel, pid: str) -> str:
    r = model.review_record
    live = sum(1 for x in model.review_loops if x.live)
    haz = "bad" if r.hazards else ""
    cards = (
        '<div class="cards">'
        f"{_card(r.repos_covered, 'repos covered')}"
        f"{_card(f'{live}/{len(model.review_loops)}', 'loops live')}"
        f"{_card(r.reviewed, 'reviewed', f'{r.flagged} flagged')}"
        f"{_card(r.hazards, 'hazards', 'transitive', haz)}"
        "</div>"
    )
    body = (
        '<div class="empty">No PRs reviewed yet.</div>'
        if not model.reviews
        else _reviews_table(model.reviews)
    )
    note = (
        '<p class="caption">The transitive ring — advisory. It '
        "re-derives each open PR's reachable determinism hazards and "
        "comments; it never blocks a merge.</p>"
    )
    every = round(model.review_interval_seconds / 60, 1)
    cad = (
        f'<p class="cad">Review loop &middot; <b>{live}</b> live &middot; '
        f"every <b>{every}m</b></p>"
    )
    return (
        f'<section class="panel" id="{pid}">'
        '<div class="heroh">Determinism review &middot; the transitive ring'
        f"</div>{note}{cards}{cad}"
        f'<div class="sec"><div class="sech">Reviews '
        f'<span class="n">{len(model.reviews)}</span></div>{body}</div>'
        "</section>"
    )


def _reviews_table(reviews: tuple[ReviewRow, ...]) -> str:
    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(row.repo)}</td>'
        f"<td>{_review_pr_link(row)}</td>"
        f"<td>{_findings_cell(row)}</td>"
        f'<td class="mono mut">{escape(", ".join(row.rules) or "—")}</td>'
        "</tr>"
        for row in reviews
    )
    return (
        '<table class="data"><thead><tr><th>repo</th><th>pr</th>'
        "<th>findings</th><th>rules</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _review_pr_link(row: ReviewRow) -> str:
    if row.pr_url is None or row.pr_number is None:
        return '<span class="mut">—</span>'
    return f'<a href="{escape(row.pr_url, quote=True)}">#{row.pr_number}</a>'


def _findings_cell(row: ReviewRow) -> str:
    if row.findings == 0:
        return '<span class="ok">clean</span>'
    label = "hazard" if row.findings == 1 else "hazards"
    link = ""
    if row.comment_url:
        link = f' <a href="{escape(row.comment_url, quote=True)}">comment</a>'
    return f'<span class="bad">{row.findings} {label}</span>{link}'


def _telemetry_panel(model: DashboardModel, pid: str, now: datetime) -> str:
    tel: RunTelemetry = model.telemetry
    if not tel.available:
        body = (
            '<div class="empty">Unavailable &mdash; ClickHouse off or no '
            "froot traces in the window.</div>"
        )
    else:
        rows = "".join(
            "<tr>"
            f'<td class="mono">{escape(a.name)}</td>'
            f'<td class="r">{a.count}</td>'
            f'<td class="r">{a.avg_ms:.0f} ms</td>'
            f'<td class="r mut">{a.max_ms:.0f} ms</td>'
            "</tr>"
            for a in tel.activities
        )
        last = f"last {_ago(tel.last_activity, now)}"
        err = "bad" if tel.error_spans else ""
        head = (
            '<div class="cards">'
            f"{_card(tel.total_spans, 'spans', last)}"
            f"{_card(tel.error_spans, 'errors', 'in the window', err)}"
            f"{_card(f'{tel.window_days}d', 'window')}</div>"
        )
        table = (
            '<div class="sec"><div class="sech">Activity latency</div>'
            '<table class="data"><thead><tr><th>activity</th><th>runs</th>'
            "<th>avg</th><th>max</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
        body = head + table
    note = (
        '<p class="caption">Cross-cutting run telemetry from ClickHouse '
        "(trace-derived, best-effort) — latency per activity across "
        "every loop.</p>"
    )
    return (
        f'<section class="panel" id="{pid}">'
        '<div class="heroh">Run telemetry &middot; ClickHouse</div>'
        f"{note}{body}</section>"
    )


# ── tabs + page ──────────────────────────────────────────────────────────────
def _loop_badge(view: LoopView) -> str:
    earned = sum(1 for g in view.class_gates if g.earned)
    if view.class_gates and earned:
        return f"{earned}/{len(view.class_gates)} earned"
    if view.track_record.open_now:
        return f"{view.track_record.open_now} open"
    return str(view.track_record.opened)


def page(model: DashboardModel) -> str:
    """Render the whole dashboard as one self-contained HTML document."""
    now = model.generated_at
    # (tab-id, panel-id, label, badge, panel-html)
    tabs: list[tuple[str, str, str, str, str]] = []
    for i, view in enumerate(model.bump_loops):
        pid, tid = f"panel-{i}", f"tab-{i}"
        tabs.append(
            (
                tid,
                pid,
                view.title,
                _loop_badge(view),
                _loop_panel(view, pid, now),
            )
        )
    tabs.append(
        (
            "tab-det",
            "panel-det",
            "Determinism review",
            str(model.review_record.reviewed),
            _review_panel(model, "panel-det"),
        )
    )
    tabs.append(
        (
            "tab-tel",
            "panel-tel",
            "Telemetry",
            "live" if model.telemetry.available else "off",
            _telemetry_panel(model, "panel-tel", now),
        )
    )

    inputs, labels, panels, rules = [], [], [], []
    for idx, (tid, pid, label, badge, panel) in enumerate(tabs):
        checked = " checked" if idx == 0 else ""
        inputs.append(
            f'<input class="tabin" type="radio" name="tab" id="{tid}"{checked}>'
        )
        labels.append(
            f'<label for="{tid}">{escape(label)}'
            f'<span class="badge">{escape(badge)}</span></label>'
        )
        panels.append(panel)
        rules.append(f"#{tid}:checked~main #{pid}{{display:block}}")
        rules.append(
            f"#{tid}:checked~main nav.tabbar label[for={tid}]"
            "{color:var(--fg);border-bottom-color:var(--accent)}"
        )
    tabcss = "".join(rules)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>froot &middot; read-model</title>"
        f"<style>{_CSS}{tabcss}</style></head><body>"
        + "".join(inputs)
        + "<main>"
        + _header(model)
        + f'<nav class="tabbar">{"".join(labels)}</nav>'
        + "".join(panels)
        + _footer()
        + "</main></body></html>"
    )


def _footer() -> str:
    return (
        "<footer><b>Authority envelope.</b> froot opens PRs everywhere and "
        "auto-merges only on an allowlisted repo where a class has earned its "
        "gate (the allowlist is empty by default, so commit authority is none "
        "until a steward opts in). Trust is earned, narrow to one loop on one "
        "repo, conditional on its environment "
        '(<span class="mono">gemma4:12b</span>), revocable, and time-expiring. '
        "Everything here is derived per request from GitHub + Temporal + "
        "ClickHouse; froot keeps no database.</footer>"
    )
