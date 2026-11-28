# ADR-0001: Proposed end-to-end AIOps stack

## Status

**Partially decided — Phase 2 Kafka transport only.** The scoped Apache Kafka choice is accepted and the Phase 2 Collector-to-Kafka producer, topics, and data-contract slice are implemented in the opt-in local profile. Architect review of that slice has not passed, and Project Owner acceptance is pending. All other proposals remain pending Project Owner decision; none of them is approved by this ADR.

## Date

2026-11-22

## Context

The project needs an end-to-end, reproducible path from synthetic microservice telemetry to stream processing, historical replay, signal search, anomaly evaluation, and incident investigation. The existing design names several alternatives but does not select one broker, a concrete metrics store, an Iceberg catalog, or an incident API framework.

Constraints from `README.md`, `description.md`, and `AGENTS.md`:

- Keep OpenTelemetry logs, metrics, and traces linked to evidence; do not present correlation or ranking as proof of causality.
- Choose one product per responsibility and keep the local profile runnable in slices rather than requiring the entire stack for every task.
- Preserve Phase 0 workload/output contracts and Phase 1 instrumentation. Do not implement a later phase until the Project Owner authorizes it.
- Prefer open protocols and components with documented interoperability. Pin exact versions only when their integration is implemented and tested.

## Proposed stack and current status

The table records the proposed architecture baseline. Only the Apache Kafka row is accepted and implemented, scoped to Phase 2; every other row remains a proposal subject to Project Owner decision and phase-specific verification.

| Responsibility | Proposed choice | Scope / rationale |
|---|---|---|
| Workload and application code | Python; retain the current standard-library demo | Implemented in Phase 0–1. Avoid rewriting the working workload. Use Python for the later API and analysis code. |
| Telemetry | OpenTelemetry Python SDK + OpenTelemetry Collector | Implemented in Phases 1–2. Keep OTLP as the signal interchange boundary. The Collector Contrib distribution is used for the Kafka exporter. |
| Event broker | **Apache Kafka**, one broker product only, KRaft mode for local development | **Accepted and implemented for Phase 2 only.** Single-node KRaft in the opt-in `streaming` Compose profile; prefer the native Kafka protocol and the future Flink Kafka connector path over an additional broker-compatibility variable. Not a production availability claim. |
| Stream processing | **Apache Flink 2.2.x with PyFlink DataStream API** and the matching Kafka connector artifact | Proposed, not implemented. Reuse Python for transforms while retaining Flink event-time, state, and checkpoint capabilities. Current official docs expose the Kafka connector for Flink 2.2.1; the current 2.3 connector page says its connector is not yet available. Use the 2.2 line as the proposed starting point, then verify the exact Flink, connector, and Iceberg artifact matrix before pinning. |
| Historical data | **MinIO** for local S3-compatible object storage; **Apache Iceberg** for table format; **Apache Polaris** as the Iceberg REST catalog | Proposed, not implemented. Gives Flink and other engines a shared table catalog and separates durable raw/curated history from serving stores. Keep local MinIO data disposable and synthetic. |
| Logs and incident documents | **OpenSearch** | Proposed, not implemented. Search raw log evidence and store/query derived incident documents; do not add a second log-search engine. |
| Metrics | **Prometheus** | Proposed, not implemented. Use a single-node Prometheus server for the demo and PromQL. Keep labels bounded; use Iceberg for longer-term historical/replay data rather than treating Prometheus as the lakehouse. |
| Traces | **Grafana Tempo**, monolithic mode for local development | Proposed, not implemented. Receive/query OTLP traces without adding a separate trace store. Use MinIO object storage with a dedicated bucket or prefix when persistent trace blocks are enabled. |
| API | **FastAPI** for the incident/evidence REST API | Proposed, not implemented. Fits the Python service stack and provides an OpenAPI-described interface. API implementation remains in its authorized phase. A read-only MCP adapter over incident/timeline/evidence queries is recorded as a future optional direction after the API and evidence retrieval exist; it is not implemented and is not part of Phase 2, and it must not expose mutation or operational actions. Recording this direction does not approve any other ADR component or authorize an MCP server implementation. |
| Detection and evaluation | Python + **scikit-learn**, starting with transparent statistical/rule baselines | Proposed, not implemented. Establish a reproducible baseline before evaluating Isolation Forest or other models; labels are for evaluation, not model input leakage. |
| Experiment tracking | **MLflow**, introduced only with the model-evaluation phase | Proposed, not implemented. Start with local tracking; add a shared tracking server/storage only if team collaboration requires it. |
| Dashboards | **Grafana** | Proposed, not implemented. Use Prometheus and Tempo data sources; expose linked log/incident evidence from OpenSearch where supported by the implemented query path. |
| Local orchestration | **Docker Compose**, split into opt-in profiles | Partially implemented: the Phase 0–1 demo profile and the Phase 2 `streaming` profile exist. Later streaming/investigation services are proposed in separately startable profiles so ordinary tests do not require the full stack. |
| Kubernetes packaging | Kubernetes + **Helm**, deferred to the deployment phase | Proposed, not implemented. Keep runtime manifests and deployment work out of early local integration phases. |
| LLM summaries | **Not in the baseline stack** | Not implemented. Reconsider only after evidence retrieval and deterministic incident output work; any later LLM may summarize retrieved evidence but must not detect incidents or invent telemetry. |

### Data flow: implemented versus proposed

Implemented in Phase 2 (opt-in `streaming` profile):

```text
Python services + OpenTelemetry SDK
  → OpenTelemetry Collector Contrib 0.143.0
      ├─ debug exporter (diagnostic only)
      └─ Kafka topics aiops.otlp.{logs,metrics,traces}.v1 (OTLP Protobuf)
```

Proposed for later phases (not implemented):

```text
Kafka topics
  → Apache Flink (validation, event-time processing, correlation/features)
      ├─ Prometheus / OpenSearch / Tempo (serving and investigation; Phase 4)
      └─ Iceberg tables on MinIO (raw/curated history and replay; Phase 3)
  → FastAPI incident/evidence API (Phase 6)
      ├─ read-only MCP adapter over incident/timeline/evidence queries (future optional direction)
      └─ Grafana dashboards and alerts
```

Phase 2 defined and tested the topic names, OTLP serialization, version suffix, partition keys, retention, malformed-request handling, retries, and backpressure configuration. The producer is implemented; its ingestion into Flink and the object-store/backend fan-out remain future work. Flink-derived incident records are proposed for OpenSearch; Iceberg remains the proposed replayable historical record. The Collector-to-serving-store fan-out must be configured and tested in its own phase to avoid silently dropping a signal when one destination fails.

Local profiles are brought up by phase: the Phase 0–1 demo profile stays small; the current `streaming` profile adds Kafka and Collector only; Phase 3 is expected to add Flink/object storage/catalog; Phase 4 is expected to add OpenSearch/Prometheus/Tempo/Grafana. Kubernetes is a later deployment target, not a prerequisite for local development.

## Alternatives considered

### Redpanda instead of Apache Kafka

Redpanda documents compatibility with Kafka clients, making it a viable option. The proposal selects Apache Kafka to minimize broker-specific compatibility assumptions with Flink's Kafka connector and to keep the project on the protocol's reference implementation. Do not run both brokers. Revisit only if local resource use or operations prove to be a material blocker and connector interoperability is demonstrated in an integration test.

### Use only the signal backends and omit Kafka/Flink

This is lighter, but does not meet the project's stated goals for event-time processing, replay, late/duplicate handling, or checkpoint/recovery evaluation.

### Store all signals in one backend

This reduces service count but weakens the project's explicit cross-signal query and evidence-linking goals. Keep one serving store per signal responsibility, with Iceberg as the historical layer.

### Add a model or LLM in the initial pipeline

Rejected for the baseline: transparent deterministic behavior and traceable evidence must exist first. MLflow is delayed until model comparisons are meaningful; LLM summaries remain optional and require a separate approval.

## Consequences

- The selected architecture is intentionally multi-component and can consume substantial local resources. Compose profiles and phase boundaries are mandatory; no all-services default startup.
- Kafka plus Flink offers a direct connector pairing but requires compatible releases and separate connector artifacts. The Flink 2.2/2.3 Kafka connector status must be rechecked before Phase 3 implementation.
- The Collector Contrib distribution is now verified for Phase 2: version 0.143.0 includes the Kafka exporter, and the opt-in Collector-to-Kafka path is implemented. This does not verify later signal backends or Flink integration.
- MinIO, Polaris, Iceberg, and Flink require an explicit catalog, credentials, table layout, and object-store integration test. These details are not verified by this ADR.
- Prometheus is a bounded-retention serving store, not the durable historical source; retention and cardinality limits must be written into the deployment profile.
- Kafka image 4.1.2, Collector Contrib 0.143.0, and the Phase 2 topic/partition/retention contract are pinned by the implemented Phase 2 files. Flink, backend, Kubernetes, and CI versions remain unpinned until their phases implement and verify them.
- Phase 0 and Phase 1 remain unchanged. The scoped Kafka decision authorizes only the implemented Phase 2 transport slice; this ADR does not authorize Phase 3+, deployment, or acceptance of any phase.

## Official references reviewed

- OpenTelemetry Collector configuration and component/pipeline model: <https://opentelemetry.io/docs/collector/configuration/>
- Redpanda Kafka protocol/client compatibility (alternative considered): <https://docs.redpanda.com/current/develop/kafka-clients/>
- Apache Flink 2.2.1 Kafka connector docs: <https://nightlies.apache.org/flink/flink-docs-release-2.2/docs/connectors/datastream/kafka/>
- Apache Flink current stable Kafka connector docs (connector availability caveat): <https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/kafka/>
- Apache Iceberg Flink integration and catalog options: <https://iceberg.apache.org/docs/latest/flink/>
- Apache Polaris catalog overview and supported engines: <https://polaris.apache.org/>
- Prometheus architecture and pull-based collection: <https://prometheus.io/docs/introduction/overview/>
- Grafana Tempo configuration and monolithic/local mode: <https://grafana.com/docs/tempo/latest/configuration/>
- OpenSearch documentation: <https://docs.opensearch.org/latest/>
- MLflow Tracking: <https://mlflow.org/docs/latest/ml/tracking/>

## Approval

Overall Project Owner decision for this proposal: **Pending**. The scoped Phase 2 Kafka selection below is accepted independently; it does not accept the remaining proposals or authorize later phases.

### Scoped Phase 2 decision

- **Accepted choice for Phase 2 only:** Apache Kafka, single-node KRaft for the opt-in local streaming profile.
- **Not accepted by this scoped decision:** any other row in the proposed stack table or the end-to-end data flow.
- **Implemented:** the Collector Contrib Kafka exporter, three versioned topics, partition/retention contract, retry/queue settings, and smoke tests. Baseline produce/read-back, malformed OTLP rejection, and a small local ingest measurement have run; limitations are recorded in `docs/PHASE_2_REPORT.md`.
- **Status:** implementation complete for this scoped slice; Architect review has not passed and Project Owner acceptance is pending. Phase 3+ and the remaining proposals are not authorized.
- Verification sources for the concrete local image/exporter configuration are listed in `docs/PHASE_2_REPORT.md`.
