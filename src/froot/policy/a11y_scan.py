"""The pure source-level accessibility sweep — the mechanical signal.

A dialect-aware regex pass over a checked-out template's lines, flagging four
high-signal risk patterns the runtime axe checks can't see at the *source*
level:

* ``role="img"`` elements / inline ``<svg>`` with no obvious accessible name,
* labelable form controls (``<input>``/``<textarea>``/``<select>``),
* a click handler (Vue ``@click`` / JSX ``onClick``) on a *non-interactive*
  element (``<div>``/``<span>``/…) with no keyboard path, and
* ``<img>`` / ``:src`` image bindings.

It is deterministic and side-effect-free — the I/O (reading files) is the
web-source adapter's job, and each flagged candidate is handed to the model to
confirm *in context*. The scan resolves only what it can do precisely (the
id-wired ``<label for>`` case); the adjacent-line judgments are the model's
frontier. This is the "spine-heavy, model-thin" split: the regex does the
finding, the model only adjudicates the ambiguity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from froot.domain.a11y import A11yCandidate, A11yKind, Dialect

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class WebSource:
    """One checked-out template, read into memory for the pure scan."""

    path: str
    dialect: Dialect
    lines: tuple[str, ...]


# Elements that are natively interactive/focusable — a click on these is
# keyboard-operable for free, so it is not a "clickable non-button" risk.
_INTERACTIVE_TAGS = frozenset(
    {
        "button",
        "a",
        "input",
        "select",
        "textarea",
        "summary",
        "label",
        "details",
        "option",
    }
)

_ROLE_IMG = re.compile(r"""\brole=(["'])img\1""")
# The element regexes require a delimiter after the tag name so a hyphenated
# custom element (``<input-mask>``, ``<svg-icon>``) isn't mistaken for the
# native one.
_SVG_OPEN = re.compile(r"<svg(?=[\s/>])")
_LABELABLE = re.compile(r"<(input|textarea|select)(?=[\s/>])")
_IMG = re.compile(r"<img(?=[\s/>])")
_OPEN_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)")
_ID_ATTR = re.compile(r"""\bid=(["'])([^"']+)\1""")
# A real <label> wired to a control's id (not an <output for> or a stray for=).
_LABEL_FOR = r"<label\b[^>]*\b(?:for|htmlFor)=(['\"]){ident}\1"
# Vue ``@click``/``@click.stop`` AND the long form ``v-on:click`` vs JSX
# ``onClick`` — the one dialect seam.
_VUE_CLICK = re.compile(r"(?:@click|v-on:click)(?:\.[a-z]+)*\s*=")
_JSX_CLICK = re.compile(r"\bonClick\s*=")
# HTML and JSX comments — stripped before the label search so a commented-out
# <label> doesn't read as a live wiring.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_JSX_COMMENT = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)

# How far back to look for the opening tag a handler sits under (templates are
# prettier-split, so the handler is often a few lines below its ``<tag``).
_TAG_LOOKBACK = 12
# How many lines on each side of a hit the model gets as context.
_CONTEXT_RADIUS = 16
_SNIPPET_MAX = 140


def dialect_for(path: str) -> Dialect | None:
    """The dialect for a file path, or ``None`` if it is not a template.

    ``.vue`` is Vue; ``.jsx``/``.tsx`` are JSX/React. Everything else (stores,
    plain ``.ts``/``.js``, styles) is out of scope for a source-level a11y pass.
    """
    lower = path.lower()
    if lower.endswith(".vue"):
        return "vue"
    if lower.endswith((".jsx", ".tsx")):
        return "jsx"
    return None


def _owning_tag(lines: tuple[str, ...], idx: int, col: int) -> str | None:
    """The tag whose opening element a handler at ``(idx, col)`` sits inside.

    An attribute belongs to the nearest *unclosed* opening tag: take the source
    up to the handler, drop everything through the last ``>`` (which closed the
    previous tag), and the first ``<tag`` left is the owner. This avoids blaming
    a wrapper's handler on an interactive child that already closed —
    ``<div @click><a>x</a></div>`` is the div, not the a — which a naive
    "last tag on the line" walk gets wrong (a silent false negative).
    """
    head = lines[max(0, idx - _TAG_LOOKBACK) : idx]
    prefix = ("\n".join(head) + "\n" if head else "") + lines[idx][:col]
    region = prefix.rsplit(">", 1)[-1]
    m = _OPEN_TAG.search(region)
    return m.group(1) if m else None


def _context(lines: tuple[str, ...], idx: int) -> str:
    """A window of source around line ``idx`` — the model's evidence."""
    lo = max(0, idx - _CONTEXT_RADIUS)
    hi = min(len(lines), idx + _CONTEXT_RADIUS + 1)
    return "\n".join(lines[lo:hi])


def _strip_comments(text: str) -> str:
    """Blank out HTML (``<!-- -->``) and JSX (``{/* */}``) comment spans."""
    return _JSX_COMMENT.sub(" ", _HTML_COMMENT.sub(" ", text))


def _label_wired(label_text: str, hit_line: str) -> bool:
    """Whether a real ``<label for>`` names this control's id.

    The one distant case the scan resolves precisely: a ``<label for="x">`` (or
    ``htmlFor``) anywhere naming an ``<input id="x">``. Restricted to
    an actual ``<label>`` element over comment-stripped source — an
    ``<output for>``, a stray ``for=``, or a commented-out label does NOT name a
    control, and since a ``True`` here is asserted to the model it must not lie.
    An ``aria-labelledby`` on the control itself is local, so the model reads it
    straight from the context window; it is not chased here.
    """
    m = _ID_ATTR.search(hit_line)
    if m is None:
        return False
    ident = re.escape(m.group(2))
    return bool(re.search(_LABEL_FOR.format(ident=ident), label_text))


def scan_sources(sources: Sequence[WebSource]) -> tuple[A11yCandidate, ...]:
    """Flag every a11y risk site across the given templates (deterministic)."""
    candidates: list[A11yCandidate] = []
    for source in sources:
        candidates.extend(_scan_one(source))
    return tuple(candidates)


def _scan_one(source: WebSource) -> list[A11yCandidate]:
    lines = source.lines
    label_text = _strip_comments("\n".join(lines))
    click = _VUE_CLICK if source.dialect == "vue" else _JSX_CLICK
    out: list[A11yCandidate] = []

    def add(line_no: int, kind: A11yKind, detail: str, snippet: str) -> None:
        out.append(
            A11yCandidate(
                file=source.path,
                line=line_no + 1,
                kind=kind,
                dialect=source.dialect,
                detail=detail,
                snippet=snippet,
                context=_context(lines, line_no),
                label_wired=(
                    _label_wired(label_text, lines[line_no])
                    if kind == "labelable"
                    else False
                ),
            )
        )

    for i, line in enumerate(lines):
        snippet = line.strip()[:_SNIPPET_MAX]
        if _ROLE_IMG.search(line):
            add(i, "role-img", "", snippet)
        if _SVG_OPEN.search(line):
            add(i, "svg", "", snippet)
        ctrl = _LABELABLE.search(line)
        if ctrl is not None:
            add(i, "labelable", f"<{ctrl.group(1)}>", snippet)
        click_m = click.search(line)
        if click_m is not None:
            tag = _owning_tag(lines, i, click_m.start())
            if tag and tag[:1].islower() and tag not in _INTERACTIVE_TAGS:
                add(i, "clickable-nonbutton", f"<{tag}>", snippet)
        if _IMG.search(line):
            add(i, "image", "", snippet)
    return out
