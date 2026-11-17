"""OpenTelemetry 初始化与 W3C Trace Context 传播。"""

from __future__ import annotations

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

_configured = False
_httpx_instrumented = False


def _traces_endpoint() -> str:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if explicit:
        return explicit
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    return f"{base}/v1/traces" if base else ""


def _configure(service_name: str) -> None:
    global _configured, _httpx_instrumented
    if _configured:
        return
    endpoint = _traces_endpoint()
    if not endpoint:
        return
    sample_ratio = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
            "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
            "deployment.environment.name": os.getenv(
                "DEPLOYMENT_ENVIRONMENT", "compose"
            ),
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    _configured = True
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True


def instrument_fastapi(app: Any, service_name: str) -> None:
    _configure(service_name)
    if _configured:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="/health,/metrics",
        )


def instrument_asgi(app: Any, service_name: str) -> Any:
    _configure(service_name)
    if not _configured:
        return app
    return OpenTelemetryMiddleware(app)


def trace_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    carrier = dict(headers or {})
    inject(carrier)
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        carrier["X-Trace-ID"] = format(span_context.trace_id, "032x")
    return carrier
