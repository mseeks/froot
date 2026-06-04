"""Tests for the source-tree loader (the analyzer's I/O boundary)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.adapters.source_tree import load_modules

if TYPE_CHECKING:
    from pathlib import Path


def test_load_modules_src_layout(tmp_path: Path):
    pkg = tmp_path / "src" / "app"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "util.py").write_text("def f():\n    return 1\n")
    (pkg / "sub" / "__init__.py").write_text("")
    (pkg / "sub" / "deep.py").write_text("x = 1\n")

    modules = load_modules(tmp_path)

    assert set(modules) == {"app", "app.util", "app.sub", "app.sub.deep"}
    assert modules["app.util"].qualname == "app.util"
    assert modules["app.util"].lines[0] == "def f():"


def test_load_modules_skips_unparseable(tmp_path: Path):
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "good.py").write_text("y = 2\n")
    (pkg / "broken.py").write_text("def (:\n")  # syntax error

    modules = load_modules(tmp_path)

    assert "app.good" in modules
    assert "app.broken" not in modules


def test_load_modules_flat_layout(tmp_path: Path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("z = 3\n")

    modules = load_modules(tmp_path)

    assert "app.mod" in modules
