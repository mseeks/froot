from __future__ import annotations

import json
from pathlib import Path

from froot.adapters.npm import (
    NpmPackageManager,
    parse_direct_dependencies,
    parse_locked_versions,
    parse_versions,
)
from tests.support import make_repo, ver


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
