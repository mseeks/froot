"""The pure documentation-reference sweep — the mechanical signal.

A deterministic pass over a checked-out Markdown doc's lines, flagging three
reference-integrity defects:

* a relative Markdown link ``[..](path)`` whose target does not exist,
* a backtick-quoted file path (e.g. ``dir/x.py``) that does not exist, and
* a ``make <target>`` mention whose Makefile target is gone.

Deterministic and side-effect-free — the I/O (reading the docs, indexing the
repo's paths, parsing the Makefile) is the doc-source adapter's job, and each
hit is handed to the model to confirm *in context* (a broken-looking ref can be
intentional or historical). External links (``http``, ``#``, ``mailto:``) are
never flagged. Spine-heavy, model-thin: the regex finds, the model adjudicates.

A relative ref is resolved against both the repo root and the doc's own
directory, so ``[api](api.md)`` in ``docs/setup.md`` matches ``docs/api.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from froot.domain.doc_refs import DocRefCandidate, DocRefKind

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class DocSource:
    """One checked-out Markdown doc, read into memory for the pure scan.

    Attributes:
        path: The doc's repo-relative POSIX path.
        lines: The doc's lines (trailing newlines stripped).
    """

    path: str
    lines: tuple[str, ...]


_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK = re.compile(r"`([^`]+)`")
# File extensions that mark a backtick span as a path even without a slash.
_PATH_EXTS = frozenset(
    {
        "py",
        "ts",
        "tsx",
        "js",
        "jsx",
        "vue",
        "toml",
        "md",
        "txt",
        "lock",
        "cfg",
        "ini",
        "sh",
        "json",
        "yaml",
        "yml",
        "css",
        "html",
        "cjs",
        "mjs",
    }
)
_SNIPPET_MAX = 140


def _looks_like_path(text: str) -> bool:
    """Whether a backtick span is a repo file path (not prose or a CLI flag)."""
    if text.startswith("-") or not re.fullmatch(r"[\w./-]+", text):
        return False
    return "/" in text or text.rsplit(".", 1)[-1] in _PATH_EXTS


def _norm(path: str) -> str:
    """Collapse ``.``/``..`` segments to a repo-relative POSIX path (no I/O)."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _doc_dir(path: str) -> str:
    """The directory a doc lives in (``""`` for a repo-root doc)."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _resolve(
    ref: str,
    doc_dir: str,
    existing: frozenset[str],
    pr_removed: frozenset[str],
) -> tuple[bool, bool]:
    """Resolve a relative ref to ``(exists, broken_by_pr)``.

    Checked against both the repo-root and doc-relative normalizations, so a ref
    counts as existing (or PR-removed) under either reading.
    """
    root_rel = _norm(ref)
    doc_rel = _norm(f"{doc_dir}/{ref}" if doc_dir else ref)
    exists = root_rel in existing or doc_rel in existing
    broken_by_pr = root_rel in pr_removed or doc_rel in pr_removed
    return exists, broken_by_pr


def scan_doc_refs(
    sources: Sequence[DocSource],
    existing_paths: frozenset[str],
    make_targets: frozenset[str],
    pr_removed: frozenset[str],
) -> tuple[DocRefCandidate, ...]:
    """Flag every missing doc reference across the docs (deterministic)."""
    out: list[DocRefCandidate] = []
    for source in sources:
        out.extend(_scan_one(source, existing_paths, make_targets, pr_removed))
    return tuple(out)


def _scan_one(
    source: DocSource,
    existing: frozenset[str],
    make_targets: frozenset[str],
    pr_removed: frozenset[str],
) -> list[DocRefCandidate]:
    doc_dir = _doc_dir(source.path)
    out: list[DocRefCandidate] = []

    def add(
        line_no: int, kind: DocRefKind, referent: str, by_pr: bool, snip: str
    ) -> None:
        out.append(
            DocRefCandidate(
                file=source.path,
                line=line_no + 1,
                kind=kind,
                referent=referent,
                snippet=snip,
                broken_by_pr=by_pr,
            )
        )

    for i, line in enumerate(source.lines):
        snippet = line.strip()[:_SNIPPET_MAX]
        for link in _LINK.finditer(line):
            tgt = link.group(1).split()[0].split("#")[0].split("?")[0]
            if not tgt or tgt.startswith(("http", "#", "mailto:")):
                continue
            exists, by_pr = _resolve(tgt, doc_dir, existing, pr_removed)
            if not exists:
                add(i, "broken-link", tgt, by_pr, snippet)
        for span in _BACKTICK.finditer(line):
            inner = span.group(1).strip()
            if inner.startswith("make "):
                parts = inner.split()
                target = parts[1] if len(parts) > 1 else ""
                if target and target not in make_targets:
                    add(i, "missing-make", target, False, snippet)
            elif _looks_like_path(inner):
                exists, by_pr = _resolve(inner, doc_dir, existing, pr_removed)
                if not exists:
                    add(i, "missing-path", inner, by_pr, snippet)
    return out
