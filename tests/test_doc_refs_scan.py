"""The pure doc-refs sweep: what it flags, what it spares, and broken-by-PR.

The signal must be high-precision (the model only confirms), so these pin the
spared cases — an existing target, an external link, a present make target, a
prose backtick — as hard as the flagged ones, plus the PR-deletion provenance
that is doc-refs' reason to exist.
"""

from __future__ import annotations

from froot.policy.doc_refs_scan import DocSource, scan_doc_refs


def _doc(path: str, *lines: str) -> DocSource:
    return DocSource(path=path, lines=tuple(lines))


def test_flags_missing_link_but_spares_existing_and_external():
    docs = (
        _doc(
            "README.md",
            "See [guide](docs/guide.md) and [gone](docs/gone.md).",
            "External [site](https://example.com) is fine.",
        ),
    )
    cands = scan_doc_refs(
        docs, frozenset({"docs/guide.md"}), frozenset(), frozenset()
    )
    assert {c.referent for c in cands} == {"docs/gone.md"}
    assert all(c.kind == "broken-link" for c in cands)


def test_broken_by_pr_when_referent_was_removed_by_the_pr():
    docs = (_doc("README.md", "See [x](src/old.py) for details."),)
    cands = scan_doc_refs(
        docs, frozenset(), frozenset(), frozenset({"src/old.py"})
    )
    assert len(cands) == 1
    assert cands[0].broken_by_pr is True


def test_missing_make_target_flagged_present_one_spared():
    docs = (_doc("README.md", "Run `make build` then `make ghost`."),)
    cands = scan_doc_refs(docs, frozenset(), frozenset({"build"}), frozenset())
    kinds = {(c.kind, c.referent) for c in cands}
    assert ("missing-make", "ghost") in kinds
    assert ("missing-make", "build") not in kinds


def test_backtick_path_missing_flagged_existing_and_prose_spared():
    docs = (
        _doc(
            "README.md",
            "Edit `src/app.py` and `src/missing.py`.",
            "The word `frobnicate` is prose, not a path.",
        ),
    )
    cands = scan_doc_refs(
        docs, frozenset({"src/app.py"}), frozenset(), frozenset()
    )
    refs = {(c.kind, c.referent) for c in cands}
    assert ("missing-path", "src/missing.py") in refs
    assert ("missing-path", "src/app.py") not in refs
    assert not any(c.referent == "frobnicate" for c in cands)


def test_relative_ref_resolves_against_the_docs_own_directory():
    # [api](api.md) inside docs/setup.md must match docs/api.md, not api.md.
    docs = (_doc("docs/setup.md", "See [api](api.md)."),)
    cands = scan_doc_refs(
        docs, frozenset({"docs/api.md"}), frozenset(), frozenset()
    )
    assert cands == ()
