"""
core/metrics.py — Application metrics in Prometheus format

WHY Prometheus?
  Prometheus is the industry standard for application metrics.
  Pull-based model: Prometheus scrapes your /metrics endpoint every 15s.
  Time-series database: stores metrics as (timestamp, labels, value).
  Query language (PromQL): compute rates, percentiles, averages over time.

  Used by: Google, Uber, Cloudflare, SoundCloud (who created it).
  Compatible with: Grafana (dashboards), Alertmanager (alerts), Datadog.

WHY not use the prometheus_client library?
  We implement a minimal subset to avoid dependencies and teach the format.
  Production: install prometheus_client and use Counter, Histogram, Gauge.
  The output format is identical — any Prometheus server can scrape it.

Prometheus metric types:
  Counter:   monotonically increasing number (requests total, errors total)
             Never decreases. Resets to 0 on restart.
             Rate of increase = requests per second.

  Gauge:     can go up AND down (active connections, memory usage, queue size)
             Current value at scrape time.

  Histogram: samples observations into configurable buckets
             Exposes sum, count, and bucket counts.
             Used for latency (P50, P95, P99) and request sizes.
             Interview question: "How do you compute P95 latency from a histogram?"
             Answer: histogram_quantile(0.95, rate(http_duration_seconds_bucket[5m]))

  Summary:   similar to histogram but computes quantiles client-side
             Less flexible, can't aggregate across instances — prefer histogram.

Interview question: "What is the RED method for monitoring services?"
  Rate:    requests per second (how busy is it?)
  Errors:  errors per second (how broken is it?)
  Duration: request latency distribution (how slow is it?)
  These three metrics cover 95% of production debugging scenarios.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
import threading


@dataclass
class Counter:
    """
    A metric that only goes up.
    Example: total HTTP requests, total errors, total logins.
    """
    name: str
    help: str
    labels: dict[str, str] = field(default_factory=dict)
    _value: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def inc(self, amount: float = 1.0, **label_kwargs) -> None:
        with self._lock:
            self._value += amount

    def get(self) -> float:
        return self._value


@dataclass
class Gauge:
    """
    A metric that can go up or down.
    Example: active connections, cache hit ratio, queue depth.
    """
    name: str
    help: str
    _value: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    def get(self) -> float:
        return self._value


class Histogram:
    """
    Samples observations into buckets.
    Used for latency distribution — tells you P50, P95, P99.

    WHY fixed buckets?
      We define latency thresholds that matter for our SLA:
        ≤10ms: excellent (cache hit)
        ≤50ms: good (simple DB query)
        ≤200ms: acceptable (complex query)
        ≤500ms: slow (ML inference)
        ≤2000ms: very slow (problem)
        >2000ms: SLA violation

      If P95 crosses 2000ms, we want to know immediately.
      Grafana + Alertmanager can alert on: histogram_quantile(0.95, ...) > 2.0
    """
    DEFAULT_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]

    def __init__(self, name: str, help: str, buckets: list[float] = None):
        self.name = name
        self.help = help
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self._counts = defaultdict(int)   # bucket_upper_bound → count
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Record one observation (e.g., request latency in seconds)."""
        with self._lock:
            self._sum += value
            self._count += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[bucket] += 1
            # +Inf bucket: all observations
            self._counts[float('inf')] += 1

    def get_prometheus_lines(self, labels: str = '') -> list[str]:
        """Serialize to Prometheus text format."""
        lines = []
        label_str = f'{{{labels}}}' if labels else ''
        with self._lock:
            cumulative = 0
            for bucket in self.buckets:
                cumulative += self._counts[bucket]
                lines.append(
                    f'{self.name}_bucket{label_str.rstrip("}")},le="{bucket}"}} {cumulative}'
                    if labels else
                    f'{self.name}_bucket{{le="{bucket}"}} {cumulative}'
                )
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
            lines.append(f'{self.name}_sum {self._sum}')
            lines.append(f'{self.name}_count {self._count}')
        return lines


class MetricsRegistry:
    """
    Central registry for all application metrics.

    WHY a registry pattern?
      All metrics are defined once and referenced everywhere.
      The /metrics endpoint iterates the registry and serializes all metrics.
      No metric is accidentally orphaned or double-counted.
    """

    def __init__(self):
        # ── HTTP metrics (RED: Rate, Errors, Duration) ──────────────────────
        self.http_requests_total = defaultdict(int)
        # Labels: method, path, status_code
        # Tracks: GET /api/v1/auth/login 200 → 1432 requests

        self.http_errors_total = defaultdict(int)
        # Labels: method, path, status_code
        # Tracks: POST /api/v1/auth/login 401 → 89 errors

        self.http_duration = Histogram(
            name='http_request_duration_seconds',
            help='HTTP request duration in seconds',
        )

        # ── Business metrics ────────────────────────────────────────────────
        self.interviews_started = Counter(
            name='devmentor_interviews_started_total',
            help='Total interview sessions started',
        )
        self.interviews_completed = Counter(
            name='devmentor_interviews_completed_total',
            help='Total interview sessions completed',
        )
        self.answers_scored = Counter(
            name='devmentor_answers_scored_total',
            help='Total answers scored by ML service',
        )
        self.ml_service_errors = Counter(
            name='devmentor_ml_errors_total',
            help='Total ML service errors (timeouts, failures)',
        )
        self.cache_hits = Counter(
            name='devmentor_cache_hits_total',
            help='Total Redis cache hits',
        )
        self.cache_misses = Counter(
            name='devmentor_cache_misses_total',
            help='Total Redis cache misses',
        )

        # ── System metrics ──────────────────────────────────────────────────
        self.active_connections = Gauge(
            name='devmentor_active_connections',
            help='Number of active HTTP connections',
        )
        self.db_pool_size = Gauge(
            name='devmentor_db_pool_size',
            help='Current database connection pool size',
        )

        self._start_time = time.time()

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Called by middleware for every HTTP request."""
        label_key = f'{method}:{path}:{status_code}'
        self.http_requests_total[label_key] += 1

        if status_code >= 400:
            self.http_errors_total[label_key] += 1

        self.http_duration.observe(duration_seconds)

    def prometheus_output(self) -> str:
        """
        Serialize all metrics to Prometheus exposition format.

        Format:
          # HELP metric_name Description of the metric
          # TYPE metric_name counter|gauge|histogram
          metric_name{label="value"} 42
          metric_name{label="other"} 17

        This is what Prometheus scrapes from GET /metrics.
        Grafana reads from Prometheus and renders dashboards.

        Interview question: "What is the Prometheus data model?"
          Metric name + set of key-value labels = unique time series.
          http_requests_total{method="GET", status="200"} is different from
          http_requests_total{method="POST", status="404"}.
          Each combination is a separate time series in the TSDB.
        """
        lines = [
            '# HELP process_uptime_seconds Time since process started',
            '# TYPE process_uptime_seconds gauge',
            f'process_uptime_seconds {time.time() - self._start_time:.2f}',
            '',
            '# HELP http_requests_total Total HTTP requests',
            '# TYPE http_requests_total counter',
        ]

        for label_key, count in self.http_requests_total.items():
            method, path, status = label_key.split(':', 2)
            lines.append(
                f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        lines += [
            '',
            '# HELP http_request_duration_seconds HTTP request duration',
            '# TYPE http_request_duration_seconds histogram',
        ]
        lines += self.http_duration.get_prometheus_lines()

        lines += [
            '',
            '# HELP devmentor_interviews_started_total Interview sessions started',
            '# TYPE devmentor_interviews_started_total counter',
            f'devmentor_interviews_started_total {self.interviews_started.get()}',
            '',
            '# HELP devmentor_interviews_completed_total Interview sessions completed',
            '# TYPE devmentor_interviews_completed_total counter',
            f'devmentor_interviews_completed_total {self.interviews_completed.get()}',
            '',
            '# HELP devmentor_cache_hits_total Cache hits',
            '# TYPE devmentor_cache_hits_total counter',
            f'devmentor_cache_hits_total {self.cache_hits.get()}',
            '',
            '# HELP devmentor_cache_misses_total Cache misses',
            '# TYPE devmentor_cache_misses_total counter',
            f'devmentor_cache_misses_total {self.cache_misses.get()}',
            '',
            '# HELP devmentor_answers_scored_total Total answers scored by ML service',
            '# TYPE devmentor_answers_scored_total counter',
            f'devmentor_answers_scored_total {self.answers_scored.get()}',
            '',
            '# HELP devmentor_ml_errors_total ML service errors',
            '# TYPE devmentor_ml_errors_total counter',
            f'devmentor_ml_errors_total {self.ml_service_errors.get()}',
            '',
            '# HELP devmentor_active_connections Active HTTP connections',
            '# TYPE devmentor_active_connections gauge',
            f'devmentor_active_connections {self.active_connections.get()}',
        ]

        return '\n'.join(lines) + '\n'


# Module-level singleton
metrics = MetricsRegistry()
