"""
Prometheus metrics collector and helpers for ratelimit-core.
Tracks request throughput, 429 rejections, evaluation latency, and remaining quotas.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("ratelimit_core.metrics")

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


RATELIMIT_REQUESTS_TOTAL: Optional[Counter] = None
RATELIMIT_CHECK_DURATION_SECONDS: Optional[Histogram] = None
RATELIMIT_REMAINING_QUOTA: Optional[Gauge] = None
RATELIMIT_CIRCUIT_BREAKER_STATE: Optional[Gauge] = None
RATELIMIT_BACKEND_ERRORS_TOTAL: Optional[Counter] = None

if PROMETHEUS_AVAILABLE:
    RATELIMIT_REQUESTS_TOTAL = Counter(
        "ratelimit_requests_total",
        "Total number of requests processed by rate limiters",
        ["status", "algorithm", "route"],
    )
    RATELIMIT_CHECK_DURATION_SECONDS = Histogram(
        "ratelimit_check_duration_seconds",
        "Latency of rate limit decision processing",
        ["algorithm"],
        buckets=(0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
    )
    RATELIMIT_REMAINING_QUOTA = Gauge(
        "ratelimit_remaining_quota",
        "Current remaining requests/tokens quota",
        ["route"],
    )
    RATELIMIT_CIRCUIT_BREAKER_STATE = Gauge(
        "ratelimit_circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 2=half_open)",
        ["backend"],
    )
    RATELIMIT_BACKEND_ERRORS_TOTAL = Counter(
        "ratelimit_backend_errors_total",
        "Total errors encountered communicating with storage backends",
        ["backend", "operation"],
    )


def record_circuit_breaker_state(backend: str, state: str) -> None:
    """Record circuit breaker state change in Prometheus gauge."""
    if not PROMETHEUS_AVAILABLE or RATELIMIT_CIRCUIT_BREAKER_STATE is None:
        return
    val_map = {"closed": 0.0, "open": 1.0, "half_open": 2.0}
    val = val_map.get(state.lower(), 0.0)
    try:
        RATELIMIT_CIRCUIT_BREAKER_STATE.labels(backend=backend).set(val)
    except Exception as exc:
        logger.debug("Failed to record circuit breaker metric: %s", exc)


def record_backend_error(backend: str, operation: str) -> None:
    """Record a storage backend failure in Prometheus counter."""
    if not PROMETHEUS_AVAILABLE or RATELIMIT_BACKEND_ERRORS_TOTAL is None:
        return
    try:
        RATELIMIT_BACKEND_ERRORS_TOTAL.labels(backend=backend, operation=operation).inc()
    except Exception as exc:
        logger.debug("Failed to record backend error metric: %s", exc)


def record_metric(
    allowed: bool,
    algorithm: str,
    route: str,
    duration: float,
    remaining: Optional[int] = None,
) -> None:
    """Record rate limit decision metrics if Prometheus is available."""
    if not PROMETHEUS_AVAILABLE:
        return

    status = "allowed" if allowed else "rejected"
    try:
        if RATELIMIT_REQUESTS_TOTAL is not None:
            RATELIMIT_REQUESTS_TOTAL.labels(status=status, algorithm=algorithm, route=route).inc()
        if RATELIMIT_CHECK_DURATION_SECONDS is not None:
            RATELIMIT_CHECK_DURATION_SECONDS.labels(algorithm=algorithm).observe(duration)
        if RATELIMIT_REMAINING_QUOTA is not None and remaining is not None:
            RATELIMIT_REMAINING_QUOTA.labels(route=route).set(remaining)
    except Exception as exc:
        logger.debug("Failed to record prometheus metric: %s", exc)


def get_latest_metrics() -> tuple[bytes, str]:
    """
    Returns (raw_metrics_bytes, content_type_header) for HTTP /metrics endpoint.
    """
    if not PROMETHEUS_AVAILABLE:
        return b"# prometheus-client not installed\n", "text/plain; version=0.0.4"
    return generate_latest(), CONTENT_TYPE_LATEST

