"""The dead-source action transform — pure, the one source edit that is text.

A :class:`~froot.domain.dead_source.DeadFile` deletes a whole file (a filesystem
op the activity does directly). A :class:`~froot.domain.dead_source.DeadExport`
strips the ``export`` modifier off one declaration — a pure string transform
that lives here so the signal (which narrows to the forms this can act on) and
the action (which applies it) share one definition and can never disagree.

The transform is deliberately conservative: it only un-exports an *inline named
declaration* (``export function f``, ``export const f``, ``export class F``,
``export type T`` …) whose declared name matches the symbol the analyzer
flagged. Everything else — clause re-exports (``export { a, b }``), ``export
default``, ``export *`` — returns ``None`` so the caller drops it, because
un-exporting those is not a single-line edit. Un-exporting can't break in-file
use (the symbol stays); cross-module use the analyzer missed surfaces as red CI.
"""

from __future__ import annotations

import re

# An inline export declaration: optional indent, ``export``, optional
# ``async``/``abstract`` modifiers, a declaration keyword, then the declared
# name. ``default`` is absent on purpose — ``export default`` has no plain
# un-exported form. ``rest`` is the line minus the ``export`` token.
_EXPORT_DECL = re.compile(
    r"^(?P<indent>\s*)export\s+"
    r"(?P<rest>(?:async\s+)?(?:abstract\s+)?"
    r"(?:function|const|let|var|class|interface|type|enum)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\b.*)$"
)


def unexport_line(line: str, symbol: str) -> str | None:
    """Strip the ``export`` modifier from ``line``, or ``None`` if it can't.

    Returns the line with ``export `` removed (indentation preserved) when it is
    an inline declaration of ``symbol``; ``None`` when the line is not an
    un-exportable inline declaration of that exact name — which tells the signal
    to drop the candidate and the action that the source shifted under it.

    Args:
        line: The source line at the analyzer's reported position (no trailing
            newline assumed; the caller splits on lines).
        symbol: The exported name the analyzer flagged; must be the one this
            line declares, or the transform refuses (it won't strip the wrong
            export off a line the analyzer mis-located).
    """
    match = _EXPORT_DECL.match(line)
    if match is None or match.group("name") != symbol:
        return None
    return f"{match.group('indent')}{match.group('rest')}"
