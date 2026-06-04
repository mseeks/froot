"""The package ecosystems froot can patch, and their manifest/lockfile names.

froot's chassis is ecosystem-agnostic; the per-ecosystem facts live here and in
the matching adapter. Two ecosystems ship today — :data:`Ecosystem.NPM`
(JavaScript) and :data:`Ecosystem.UV` (Python) — and each is exactly one enum
member plus one adapter (:mod:`froot.adapters.npm`, :mod:`froot.adapters.uv`),
selected by :func:`froot.adapters.registry.package_manager_for`. A further
ecosystem is the same shape: add a member, handle it in the ``match`` statements
below (they fail to type-check until it is, which is the point), and add an
adapter.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never


class Ecosystem(StrEnum):
    """A package manager whose dependencies froot can propose patches for."""

    NPM = "npm"
    UV = "uv"


def manifest_filename(ecosystem: Ecosystem) -> str:
    """The dependency manifest a human edits for this ecosystem."""
    match ecosystem:
        case Ecosystem.NPM:
            return "package.json"
        case Ecosystem.UV:
            return "pyproject.toml"
    assert_never(ecosystem)


def lockfile_filename(ecosystem: Ecosystem) -> str:
    """The resolved lockfile froot regenerates alongside the manifest."""
    match ecosystem:
        case Ecosystem.NPM:
            return "package-lock.json"
        case Ecosystem.UV:
            return "uv.lock"
    assert_never(ecosystem)
