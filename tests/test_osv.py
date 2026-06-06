from __future__ import annotations

import httpx
import pytest

from froot.adapters.osv import (
    OsvAdvisorySource,
    _advisory_from_record,
    _osv_ecosystem,
    _ranges_from_affected,
)
from froot.domain.ecosystem import Ecosystem
from tests.support import make_installed

_VULN_RECORD = {
    "id": "GHSA-1",
    "aliases": ["CVE-1"],
    "affected": [
        {
            "package": {"name": "left-pad", "ecosystem": "npm"},
            "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.4.3"}]}],
        }
    ],
}


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route the adapter's AsyncClient through a MockTransport handler.

    The adapter calls ``httpx.AsyncClient(...)``, so patching the shared httpx
    module's attribute reaches it (restored after the test by monkeypatch).
    """
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_advisories_batches_then_fetches_and_shapes(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/querybatch":
            # First package has a vuln; the second returns the empty {} slot —
            # exercising the zip alignment between queries and results.
            return httpx.Response(
                200, json={"results": [{"vulns": [{"id": "GHSA-1"}]}, {}]}
            )
        if request.url.path == "/v1/vulns/GHSA-1":
            return httpx.Response(200, json=_VULN_RECORD)
        return httpx.Response(404)

    _mock_httpx(monkeypatch, handler)
    installed = (
        make_installed("left-pad", "1.4.2"),
        make_installed("safe-pkg", "2.0.0"),
    )
    advisories = await OsvAdvisorySource().advisories(installed)
    assert len(advisories) == 1
    assert advisories[0].id == "GHSA-1"
    assert advisories[0].package == "left-pad"
    assert advisories[0].aliases == ("CVE-1",)


async def test_advisories_empty_when_batch_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)  # OSV down

    _mock_httpx(monkeypatch, handler)
    advisories = await OsvAdvisorySource().advisories(
        (make_installed("left-pad", "1.4.2"),)
    )
    assert advisories == ()


async def test_advisories_empty_for_no_installed():
    assert await OsvAdvisorySource().advisories(()) == ()


def test_osv_ecosystem_strings():
    assert _osv_ecosystem(Ecosystem.NPM) == "npm"
    assert _osv_ecosystem(Ecosystem.UV) == "PyPI"


def test_ranges_pairs_introduced_and_fixed():
    affected = {
        "ranges": [
            {
                "type": "SEMVER",
                "events": [{"introduced": "1.0.0"}, {"fixed": "1.2.3"}],
            }
        ]
    }
    ranges = _ranges_from_affected(affected)
    assert [(r.introduced, r.fixed) for r in ranges] == [("1.0.0", "1.2.3")]


def test_ranges_splits_multiple_branches():
    affected = {
        "ranges": [
            {
                "events": [
                    {"introduced": "0"},
                    {"fixed": "0.2.1"},
                    {"introduced": "1.0.0"},
                    {"fixed": "1.2.3"},
                ]
            }
        ]
    }
    ranges = _ranges_from_affected(affected)
    assert [(r.introduced, r.fixed) for r in ranges] == [
        ("0", "0.2.1"),
        ("1.0.0", "1.2.3"),
    ]


def test_ranges_unfixed_span_has_no_fix():
    affected = {"ranges": [{"events": [{"introduced": "0"}]}]}
    ranges = _ranges_from_affected(affected)
    assert ranges[0].fixed is None


def test_advisory_keeps_only_the_matching_package():
    record = {
        "id": "GHSA-x",
        "aliases": ["CVE-1"],
        "affected": [
            {
                "package": {"name": "left-pad", "ecosystem": "npm"},
                "ranges": [
                    {"events": [{"introduced": "0"}, {"fixed": "1.4.3"}]}
                ],
            },
            {
                "package": {"name": "other", "ecosystem": "npm"},
                "ranges": [
                    {"events": [{"introduced": "0"}, {"fixed": "9.9.9"}]}
                ],
            },
        ],
    }
    advisory = _advisory_from_record(
        record, make_installed("left-pad", "1.4.2"), "npm"
    )
    assert advisory is not None
    assert advisory.id == "GHSA-x"
    assert advisory.aliases == ("CVE-1",)
    assert [(r.introduced, r.fixed) for r in advisory.ranges] == [
        ("0", "1.4.3")
    ]


def test_advisory_none_when_package_not_affected():
    record = {
        "id": "GHSA-x",
        "affected": [
            {"package": {"name": "other", "ecosystem": "npm"}, "ranges": []}
        ],
    }
    assert (
        _advisory_from_record(
            record, make_installed("left-pad", "1.4.2"), "npm"
        )
        is None
    )
