# Báo cáo triển khai và nghiệm thu Phase 1 — OpenTelemetry instrumentation and collection

## 1. Phạm vi và kết quả

Phase 1 được triển khai trên workload `gateway → orders → inventory`: OpenTelemetry Python SDK phát logs, metrics và traces; W3C Trace Context được inject/extract qua HTTP; Collector local nhận OTLP/HTTP và chỉ xuất qua debug exporter. Không triển khai Kafka/Redpanda, Flink, signal backend, anomaly model hay dashboard (Phase 2 trở đi).

Năm scenario Phase 0, ground truth/run ID, JSONL compatibility events, manifest và quy tắc từ chối ghi đè/`--force` vẫn được giữ. Event JSONL hiện vẫn là compatibility envelope Phase 0; OTel signals là telemetry thực được Collector nhận riêng.

## 2. Quyết định thiết kế và phiên bản

- Python 3.14.5 là runtime đã kiểm thử; các package OTel yêu cầu Python `>=3.10`.
- Pin trực tiếp `opentelemetry-api`, `opentelemetry-sdk` và `opentelemetry-exporter-otlp-proto-http` ở `1.44.0`. `opentelemetry-semantic-conventions==0.65b0` được SDK kéo theo.
- **Private API compatibility risk:** tại đúng bản `opentelemetry-exporter-otlp-proto-http==1.44.0`, distribution chỉ có module `opentelemetry/exporter/otlp/proto/http/_log_exporter/__init__.py` cho `OTLPLogExporter`; class có `__module__` là `opentelemetry.exporter.otlp.proto.http._log_exporter`. Package cha `opentelemetry.exporter.otlp.proto.http` không export tên log-related nào khác ngoài `_log_exporter`. Tài liệu Python exporter chính thức hướng dẫn OTLP HTTP trace và metric imports nhưng không tài liệu hóa public OTLP Logs exporter import; instrumentation docs nói Logs API/SDK còn đang phát triển. Vì không tìm thấy public exporter surface được tài liệu hỗ trợ, code giữ import private để tiếp tục gửi logs OTLP. Pin 1.44.0 và test import tập trung bảo vệ cấu hình hiện tại, **không** biến API private thành ổn định: upgrade có thể đổi/xóa module hoặc hành vi và phải xác minh lại import, test logs, rồi chạy Collector smoke.
- Dùng SDK provider riêng cho mỗi service để mỗi signal có Resource `service.name` đúng; không dùng global providers trong workload một-process.
- Dùng SDK Tracer/Meter/Logger API trực tiếp. Python Logs API/SDK hiện vẫn được tài liệu chính thức mô tả là đang phát triển; do đó phụ thuộc được pin để giới hạn biến động API. `LoggerProvider` và `Logger.emit` là phần có rủi ro ổn định cao hơn traces/metrics; thay đổi phiên bản phải chạy lại test.
- Traces gồm client và server spans; W3C `traceparent` được propagate qua HTTP. `X-Run-ID` và header parent-span tương thích nội bộ chỉ duy trì liên kết event envelope Phase 0, không tham gia metric attributes.
- Metrics gồm `http.server.request.count`, `http.server.request.errors` và histogram `http.server.request.duration` (seconds). Thuộc tính được giới hạn ở method, status code và một trong năm scenario; `run_id`/`trace_id` không được ghi làm dimensions.
- Collector dùng OTLP/HTTP 4318, `memory_limiter`, `resource`, `batch`, và `debug` exporter cho cả ba pipeline. Collector 0.143.0 được pin; Compose chỉ publish `127.0.0.1:4318`, không publish gRPC hay cổng quản trị.
- Unit/integration test tạo provider với in-memory exporters; không cần Collector chạy. CLI mặc định dùng OTLP exporter để gửi đến Collector local.

## 3. Files tạo/sửa

- `requirements.txt` — direct dependency versions cố định.
- `demo/telemetry.py` — per-service providers, OTLP/in-memory exporters, counters, histogram và logs.
- `demo/workload.py` — instrument HTTP client/server, W3C context propagation, log/metric/span capture và lifecycle flush.
- `tests/test_workload.py` — assertions OTel cho năm scenario, resources, parent-child context, log correlation, error status, metric names/cardinality; giữ các test Phase 0; thêm focused guard xác nhận exporter version `1.44.0` cùng private module path đang dùng.
- `collector/otel-collector.yaml` — OTLP receiver và ba debug pipelines.
- `collector/compose.yaml` — tùy chọn chạy Collector riêng, loopback-only host port.
- `README.md` — setup/run Collector, trạng thái phase và giới hạn.
- `description.md` — thiết kế, nghiệm thu và trạng thái Phase 1.
- `docs/PHASE_0_REPORT.md` — làm rõ Phase 1 chưa bắt đầu tại thời điểm hoàn tất Phase 0, tránh nhầm với trạng thái hiện tại.
- `docs/PHASE_1_REPORT.md` — báo cáo này.

## 4. Tiêu chí nghiệm thu và bằng chứng

| Tiêu chí | Bằng chứng | Trạng thái |
|---|---|---|
| Năm scenario cũ vẫn chạy; ground truth, run ID, JSONL contract và output collision safety được giữ | `python -m unittest discover -s tests -v` — bộ test Phase 0 và Phase 1 cùng chạy | PASS |
| Mỗi service phát logs, metrics, traces với Resource `service.name` đúng | In-memory assertions trên từng service trong cả năm scenario; Collector debug output cho `gateway`, `orders`, `inventory` | PASS |
| W3C trace context liên kết client/server spans qua HTTP | In-memory test kiểm tra một trace ID và quan hệ client/server parent IDs xuyên đủ ba service | PASS |
| OTel logs có trace ID/span ID khớp server span và timestamp có giá trị | In-memory tests đối chiếu log record với server span; native Collector smoke xác nhận log timestamp không phải epoch-zero | PASS |
| Import OTLP Logs exporter đúng package pin và đường dẫn hiện được dùng | `python -c "from importlib.metadata import version; from opentelemetry.exporter.otlp.proto.http import _log_exporter; assert version('opentelemetry-exporter-otlp-proto-http') == '1.44.0'; assert _log_exporter.OTLPLogExporter.__module__ == 'opentelemetry.exporter.otlp.proto.http._log_exporter'"` — PASS; tài liệu exporter chính thức không chỉ định public Logs import | PASS — private compatibility risk documented; no supported public importer identified |
| Có request/error counters và duration histogram; không có `run_id`/`trace_id` metric dimensions | In-memory metric reader kiểm tra các metric và attributes của từng scenario/service; Collector nhận `ResourceMetrics` | PASS |
| Collector config và Compose chỉ xuất debug; host receiver bind loopback | `otelcol.exe validate`; PyYAML parse/contract check; config `ports: [127.0.0.1:4318:4318]` | PASS |
| Collector thực nhận đủ logs, metrics, traces | OpenTelemetry Collector Windows binary 0.143.0 chạy local; debug output có ResourceSpans, ResourceMetrics, ResourceLogs và đủ ba service resources | PASS |
| Docker Compose smoke | `docker pull otel/opentelemetry-collector:0.143.0` không kết nối được Docker Engine named pipe | BLOCKED — Docker CLI có nhưng Docker Desktop Linux Engine chưa chạy |

## 5. Lệnh xác minh và kết quả

Môi trường: Windows, Python 3.14.5. Phiên bản OTel direct dependencies: 1.44.0; Collector binary kiểm tra: 0.143.0.

| Lệnh/thao tác | Kết quả |
|---|---|
| `python -m pip install -r requirements.txt` | PASS — API/SDK 1.44.0 đã có; OTLP HTTP exporter 1.44.0 cài thành công. |
| `python -m unittest discover -s tests -v` | PASS — 10 tests passed; gồm 5 scenario với in-memory SDK providers, Phase 0 output safety và focused private-import guard. |
| `python -m unittest tests.test_workload.WorkloadTests.test_pinned_otlp_logs_exporter_private_import_is_available -v` | PASS — focused guard xác nhận distribution đang cài là 1.44.0 và class được cung cấp qua private `_log_exporter` module. |
| `python -m compileall -q demo tests` | PASS — exit code 0. |
| PowerShell here-string kiểm tra cấu trúc YAML bằng `yaml.safe_load` (script bên dưới) | PASS — cả Collector/Compose YAML parse; ba pipelines, processor/exporter references và loopback binding đúng. |
| `& 'C:\Users\Admin\AppData\Local\Temp\opencode\phase1-collector\otelcol.exe' validate --config='collector/otel-collector.yaml'` | PASS — Collector 0.143.0 chấp nhận config. Binary tải từ release chính thức, chỉ dùng trong thư mục temp. |
| Native Collector smoke: `$collector = Start-Process -FilePath (Join-Path $temp 'otelcol.exe') -ArgumentList @('--config=collector/otel-collector.yaml') -WorkingDirectory 'D:\Dongphh\faud_detec' -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru`; readiness check tới `127.0.0.1:4318`; `python -m demo.workload --scenario baseline`; dừng process và kiểm tra log files | PASS — baseline HTTP 200; Collector debug output ghi traces (6 spans), logs (3 records) và metrics (36 datapoints trong chu kỳ export quan sát được); output có service resources đủ `gateway`, `orders`, `inventory`, cùng `deployment.environment.name=local`. Log timestamps được kiểm tra không phải epoch-zero. |
| `docker --version` | PASS — Docker CLI 29.8.2 có mặt; không chứng minh daemon hoạt động. |
| `docker pull otel/opentelemetry-collector:0.143.0` | BLOCKED — `failed to connect to the docker API ... dockerDesktopLinuxEngine ... The system cannot find the file specified`; vì vậy Compose runtime smoke chưa chạy. |
| Lint | SKIPPED — repository không có cấu hình/lệnh linter được thiết lập; syntax compile và Collector/YAML validation đã chạy. |
| `git status --short --branch` | BLOCKED — workspace không phải Git repository. Không commit/push. |

Script YAML validation đã chạy:

```powershell
@'
import yaml
from pathlib import Path
collector = yaml.safe_load(Path('collector/otel-collector.yaml').read_text(encoding='utf-8'))
compose = yaml.safe_load(Path('collector/compose.yaml').read_text(encoding='utf-8'))
assert collector['receivers']['otlp']['protocols']['http']['endpoint'] == '0.0.0.0:4318'
assert set(collector['service']['pipelines']) == {'traces', 'metrics', 'logs'}
for pipeline in collector['service']['pipelines'].values():
    assert pipeline['receivers'] == ['otlp']
    assert pipeline['processors'] == ['memory_limiter', 'resource', 'batch']
    assert pipeline['exporters'] == ['debug']
assert compose['services']['otel-collector']['image'] == 'otel/opentelemetry-collector:0.143.0'
assert compose['services']['otel-collector']['ports'] == ['127.0.0.1:4318:4318']
print('PASS: collector and Compose YAML parse; signal pipelines and loopback port contract verified')
'@ | python -
```

## 6. Khó khăn, giới hạn và chưa kiểm tra

- HTTP header names được chuẩn hóa theo title case trên server; W3C extraction yêu cầu carrier lookup lowercase. Handler hiện lowercase keys khi extract; test xác nhận trace xuyên đủ ba service.
- Smoke ban đầu phát hiện log timestamps là epoch-zero khi không truyền timestamp cho `Logger.emit`; implementation hiện gán timestamp nanoseconds và smoke sau sửa xác nhận timestamp thực.
- Docker CLI khả dụng nhưng daemon không chạy. Thay vào đó đã validate và chạy chính thức Collector binary 0.143.0 trên Windows; Compose file chưa được thực thi bởi Docker Compose.
- Collector nhận OTel signals thật trong baseline smoke; failure scenarios đã chạy với in-memory exporters, chưa chạy tất cả scenario qua Collector thực tế.
- `debug` exporter chỉ in và không lưu dữ liệu; không có backend, persistence, retention hoặc truy vấn lịch sử.
- Workload vẫn dùng ba HTTP server cùng một process; chưa kiểm tra container/process isolation, network failure thực, TLS hoặc triển khai production.
- Chỉ Python 3.14.5 được chạy; Python 3.10+ được package metadata xác nhận, nhưng chưa chạy test trên mọi phiên bản Python được hỗ trợ.
- Chưa chạy performance/load test, CI, Docker Compose smoke, Kubernetes, broker, Flink hoặc backend tests; các phần sau Phase 1 nằm ngoài phạm vi.
- Logs API/SDK OpenTelemetry Python còn đang phát triển theo tài liệu chính thức; API này có thể đổi ở các release sau.
- Không xác định được public OTLP Logs exporter import path được tài liệu chính thức hỗ trợ ở package pin. Việc giữ private import là compatibility risk đã biết; focused test chỉ phát hiện lệch phiên bản/path cơ bản, không cam kết tương thích sau nâng cấp.

## 7. Trạng thái implementation, review và owner acceptance

| Trạng thái | Kết luận |
|---|---|
| Implementation | **Complete** — instrumentation, Collector config, dependency pins, test seams và tài liệu đã triển khai; unit/in-memory verification và native Collector validation/receipt smoke đã qua. Docker Compose smoke còn blocked như ghi trên. |
| Architect review | **Passed after fixes** — finding về import private của OTLP Logs exporter đã được điều tra trên đúng package pin, không tìm thấy public import được tài liệu hỗ trợ, và rủi ro tương thích cùng yêu cầu kiểm tra khi upgrade đã được ghi rõ trong code-test/docs. Review xác nhận nội dung sửa và các kiểm tra trong phạm vi; Docker Compose runtime vẫn blocked như đã nêu. |
| Project Owner acceptance | **Pending** — chưa có quyết định nghiệm thu Phase 1. |

Tại thời điểm Phase 1 hoàn tất, Phase 2 chưa bắt đầu. Trạng thái hiện tại của Phase 2 được ghi trong [`docs/PHASE_2_REPORT.md`](PHASE_2_REPORT.md); hoàn thành implementation và test không đồng nghĩa review/owner acceptance.

## 8. Tài liệu tham khảo chính thức

- OpenTelemetry Python instrumentation, traces/metrics/logs APIs và caveat Logs đang phát triển: <https://opentelemetry.io/docs/languages/python/instrumentation/>
- OpenTelemetry Python exporters, OTLP/HTTP và Collector exporter setup: <https://opentelemetry.io/docs/languages/python/exporters/>
- OpenTelemetry OTLP HTTP exporter distribution (exact pinned package): <https://pypi.org/project/opentelemetry-exporter-otlp-proto-http/1.44.0/>
- OpenTelemetry Collector configuration, pipelines/processors/exporters và validation command: <https://opentelemetry.io/docs/collector/configuration/>
- OpenTelemetry Collector release 0.143.0: <https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.143.0>
- Python logging instrumentation reference (SDK `LoggingHandler` deprecation context): <https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/logging/logging.html>

## 9. Follow-up: private OTLP Logs exporter import review finding

Đã điều tra đúng package cài `opentelemetry-exporter-otlp-proto-http==1.44.0`: distribution chứa file `_log_exporter/__init__.py`; `OTLPLogExporter.__module__` trỏ tới `opentelemetry.exporter.otlp.proto.http._log_exporter`; package cha không expose một public log-exporter name. Python exporter guide có ví dụ public import cho OTLP trace và metrics, nhưng không cung cấp import path cho OTLP logs; instrumentation guide ghi Logs API/SDK còn đang phát triển. Không có public supported import path nào được tìm thấy trong package pin và các tài liệu chính thức đã đối chiếu.

Do đó code giữ import hiện tại và pin 1.44.0. README, phase design và báo cáo này nay nêu rõ đây là private API dependency; upgrade có thể đổi hoặc xóa module/hành vi. Focused guard kiểm tra phiên bản và module path; guard không đảm bảo tương thích tương lai, nên upgrade vẫn cần đánh giá API, chạy test logs và Collector smoke.

Xác minh follow-up:

- `python -m unittest tests.test_workload.WorkloadTests.test_pinned_otlp_logs_exporter_private_import_is_available -v` — PASS, 1 test.
- `python -m unittest discover -s tests -v` — PASS, 10 tests.
- `python -m compileall -q demo tests` — PASS.
- Không đổi dependency, exporter implementation, Collector config hay phase scope trong finding này. Architect review đã passed sau khi ghi nhận rủi ro private API; Project Owner acceptance vẫn pending.
