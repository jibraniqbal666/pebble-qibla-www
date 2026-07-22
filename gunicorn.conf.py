"""Gunicorn config for pebble-qibla-www.

Note: OpenTelemetry Prometheus metrics are process-local. Do not set
PROMETHEUS_MULTIPROC_DIR — that mode is for prometheus_client file-based
aggregation and hides OTel's PrometheusMetricReader series.
"""
