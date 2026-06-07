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

_LIGHT = (
    "--fg:#1b1f24;--mut:#586273;--faint:#8b94a3;--line:#e9ebef;--hair:#d6dae1;"
    "--bg:#fcfcfd;--tint:#f5f6f9;--accent:#7c3aed;--ok:#2f7d4f;--warn:#8a6011;"
    "--bad:#b23a2e"
)
_DARK = (
    "--fg:#e7e9ee;--mut:#9aa3b2;--faint:#6b7484;--line:#22262e;--hair:#333a45;"
    "--bg:#0b0d10;--tint:#14171c;--accent:#a78bfa;--ok:#4cae6e;--warn:#d6a23f;"
    "--bad:#e07a6e"
)
# Editorial-minimal "read-model" idiom: structure from hairlines + whitespace +
# type, never from box fills; semantic color rides on dots and the value text,
# not on filled chips. Light is the default; a toggle (data-theme) forces either
# theme, and bare system preference is honored when nothing is forced.
_CSS = f"""
:root{{{_LIGHT};
--serif:"Iowan Old Style",Palatino,Georgia,"Times New Roman",ui-serif,serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
@media(prefers-color-scheme:dark){{:root:not([data-theme]){{{_DARK}}}}}
:root[data-theme=dark]{{{_DARK}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}}
main{{padding:0 clamp(16px,3vw,46px) 72px}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.mono{{font-family:var(--mono);font-size:.92em}}
.serif{{font-family:var(--serif)}}
.mut{{color:var(--mut)}}.ok{{color:var(--ok)}}.warn{{color:var(--warn)}}
.bad{{color:var(--bad)}}.acc{{color:var(--accent)}}
.num{{font-variant-numeric:tabular-nums}}
/* status dot — the one carrier of valence besides the value text itself */
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;flex:none}}
.dot.ok{{background:var(--ok)}}.dot.warn{{background:var(--warn)}}
.dot.bad{{background:var(--bad)}}.dot.mute{{background:var(--faint)}}
.dot.acc{{background:var(--accent)}}
/* header */
header{{display:flex;align-items:center;flex-wrap:wrap;gap:9px 22px;
padding:26px 0 18px;border-bottom:1px solid var(--line)}}
h1{{font-family:var(--serif);font-size:23px;margin:0;letter-spacing:-.01em;
font-weight:600;display:inline-flex;align-items:center;gap:9px}}
.ic{{width:15px;height:15px;flex:none}}
.mark{{width:18px;height:18px;flex:none;color:var(--accent)}}
.hstatus{{display:flex;align-items:center;gap:7px;font-size:13px}}
.hmeta{{margin-left:auto;display:flex;flex-wrap:wrap;align-items:center;
gap:7px 16px;color:var(--mut);font-size:12px}}
.srcs{{display:inline-flex;flex-wrap:wrap;align-items:center;gap:5px 14px}}
.src{{display:inline-flex;align-items:center;gap:6px}}
.themetgl{{background:transparent;border:1px solid var(--line);border-radius:
999px;width:30px;height:30px;cursor:pointer;color:var(--mut);font-size:14px;
line-height:1;display:inline-flex;align-items:center;justify-content:center;
transition:border-color .14s,color .14s}}
.themetgl:hover{{border-color:var(--fg);color:var(--fg)}}
/* tabs (CSS-only radios) */
.tabin{{position:absolute;opacity:0;pointer-events:none}}
nav.tabbar{{display:flex;flex-wrap:wrap;gap:2px 6px;margin:16px 0 0;
border-bottom:1px solid var(--line)}}
nav.tabbar label{{display:inline-flex;align-items:center;gap:8px;cursor:pointer;
padding:10px 4px;margin:0 12px -1px 0;font-size:13.5px;font-weight:600;
color:var(--mut);border-bottom:2px solid transparent;white-space:nowrap;
transition:color .14s}}
nav.tabbar label:hover{{color:var(--fg)}}
nav.tabbar label.aside{{margin-left:auto}}
nav.tabbar label .badge{{font-family:var(--mono);font-weight:500;font-size:11px;
color:var(--faint)}}
.panel{{display:none;padding:26px 0 0;animation:fade .16s ease}}
@keyframes fade{{from{{opacity:.45}}to{{opacity:1}}}}
/* gate hero */
.hero{{display:grid;align-items:start;margin:0 0 4px;gap:22px 40px;
grid-template-columns:minmax(330px,1.05fr) minmax(300px,1fr)}}
@media(max-width:780px){{.hero{{grid-template-columns:1fr}}}}
.heroh{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;
color:var(--mut);font-weight:600;margin:0 0 14px;padding-bottom:7px;
border-bottom:1px solid var(--line);display:flex;align-items:center;gap:7px}}
.gateflow{{display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.bearings{{display:flex;flex-direction:column;min-width:172px;flex:1 1 172px}}
.bearing{{display:flex;align-items:center;justify-content:space-between;gap:12px;
padding:7px 0;border-bottom:1px solid var(--line);font-size:12.5px}}
.bearing:last-child{{border-bottom:0}}
.bearing .bl{{color:var(--mut)}}
.bearing .bv{{display:inline-flex;align-items:center;gap:7px;font-weight:600;
font-variant-numeric:tabular-nums}}
.bearing.armed .bv{{color:var(--faint);font-weight:500}}
.flowarrow{{color:var(--hair);font-size:17px;line-height:1}}
.gatenode{{flex:0 0 auto;text-align:center;padding:2px 6px}}
.gatenode .gl{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;
color:var(--mut);font-weight:600}}
.gatenode .gv{{font-family:var(--serif);font-size:30px;font-weight:600;
line-height:1.1;color:var(--fg);font-variant-numeric:tabular-nums}}
.gatenode .gs{{font-size:11px;color:var(--faint)}}
.outcome{{flex:0 0 auto;display:flex;flex-direction:column;gap:3px}}
.outcome .ot{{display:flex;align-items:center;gap:7px;font-size:15px;
font-weight:700;letter-spacing:.02em}}
.outcome .os{{font-size:11px;color:var(--faint)}}
.outcome.act .ot{{color:var(--ok)}}
.outcome.hold .ot{{color:var(--mut)}}
.caption{{color:var(--mut);font-size:12px;margin:14px 0 0;line-height:1.5;
max-width:62ch}}
/* per-class table inside the hero */
.classes{{width:100%;border-collapse:collapse;font-size:12.5px}}
.classes th,.classes td{{text-align:left;padding:7px 12px 7px 0;
border-bottom:1px solid var(--line);vertical-align:baseline}}
.classes th{{color:var(--faint);font-weight:600;font-size:10.5px;
text-transform:uppercase;letter-spacing:.06em}}
.classes td.r{{font-variant-numeric:tabular-nums}}
.pill{{display:inline-flex;align-items:center;gap:6px;font-size:12px;
font-weight:600}}
.pill.ok{{color:var(--ok)}}.pill.hold{{color:var(--mut);font-weight:500}}
/* metric strip — bare stats, no boxes; a hairline frames the row */
.cards{{display:grid;gap:20px 30px;margin:26px 0 0;padding:18px 0 0;
border-top:1px solid var(--line);
grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}}
.card .n{{font-size:26px;font-weight:600;line-height:1.05;
font-variant-numeric:tabular-nums;letter-spacing:-.01em}}
.card .l{{color:var(--mut);font-size:11px;text-transform:uppercase;
letter-spacing:.05em;font-weight:600;margin-top:5px}}
.card .x{{color:var(--faint);font-size:11.5px;margin-top:3px}}
/* section + detail */
.sec{{margin:30px 0 0}}
.sech{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;
color:var(--mut);font-weight:600;margin:0 0 12px;padding-bottom:7px;
border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}}
.sech .n{{color:var(--faint);font-weight:500;letter-spacing:0;
text-transform:none}}
details.fold{{margin:14px 0 0;border-top:1px solid var(--line)}}
details.fold>summary{{cursor:pointer;list-style:none;padding:11px 0;
font-size:12px;font-weight:600;color:var(--mut);display:flex;
align-items:center;gap:9px}}
details.fold>summary:hover{{color:var(--fg)}}
details.fold>summary::-webkit-details-marker{{display:none}}
details.fold>summary::before{{content:"\\25B8";color:var(--hair);font-size:10px}}
details.fold[open]>summary::before{{content:"\\25BE"}}
details.fold>summary .c{{color:var(--faint);font-weight:500}}
details.fold .body{{padding:2px 0 16px}}
table.data{{width:100%;border-collapse:collapse;font-size:12.5px}}
table.data th,table.data td{{text-align:left;padding:7px 14px 7px 0;
border-bottom:1px solid var(--line);vertical-align:baseline}}
table.data th{{color:var(--faint);font-weight:600;font-size:10.5px;
text-transform:uppercase;letter-spacing:.05em}}
table.data td.r{{font-variant-numeric:tabular-nums;white-space:nowrap}}
.empty{{color:var(--faint);font-size:13px;padding:16px 0}}
.t{{font-size:12px;color:var(--mut)}}
.t.ok{{color:var(--ok)}}.t.warn{{color:var(--warn)}}.t.bad{{color:var(--bad)}}
.cad{{color:var(--mut);font-size:12px;margin:18px 0 0}}
.cad b{{color:var(--fg);font-weight:600}}
footer{{margin:46px 0 0;padding-top:18px;border-top:1px solid var(--line);
color:var(--mut);font-size:12px;line-height:1.7;max-width:92ch}}
footer b{{color:var(--fg);font-weight:600}}
"""

# The page's only script: set the saved theme before first paint (no flash) and
# expose the toggle. Inline + tiny, so the page stays one self-contained file
# with no external request; absent JS, the page simply follows the OS theme.
_THEME_JS = (
    "(function(){var k='froot-theme',r=document.documentElement,"
    "s=localStorage.getItem(k);if(s)r.setAttribute('data-theme',s);"
    "window.__toggleTheme=function(){var c=r.getAttribute('data-theme')||"
    "(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');"
    "var n=c==='dark'?'light':'dark';r.setAttribute('data-theme',n);"
    "localStorage.setItem(k,n);};})();"
)

# A small set of hairline line-icons (inline SVG, stroke = currentColor, so they
# inherit the muted ink and theme themselves). Anchors for the eye — tabs,
# section headers, the wordmark — never on the number strip. Paths are 24x24.
_ICONS = {
    "package": (
        '<path d="M21 8v8a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 3 '
        '16V8a2 2 0 0 1 1-1.73l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8Z"/>'
        '<path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'
    ),
    "shield": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 '
        "4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 "
        '0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
    ),
    "shield-check": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 '
        "4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 "
        '0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>'
    ),
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "layers": (
        '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 '
        '3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
        '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>'
    ),
    "inbox": (
        '<path d="M22 12h-6l-2 3h-4l-2-3H2"/>'
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45'
        '-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
    ),
    "lock": (
        '<rect width="18" height="11" x="3" y="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "lock-open": (
        '<rect width="18" height="11" x="3" y="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 9.9-1"/>'
    ),
    "merge": (
        '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>'
        '<path d="M6 21V9a9 9 0 0 0 9 9"/>'
    ),
}


def _icon(name: str, cls: str = "ic") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


def _wordmark() -> str:
    """The froot mark: a fruit in the accent, with a single green leaf.

    Two-tone on purpose — the one spot color is allowed to be richer. The body
    and stem ride the accent (currentColor); the leaf is the semantic green,
    so the mark reads as a piece of fruit, not a logo abstraction.
    """
    return (
        '<svg class="mark" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="11.5" cy="14.5" r="6.2"/><path d="M11.5 8.3V4"/>'
        '<path d="M11.5 5.5c1.4-2 3.5-2.6 5.8-2.2-.4 2.5-2.5 3.7-5.8 2.2z" '
        'stroke="var(--ok)"/></svg>'
    )


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
    sources = "".join(
        f'<span class="src">{_dot("ok" if s.ok else "bad")}'
        f"{escape(s.name)}</span>"
        for s in model.sources
    )
    return (
        "<header>"
        f"<h1>{_wordmark()}froot</h1>"
        f'<span class="hstatus">{_dot(kind)}{escape(label)}</span>'
        f'<span class="hmeta"><span class="srcs">{sources}</span>'
        '<button class="themetgl" type="button" onclick="__toggleTheme()"'
        ' title="Toggle light / dark"'
        ' aria-label="Toggle light or dark theme">&#9680;</button>'
        "</span></header>"
    )


# ── the gate hero (per loop) ─────────────────────────────────────────────────
def _bearing(label: str, value: str, kind: str, *, armed: bool = False) -> str:
    cls = "bearing armed" if armed else "bearing"
    dot = _dot("mute" if armed else kind)
    return (
        f'<div class="{cls}"><span class="bl">{escape(label)}</span>'
        f'<span class="bv {kind}">{dot}{escape(value)}</span></div>'
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
            f'<div class="outcome act"><div class="ot">{_icon("merge")}'
            "AUTO-MERGE</div>"
            '<div class="os">a class is acting now</div></div>'
        )
    elif earned:
        out = (
            f'<div class="outcome act"><div class="ot">{_icon("lock-open")}'
            "EARNED</div>"
            '<div class="os">acts where allowlisted</div></div>'
        )
    else:
        out = (
            f'<div class="outcome hold"><div class="ot">{_icon("lock")}HOLD'
            "</div><div class="
            '"os">building the record</div></div>'
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
        f'<div><div class="heroh">{_icon("shield-check")}'
        "Earned autonomy &middot; the gate</div>"
        f"{flow}{caption}</div>"
    )


def _class_table(view: LoopView) -> str:
    if not view.class_gates:
        return (
            f'<div><div class="heroh">{_icon("layers")}Classes</div>'
            '<div class="empty">No classes yet &mdash; a (repo, loop) '
            "earns the gate from its own track record.</div></div>"
        )
    rows = "".join(_class_row(g) for g in view.class_gates)
    return (
        f'<div><div class="heroh">{_icon("layers")}Per-class standing</div>'
        '<table class="classes"><thead><tr><th>repo</th><th>rate</th>'
        "<th>defect</th><th>gate</th><th>budget/wk</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _class_row(g: ClassGate) -> str:
    if g.earned:
        gate = f'<span class="pill ok">{_dot("ok")}earned</span>'
    else:
        gate = (
            f'<span class="pill hold">{_dot("mute")}hold</span> '
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
            f'<div class="sec"><div class="sech">{_icon("inbox")}'
            'Approval queue <span class="n">empty</span></div>'
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
        f'<div class="sec"><div class="sech">{_icon("inbox")}Approval queue '
        f'<span class="n">{len(view.gate)} yours</span></div>'
        '<table class="data"><thead><tr><th>package</th><th>&rarr;</th>'
        "<th>gate</th><th>pr</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _queue_badge(row: BumpRow) -> str:
    if row.would_auto_merge:
        return f'<span class="pill ok">{_dot("ok")}would auto-merge</span>'
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
        f'<div class="heroh">{_icon("search")}'
        "Determinism review &middot; the transitive ring"
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
        f'<div class="heroh">{_icon("activity")}Run telemetry '
        "&middot; ClickHouse</div>"
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
    # (tab-id, panel-id, icon, label, badge, panel-html)
    tabs: list[tuple[str, str, str, str, str, str]] = []
    for i, view in enumerate(model.bump_loops):
        pid, tid = f"panel-{i}", f"tab-{i}"
        icon = "shield" if view.loop == "security-patch" else "package"
        tabs.append(
            (
                tid,
                pid,
                icon,
                view.title,
                _loop_badge(view),
                _loop_panel(view, pid, now),
            )
        )
    tabs.append(
        (
            "tab-det",
            "panel-det",
            "search",
            "Determinism review",
            str(model.review_record.reviewed),
            _review_panel(model, "panel-det"),
        )
    )
    tabs.append(
        (
            "tab-tel",
            "panel-tel",
            "activity",
            "Telemetry",
            "live" if model.telemetry.available else "off",
            _telemetry_panel(model, "panel-tel", now),
        )
    )

    inputs, labels, panels, rules = [], [], [], []
    for idx, (tid, pid, icon, label, badge, panel) in enumerate(tabs):
        checked = " checked" if idx == 0 else ""
        inputs.append(
            f'<input class="tabin" type="radio" name="tab" id="{tid}"{checked}>'
        )
        # Telemetry is cross-cutting, not a loop — float it to the far right.
        lcls = ' class="aside"' if tid == "tab-tel" else ""
        labels.append(
            f'<label{lcls} for="{tid}">{_icon(icon)}{escape(label)}'
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
        f"<style>{_CSS}{tabcss}</style>"
        f"<script>{_THEME_JS}</script></head><body>"
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
