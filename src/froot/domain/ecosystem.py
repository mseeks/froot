"""The package ecosystems froot can patch, and their manifest/lockfile names.

froot's chassis is ecosystem-agnostic; the per-ecosystem facts live here and in
the matching adapter. v1 ships :data:`Ecosystem.NPM`; ``uv`` (Python) is the
documented next ecosystem (SPEC roadmap) and slots in as one new enum member
plus one new adapter — the ``match`` statements below will fail to type-check
until it is handled, which is the point.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never


class Ecosystem(StrEnum):
    """A package manager whose dependencies froot can propose patches for."""

    NPM = "npm"


def manifest_filename(ecosystem: Ecosystem) -> str:
    """The dependency manifest a human edits for this ecosystem."""
    match ecosystem:
        case Ecosystem.NPM:
            return "package.json"
    assert_never(ecosystem)


def lockfile_filename(ecosystem: Ecosystem) -> str:
    """The resolved lockfile froot regenerates alongside the manifest."""
    match ecosystem:
        case Ecosystem.NPM:
            return "package-lock.json"
    assert_never(ecosystem)
