from __future__ import annotations

import pytest

from froot.adapters.changelog_http import (
    _version_description,
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


def test_version_description():
    metadata = {"versions": {"1.4.3": {"description": "A tiny lib."}}}
    assert _version_description(metadata, "1.4.3") == "A tiny lib."
    assert _version_description(metadata, "9.9.9") is None
    assert _version_description({}, "1.4.3") is None
