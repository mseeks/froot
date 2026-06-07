from __future__ import annotations

import json

import pytest

import froot.adapters.uv as uv_mod
from froot.adapters.npm import NpmPackageManager
from froot.adapters.registry import package_manager_for
from froot.adapters.uv import (
    UvPackageManager,
    _pinned_python_minor,
    normalize_name,
    parse_available_versions,
    parse_deptry_unused,
    parse_direct_dependencies,
    parse_locked_versions,
    parse_main_and_dev_dependencies,
)
from froot.domain.ecosystem import Ecosystem
from froot.domain.sandbox import SandboxResult
from tests.support import FakeSandbox, make_removal, make_repo, ver

# A pyproject with a main dep, a dev-group dep, and an optional-extra dep.
_PYPROJECT = """
[project]
name = "x"
dependencies = ["requests>=2", "Pillow>=10"]
[project.optional-dependencies]
extra = ["rich>=13"]
[dependency-groups]
dev = ["pytest>=8", "mypy>=1"]
"""


def test_parse_main_and_dev_dependencies_splits_sections():
    main, dev = parse_main_and_dev_dependencies(_PYPROJECT)
    assert main == frozenset({"requests", "pillow"})  # normalized
    assert dev == frozenset({"pytest", "mypy"})
    # the optional-extra (rich) is in neither set -> skipped by the loop


def test_parse_deptry_unused_extracts_dep002_only():
    payload = json.dumps(
        [
            {"error": {"code": "DEP002"}, "module": "requests"},
            {"error": {"code": "DEP002"}, "module": "pytest"},
            {"error": {"code": "DEP001"}, "module": "missing-import"},
        ]
    )
    assert parse_deptry_unused(payload) == ("requests", "pytest")


def test_parse_deptry_unused_empty_or_garbage():
    assert parse_deptry_unused("") == ()
    assert parse_deptry_unused("[]") == ()
    assert parse_deptry_unused("not json") == ()


async def test_list_unused_runs_deptry_in_sandbox_and_classifies(tmp_path):
    # deptry (in the sandbox) flags a main dep, a dev-group dep, and an
    # optional-extra dep; the loop keeps the first two with the right section
    # and skips the unsupported extra.
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    deptry_json = json.dumps(
        [
            {"error": {"code": "DEP002"}, "module": "requests"},  # main
            {"error": {"code": "DEP002"}, "module": "pytest"},  # dev group
            {"error": {"code": "DEP002"}, "module": "rich"},  # extra -> skip
        ]
    )
    sandbox = FakeSandbox(
        SandboxResult(exit_code=1, stdout=deptry_json, stderr="")
    )
    removals = await UvPackageManager(sandbox=sandbox).list_unused(
        make_repo(ecosystem=Ecosystem.UV), tmp_path
    )
    assert {(r.package, r.dev) for r in removals} == {
        ("requests", False),
        ("pytest", True),
    }
    assert all(r.justification == "unused (deptry)" for r in removals)
    # the deptry script (uv sync + deptry) ran in the sandbox
    assert any("deptry" in s for s in sandbox.scripts)


async def test_list_unused_degrades_when_sandbox_fails(tmp_path):
    # An unconfigured/failing sandbox yields no removals, never an exception
    # that would fail the scan — so the uv arm stays quiet until the key is set.
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)

    class _BoomSandbox:
        async def run(self, workdir, script, *, timeout_seconds=None):
            raise RuntimeError("FROOT_E2B_API_KEY is unset")

    removals = await UvPackageManager(sandbox=_BoomSandbox()).list_unused(
        make_repo(ecosystem=Ecosystem.UV), tmp_path
    )
    assert removals == ()


async def test_list_unused_no_manifest_yields_nothing(tmp_path):
    sandbox = FakeSandbox()
    removals = await UvPackageManager(sandbox=sandbox).list_unused(
        make_repo(ecosystem=Ecosystem.UV), tmp_path
    )
    assert removals == ()
    assert sandbox.scripts == []  # never even spun a sandbox


async def test_remove_dependency_runs_uv_remove(monkeypatch, tmp_path):
    seen: list[str] = []

    async def fake_run_text(*args: str, cwd):
        seen.extend(args)
        return 0, "", ""

    monkeypatch.setattr(uv_mod, "run_text", fake_run_text)
    await UvPackageManager().remove_dependency(
        make_removal(package="requests", ecosystem=Ecosystem.UV, dev=False),
        tmp_path,
    )
    assert seen == ["uv", "remove", "requests", "--no-sync"]


async def test_remove_dependency_dev_uses_dev_flag(monkeypatch, tmp_path):
    seen: list[str] = []

    async def fake_run_text(*args: str, cwd):
        seen.extend(args)
        return 0, "", ""

    monkeypatch.setattr(uv_mod, "run_text", fake_run_text)
    await UvPackageManager().remove_dependency(
        make_removal(package="pytest", ecosystem=Ecosystem.UV, dev=True),
        tmp_path,
    )
    assert seen == ["uv", "remove", "--dev", "pytest", "--no-sync"]


async def test_remove_dependency_raises_on_failure(monkeypatch, tmp_path):
    async def fake_run_text(*args: str, cwd):
        return 1, "", "not found"

    monkeypatch.setattr(uv_mod, "run_text", fake_run_text)
    with pytest.raises(RuntimeError, match="uv remove failed"):
        await UvPackageManager().remove_dependency(
            make_removal(ecosystem=Ecosystem.UV), tmp_path
        )


async def test_list_installed_reads_direct_deps_and_locked_versions(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["Jinja2>=2.10"]\n'
    )
    (tmp_path / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "jinja2"\nversion = "2.10.0"\n'
    )
    installed = await UvPackageManager().list_installed(
        make_repo(ecosystem=Ecosystem.UV), tmp_path
    )
    assert {p.package: str(p.version) for p in installed} == {
        "jinja2": "2.10.0"
    }


def test_normalize_name_pep503():
    assert normalize_name("Pydantic-Settings") == "pydantic-settings"
    assert normalize_name("Foo.Bar_Baz") == "foo-bar-baz"
    assert normalize_name("requests") == "requests"


def test_parse_direct_dependencies_all_sections_normalized():
    pyproject = """
    [project]
    dependencies = [
        "Requests>=2.0",
        "pydantic-ai-slim[openai]>=0.0.20",
        "tomli ; python_version < '3.11'",
    ]
    [project.optional-dependencies]
    dev = ["pytest>=8", "Mypy"]
    [dependency-groups]
    lint = ["ruff>=0.8", {include-group = "dev"}]
    """
    assert parse_direct_dependencies(pyproject) == frozenset(
        {"requests", "pydantic-ai-slim", "tomli", "pytest", "mypy", "ruff"}
    )


def test_parse_direct_dependencies_empty_and_malformed():
    assert parse_direct_dependencies("[project]\n") == frozenset()
    assert parse_direct_dependencies("not = valid = toml") == frozenset()


def test_parse_locked_versions_keys_on_normalized_name():
    lock = """
    version = 1
    [[package]]
    name = "froot"
    version = "0.1.0"
    [[package]]
    name = "Pydantic-Settings"
    version = "2.4.0"
    [[package]]
    name = "idna"
    version = "3.6"
    [[package]]
    name = "no-version-entry"
    """
    locked = parse_locked_versions(lock)
    assert locked["pydantic-settings"] == "2.4.0"
    assert locked["idna"] == "3.6"
    assert locked["froot"] == "0.1.0"
    assert "no-version-entry" not in locked


def test_parse_locked_versions_malformed():
    assert parse_locked_versions("not = valid = toml") == {}


def _pypi(releases: dict[str, list[dict[str, object]]]) -> str:
    return json.dumps({"releases": releases})


def test_parse_available_versions_filters_and_parses():
    payload = _pypi(
        {
            "1.2.3": [{"filename": "x.whl", "yanked": False}],
            "1.2.4": [{"filename": "y.whl"}],  # no yanked key == not yanked
            "1.3.0rc1": [{"yanked": False}],  # prerelease: not semver, dropped
            "0.9.0": [{"yanked": True}],  # fully yanked: dropped
            "1.2.5": [],  # no files: dropped
            "not-a-version": [{"yanked": False}],  # unparseable: dropped
        }
    )
    assert set(parse_available_versions(payload)) == {
        ver("1.2.3"),
        ver("1.2.4"),
    }


def test_parse_available_versions_empty_or_garbage():
    assert parse_available_versions("") == ()
    assert parse_available_versions("   ") == ()
    assert parse_available_versions("not json") == ()
    assert parse_available_versions(json.dumps({"info": {}})) == ()


def test_package_manager_for_dispatch():
    assert isinstance(package_manager_for(Ecosystem.NPM), NpmPackageManager)
    assert isinstance(package_manager_for(Ecosystem.UV), UvPackageManager)


def test_pinned_python_minor_truncates_patch(tmp_path):
    (tmp_path / ".python-version").write_text("3.13.13\n")
    assert _pinned_python_minor(tmp_path) == "3.13"


def test_pinned_python_minor_absent_or_malformed(tmp_path):
    assert _pinned_python_minor(tmp_path) is None
    (tmp_path / ".python-version").write_text("system\n")
    assert _pinned_python_minor(tmp_path) is None
