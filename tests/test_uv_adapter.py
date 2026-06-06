from __future__ import annotations

import json

from froot.adapters.npm import NpmPackageManager
from froot.adapters.registry import package_manager_for
from froot.adapters.uv import (
    UvPackageManager,
    _pinned_python_minor,
    normalize_name,
    parse_available_versions,
    parse_direct_dependencies,
    parse_locked_versions,
)
from froot.domain.ecosystem import Ecosystem
from tests.support import make_repo, ver


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
