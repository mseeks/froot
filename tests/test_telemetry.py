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
