"""The OSV.dev advisory source — froot's security signal, one source for all.

Backs :class:`~froot.ports.protocols.AdvisorySource`. OSV (osv.dev) is Google's
cross-ecosystem vuln database; it speaks both ``npm`` and ``PyPI``, so one
single adapter covers every ecosystem froot patches. Two calls: a batch query of
the installed ``(name, ecosystem, version)`` set returns the vuln ids affecting
each, then each vuln record is fetched for its affected ranges (the fixed
versions the policy needs). No auth, no key.

Best-effort by contract: a failed batch yields no advisories (the loop simply
finds nothing to do this tick) and a failed single fetch drops that one vuln, so
a flaky OSV never blocks the loop. The adapter only *shapes* OSV's JSON into
domain values; deciding the clearing target is the pure
:func:`froot.policy.candidates.select_security_candidates`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, assert_never, final

import httpx

from froot.domain.advisory import Advisory, VulnRange
from froot.domain.ecosystem import Ecosystem

if TYPE_CHECKING:
    from froot.domain.candidate import InstalledPackage

_API = "https://api.osv.dev"
_TIMEOUT = 30.0


def _osv_ecosystem(ecosystem: Ecosystem) -> str:
    """OSV's name for an ecosystem (case-sensitive: ``npm`` / ``PyPI``)."""
    match ecosystem:
        case Ecosystem.NPM:
            return "npm"
        case Ecosystem.UV:
            return "PyPI"
    assert_never(ecosystem)


def _ranges_from_affected(affected: Any) -> tuple[VulnRange, ...]:
    """Flatten an affected entry's ranges' events into ``VulnRange``s.

    OSV events are a sequence of ``{introduced: X}`` / ``{fixed: Y}`` markers;
    each ``introduced`` opens a span that the next ``fixed`` (if any) closes.
    """
    ranges: list[VulnRange] = []
    for spec in affected.get("ranges", []):
        introduced: str | None = None
        for event in spec.get("events", []):
            if "introduced" in event:
                if introduced is not None:
                    ranges.append(VulnRange(introduced=introduced))
                introduced = str(event["introduced"])
            elif "fixed" in event and introduced is not None:
                ranges.append(
                    VulnRange(introduced=introduced, fixed=str(event["fixed"]))
                )
                introduced = None
        if introduced is not None:
            ranges.append(VulnRange(introduced=introduced))
    return tuple(ranges)


def _advisory_from_record(
    record: Any, package: InstalledPackage, osv_ecosystem: str
) -> Advisory | None:
    """Shape one OSV vuln record into an :class:`Advisory` for ``package``.

    Keeps only the entries for this package + ecosystem (a vuln can name
    several), so the policy never matches a range from a different package.
    """
    ranges: list[VulnRange] = []
    for affected in record.get("affected", []):
        pkg = affected.get("package", {})
        if (
            pkg.get("name") == package.package
            and pkg.get("ecosystem") == osv_ecosystem
        ):
            ranges.extend(_ranges_from_affected(affected))
    if not ranges:
        return None
    return Advisory(
        id=str(record["id"]),
        aliases=tuple(str(a) for a in record.get("aliases", [])),
        package=package.package,
        ecosystem=package.ecosystem,
        ranges=tuple(ranges),
    )


@final
class OsvAdvisorySource:
    """An :class:`~froot.ports.protocols.AdvisorySource` over OSV.dev."""

    async def advisories(
        self, installed: tuple[InstalledPackage, ...]
    ) -> tuple[Advisory, ...]:
        """Return the advisories affecting ``installed`` (best-effort)."""
        if not installed:
            return ()
        async with httpx.AsyncClient(base_url=_API, timeout=_TIMEOUT) as client:
            vuln_ids = await self._query_batch(client, installed)
            advisories: list[Advisory] = []
            for package, ids in vuln_ids:
                osv_ecosystem = _osv_ecosystem(package.ecosystem)
                for vuln_id in ids:
                    record = await self._fetch_vuln(client, vuln_id)
                    if record is None:
                        continue
                    advisory = _advisory_from_record(
                        record, package, osv_ecosystem
                    )
                    if advisory is not None:
                        advisories.append(advisory)
        return tuple(advisories)

    async def _query_batch(
        self,
        client: httpx.AsyncClient,
        installed: tuple[InstalledPackage, ...],
    ) -> list[tuple[InstalledPackage, tuple[str, ...]]]:
        """Batch-query OSV; return each package paired with its vuln ids."""
        queries = [
            {
                "package": {
                    "name": package.package,
                    "ecosystem": _osv_ecosystem(package.ecosystem),
                },
                "version": str(package.version),
            }
            for package in installed
        ]
        try:
            resp = await client.post(
                "/v1/querybatch", json={"queries": queries}
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return []  # best-effort: a failed batch means nothing to do
        results = resp.json().get("results", [])
        out: list[tuple[InstalledPackage, tuple[str, ...]]] = []
        for package, result in zip(installed, results, strict=False):
            ids = tuple(
                str(v["id"]) for v in result.get("vulns", []) if "id" in v
            )
            if ids:
                out.append((package, ids))
        return out

    async def _fetch_vuln(
        self, client: httpx.AsyncClient, vuln_id: str
    ) -> Any | None:
        """Fetch one vuln's full record, or ``None`` if it can't be read."""
        try:
            resp = await client.get(f"/v1/vulns/{vuln_id}")
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        return resp.json()
