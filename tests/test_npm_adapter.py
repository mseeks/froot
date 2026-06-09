from __future__ import annotations

import json
from pathlib import Path

import pytest

from froot.adapters import npm as npm_mod
from froot.adapters.npm import (
    NpmPackageManager,
    narrow_unexportable,
    parse_direct_dependencies,
    parse_knip_exports,
    parse_knip_files,
    parse_knip_unused,
    parse_locked_versions,
    parse_versions,
)
from froot.domain.dead_source import DeadFile
from froot.domain.ecosystem import Ecosystem
from froot.domain.removal import Removal
from tests.support import make_removal, make_repo, ver


async def test_list_installed_reads_direct_deps_and_locked_versions(
    tmp_path: Path,
):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"left-pad": "^1.4.2"}, '
        '"devDependencies": {"jest": "^29.0.0"}}'
    )
    (tmp_path / "package-lock.json").write_text(
        '{"packages": {"node_modules/left-pad": {"version": "1.4.2"}, '
        '"node_modules/jest": {"version": "29.0.0"}}}'
    )
    installed = await NpmPackageManager().list_installed(make_repo(), tmp_path)
    assert {p.package: str(p.version) for p in installed} == {
        "jest": "29.0.0",
        "left-pad": "1.4.2",
    }


def test_parse_direct_dependencies_deps_and_devdeps():
    package_json = json.dumps(
        {
            "dependencies": {"left-pad": "^1.4.2", "chalk": "^5.3.0"},
            "devDependencies": {"vitest": "^1.0.0"},
        }
    )
    assert parse_direct_dependencies(package_json) == frozenset(
        {"left-pad", "chalk", "vitest"}
    )


def test_parse_direct_dependencies_empty():
    assert parse_direct_dependencies(json.dumps({})) == frozenset()


def test_parse_locked_versions_v3_packages_skips_transitive():
    lock = json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "root"},
                "node_modules/left-pad": {"version": "1.4.2"},
                "node_modules/@scope/pkg": {"version": "2.0.1"},
                "node_modules/left-pad/node_modules/nested": {
                    "version": "9.9.9"
                },
            },
        }
    )
    locked = parse_locked_versions(lock)
    assert locked["left-pad"] == "1.4.2"
    assert locked["@scope/pkg"] == "2.0.1"
    assert "nested" not in locked


def test_parse_locked_versions_v1_fallback():
    lock = json.dumps(
        {
            "lockfileVersion": 1,
            "dependencies": {"left-pad": {"version": "1.4.2"}},
        }
    )
    assert parse_locked_versions(lock) == {"left-pad": "1.4.2"}


def test_parse_versions_array_and_single():
    assert parse_versions(json.dumps(["1.4.1", "1.4.2"])) == (
        ver("1.4.1"),
        ver("1.4.2"),
    )
    assert parse_versions(json.dumps("1.0.0")) == (ver("1.0.0"),)


def test_parse_versions_empty_or_garbage_yields_empty():
    assert parse_versions("") == ()
    assert parse_versions("   ") == ()
    assert parse_versions("not json at all") == ()


def test_parse_versions_drops_unparseable():
    raw = json.dumps(["1.4.2", "not-a-version", "1.4.3"])
    assert parse_versions(raw) == (ver("1.4.2"), ver("1.4.3"))


# A realistic knip --reporter json body: one production dep and one dev dep
# unused, the rest of the issue fields present but empty (knip always emits the
# full shape).
_KNIP_JSON = json.dumps(
    {
        "issues": [
            {
                "file": "package.json",
                "dependencies": [{"name": "left-pad", "line": 5, "col": 6}],
                "devDependencies": [{"name": "is-odd", "line": 9, "col": 6}],
                "unlisted": [],
                "exports": [],
            }
        ]
    }
)


def test_parse_knip_unused_splits_deps_and_dev_deps():
    assert parse_knip_unused(_KNIP_JSON) == (
        ("left-pad", False),
        ("is-odd", True),
    )


def test_parse_knip_unused_tolerates_leading_plugin_chatter():
    # knip plugins print progress to stdout before the JSON; the parser locates
    # the object rather than assuming a clean stream.
    noisy = "info Nuxt Icon server bundle mode is set to local\n" * 3 + (
        _KNIP_JSON
    )
    assert parse_knip_unused(noisy) == (
        ("left-pad", False),
        ("is-odd", True),
    )


def test_parse_knip_unused_empty_or_garbage_yields_empty():
    assert parse_knip_unused("") == ()
    assert parse_knip_unused("   ") == ()
    assert parse_knip_unused("not json at all") == ()
    assert parse_knip_unused(json.dumps({"issues": []})) == ()
    assert (
        parse_knip_unused(
            json.dumps(
                {"issues": [{"dependencies": [], "devDependencies": []}]}
            )
        )
        == ()
    )


async def test_list_unused_builds_removals_from_knip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    async def fake_run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
        # knip exits 1 *because* it found issues; the adapter must still parse.
        return 1, _KNIP_JSON, ""

    monkeypatch.setattr(npm_mod, "run_text", fake_run_text)
    result = await NpmPackageManager().list_unused(make_repo(), tmp_path)
    assert [(r.package, r.dev) for r in result if isinstance(r, Removal)] == [
        ("left-pad", False),
        ("is-odd", True),
    ]
    assert all(r.justification == "unused (knip)" for r in result)


async def test_list_unused_degrades_when_knip_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # knip is baked into the worker image, but if it is missing (e.g. local dev)
    # the signal yields no removals rather than raising and failing the scan.
    async def fake_run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
        raise FileNotFoundError("knip")

    monkeypatch.setattr(npm_mod, "run_text", fake_run_text)
    removals = await NpmPackageManager().list_unused(make_repo(), tmp_path)
    assert removals == ()


# A knip body with all three dead-code shapes: a top-level unused file, an
# unused export and an unused type (both inline), plus an unused dependency.
_KNIP_DEAD_CODE_JSON = json.dumps(
    {
        "files": ["src/orphan.ts"],
        "issues": [
            {
                "file": "package.json",
                "dependencies": [{"name": "left-pad", "line": 5, "col": 6}],
                "devDependencies": [],
                "exports": [],
            },
            {
                "file": "src/util.ts",
                "dependencies": [],
                "devDependencies": [],
                "exports": [{"name": "gone", "line": 2, "col": 8}],
                "types": [{"name": "Unused", "line": 4, "col": 13}],
            },
        ],
    }
)


def test_parse_knip_files():
    assert parse_knip_files(_KNIP_DEAD_CODE_JSON) == ("src/orphan.ts",)
    assert parse_knip_files(json.dumps({"issues": []})) == ()  # no files key
    assert parse_knip_files("not json") == ()


def test_parse_knip_exports_folds_exports_and_types():
    # Unused values and unused types are both exported-but-unimported symbols
    # the action un-exports the same way, so they fold into (file, name, line).
    assert parse_knip_exports(_KNIP_DEAD_CODE_JSON) == (
        ("src/util.ts", "gone", 2),
        ("src/util.ts", "Unused", 4),
    )


def test_parse_knip_exports_skips_entries_missing_name_or_line():
    body = json.dumps(
        {"issues": [{"file": "a.ts", "exports": [{"name": "x"}, {"line": 3}]}]}
    )
    assert parse_knip_exports(body) == ()


def test_narrow_unexportable_keeps_inline_drops_the_rest(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.ts").write_text(
        "const keep = 1\nexport function gone() {}\nexport { reexp }\n"
    )
    exports = (
        ("src/util.ts", "gone", 2),  # inline decl -> kept
        ("src/util.ts", "reexp", 3),  # clause re-export -> dropped
        ("src/util.ts", "missing", 99),  # line out of range -> dropped
        ("src/absent.ts", "x", 1),  # unreadable file -> dropped
    )
    kept, dropped = narrow_unexportable(tmp_path, exports, Ecosystem.NPM)
    assert [(e.file, e.symbol, e.line) for e in kept] == [
        ("src/util.ts", "gone", 2)
    ]
    assert dropped == 3
    assert all(e.justification == "unused export (knip)" for e in kept)


async def test_list_unused_surfaces_deps_files_and_exports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # One knip run yields all three kinds; the exports are narrowed against the
    # real source lines in the checkout (both are inline declarations here).
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.ts").write_text(
        "const keep = 1\n"
        "export function gone() {}\n"
        "const x = 1\n"
        "export type Unused = number\n"
    )

    async def fake_run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
        return 1, _KNIP_DEAD_CODE_JSON, ""

    monkeypatch.setattr(npm_mod, "run_text", fake_run_text)
    items = await NpmPackageManager().list_unused(make_repo(), tmp_path)
    assert [item.kind for item in items] == [
        "removal",
        "dead_file",
        "dead_export",
        "dead_export",
    ]
    files = [item for item in items if isinstance(item, DeadFile)]
    assert files[0].path == "src/orphan.ts"


async def test_remove_dependency_runs_npm_uninstall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    seen: list[str] = []

    async def fake_run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
        seen.extend(args)
        return 0, "", ""

    monkeypatch.setattr(npm_mod, "run_text", fake_run_text)
    await NpmPackageManager().remove_dependency(
        make_removal(package="left-pad"), tmp_path
    )
    assert seen == [
        "npm",
        "uninstall",
        "left-pad",
        "--package-lock-only",
        "--ignore-scripts",
    ]


async def test_remove_dependency_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    async def fake_run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
        return 1, "", "E404 not found"

    monkeypatch.setattr(npm_mod, "run_text", fake_run_text)
    with pytest.raises(RuntimeError, match="npm uninstall failed"):
        await NpmPackageManager().remove_dependency(make_removal(), tmp_path)
