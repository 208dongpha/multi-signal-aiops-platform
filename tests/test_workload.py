import json
import unittest
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from opentelemetry.exporter.otlp.proto.http import _log_exporter
from opentelemetry.trace import StatusCode

from demo.telemetry import create_in_memory_telemetry
from demo.workload import SCENARIOS, run_scenario, validate_event, write_run_outputs


class WorkloadTests(unittest.TestCase):
    def test_pinned_otlp_logs_exporter_private_import_is_available(self):
        self.assertEqual(version("opentelemetry-exporter-otlp-proto-http"), "1.44.0")
        self.assertEqual(
            _log_exporter.OTLPLogExporter.__module__,
            "opentelemetry.exporter.otlp.proto.http._log_exporter",
        )

    def test_every_labeled_scenario_runs_through_the_service_chain(self):
        for scenario_id, expected in SCENARIOS.items():
            with self.subTest(scenario=scenario_id):
                services = {}

                def factory(service_name):
                    service = create_in_memory_telemetry(service_name)
                    services[service_name] = service
                    return service

                result = run_scenario(scenario_id, telemetry_factory=factory)
                self.assertEqual(result["scenario_id"], scenario_id)
                self.assertEqual(result["expected_outcome"], expected["expected_outcome"])
                self.assertEqual(result["status"], expected["expected_http_status"])
                truth = result["ground_truth"]
                self.assertEqual(truth["scenario_id"], scenario_id)
                self.assertEqual(truth["injected_service"], expected["injected_service"])
                self.assertEqual(truth["fault_type"], expected["fault_type"])
                self.assertEqual(truth["expected_outcome"], expected["expected_outcome"])
                start = datetime.fromisoformat(truth["scenario_start_utc"])
                end = datetime.fromisoformat(truth["scenario_end_utc"])
                self.assertLessEqual(start, end)
                self.assertTrue(result["events"])
                event_ids = [event["event_id"] for event in result["events"]]
                self.assertEqual(len(event_ids), len(set(event_ids)))
                for event in result["events"]:
                    validate_event(event)
                    self.assertEqual(event["run_id"], result["run_id"])
                    event_time = datetime.fromisoformat(event["timestamp"])
                    self.assertLessEqual(start, event_time)
                    self.assertLessEqual(event_time, end)

                for service_name, service in services.items():
                    spans = service.span_exporter.get_finished_spans()
                    self.assertTrue(spans)
                    self.assertTrue(all(span.resource.attributes["service.name"] == service_name for span in spans))
                    logs = service.log_exporter.get_finished_logs()
                    self.assertTrue(logs)
                    self.assertTrue(all(log.resource.attributes["service.name"] == service_name for log in logs))
                    server_span = next(span for span in spans if span.name == f"{service_name} server request")
                    self.assertTrue(any(
                        log.log_record.trace_id == server_span.context.trace_id
                        and log.log_record.span_id == server_span.context.span_id
                        for log in logs
                    ))
                    metric_data = service.metric_reader.get_metrics_data()
                    self.assertEqual(metric_data.resource_metrics[0].resource.attributes["service.name"], service_name)
                    metric_names = {
                        metric.name
                        for scope in metric_data.resource_metrics[0].scope_metrics
                        for metric in scope.metrics
                    }
                    self.assertTrue({
                        "http.server.request.count",
                        "http.server.request.errors",
                        "http.server.request.duration",
                    }.issubset(metric_names))
                    for scope in metric_data.resource_metrics[0].scope_metrics:
                        for metric in scope.metrics:
                            for point in metric.data.data_points:
                                self.assertNotIn("run_id", point.attributes)
                                self.assertNotIn("trace_id", point.attributes)
                    if scenario_id in {"http_5xx", "timeout_retry", "dependency_failure"} and service_name in {"gateway", "orders"}:
                        self.assertEqual(server_span.status.status_code, StatusCode.ERROR)

    def test_timeout_retry_is_bounded_and_reproducible(self):
        result = run_scenario("timeout_retry")
        inventory_spans = [event for event in result["events"] if event["signal_type"] == "trace" and event["service_name"] == "inventory"]
        self.assertEqual(len(inventory_spans), 2)
        self.assertEqual(result["status"], 504)

    def test_events_have_contract_fields_and_share_trace_id(self):
        result = run_scenario("baseline")
        self.assertTrue(result["events"])
        trace_ids = set()
        for event in result["events"]:
            validate_event(event)
            trace_ids.add(event["trace_id"])
        self.assertEqual(len(trace_ids), 1)
        self.assertEqual({event["signal_type"] for event in result["events"]}, {"log", "metric", "trace"})
        spans = {event["service_name"]: event for event in result["events"] if event["signal_type"] == "trace"}
        self.assertIsNone(spans["gateway"]["parent_span_id"])
        self.assertEqual(spans["orders"]["parent_span_id"], spans["gateway"]["span_id"])
        self.assertEqual(spans["inventory"]["parent_span_id"], spans["orders"]["span_id"])

    def test_otel_resources_context_logs_and_metrics_are_service_scoped(self):
        services = {}

        def factory(service_name):
            service = create_in_memory_telemetry(service_name)
            services[service_name] = service
            return service

        result = run_scenario("baseline", telemetry_factory=factory)
        self.assertEqual(result["status"], 200)

        spans_by_service = {}
        all_spans = []
        for service_name, service in services.items():
            spans = service.span_exporter.get_finished_spans()
            self.assertTrue(spans)
            self.assertTrue(all(span.resource.attributes["service.name"] == service_name for span in spans))
            all_spans.extend(spans)
            server_span = next(span for span in spans if span.name == f"{service_name} server request")
            spans_by_service[service_name] = server_span

            logs = service.log_exporter.get_finished_logs()
            self.assertTrue(logs)
            self.assertTrue(all(log.resource.attributes["service.name"] == service_name for log in logs))
            correlated = next(
                log.log_record for log in logs
                if log.log_record.trace_id == server_span.context.trace_id
                and log.log_record.span_id == server_span.context.span_id
            )
            self.assertEqual(correlated.trace_id, server_span.context.trace_id)
            self.assertEqual(correlated.span_id, server_span.context.span_id)
            self.assertGreater(correlated.timestamp, 0)

            metrics = service.metric_reader.get_metrics_data()
            resource_metrics = metrics.resource_metrics[0]
            self.assertEqual(resource_metrics.resource.attributes["service.name"], service_name)
            metric_names = {metric.name for scope in resource_metrics.scope_metrics for metric in scope.metrics}
            self.assertTrue({"http.server.request.count", "http.server.request.errors", "http.server.request.duration"}.issubset(metric_names))
            for scope in resource_metrics.scope_metrics:
                for metric in scope.metrics:
                    for point in metric.data.data_points:
                        self.assertNotIn("run_id", point.attributes)
                        self.assertNotIn("trace_id", point.attributes)

        client_spans = {span.name: span for span in all_spans if span.name.startswith("HTTP GET ")}
        root_client = client_spans["HTTP GET gateway"]
        gateway_client = client_spans["HTTP GET orders"]
        inventory_client = client_spans["HTTP GET inventory"]
        self.assertEqual(spans_by_service["gateway"].parent.span_id, root_client.context.span_id)
        self.assertEqual(gateway_client.parent.span_id, spans_by_service["gateway"].context.span_id)
        self.assertEqual(spans_by_service["orders"].parent.span_id, gateway_client.context.span_id)
        self.assertEqual(inventory_client.parent.span_id, spans_by_service["orders"].context.span_id)
        self.assertEqual(spans_by_service["inventory"].parent.span_id, inventory_client.context.span_id)
        self.assertEqual(len({span.context.trace_id for span in all_spans}), 1)

    def test_http_5xx_marks_otel_spans_and_error_metrics(self):
        services = {}

        def factory(service_name):
            service = create_in_memory_telemetry(service_name)
            services[service_name] = service
            return service

        run_scenario("http_5xx", telemetry_factory=factory)
        inventory_spans = services["inventory"].span_exporter.get_finished_spans()
        self.assertTrue(any(span.status.status_code == StatusCode.ERROR for span in inventory_spans))
        metrics = services["inventory"].metric_reader.get_metrics_data()
        counter = next(
            metric for scope in metrics.resource_metrics[0].scope_metrics for metric in scope.metrics
            if metric.name == "http.server.request.errors"
        )
        self.assertGreater(sum(point.value for point in counter.data.data_points), 0)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            run_scenario("not-a-scenario")

    def test_existing_events_file_blocks_both_outputs_without_force(self):
        with TemporaryDirectory() as directory:
            events_path = Path(directory) / "events.jsonl"
            manifest_path = Path(str(events_path) + ".run.json")
            events_path.write_text("event sentinel", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "--force"):
                write_run_outputs(events_path, {"run_id": "run", "events": []})

            self.assertEqual(events_path.read_text(encoding="utf-8"), "event sentinel")
            self.assertFalse(manifest_path.exists())

    def test_existing_manifest_blocks_both_outputs_without_force(self):
        with TemporaryDirectory() as directory:
            events_path = Path(directory) / "events.jsonl"
            manifest_path = Path(str(events_path) + ".run.json")
            manifest_path.write_text("manifest sentinel", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "--force"):
                write_run_outputs(events_path, {"run_id": "run", "events": []})

            self.assertFalse(events_path.exists())
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), "manifest sentinel")

    def test_force_explicitly_replaces_both_output_files(self):
        with TemporaryDirectory() as directory:
            events_path = Path(directory) / "events.jsonl"
            manifest_path = Path(str(events_path) + ".run.json")
            events_path.write_text("old events", encoding="utf-8")
            manifest_path.write_text("old manifest", encoding="utf-8")

            write_run_outputs(events_path, {"run_id": "run", "events": [{"run_id": "run"}]}, force=True)

            self.assertIn('"run_id": "run"', events_path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"], "run")


if __name__ == "__main__":
    unittest.main()
