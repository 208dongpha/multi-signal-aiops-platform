"""Synthetic three-service HTTP workload for labeled failure experiments."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from opentelemetry import propagate
from opentelemetry.context import attach, detach
from opentelemetry.trace import SpanKind, Status, StatusCode

from demo.telemetry import create_in_memory_telemetry, create_otlp_telemetry


SCENARIOS = {
    "baseline": {"description": "Normal request", "injected_service": None, "fault_type": None, "expected_outcome": "success", "expected_http_status": 200},
    "latency": {"description": "Inventory responds slowly", "injected_service": "inventory", "fault_type": "injected_latency", "expected_outcome": "degraded_success", "expected_http_status": 200},
    "http_5xx": {"description": "Inventory returns HTTP 500", "injected_service": "inventory", "fault_type": "http_5xx", "expected_outcome": "dependency_error", "expected_http_status": 502},
    "timeout_retry": {"description": "Inventory exceeds timeout; orders retries once", "injected_service": "inventory", "fault_type": "timeout_with_retry", "expected_outcome": "timeout", "expected_http_status": 504},
    "dependency_failure": {"description": "Inventory dependency is unavailable", "injected_service": "inventory", "fault_type": "dependency_unavailable", "expected_outcome": "dependency_unavailable", "expected_http_status": 503},
}

SERVICE_NAMES = ("gateway", "orders", "inventory")
_ports: dict[str, int] = {}
_events: list[dict] = []
_event_lock = threading.Lock()
_config: dict = {}
_telemetry: dict = {}


def validate_event(event: dict) -> None:
    required = {"schema_version", "event_id", "run_id", "timestamp", "signal_type", "service_name", "trace_id", "scenario_id", "attributes"}
    if not required.issubset(event):
        raise ValueError(f"Missing event fields: {sorted(required - event.keys())}")
    if event["schema_version"] != "1.0" or event["signal_type"] not in {"log", "metric", "trace"}:
        raise ValueError("Unsupported event schema version or signal_type")
    if event["service_name"] not in SERVICE_NAMES or event["scenario_id"] not in SCENARIOS:
        raise ValueError("Unknown service_name or scenario_id")
    if len(event["run_id"]) != 32 or any(char not in "0123456789abcdef" for char in event["run_id"]):
        raise ValueError("run_id must be a 32-character lowercase hexadecimal identifier")
    signal_fields = {
        "log": {"message", "severity"},
        "metric": {"metric_name", "metric_value"},
        "trace": {"span_id", "parent_span_id", "duration_ms", "status"},
    }[event["signal_type"]]
    if not signal_fields.issubset(event):
        raise ValueError(f"Missing {event['signal_type']} fields: {sorted(signal_fields - event.keys())}")


def _emit(run_id: str, service: str, trace_id: str, span_id: str, parent_span_id: str | None, scenario: str, status: int, started: float, message: str, attempt: int = 1) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    common = {
        "schema_version": "1.0", "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id, "service_name": service, "trace_id": trace_id, "scenario_id": scenario,
        "attributes": {"http.status_code": status, "attempt": attempt},
    }
    events = [
        {**common, "event_id": uuid.uuid4().hex, "signal_type": "log", "severity": "INFO" if status < 400 else "ERROR", "message": message},
        {**common, "event_id": uuid.uuid4().hex, "signal_type": "metric", "metric_name": "http.server.request.duration_ms", "metric_value": duration_ms},
        {**common, "event_id": uuid.uuid4().hex, "signal_type": "trace", "span_id": span_id, "parent_span_id": parent_span_id, "duration_ms": duration_ms, "status": "OK" if status < 400 else "ERROR"},
    ]
    with _event_lock:
        _events.extend(events)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def _reply(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Expected when the timeout/retry scenario abandons a slow attempt.

    def do_GET(self) -> None:
        service = self.server.service_name
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        scenario = params.get("scenario", ["baseline"])[0]
        run_id = self.headers.get("X-Run-ID", "")
        logical_parent_span_id = self.headers.get("X-AIOps-Parent-Span-ID")
        attempt = int(params.get("attempt", ["1"])[0])
        telemetry = _telemetry[service]
        token = attach(propagate.extract({key.lower(): value for key, value in self.headers.items()}))
        started = time.perf_counter()
        status, message = 200, "request completed"
        body = {}
        try:
            with telemetry.tracer.start_as_current_span(
                f"{service} server request", kind=SpanKind.SERVER
            ) as span:
                span.set_attribute("http.request.method", "GET")
                span.set_attribute("service.name", service)
                if scenario in SCENARIOS:
                    span.set_attribute("scenario.id", scenario)
                try:
                    if scenario not in SCENARIOS:
                        status, message = 400, "unknown scenario"
                    elif service == "gateway":
                        status, body = self._call(
                            "orders", scenario, run_id,
                            logical_parent_span_id=f"{span.get_span_context().span_id:016x}",
                        )
                        message = "forwarded request to orders"
                    elif service == "orders":
                        status, body, message = self._orders(scenario, run_id, f"{span.get_span_context().span_id:016x}")
                    else:
                        status, body, message = self._inventory(scenario)
                    if status == 200 and service == "inventory":
                        body = {"inventory": "available"}
                except Exception as exc:
                    status, body, message = 503, {"error": "service request failed"}, type(exc).__name__
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                elapsed = time.perf_counter() - started
                telemetry.record_request(scenario if scenario in SCENARIOS else "baseline", status, elapsed)
                telemetry.log_request(message, scenario if scenario in SCENARIOS else "baseline", status)
                span_context = span.get_span_context()
                _emit(
                    run_id, service, f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}",
                    logical_parent_span_id, scenario if scenario in SCENARIOS else "baseline", status,
                    started, message, attempt,
                )
        finally:
            detach(token)
        self._reply(status, {"service": service, "scenario_id": scenario, **body})

    def _call(self, target: str, scenario: str, run_id: str, attempt: int = 1, logical_parent_span_id: str | None = None) -> tuple[int, dict]:
        query = urllib.parse.urlencode({"scenario": scenario, "attempt": attempt})
        timeout = _config["gateway_timeout_seconds"] if target == "orders" else _config["request_timeout_seconds"]
        telemetry = _telemetry[self.server.service_name]
        with telemetry.tracer.start_as_current_span(f"HTTP GET {target}", kind=SpanKind.CLIENT) as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("peer.service", target)
            headers = {"X-Run-ID": run_id}
            if logical_parent_span_id:
                headers["X-AIOps-Parent-Span-ID"] = logical_parent_span_id
            propagate.inject(headers)
            request = urllib.request.Request(f"http://127.0.0.1:{_ports[target]}/?{query}", headers=headers)
            try:
                try:
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        status, body = response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    try:
                        status, body = exc.code, json.loads(exc.read())
                    finally:
                        exc.close()
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                return status, body
            except (TimeoutError, urllib.error.URLError) as exc:
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(exc)
                raise

    def _orders(self, scenario: str, run_id: str, span_id: str) -> tuple[int, dict, str]:
        attempts = 2 if scenario == "timeout_retry" else 1
        for attempt in range(1, attempts + 1):
            try:
                status, body = self._call("inventory", scenario, run_id, attempt, span_id)
                if status == 200:
                    return 200, {"order": "accepted", "inventory": body}, "order accepted"
                if scenario == "dependency_failure":
                    return 503, {"error": "inventory unavailable"}, "dependency unavailable"
                return 502, {"error": "inventory returned an error"}, "dependency returned HTTP error"
            except (TimeoutError, urllib.error.URLError):
                if attempt == attempts:
                    return 504, {"error": "inventory request timed out after retries"}, "inventory timeout"
        return 504, {"error": "inventory request timed out"}, "inventory timeout"

    def _inventory(self, scenario: str) -> tuple[int, dict, str]:
        if scenario == "latency":
            time.sleep(_config["latency_delay_seconds"])
        elif scenario == "timeout_retry":
            time.sleep(_config["timeout_delay_seconds"])
        elif scenario == "http_5xx":
            return 500, {"error": "synthetic inventory failure"}, "synthetic HTTP 500"
        elif scenario == "dependency_failure":
            return 503, {"error": "synthetic dependency unavailable"}, "synthetic dependency unavailable"
        return 200, {"inventory": "available"}, "inventory lookup completed"


def run_scenario(scenario_id: str, telemetry_factory=create_in_memory_telemetry) -> dict:
    """Start all local services, issue one labeled request, and collect synthetic signals."""
    global _ports, _events, _config, _telemetry
    if scenario_id not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    _config = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
    _events = []
    _telemetry = {name: telemetry_factory(name) for name in SERVICE_NAMES}
    servers = []
    threads = []
    for name in SERVICE_NAMES:
        server = ThreadingHTTPServer((_config["host"], 0), _Handler)
        server.daemon_threads = True
        server.service_name = name
        server.telemetry = _telemetry[name]
        servers.append(server)
    _ports = {name: server.server_address[1] for name, server in zip(SERVICE_NAMES, servers)}
    try:
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        run_id = uuid.uuid4().hex
        scenario_start_utc = datetime.now(timezone.utc).isoformat()
        query = urllib.parse.urlencode({"scenario": scenario_id})
        root_telemetry = _telemetry["gateway"]
        with root_telemetry.tracer.start_as_current_span("HTTP GET gateway", kind=SpanKind.CLIENT) as root_span:
            root_span.set_attribute("http.request.method", "GET")
            root_span.set_attribute("peer.service", "gateway")
            headers = {"X-Run-ID": run_id}
            propagate.inject(headers)
            request = urllib.request.Request(
                f"http://{_config['host']}:{_ports['gateway']}/?{query}", headers=headers
            )
            try:
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        status, body = response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    try:
                        status, body = exc.code, json.loads(exc.read())
                    finally:
                        exc.close()
                root_span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    root_span.set_status(Status(StatusCode.ERROR))
            except Exception as exc:
                root_span.set_status(Status(StatusCode.ERROR))
                root_span.record_exception(exc)
                raise
        # Slow timed-out attempts can finish after the client response; allow their telemetry to flush.
        time.sleep(_config["telemetry_flush_seconds"])
        scenario_end_utc = datetime.now(timezone.utc).isoformat()
        events = sorted(_events, key=lambda event: event["timestamp"])
        scenario = SCENARIOS[scenario_id]
        ground_truth = {
            "scenario_id": scenario_id,
            "injected_service": scenario["injected_service"],
            "fault_type": scenario["fault_type"],
            "expected_outcome": scenario["expected_outcome"],
            "scenario_start_utc": scenario_start_utc,
            "scenario_end_utc": scenario_end_utc,
        }
        return {"run_id": run_id, "scenario_id": scenario_id, "expected_outcome": scenario["expected_outcome"], "ground_truth": ground_truth, "status": status, "response": body, "events": events}
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        for telemetry in _telemetry.values():
            telemetry.shutdown()


def write_run_outputs(events_path: Path, result: dict, force: bool = False) -> Path:
    """Write events and their manifest without clobbering existing files by default."""
    events_path = Path(events_path)
    manifest_path = events_path.with_suffix(events_path.suffix + ".run.json")
    paths = (events_path, manifest_path)
    events_data = "".join(json.dumps(event) + "\n" for event in result["events"]).encode("utf-8")
    manifest = {key: value for key, value in result.items() if key != "events"}
    manifest_data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    payloads = (events_data, manifest_data)

    collisions = [path for path in paths if path.exists()]
    if collisions and not force:
        names = ", ".join(str(path) for path in collisions)
        raise FileExistsError(f"Refusing to overwrite existing output(s): {names}. Pass --force to replace them.")

    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)

    if force:
        staged = []
        try:
            for path, payload in zip(paths, payloads):
                descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
                staged.append((Path(temporary_path), path))
                with os.fdopen(descriptor, "wb") as output:
                    output.write(payload)
            for temporary_path, path in staged:
                os.replace(temporary_path, path)
            return manifest_path
        finally:
            for temporary_path, _ in staged:
                temporary_path.unlink(missing_ok=True)

    reserved = []
    descriptors = {}
    try:
        for path in paths:
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            except FileExistsError as exc:
                raise FileExistsError(f"Refusing to overwrite existing output: {path}. Pass --force to replace both outputs.") from exc
            reserved.append(path)
            descriptors[path] = descriptor
        for path, payload in zip(paths, payloads):
            descriptor = descriptors.pop(path)
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
        return manifest_path
    except Exception:
        for descriptor in descriptors.values():
            os.close(descriptor)
        for path in reserved:
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="baseline")
    parser.add_argument("--events", type=Path, help="Write telemetry events as JSON Lines to this path")
    parser.add_argument("--force", action="store_true", help="Replace existing event and run-manifest output files")
    args = parser.parse_args()
    result = run_scenario(args.scenario, telemetry_factory=create_otlp_telemetry)
    if args.events:
        try:
            manifest_path = write_run_outputs(args.events, result, force=args.force)
        except FileExistsError as exc:
            parser.error(str(exc))
    print(json.dumps({key: value for key, value in result.items() if key != "events"}, indent=2))
    outputs = f"; events: {args.events}; run manifest: {manifest_path}" if args.events else ""
    print(f"Collected {len(result['events'])} synthetic telemetry events{outputs}")


if __name__ == "__main__":
    main()
