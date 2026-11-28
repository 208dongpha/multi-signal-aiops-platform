# Báo cáo triển khai và nghiệm thu Phase 2 — Event transport and streaming data contract

## 1. Phạm vi và kết quả

Phase 2 bổ sung đường truyền OpenTelemetry logs, metrics và traces từ Collector Contrib tới Kafka local. Phase 0 JSONL compatibility output và schema `demo/telemetry.schema.json` không đổi, không được gửi vào Kafka trong luồng này. Dữ liệu smoke hoàn toàn synthetic.

Đã triển khai và xác minh trên Docker Desktop:

- Kafka 4.1.2, single-node KRaft, Compose profile `streaming`, không lưu volume.
- Collector Contrib 0.143.0 với Kafka exporter và `debug` exporter.
- Ba topic: `aiops.otlp.logs.v1`, `aiops.otlp.metrics.v1`, `aiops.otlp.traces.v1`; OTLP Protobuf payload.
- Mỗi topic một partition, replication factor 1, retention `604800000` ms (7 ngày), tạo tường minh trước khi bật Collector.
- Logs/traces partition key theo trace ID; metrics key theo hash resource attributes.
- Malformed OTLP bị receiver từ chối; exporter retry/backpressure và duplicate policy được ghi rõ.
- Baseline produce/read-back chạy qua cả ba topic; thực hiện phép đo nhỏ năm lần baseline.

Đây là profile local đơn broker, không có HA, schema registry, DLQ, consumer, deduplication, Flink, hay production guarantee. Kết quả throughput dưới đây là phép đo smoke cục bộ, không phải benchmark. MCP adapter chỉ là extension tùy chọn read-only ở Phase 6 tương lai và không được triển khai trong Phase 2.

## 2. Quyết định thiết kế và nguồn chính thức

- **Quyết định có phạm vi:** Apache Kafka cho Phase 2; các proposal còn lại trong ADR-0001 vẫn pending. KRaft local chạy trên image JVM `apache/kafka:4.1.2`.
- **Collector:** `otel/opentelemetry-collector-contrib:0.143.0`; manifest release 0.143.0 xác nhận distribution này tồn tại, và Kafka exporter README/config được đọc từ tag v0.143.0. README ghi Kafka exporter là beta cho logs/metrics/traces, dùng synchronous producer, đề xuất batch/queued retry để tăng khả năng chịu lỗi.
- **Encoding/topics:** OTLP Protobuf, chủ động đặt signal-specific topic và encoding (không dùng config `topic`/`encoding` deprecated).
- **Queue/retry:** queue tối đa 1.000 batches trong memory; retry từ 5s, max interval 30s, tối đa 300s. Khi outage kéo dài hoặc queue đầy, dữ liệu có thể bị loại bỏ. Producer không bảo đảm exactly-once; retry có thể sinh duplicate, consumer cần idempotency.
- **Schema/versioning:** payload là OTLP Protobuf, không phải Phase 0 envelope và không có schema registry ở phase này. Topic suffix `.v1` đánh dấu hợp đồng ingest; thay đổi breaking cần topic version mới và consumer migration. OTel API/schema evolution theo dependency/version cần được quản lý cùng release của Collector.
- **Malformed payload:** request không parse được theo OTLP Protobuf bị OTLP receiver trả lỗi HTTP, không được gửi vào Kafka. Không có DLQ ở Phase 2.
- **Retention/partitions:** topic được tạo rõ với một partition, replication factor một và retention bảy ngày. Dùng một partition để giữ cấu hình local nhỏ; key strategy hiện không tăng song song hóa.
- **Network:** host ports Kafka `127.0.0.1:9092`, OTLP HTTP `127.0.0.1:4318`; Collector trong Compose dùng listener nội bộ `broker:19092`.
- **Test dependency:** `tests/test_streaming_contract.py` parse YAML bằng PyYAML, nên `PyYAML==6.0.3` được pin trực tiếp trong `requirements.txt` như test/config-validation dependency. Không thêm requirements file riêng vì đây là dependency trực tiếp duy nhất cho test và đã có sẵn môi trường test Python hiện tại.

Nguồn chính thức đã đối chiếu:

- Apache Kafka 4.1 Docker guide (image JVM, tag và port mặc định): <https://kafka.apache.org/41/getting-started/docker/>
- Apache Kafka 4.1 Quick Start (KRaft standalone, topic/produce/read flow và Docker image): <https://kafka.apache.org/41/getting-started/quickstart/>
- Apache Kafka Docker single-node plaintext Compose sample (KRaft environment variables/listeners, single-node replication settings): <https://github.com/apache/kafka/blob/trunk/docker/examples/docker-compose-files/single-node/plaintext/docker-compose.yml>
- Apache Kafka Docker example README (single-node examples, listeners và CLI): <https://github.com/apache/kafka/blob/trunk/docker/examples/README.md>
- OpenTelemetry Collector Contrib Kafka exporter tại tag 0.143.0: <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.143.0/exporter/kafkaexporter/README.md>
- Kafka exporter factory/config tại tag 0.143.0: <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.143.0/exporter/kafkaexporter/factory.go> và <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.143.0/exporter/kafkaexporter/config.go>
- Collector Contrib 0.143.0 distribution manifest: <https://github.com/open-telemetry/opentelemetry-collector-releases/blob/v0.143.0/distributions/otelcol-contrib/manifest.yaml>

## 3. Files tạo/sửa

- Tạo `collector/otel-collector-kafka.yaml` — Collector Kafka exporter, topic/encoding/key, retry/queue và các pipelines.
- Tạo `collector/streaming.compose.yaml` — Kafka KRaft và Collector Contrib trong opt-in profile; chỉ publish host ports trên loopback.
- Tạo `tests/test_streaming_contract.py` — kiểm tra cấu hình topic, encoding, key, profile và listener.
- Sửa `requirements.txt` — pin `PyYAML==6.0.3` làm direct test/config-validation dependency cho test đọc YAML; không thêm requirements file riêng.
- Sửa `README.md` — profile Phase 2, hướng dẫn tạo topics và produce/read-back smoke, lệnh PowerShell tái lập malformed OTLP rejection, MCP future-only, giới hạn, trạng thái.
- Sửa `description.md` — thiết kế/trạng thái Phase 2 và optional read-only MCP adapter ở Phase 6.
- Sửa `docs/decisions/0001-proposed-target-stack.md` — chỉ lựa chọn Kafka Phase 2 là scoped decision; phân biệt phần đã implement với proposal chưa implement; MCP future-only.
- Sửa `docs/PHASE_1_REPORT.md` — câu “Phase 2 chưa bắt đầu” đổi thành mốc lịch sử tại thời điểm Phase 1 hoàn tất, trỏ sang báo cáo Phase 2 hiện tại.
- Tạo `docs/PHASE_2_REPORT.md` — báo cáo này.
- Không sửa workload Phase 0/1, schema JSONL, SDK dependency pins hoặc cấu hình Collector Phase 1.

## 4. Tiêu chí nghiệm thu và bằng chứng

| Tiêu chí | Bằng chứng | Trạng thái |
|---|---|---|
| Phase 0 JSONL/schema và Phase 1 instrumentation không bị thay đổi | Diff/file inspection; Phase 0/1 tests pass | PASS |
| Kafka chạy opt-in, KRaft, loopback-only, Collector Contrib có Kafka exporter | `docker compose --profile streaming -f collector/streaming.compose.yaml config`; Kafka và Collector containers đều `Up`; Collector log báo `Everything is ready` | PASS |
| Logs/metrics/traces vào đúng topic với payload hợp đồng | Chạy `python -m demo.workload --scenario baseline` (HTTP 200, 9 synthetic compatibility events); đọc lại ít nhất một OTLP Protobuf Kafka record từ cả ba topic | PASS |
| Topic partition, replication và retention tường minh | `kafka-topics.sh --describe` cho topic logs: partition count 1, replication factor 1, `retention.ms=604800000`; ba topic được tạo với cùng flags | PASS |
| Payload OTLP malformed được báo lỗi, không âm thầm chấp nhận | Gửi byte `0xff` tới `/v1/logs`, nhận HTTP 400 | PASS |
| Retry, queue, backpressure, duplicate và schema-version policy được xác định | Explicit exporter config và tài liệu Phase 2 | PASS — cấu hình/chính sách; không có outage/retry stress test |
| Ingest đo bằng workload được mô tả | 5 lần `baseline`, tổng 43.165 s; log-end-offset tăng 15 log, 208 metric, 15 trace records (238 record tổng), 5.514 Kafka records/s | PASS — smoke measurement, không phải benchmark |
| Kiểm thử unit regression chạy không cần Kafka | `python -m unittest discover -s tests -v` — 13 tests passed | PASS |
| Test/config validation dependency tái lập được từ requirements | `PyYAML==6.0.3` trong `requirements.txt`; `python -m pip show PyYAML` báo Version 6.0.3 | PASS |
| Đánh giá Architect độc lập và Project Owner acceptance | Chưa có review độc lập được xác nhận; owner chưa quyết định nghiệm thu | NOT VERIFIED / PENDING |

## 5. Lệnh kiểm tra và kết quả

Môi trường ghi nhận: Windows, Python 3.14.5, Docker Desktop server 29.8.2, Kafka image 4.1.2, Collector Contrib image 0.143.0.

| Lệnh/thao tác | Kết quả |
|---|---|
| `python -m unittest tests.test_streaming_contract -v` trước implementation | RED — 3 lỗi `FileNotFoundError` do hai config files chưa được tạo |
| `python -m unittest tests.test_streaming_contract -v` sau implementation | PASS — 3 tests |
| `python -m unittest discover -s tests -v` | PASS — 13 tests |
| `python -m pip show PyYAML` | PASS — Version `6.0.3`, khớp pin `requirements.txt` |
| `python -m compileall -q demo tests` | PASS |
| `docker compose --profile streaming -f collector/streaming.compose.yaml config` | PASS — Compose config parse; listener/ports/profiles đúng |
| YAML parse/contract assertion bằng PyYAML | PASS — YAML hợp lệ và collector broker endpoint khớp Compose |
| `docker info --format 'server={{.ServerVersion}} os={{.OperatingSystem}}'` | PASS — Docker Desktop server 29.8.2 |
| `docker compose --profile streaming -f collector/streaming.compose.yaml up -d kafka` | PASS — pull image và khởi chạy Kafka |
| `docker ... kafka-topics.sh --create ...` cho ba topic | PASS — topics được tạo; Kafka CLI phát warning về dấu `.` trong tên topic, nhưng không có underscore trong tên nên không có trùng lẫn hai dấu phân cách |
| `docker compose --profile streaming -f collector/streaming.compose.yaml up -d otel-collector` và `logs --no-color otel-collector` | PASS — image Contrib 0.143.0 khởi động, log xác nhận ready, không có config/exporter startup error |
| `python -m demo.workload --scenario baseline` | PASS — HTTP 200 |
| `kafka-console-consumer.sh` với `--max-messages 1` trên ba topic | PASS — cả logs, metrics, traces đều đọc được record; output là binary Protobuf |
| POST malformed byte `0xff` tới `http://127.0.0.1:4318/v1/logs` với content type `application/x-protobuf` | PASS — HTTP 400 |
| Đo 5 baseline runs và Kafka log-end-offset delta | PASS — 238 records / 43.165 s = 5.514 records/s |
| `docker compose ... stop` | Đã dùng sau smoke; không xóa containers, images hay volumes |
| `git status --short --branch` | BLOCKED — workspace không phải Git repository |

### Lệnh PowerShell tái lập malformed OTLP rejection

Collector phải đang chạy trong profile `streaming`. Chạy nguyên block sau từ thư mục repository; block gửi byte thô `0xff` (không phải JSON, không được encode lại) tới OTLP HTTP receiver và yêu cầu đúng HTTP 400:

```powershell
@'
import urllib.error
import urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:4318/v1/logs",
    data=b"\xff",
    headers={"Content-Type": "application/x-protobuf"},
    method="POST",
)
try:
    urllib.request.urlopen(request)
except urllib.error.HTTPError as error:
    print(f"HTTP {error.code}: malformed OTLP request rejected")
    assert error.code == 400
else:
    raise AssertionError("malformed OTLP request unexpectedly accepted")
'@ | python -
```

Kết quả đã chạy trong phiên này: `HTTP 400: malformed OTLP request rejected`. Lệnh này chỉ cần khi smoke profile `streaming`; unit suite bình thường không cần Docker.

### Xác minh sau correction pass

Sau khi sửa tài liệu/ADR và bổ sung lệnh tái lập, các kiểm tra sau đã chạy lại:

| Lệnh | Kết quả |
|---|---|
| `python -m unittest discover -s tests -v` | PASS — 13 tests, 11.209 s |
| `python -m compileall -q demo tests` | PASS — exit 0, không output |
| `docker compose --profile streaming -f collector/streaming.compose.yaml config` | PASS — Compose config parse thành công |
| PyYAML parse bốn file `collector/*.yaml` | PASS — tất cả parse thành công |
| `python -m pip show PyYAML` | PASS — Version `6.0.3`, khớp pin trong `requirements.txt` |

Không thay đổi Kafka implementation, collector config hay test hành vi trong correction pass; không bật lại container, không xóa container/image/volume.

Phép đo ingest dùng đúng năm lần CLI baseline nối tiếp, không tải song song; delta offset được đọc qua Kafka `kafka-get-offsets.sh`. Đây là kết quả quan sát trong một môi trường local cụ thể, gồm startup/flush overhead và periodic metric exports; không suy rộng thành capacity hoặc production benchmark.

## 6. Giới hạn và hạng mục chưa kiểm tra

- Không có Kafka consumer application, DLQ, deduplication, exactly-once, Flink, schema registry, TLS/authentication hoặc persistence volume trong scope.
- Broker đơn, replication factor một, một partition/topic; không có HA.
- Đường malformed kiểm tra request không hợp lệ bị reject; chưa stress-test malformed OTLP variants.
- Retry outage, queue saturation, producer restart, data loss window và duplicate delivery chưa được fault-injection test.
- Một workload năm lần không đánh giá p95 latency, saturation, sustained throughput, backpressure under load hay khả năng mở rộng.
- Test unit/config chạy độc lập không cần Kafka; runtime smoke cần Docker Desktop và được chạy trong phiên này.
- Không thay đổi hoặc migrate Phase 0 JSONL schema. Kafka chứa OTel signals từ SDK/Collector chứ không chứa compatibility JSONL.
- Không có MCP adapter, FastAPI incident API hoặc evidence retrieval trong Phase 2. MCP chỉ là extension tùy chọn read-only cho incident/timeline/evidence ở Phase 6 tương lai; không thuộc implementation hiện tại.
- Không có benchmark kết luận, production readiness claim hoặc causal/root-cause claim.

## 7. Trạng thái implementation, review và owner acceptance

| Trạng thái | Kết luận |
|---|---|
| Implementation | **Complete for the Phase 2 scoped broker/exporter/data-contract slice** — config, tests, runtime baseline produce/read-back, malformed request rejection và phép đo smoke đã qua. Các giới hạn nêu trên còn nguyên. |
| Architect review | **Not passed** — chưa có review độc lập hoàn tất cho diff này; các finding nếu có chưa được đóng. |
| Project Owner acceptance | **Pending** — chưa có quyết định nghiệm thu Phase 2. |

Không có phase sau nào được bắt đầu; ADR-0001 ngoài quyết định Kafka Phase 2 vẫn pending.
