"""OpenTelemetry SDK setup for the three local workload services."""

from __future__ import annotations

import time

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class ServiceTelemetry:
    """Own signal providers for one service, avoiding global-provider collisions."""

    def __init__(self, service_name: str, *, in_memory: bool = False):
        resource = Resource.create({SERVICE_NAME: service_name})
        self.tracer_provider = TracerProvider(resource=resource)
        self.logger_provider = LoggerProvider(resource=resource)

        if in_memory:
            from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
            from opentelemetry.sdk.metrics.export import InMemoryMetricReader
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

            self.span_exporter = InMemorySpanExporter()
            self.log_exporter = InMemoryLogRecordExporter()
            self.metric_reader = InMemoryMetricReader()
            self.tracer_provider.add_span_processor(SimpleSpanProcessor(self.span_exporter))
            self.logger_provider.add_log_record_processor(SimpleLogRecordProcessor(self.log_exporter))
            self.meter_provider = MeterProvider(resource=resource, metric_readers=[self.metric_reader])
        else:
            self.span_exporter = None
            self.log_exporter = None
            self.metric_reader = None
            self.tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            self.meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=250)],
            )

        self.tracer = self.tracer_provider.get_tracer("aiops.demo")
        meter = self.meter_provider.get_meter("aiops.demo")
        self.requests = meter.create_counter(
            "http.server.request.count", unit="{request}", description="HTTP requests handled"
        )
        self.errors = meter.create_counter(
            "http.server.request.errors", unit="{request}", description="HTTP requests returning errors"
        )
        self.duration = meter.create_histogram(
            "http.server.request.duration", unit="s", description="HTTP server request duration"
        )

        self.logger = self.logger_provider.get_logger("aiops.demo")

    def record_request(self, scenario: str, status_code: int, duration_seconds: float) -> None:
        # Only bounded dimensions are used; run_id and trace_id never become metric labels.
        attributes = {
            "http.request.method": "GET",
            "http.response.status_code": status_code,
            "scenario.id": scenario,
        }
        self.requests.add(1, attributes)
        self.errors.add(1 if status_code >= 400 else 0, attributes)
        self.duration.record(duration_seconds, attributes)

    def log_request(self, message: str, scenario: str, status_code: int) -> None:
        self.logger.emit(
            timestamp=time.time_ns(),
            body=message,
            severity_number=SeverityNumber.ERROR if status_code >= 400 else SeverityNumber.INFO,
            severity_text="ERROR" if status_code >= 400 else "INFO",
            attributes={"scenario.id": scenario, "http.response.status_code": status_code},
        )

    def shutdown(self) -> None:
        self.tracer_provider.force_flush()
        self.logger_provider.force_flush()
        self.meter_provider.force_flush()
        self.tracer_provider.shutdown()
        self.logger_provider.shutdown()
        self.meter_provider.shutdown()


def create_in_memory_telemetry(service_name: str) -> ServiceTelemetry:
    """Create SDK providers with in-memory exporters for isolated tests."""
    return ServiceTelemetry(service_name, in_memory=True)


def create_otlp_telemetry(service_name: str) -> ServiceTelemetry:
    """Create SDK providers exporting OTLP/HTTP to the configured Collector."""
    return ServiceTelemetry(service_name)
