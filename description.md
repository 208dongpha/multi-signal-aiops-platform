# Project Design and Implementation Phases

## 1. Mục đích tài liệu

Tài liệu này chia dự án **Multi-Signal AIOps Platform for Microservices** thành các phase có đầu ra, phụ thuộc và tiêu chí nghiệm thu rõ ràng. Kiến trúc đích được thiết kế đầy đủ, nhưng mỗi phase phải để lại một lát dọc có thể chạy, kiểm thử và review được. Không xem việc kết nối nhiều sản phẩm là bằng chứng dự án đã hoàn thành.

## 2. Phạm vi và nguyên tắc thiết kế

### Bài toán

Thu thập logs, metrics và distributed traces từ một hệ thống microservices; xử lý telemetry theo streaming; phát hiện tín hiệu bất thường; tương quan các tín hiệu thành incident; cung cấp timeline và bằng chứng để hỗ trợ kỹ sư điều tra.

### Ngoài phạm vi cam kết

- Không tuyên bố model tự xác định nguyên nhân gốc chính xác nếu chưa có đánh giá nhân quả phù hợp.
- Không dùng LLM làm bộ phát hiện hoặc nguồn dữ kiện telemetry.
- Không cam kết production-grade/high availability chỉ dựa vào demo local.
- Không thêm công nghệ tương đương chỉ để tăng số lượng thành phần.

### Nguyên tắc

1. Một công nghệ cho mỗi trách nhiệm; lựa chọn Kafka hoặc Redpanda, không mặc định triển khai cả hai.
2. Ưu tiên giao thức mở và schema rõ ràng; giữ liên kết giữa service, timestamp, trace ID và incident.
3. Xử lý event-time, dữ liệu trễ, duplicate, replay, checkpoint và khôi phục như các yêu cầu cần kiểm thử.
4. Lưu được dữ liệu cần thiết để tái lập phân tích; tách raw khỏi curated data.
5. Có baseline dễ giải thích trước khi thêm mô hình phức tạp.
6. Mọi kết luận hiển thị phải truy ngược được về log, metric, trace hoặc quy tắc đã áp dụng.
7. Mọi chỉ số hiệu năng phải đo được, có mô tả workload và môi trường.
8. Chỉ mở rộng phạm vi sau khi lát hiện tại có tiêu chí nghiệm thu và tài liệu review.

## 3. Kiến trúc đích

```text
Kubernetes microservices + OpenTelemetry SDK
  → OpenTelemetry Collector
  → Apache Kafka (selected for Phase 2/local streaming; OTLP Protobuf topics)
  → Apache Flink
      ├─ MinIO/S3 + Iceberg: raw/curated history, replay, training
      ├─ OpenSearch: log/event search
      ├─ Prometheus-compatible store: metrics
      └─ Tempo: distributed traces
  → feature pipeline + anomaly detection + event correlation
  → Incident API + alerting + timeline + evidence links
  → Grafana; optional grounded LLM summary
```

Chỉ broker Kafka và đường Collector→Kafka thuộc Phase 2 đã triển khai. Các thành phần còn lại trong sơ đồ trên (Flink, lakehouse, signal stores, detection, incident API, Grafana) vẫn là kiến trúc đề xuất và chưa triển khai; Phase 3 trở đi chưa bắt đầu.

Môi trường phát triển có thể bắt đầu bằng Docker Compose. Kubernetes là môi trường đích để thể hiện triển khai workload và vận hành; không bắt buộc mọi backend phải chạy trong Kubernetes nếu điều đó làm demo cá nhân quá nặng. Cần ghi rõ profile local và profile Kubernetes khác nhau ở đâu.

Đề xuất lựa chọn stack tổng thể đang chờ Project Owner quyết định tại [`docs/decisions/0001-proposed-target-stack.md`](docs/decisions/0001-proposed-target-stack.md). Quyết định Kafka cho Phase 2 đã được chấp thuận có phạm vi và Phase 2 đã triển khai xong phần broker/Collector/topic contract, đang chờ Architect review và Project Owner acceptance. Các lựa chọn còn lại trong ADR vẫn chưa phải quyết định cuối cùng, và Phase 3 trở đi chưa bắt đầu.

## 4. Các phase

### Phase 0 — Foundation, specification, and reproducible failure workload

**Mục tiêu:** Tạo hợp đồng dữ liệu ban đầu và workload có thể sinh lỗi đã biết trước; đây là nguồn ground truth cho pipeline và đánh giá. Phase này đã được Project Owner ủy quyền triển khai riêng, không bao gồm Phase 1.

**Thiết kế/công việc đã triển khai:**
- Workload HTTP ba service trong một tiến trình local: `gateway → orders → inventory`; mỗi service lắng nghe trên cổng localhost động.
- Scenario labels tường minh: `baseline`, `latency`, `http_5xx`, `timeout_retry`, `dependency_failure`; kết quả kỳ vọng và HTTP status được khai báo cùng fixture trong `demo/workload.py`.
- `orders` gọi `inventory` qua HTTP; timeout/retry có giới hạn hai lần gọi. Kịch bản dependency failure mô phỏng dependency không khả dụng bằng HTTP 503.
- Sinh `run_id` trước khi gọi gateway; gắn cùng `run_id` vào mọi event và dùng `event_id` duy nhất cho từng event để consumer nhóm event theo run và phân biệt bản ghi.
- Kết quả run có `ground_truth`: `scenario_id`, `injected_service` (null cho baseline), `fault_type` (null cho baseline), `expected_outcome`, `scenario_start_utc` và `scenario_end_utc`. Cửa sổ bắt đầu ngay trước request gateway và kết thúc sau khi nhận response cùng telemetry flush đã cấu hình; thời gian là UTC ISO 8601.
- Khi dùng `--events PATH`, ghi event JSONL và manifest `PATH.run.json` với metadata/ground truth của run; consumer nối manifest và events bằng `run_id`.
- Mỗi request phát sinh các event synthetic dạng log, metric và trace; dùng chung `trace_id`, có service name, timestamp UTC, scenario label và thông tin span cha/con.
- Cấu hình thời gian local tại `demo/config.json`; schema envelope ban đầu tại `demo/telemetry.schema.json`.
- Chỉ dùng Python standard library; chưa thêm CI hoặc backend telemetry.

**Đầu ra:** `demo/workload.py`, cấu hình local, schema telemetry, unit tests, lệnh chạy và tài liệu Phase 0 (`README.md`, báo cáo `docs/PHASE_0_REPORT.md`).

**Trạng thái:** Implementation hoàn tất. Architect review đã passed sau khi sửa các findings; Project Owner acceptance đang pending. Review pass không đồng nghĩa phase đã được owner nghiệm thu.

**Tiêu chí/bằng chứng triển khai:** Workload trả đúng kết quả cho các scenario; ghi ground truth fault/window; gắn `run_id` lên mọi event; nhãn độc lập với model; retry timeout bị giới hạn; signals liên kết bằng trace ID. Bằng chứng và trạng thái chi tiết nằm trong [`docs/PHASE_0_REPORT.md`](docs/PHASE_0_REPORT.md).

**Phụ thuộc:** Không.

### Phase 1 — OpenTelemetry instrumentation and collection

**Mục tiêu:** Thu thập ba loại tín hiệu và xác nhận chúng có thể liên kết với nhau.

**Thiết kế/công việc:**
- Instrument ba service bằng OpenTelemetry Python SDK 1.44.0; mỗi service có Resource riêng với `service.name`.
- Tạo server/client spans, propagate W3C Trace Context qua HTTP headers, gắn OTel log records với trace/span hiện hành.
- Phát request count/error counters và duration histogram; chỉ dùng các thuộc tính bounded (method, status, scenario), không dùng `run_id`/`trace_id` làm metric attributes.
- Collector config nhận OTLP/HTTP cho logs/metrics/traces, áp dụng memory limiter, resource (`deployment.environment.name=local`) và batch processors, xuất qua `debug` exporter.
- Với dependency pin 1.44.0, OTLP Logs exporter hiện được import từ module private `_log_exporter`; chưa thấy public import path được tài liệu Python chính thức hỗ trợ. Giữ pin và test import này khi nâng cấp vì Logs API/SDK còn đang phát triển.
- Collector chạy riêng qua Compose; host chỉ publish `127.0.0.1:4318`. Không thêm backend hoặc broker.
- Unit/integration tests dùng in-memory SDK exporters, không cần Collector chạy.

**Đầu ra:** `demo/telemetry.py`, instrumented workload, `requirements.txt`, Collector/Compose config và hướng dẫn kiểm tra; Phase 0 JSONL/manifest safety và ground-truth/run-ID contract được giữ nguyên.

**Nghiệm thu:** Mỗi scenario tạo OTel signals; resource service identity đúng cho từng service; trace parent/child đi qua W3C headers; logs gắn trace/span ID; request/error metrics và duration histogram tồn tại, không có ID cardinality cao. Collector smoke nhận cả ba signals nếu runtime khả dụng.

**Phụ thuộc:** Phase 0.

**Trạng thái:** Implementation complete sau khi test in-memory cho cả năm scenario và kiểm tra cấu hình/CLI hoàn tất. Collector receipt smoke được ghi riêng theo bằng chứng thực tế. Architect review đã passed sau khi ghi nhận private OTLP Logs exporter dependency và rủi ro tương thích; Project Owner acceptance đang pending.

### Phase 2 — Event transport and streaming data contract

**Mục tiêu:** Đưa telemetry vào broker qua các topic có hợp đồng ổn định.

**Thiết kế/công việc:**
- Quyết định riêng cho Phase 2: Apache Kafka 4.1.2, single-node KRaft local; không phê duyệt các đề xuất còn lại trong ADR-0001.
- Collector Contrib 0.143.0 xuất OTel logs/metrics/traces dạng OTLP Protobuf tới ba topic `aiops.otlp.{logs,metrics,traces}.v1`; giữ nguyên Phase 0 JSONL, không đưa JSONL vào đường OTel/Kafka.
- Topic có một partition, replication factor 1 và retention 7 ngày. Logs/traces key theo trace ID; metrics key theo resource attributes. Thay đổi phá vỡ wire contract dùng topic version mới.
- OTLP request sai định dạng bị Collector receiver từ chối trước khi Kafka; exporter retry có backoff tối đa năm phút, queue RAM tối đa 1.000 batches; hết thời gian retry hoặc đầy queue có thể làm mất dữ liệu. Retry có thể tạo duplicate; consumer cần idempotency.
- Đo khả năng ingest bằng workload mô tả được.

**Đầu ra:** Broker config, topic/schema contracts, producer path và smoke/integration tests.

**Nghiệm thu:** Telemetry vào đúng topic; payload hợp lệ được đọc lại; payload OTLP không hợp lệ bị receiver từ chối và không âm thầm đi vào topic.

**Phụ thuộc:** Phase 1.

**Trạng thái hiện tại:** Kafka/Collector config và hợp đồng topic đã được kiểm tra; baseline produce/read-back, malformed OTLP rejection và phép đo ingest local nhỏ đã chạy qua Docker. Implementation Phase 2 hoàn tất cho scoped slice; Architect review chưa passed và Project Owner acceptance đang pending. Phase 3 trở đi chưa bắt đầu.

### Phase 3 — Flink event-time processing and lakehouse

**Mục tiêu:** Chuẩn hóa và tổng hợp stream, đồng thời lưu lịch sử có thể replay.

**Thiết kế/công việc:**
- Xây Flink job parse/validate/enrich và tạo windowed aggregates.
- Định nghĩa event-time, watermark và chính sách late events.
- Thiết kế idempotency/deduplication, checkpoint, restart và replay.
- Lưu raw và curated datasets trên MinIO/S3 với Iceberg; mô tả partitioning và schema evolution.
- Đưa malformed events vào đường xử lý lỗi có thể kiểm tra (DLQ/quarantine).

**Đầu ra:** Flink job, Iceberg table layout, replay procedure, data-quality checks và test dữ liệu lỗi/trễ/trùng.

**Nghiệm thu:** Kết quả tổng hợp đúng trên fixture; late/duplicate/malformed events có hành vi được định nghĩa; restart/replay không tạo sai lệch ngoài chính sách đã công bố.

**Phụ thuộc:** Phase 2.

### Phase 4 — Signal backends and evidence retrieval

**Mục tiêu:** Cho phép truy vấn log, metric, trace và lịch sử đã chuẩn hóa.

**Thiết kế/công việc:**
- Cấu hình OpenSearch cho logs/events, Prometheus-compatible store cho metrics và Tempo cho traces.
- Thiết lập mapping/labels và liên kết giữa service, time range, trace ID.
- Tạo truy vấn hoặc API helper để lấy bằng chứng theo incident candidate.
- Cân nhắc cardinality, retention và dung lượng trong môi trường demo.

**Đầu ra:** Backend configs, provisioning, truy vấn mẫu và dashboard kiểm tra từng signal.

**Nghiệm thu:** Một request có thể được điều tra xuyên từ metric/log sang trace trong khoảng thời gian tương ứng; truy vấn lịch sử Iceberg có thể tái lập kết quả tổng hợp.

**Phụ thuộc:** Phase 1–3. Có thể phát triển backend song song về mặt kế hoạch, nhưng việc tích hợp được nghiệm thu sau khi các hợp đồng telemetry ổn định.

### Phase 5 — Feature pipeline and anomaly detection

**Mục tiêu:** Phát hiện bất thường đa tín hiệu và so sánh với baseline.

**Thiết kế/công việc:**
- Tạo features theo service/window: request rate, error rate, latency quantiles, error-template counts, failed spans, retries/timeouts.
- Xây baseline rule/statistical có thể giải thích.
- Huấn luyện/evaluate một mô hình unsupervised (ví dụ Isolation Forest) trên feature đã định nghĩa.
- Ghi cấu hình, dữ liệu, metrics đánh giá và version bằng MLflow.
- Chọn ngưỡng theo false-positive trade-off trên scenario có nhãn; tránh leakage từ nhãn vào feature.

**Đầu ra:** Feature contract, baseline, model pipeline, experiment record và report so sánh.

**Nghiệm thu:** Có precision/recall/F1, false-positive rate và time-to-alert cho từng scenario; kết quả baseline và model được so sánh cùng tập dữ liệu/quy trình.

**Phụ thuộc:** Phase 0, 3 và 4.

### Phase 6 — Event correlation, incident API, and service ranking

**Mục tiêu:** Gom anomalies liên quan thành incident có timeline và xếp hạng service phục vụ điều tra. Sau khi Incident API và evidence retrieval ổn định, có thể bổ sung tùy chọn một MCP adapter chỉ đọc để client MCP truy vấn incident, timeline và evidence.

**Thiết kế/công việc:**
- Định nghĩa cửa sổ gom incident và điều kiện mở/cập nhật/đóng incident.
- Xây dependency graph từ topology đã biết hoặc cấu hình khai báo.
- Tính service ranking bằng các yếu tố giải thích được: thời điểm bắt đầu, độ lớn, mức độ lan truyền và dependency relation.
- Lưu evidence references và lý do đóng góp vào rank.
- Tạo API/query contract cho incident timeline và evidence retrieval.
- **Tùy chọn, chưa triển khai:** adapter MCP chỉ đọc, đặt sau Incident API/evidence retrieval; chỉ expose tool truy vấn incident, timeline và evidence. Không expose mutation, điều khiển vận hành, hay hành động thay đổi hệ thống; kết quả correlation/ranking vẫn là gợi ý điều tra, không phải kết luận nhân quả.

**Đầu ra:** Correlation logic, incident schema/API, ranking explanation và timeline; tùy chọn MCP adapter read-only cho incident/timeline/evidence, không thuộc phạm vi hiện tại.

**Nghiệm thu:** Với lỗi được cài đặt, incident chứa thời gian và bằng chứng phù hợp; top-k ranking được báo cáo theo nhãn ground truth; không khẳng định nhân quả vượt quá dữ liệu. Nếu MCP adapter tùy chọn được triển khai sau này, nó chỉ trả về incident/timeline/evidence đã có và không cung cấp thao tác thay đổi; phase hiện tại không bao gồm adapter này.

**Phụ thuộc:** Phase 5 và backend evidence ở Phase 4.

### Phase 7 — Grafana, alerting, and optional grounded summary

**Mục tiêu:** Cung cấp trải nghiệm vận hành và điều tra xuyên suốt.

**Thiết kế/công việc:**
- Tạo dashboard service health, latency/error trends, pipeline health và incidents.
- Tạo alert có severity, deduplication/grouping và link đến incident/evidence.
- (Tùy chọn) Tạo LLM summary chỉ dựa trên evidence đã truy xuất; gắn nguồn cho từng nhận định, thể hiện phần chưa biết và kiểm thử hallucination.
- Giữ deterministic alerts hoạt động độc lập nếu LLM không khả dụng.

**Đầu ra:** Grafana dashboards/provisioning, alert rules và (nếu có) summary endpoint.

**Nghiệm thu:** Từ cảnh báo có thể mở incident, timeline và nguồn evidence; tắt LLM không làm hỏng detection/alerting.

**Phụ thuộc:** Phase 6.

### Phase 8 — Kubernetes deployment, CI/CD, reliability, and benchmark

**Mục tiêu:** Kiểm chứng khả năng dựng lại, triển khai và chịu lỗi trong phạm vi dự án.

**Thiết kế/công việc:**
- Đóng gói ứng dụng và cấu hình Kubernetes/Helm; quản lý config/secrets an toàn.
- Tạo CI cho lint, tests, schema/config validation và build images.
- Kiểm thử tải, restart, broker/processor interruption, late/duplicate events và storage/query behavior.
- Theo dõi độ trễ xử lý, consumer lag, checkpoint/recovery, tài nguyên và chất lượng cảnh báo.
- Ghi cách cài, giới hạn đã biết, benchmark environment và quy trình cleanup.

**Đầu ra:** Deployment manifests/charts, CI workflows, test/benchmark report, runbook và demo end-to-end.

**Nghiệm thu:** Có thể dựng lại theo tài liệu; test failure/recovery có kết quả; mọi số liệu được ghi kèm workload/hardware/config; không tuyên bố production readiness ngoài bằng chứng.

**Phụ thuộc:** Các phase trước; có thể xây CI sớm nhưng nghiệm thu toàn hệ thống ở đây.

## 5. Ma trận đánh giá tổng thể

| Khía cạnh | Thước đo / bằng chứng |
|---|---|
| Detection | Precision, recall, F1, false-positive rate, time-to-alert |
| Correlation | Incident grouping quality và service ranking top-k trên scenario có nhãn |
| Streaming | Throughput, end-to-end latency, late/duplicate handling, recovery behavior |
| Data quality | Tỷ lệ record hợp lệ, quarantine/DLQ counts, schema compatibility checks |
| Reliability | Restart/replay/checkpoint outcomes và consumer lag recovery |
| Resource use | CPU, memory, storage/query footprint trên workload công bố |
| Evidence usability | Khả năng truy ngược cảnh báo tới metric, log, trace cụ thể |

Không đặt trước số liệu thành tích. Xác định workload, môi trường, seed/scenario và quy trình đo; lưu kết quả để có thể chạy lại.

## 6. Quy trình tài liệu và review

- Trước phase: cập nhật `description.md` nếu scope, phụ thuộc, lựa chọn hoặc acceptance criteria đổi; ghi rõ quyết định và lý do.
- Sau mỗi phase: cập nhật README nếu trạng thái kiến trúc/khởi chạy thay đổi; bổ sung tài liệu vận hành, benchmark hoặc phase report phù hợp.
- Báo cáo phải phân biệt đã chạy, thất bại, bị chặn và chưa xác minh; không ghi kết quả dự kiến như kết quả đo được.
- Dừng sau khi hoàn tất phase được giao để Project Owner review; không tự động mở rộng sang phase kế tiếp.

## 7. Trạng thái hiện tại

| Phase | Trạng thái |
|---|---|
| Phase 0 — Foundation and failure workload | Implementation complete; Architect review passed after fixes; Project Owner acceptance pending |
| Phase 1 — Telemetry and collection | Implementation complete; Architect review passed after documenting private OTLP Logs exporter compatibility risk; Project Owner acceptance pending |
| Phase 2 — Event transport | Implementation complete; baseline Kafka smoke and local ingest measurement passed; Architect review and Project Owner acceptance pending |
| Phase 3 — Flink and lakehouse | Chưa bắt đầu |
| Phase 4 — Signal backends | Chưa bắt đầu |
| Phase 5 — Detection and MLOps | Chưa bắt đầu |
| Phase 6 — Correlation and incident API | Chưa bắt đầu |
| Phase 7 — Dashboard and summaries | Chưa bắt đầu |
| Phase 8 — Deployment and benchmark | Chưa bắt đầu |

Chỉ cập nhật trạng thái thành “đang làm”, “hoàn thành” hoặc “được duyệt” khi có căn cứ tương ứng; hoàn thành triển khai không đồng nghĩa với Project Owner đã duyệt phase.
