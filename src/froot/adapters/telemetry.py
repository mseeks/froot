"""OpenTelemetry wiring: a tracer provider, SDK metrics, and instrumentation.

The run-telemetry half of "derive, never store": traces and the Temporal SDK's
runtime metrics export OTLP/HTTP to the in-cluster collector, which adds the
ClickStack token on forward. Metrics are
CUMULATIVE to match what is already in ClickStack.

All of it is gated on :class:`~froot.config.settings.TelemetrySettings`
(``FROOT_OTEL``) and is a no-op when off, so tests and local runs stay
telemetry-free (no exporter threads). It is never imported by a workflow- or
activity-decorated module, so no OpenTelemetry import enters the Temporal
workflow sandbox graph.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from froot.config.settings import TelemetrySettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx
    from temporalio.client import Interceptor as ClientInterceptor
    from temporalio.runtime import Runtime

# In-cluster collector. Both signals export
# OTLP/HTTP :4318; the collector adds the ClickStack token on forward.
_COLLECTOR = "temporal-otel-collector.temporal.svc.cluster.local"
_TRACES_ENDPOINT = f"http://{_COLLECTOR}:4318/v1/traces"
_METRICS_ENDPOINT = f"http://{_COLLECTOR}:4318/v1/metrics"

_tracing_configured = False


def otel_enabled() -> bool:
    """True when telemetry is on (the Deployments set ``FROOT_OTEL``)."""
    return TelemetrySettings().otel


def set_span_attributes(**attributes: int | float | str | bool) -> None:
    """Annotate the activity's current span with froot-namespaced attributes.

    A thin, dependency-light way for an activity to record *what it decided* —
    e.g. how many upgrades it saw versus how many candidates it kept — onto the
    span the Temporal tracing interceptor already opened. Keys are prefixed
    ``froot.`` so they never collide with the interceptor's own attributes.

    Lazy-imports OpenTelemetry inside the body, so no otel import enters any
    module's top-level graph (the Temporal workflow sandbox stays clean), and is
    a no-op when ``FROOT_OTEL`` is off — so tests and local runs add no spans
    and pay nothing. Call it from an activity body, never from a workflow.
    """
    if not otel_enabled():
        return
    from opentelemetry import trace

    span = trace.get_current_span()
    for key, value in attributes.items():
        span.set_attribute(f"froot.{key}", value)


def setup_tracing(service_name: str) -> None:
    """Install a global TracerProvider exporting OTLP/HTTP to the collector.

    Gated on ``FROOT_OTEL`` and idempotent: the provider (and its one background
    export thread) is built at most once per process.

    Args:
        service_name: The ``service.name`` resource attribute for this process.
    """
    global _tracing_configured
    if _tracing_configured or not otel_enabled():
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=_TRACES_ENDPOINT))
    )
    trace.set_tracer_provider(provider)
    _tracing_configured = True


def tracing_interceptors() -> Sequence[ClientInterceptor]:
    """Temporal interceptors that carry trace context across the boundary.

    ``always_create_workflow_spans=True`` so the schedule-/loop-started
    workflows (the scan loop) are traced too. Empty when telemetry is off.
    """
    if not otel_enabled():
        return []
    from temporalio.contrib.opentelemetry import TracingInterceptor

    return [TracingInterceptor(always_create_workflow_spans=True)]


def metrics_runtime() -> Runtime | None:
    """A Temporal Runtime that pushes SDK metrics OTLP, or ``None`` (off).

    ``None`` is accepted by ``Client.connect(runtime=...)`` (default runtime).
    """
    if not otel_enabled():
        return None
    from temporalio.runtime import (
        OpenTelemetryConfig,
        OpenTelemetryMetricTemporality,
        Runtime,
        TelemetryConfig,
    )

    return Runtime(
        telemetry=TelemetryConfig(
            metrics=OpenTelemetryConfig(
                url=_METRICS_ENDPOINT,
                metric_temporality=OpenTelemetryMetricTemporality.CUMULATIVE,
                metric_periodicity=timedelta(seconds=30),
                http=True,
            )
        )
    )


def instrument_httpx(client: httpx.Client) -> None:
    """Instrument one httpx client so W3C traceparent rides outbound calls."""
    if not otel_enabled():
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor.instrument_client(client)


def shutdown_tracing() -> None:
    """Flush + shut down the tracer provider on graceful termination.

    The BatchSpanProcessor buffers spans (~5s) and Python's ``atexit`` does NOT
    run on an unhandled SIGTERM, so without this the worker's last span batch is
    dropped on every (Recreate) rollout.
    """
    if not otel_enabled():
        return
    from opentelemetry import trace

    shutdown = getattr(trace.get_tracer_provider(), "shutdown", None)
    if shutdown is not None:
        shutdown()
