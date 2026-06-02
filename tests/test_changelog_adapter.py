from __future__ import annotations

import pytest

from froot.adapters.changelog_http import github_repo_from_registry


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
