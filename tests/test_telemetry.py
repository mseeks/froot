from __future__ import annotations

import pytest

from froot.adapters import telemetry


def test_otel_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FROOT_OTEL", raising=False)
    assert telemetry.otel_enabled() is False
    assert telemetry.tracing_interceptors() == []
    assert telemetry.metrics_runtime() is None


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_otel_enabled_flag(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("FROOT_OTEL", value)
    assert telemetry.otel_enabled() is True


def test_set_span_attributes_is_noop_when_off(monkeypatch: pytest.MonkeyPatch):
    # With telemetry off the helper must touch no OpenTelemetry API at all —
    # it returns before importing the trace module, so local runs and tests
    # never pay for spans. (A raising import would surface as an error here.)
    monkeypatch.delenv("FROOT_OTEL", raising=False)
    telemetry.set_span_attributes(scan_considered=3, scan_loop="x")


def test_set_span_attributes_records_on_current_span(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("FROOT_OTEL", "1")
    recorded: dict[str, object] = {}

    class _FakeSpan:
        def set_attribute(self, key: str, value: object) -> None:
            recorded[key] = value

    # Patch the real (installed) trace module's current-span accessor, so the
    # helper writes its froot-namespaced attributes onto our recording span.
    from opentelemetry import trace

    monkeypatch.setattr(trace, "get_current_span", lambda: _FakeSpan())
    telemetry.set_span_attributes(scan_considered=5, scan_loop="security-patch")
    assert recorded["froot.scan_considered"] == 5
    assert recorded["froot.scan_loop"] == "security-patch"
