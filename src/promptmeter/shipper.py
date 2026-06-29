"""Ship normalized events to an OTLP backend.

- **Logs** → the redacted transcript body per line, tagged `x-scope-orgid:
  <tenant>` so a multi-tenant Loki stores it per owner.
- **Metrics** → `ai_tx_*` gauges, built by hand so they can be back-dated to each
  message's event time (the metrics SDK won't backdate), then exported once.

Incremental: a per-session byte-offset ledger means re-runs tail only new lines.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

from .config import Config
from .events import Event
from .metrics import derive
from .providers import Provider
from .redaction import Redactor


class State:
    """Per-session byte-offset ledger (resumable tailing)."""
    def __init__(self, path: Path, reset: bool = False):
        self.path = path
        self.offsets: dict[str, int] = {}
        if not reset and path.exists():
            try:
                self.offsets = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                pass

    def get(self, key: str) -> int:
        return self.offsets.get(key, 0)

    def set(self, key: str, offset: int) -> None:
        self.offsets[key] = offset

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.offsets))


class Shipper:
    def __init__(self, cfg: Config, redactor: Redactor):
        self.cfg = cfg
        self.redactor = redactor

    def run(self, provider: Provider, *, dry_run: bool = False, reset: bool = False,
            limit: int = 0, metrics_only: bool = False, projects: str = "*") -> int:
        state = State(self.cfg.state_path, reset=reset)
        host = socket.gethostname()
        shipped = 0

        log_emit = metric_series = flush = None
        if not dry_run:
            log_emit, metric_series, flush, finalize = self._otlp(host)

        for session in provider.discover(projects=projects):
            start = state.get(session.key)
            last_offset = start
            tool_use_times: dict[str, int] = {}
            for offset, ev in provider.parse(session, start_offset=start):
                if not metrics_only:
                    self._ship_log(ev, log_emit, dry_run)
                if not dry_run:
                    derive(ev, self.cfg.owner, tool_use_times,
                           lambda n, v, ts, **lbl: metric_series.add(n, v, ts, **lbl))
                last_offset = offset
                shipped += 1
                if limit and shipped >= limit:
                    break
            # Advance the ledger only for content lines (metrics_only leaves it alone
            # so it stays an idempotent metric backfill).
            if not dry_run and not metrics_only and last_offset > start:
                state.set(session.key, last_offset)
            if limit and shipped >= limit:
                break

        if dry_run:
            print(f"[dry-run] would ship {shipped} records as owner={self.cfg.owner} "
                  f"(tenant {self.cfg.tenant})")
            return shipped

        if not metrics_only:
            flush()
            state.save()
        finalize()
        print(f"shipped {shipped} records as owner={self.cfg.owner} (tenant {self.cfg.tenant})")
        return shipped

    # --- OTLP plumbing -----------------------------------------------------

    def _ship_log(self, ev: Event, log_emit, dry_run: bool) -> None:
        body = self.redactor.redact(ev.body)
        if dry_run or not body:
            return
        attrs = {k: v for k, v in ev.metadata.items() if v}
        attrs.update(provider=ev.provider, project=ev.project,
                     session_title=ev.session_title)
        log_emit(body, attrs, ev.timestamp_ns)

    def _otlp(self, host: str):
        from opentelemetry._logs import SeverityNumber
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics.export import (
            Gauge, Metric, MetricsData, NumberDataPoint, ResourceMetrics, ScopeMetrics)
        from opentelemetry.sdk.util.instrumentation import InstrumentationScope

        resource = Resource.create({
            "service.name": "promptmeter",
            "service.namespace": "ai-telemetry",
            "host.name": host,
        })
        # Logs carry the per-owner Loki tenant; metrics do not (Mimir scopes on `owner`).
        log_headers = dict(self.cfg.headers, **{"x-scope-orgid": self.cfg.tenant})
        provider = LoggerProvider(resource=resource)
        log_exporter = OTLPLogExporter(endpoint=self.cfg.endpoint,
                                       headers=tuple(log_headers.items()),
                                       insecure=self.cfg.insecure, timeout=30)
        batch = BatchLogRecordProcessor(log_exporter, max_queue_size=65536,
                                        max_export_batch_size=512)
        provider.add_log_record_processor(batch)
        logger = provider.get_logger("promptmeter")

        # Loki rejects entries far behind a stream's head, so stamp each log with a
        # monotonic INGESTION timestamp (always ahead) and keep the real event time
        # as the `event_time` attribute. Loki order == ship order.
        ts_base = time.time_ns()
        seq = [0]

        def log_emit(body: str, attrs: dict, event_ts_ns: int | None) -> None:
            seq[0] += 1
            a = dict(attrs)
            if event_ts_ns:
                a["event_time"] = str(event_ts_ns)
            logger.emit(
                timestamp=ts_base + seq[0],
                observed_timestamp=time.time_ns(),
                severity_number=SeverityNumber.INFO,
                body=body, attributes=a)

        class Series:
            def __init__(self):
                self.data: dict[str, list] = {}

            def add(self, name: str, value: float, ts_ns: int, **labels):
                labels = {k: v for k, v in labels.items() if v not in (None, "")}
                self.data.setdefault(name, []).append(NumberDataPoint(
                    attributes=labels, start_time_unix_nano=int(ts_ns),
                    time_unix_nano=int(ts_ns), value=value))

        series = Series()
        scope = InstrumentationScope("promptmeter")
        metric_exporter = OTLPMetricExporter(endpoint=self.cfg.endpoint,
                                             headers=tuple(self.cfg.headers.items()),
                                             insecure=self.cfg.insecure, timeout=30)

        def flush():
            provider.force_flush()

        def finalize():
            metrics = [Metric(name=n, description="", unit="", data=Gauge(data_points=pts))
                       for n, pts in series.data.items() if pts]
            if metrics:
                metric_exporter.export(MetricsData(resource_metrics=[ResourceMetrics(
                    resource=resource,
                    scope_metrics=[ScopeMetrics(scope=scope, metrics=metrics, schema_url="")],
                    schema_url="")]))
            provider.shutdown()

        return log_emit, series, flush, finalize
