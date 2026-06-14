"""The doc-source adapter's I/O: ``.md`` filtering, path indexing, make targets.

Thin I/O, but with real logic the pure scan depends on — directory indexing (so
a link to a folder resolves), skip-dir pruning (so node_modules doesn't bloat or
slow the index), and Makefile-target parsing. tmp_path stands in for a checkout.
"""

from __future__ import annotations

from pathlib import Path

from froot.adapters.doc_source import (
    index_paths,
    load_doc_sources,
    make_targets,
)


def test_load_doc_sources_reads_md_and_skips_the_rest(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Title\nbody\n")
    (tmp_path / "code.py").write_text("x = 1\n")
    sources = load_doc_sources(tmp_path, ["README.md", "code.py", "missing.md"])
    assert [s.path for s in sources] == [
        "README.md"
    ]  # non-.md + absent dropped
    assert sources[0].lines == ("# Title", "body")


def test_index_paths_includes_dirs_and_prunes_skip_dirs(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("")
    nested = tmp_path / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("")
    idx = index_paths(tmp_path)
    assert "src/app.py" in idx
    assert "src" in idx  # dirs indexed so a link to a folder resolves
    assert not any(p.startswith("node_modules") for p in idx)  # pruned


def test_make_targets_parses_names_and_is_empty_without_a_makefile(
    tmp_path: Path,
):
    assert make_targets(tmp_path) == frozenset()
    (tmp_path / "Makefile").write_text(
        "build:\n\techo hi\ntest: build\n\tpytest\n"
    )
    assert make_targets(tmp_path) == frozenset({"build", "test"})
