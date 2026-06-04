from __future__ import annotations

import pytest

from froot.adapters.changelog_http import (
    github_repo_from_pypi,
    github_repo_from_registry,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "git+https://github.com/sindresorhus/p-limit.git",
            "sindresorhus/p-limit",
        ),
        ("https://github.com/a/b", "a/b"),
        ("git://github.com/a/b.git", "a/b"),
    ],
)
def test_github_repo_from_registry(url: str, expected: str):
    ref = github_repo_from_registry({"repository": {"url": url}})
    assert ref is not None
    assert ref.slug == expected


def test_github_repo_from_registry_none_cases():
    assert github_repo_from_registry({"repository": {"url": "x"}}) is None
    assert github_repo_from_registry({}) is None
    assert github_repo_from_registry("not-a-dict") is None


def test_github_repo_from_registry_string_form_and_missing():
    # A bare string ``repository`` and an empty url both behave sanely.
    ref = github_repo_from_registry({"repository": "github.com/a/b"})
    assert ref is not None
    assert ref.slug == "a/b"
    assert github_repo_from_registry({"repository": {"url": ""}}) is None


def test_github_repo_from_pypi_project_urls():
    meta = {
        "info": {
            "project_urls": {
                "Homepage": "https://example.com",
                "Source": "https://github.com/pallets/flask",
            }
        }
    }
    ref = github_repo_from_pypi(meta)
    assert ref is not None
    assert ref.slug == "pallets/flask"


def test_github_repo_from_pypi_prefers_source_over_homepage():
    # A non-code homepage on GitHub must not win over the explicit source link.
    meta = {
        "info": {
            "project_urls": {
                "Homepage": "https://github.com/wrong/homepage",
                "Repository": "https://github.com/right/repo",
            }
        }
    }
    ref = github_repo_from_pypi(meta)
    assert ref is not None
    assert ref.slug == "right/repo"


def test_github_repo_from_pypi_home_page_fallback():
    meta = {"info": {"project_urls": None, "home_page": "git://github.com/a/b"}}
    ref = github_repo_from_pypi(meta)
    assert ref is not None
    assert ref.slug == "a/b"


def test_github_repo_from_pypi_none_cases():
    no_github = {"info": {"project_urls": {"Homepage": "https://x.io"}}}
    assert github_repo_from_pypi(no_github) is None
    assert github_repo_from_pypi({}) is None
    assert github_repo_from_pypi("not-a-dict") is None


def test_github_repo_from_pypi_ignores_sponsors_funding_link():
    # A "GitHub Sponsors" label contains no source-role hint and resolves to the
    # reserved 'sponsors' namespace, so the real Source link must win.
    meta = {
        "info": {
            "project_urls": {
                "GitHub Sponsors": "https://github.com/sponsors/encode",
                "Source Code": "https://github.com/encode/httpx",
            }
        }
    }
    ref = github_repo_from_pypi(meta)
    assert ref is not None
    assert ref.slug == "encode/httpx"


def test_github_repo_from_pypi_funding_only_yields_none():
    meta = {
        "info": {
            "project_urls": {
                "Funding": "https://github.com/sponsors/somebody",
                "Homepage": "https://example.org",
            }
        }
    }
    assert github_repo_from_pypi(meta) is None


def test_github_repo_from_pypi_strips_fragment_and_query():
    frag = github_repo_from_pypi(
        {"info": {"home_page": "https://github.com/encode/httpx#readme"}}
    )
    query = github_repo_from_pypi(
        {"info": {"home_page": "https://github.com/encode/httpx?tab=readme"}}
    )
    assert frag is not None and frag.slug == "encode/httpx"
    assert query is not None and query.slug == "encode/httpx"
