"""Select the package-manager adapter for an ecosystem.

The chassis is ecosystem-agnostic; this is the single place that maps an
:class:`~froot.domain.ecosystem.Ecosystem` to its concrete
:class:`~froot.ports.protocols.PackageManager`. The imports are deferred into
the ``match`` arms so resolving one ecosystem never imports another's adapter
(or its HTTP stack), keeping the activities' lazy-import discipline intact, and
``assert_never`` makes a newly added ecosystem fail to type-check here until it
is wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from froot.domain.ecosystem import Ecosystem

if TYPE_CHECKING:
    from froot.ports.protocols import PackageManager


def package_manager_for(ecosystem: Ecosystem) -> PackageManager:
    """Return the package-manager adapter for ``ecosystem``."""
    match ecosystem:
        case Ecosystem.NPM:
            from froot.adapters.npm import NpmPackageManager

            return NpmPackageManager()
        case Ecosystem.UV:
            from froot.adapters.uv import UvPackageManager

            return UvPackageManager()
    assert_never(ecosystem)
