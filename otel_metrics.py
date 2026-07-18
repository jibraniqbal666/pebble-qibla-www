"""OpenTelemetry metrics setup with Prometheus scrape endpoint."""

from __future__ import annotations

import os

from flask import Response, request
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from werkzeug.exceptions import NotFound, Unauthorized

_meter: metrics.Meter | None = None
_subscribe_counter = None
_geocode_counter = None
_timetable_cache_counter = None
_pins_generated_counter = None
_initialized = False


def _get_meter() -> metrics.Meter:
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("pebble-qibla")
    return _meter


def _ensure_instruments() -> None:
    global _subscribe_counter, _geocode_counter, _timetable_cache_counter, _pins_generated_counter
    meter = _get_meter()
    if _subscribe_counter is None:
        _subscribe_counter = meter.create_counter(
            "qibla.subscribe.total",
            description="Total successful subscribe requests",
        )
    if _geocode_counter is None:
        _geocode_counter = meter.create_counter(
            "qibla.geocode.total",
            description="Geocode attempts by result",
        )
    if _timetable_cache_counter is None:
        _timetable_cache_counter = meter.create_counter(
            "qibla.timetable.cache.total",
            description="Timetable cache lookups by layer and method",
        )
    if _pins_generated_counter is None:
        _pins_generated_counter = meter.create_counter(
            "qibla.timeline.pins.generated",
            description="Timeline pins generated for adhoc fetch",
        )


def record_subscribe() -> None:
    _ensure_instruments()
    _subscribe_counter.add(1)


def record_geocode(result: str) -> None:
    _ensure_instruments()
    _geocode_counter.add(1, {"result": result})


def record_timetable_cache(layer: str, method: str) -> None:
    _ensure_instruments()
    _timetable_cache_counter.add(1, {"layer": layer, "method": method})


def record_pins_generated(count: int) -> None:
    if count <= 0:
        return
    _ensure_instruments()
    _pins_generated_counter.add(count)


def metrics_response() -> Response:
    """Return Prometheus text exposition from this process's MeterProvider.

    OpenTelemetry's PrometheusMetricReader keeps series in-process. Gunicorn
    workers each expose their own values; do not set PROMETHEUS_MULTIPROC_DIR
    (prometheus_client multiproc files are not used by the OTel reader and
    would hide these series).
    """
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def _authorize_metrics() -> None:
    """Require Bearer token from METRICS_TOKEN. Disabled (404) when unset."""
    expected = os.environ.get("METRICS_TOKEN")
    if not expected:
        raise NotFound()
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {expected}":
        return
    raise Unauthorized(www_authenticate='Bearer realm="metrics"')


def init_metrics(app) -> None:
    """Configure MeterProvider, Flask instrumentation, and /metrics route."""
    global _initialized, _meter
    if _initialized:
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", "pebble-qibla-www")
    resource = Resource.create({"service.name": service_name})
    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _meter = metrics.get_meter("pebble-qibla")
    _ensure_instruments()

    FlaskInstrumentor().instrument_app(
        app,
        meter_provider=provider,
        excluded_urls="metrics",
    )

    @app.route("/metrics")
    def prometheus_metrics():
        _authorize_metrics()
        return metrics_response()

    _initialized = True
