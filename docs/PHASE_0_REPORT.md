# Báo cáo triển khai và nghiệm thu Phase 0

## 1. Phạm vi và kết quả

Đã hoàn tất Phase 0 theo phạm vi được ủy quyền: workload microservices local có scenario lỗi tái lập, nhãn ground truth, hợp đồng event ban đầu, cấu hình chạy, test và tài liệu. Chỉ dùng Python standard library; không triển khai Phase 1 hoặc OpenTelemetry SDK/Collector, Kafka/Redpanda, Flink, backend lưu trữ hay dashboard.

### Tính năng đã giao

- Ba HTTP service `gateway → orders → inventory`, mỗi service trên cổng localhost động; service chạy trong thread của một tiến trình.
- Năm scenario: `baseline`, `latency`, `http_5xx`, `timeout_retry`, `dependency_failure`. Orders retry tối đa một lần sau lần đầu (tối đa hai lần gọi inventory).
- Mỗi service request tạo log, metric duration và trace span synthetic. Các event có `event_id` riêng, `run_id` chung cho run và `trace_id` chung cho request; span cha/con được nối.
- Kết quả run chứa `ground_truth`: `scenario_id`, `injected_service`, `fault_type`, `expected_outcome`, `scenario_start_utc`, `scenario_end_utc`. Baseline dùng null cho service inject và fault type.
- Cửa sổ scenario bắt đầu ngay trước request gateway và kết thúc sau khi nhận response cùng thời gian telemetry flush cấu hình; timestamps là UTC ISO 8601.
- `--events PATH` ghi JSONL và `PATH.run.json` manifest có cùng `run_id`/ground truth. Mặc định từ chối ghi nếu một trong hai output path tồn tại; `--force` là opt-in thay thế cả hai output.

## 2. Quyết định thiết kế

- Không thêm dependency để demo chạy được trên Python 3.10+.
- Dùng HTTP thực giữa ba endpoint nhưng giữ tất cả trong một process để local setup nhẹ. Đây chưa phải mô hình triển khai process/container độc lập.
- Cổng được cấp động; timeout và delay đặt trong `demo/config.json`.
- Dependency failure mô phỏng bằng HTTP 503 có kiểm soát, không dừng process inventory. `http_5xx` riêng biệt trả lỗi inventory 500; timeout scenario tạo timeout ở orders và retry có giới hạn.
- Event schema `1.0` là hợp đồng synthetic ban đầu, không tuyên bố là OpenTelemetry canonical data model.
- Output mặc định dùng tạo file độc quyền để ngăn race-time clobber; `--force` ghi payload vào file tạm trước khi replace từng output.

## 3. Files đã tạo/thay đổi trong Phase 0

- `demo/__init__.py` — package entry point.
- `demo/workload.py` — service, scenario, ground truth, event generation, CLI và output handling.
- `demo/config.json` — cấu hình địa chỉ/timeout/delay local.
- `demo/telemetry.schema.json` — JSON Schema Draft 2020-12 cho event.
- `tests/test_workload.py` — test scenario, ground truth, event/schema contract, retry và collision/force behavior.
- `README.md` — hướng dẫn chạy, output safety và trạng thái.
- `description.md` — kế hoạch và trạng thái phase.
- `docs/PHASE_0_REPORT.md` — báo cáo implementation/acceptance.
- `AGENTS.md` — yêu cầu acceptance report đầy đủ, factual và owner-facing.

## 4. Acceptance criteria và bằng chứng

Các trạng thái dưới đây đánh giá bằng chứng triển khai; không thay thế quyết định nghiệm thu của Project Owner.

| Tiêu chí | Bằng chứng | Trạng thái |
|---|---|---|
| Workload 3 service và scenario có nhãn trả kết quả kỳ vọng | `python -m unittest discover -s tests -v`; test chạy toàn bộ 5 scenario và kiểm tra HTTP status/outcome | PASS |
| Ground truth gồm service/fault/outcome và UTC start/end có semantics rõ | Test scenario kiểm tra các field, null baseline, timezone-aware timestamps và mọi event nằm trong run window | PASS |
| Event gắn được vào run và có event IDs riêng | Test xác nhận mỗi event `run_id` bằng result, event IDs không trùng trong run; CLI JSONL + manifest nối được bằng `run_id` | PASS |
| Event conform với schema ban đầu | Draft 2020-12 schema validation cho events của cả 5 scenario | PASS |
| Timeout/retry hữu hạn | Test xác nhận 2 inventory spans và kết quả 504 cho `timeout_retry` | PASS |
| Output không ghi đè file có sẵn nếu thiếu opt-in | Hai test sentinel trong temporary directory cho event path và manifest path; CLI collision smoke xác nhận không đổi sentinel/không tạo output còn thiếu | PASS |
| Ghi đè chỉ khi explicit opt-in | Unit test và CLI smoke với `--force` xác nhận cả hai output được ghi lại | PASS |

## 5. Lệnh xác minh và kết quả thực tế

Môi trường: Python 3.14.5 trên Windows.

| Lệnh | Kết quả |
|---|---|
| `python -m unittest discover -s tests -v` | PASS — 7 tests passed. |
| `python -m unittest tests.test_workload.WorkloadTests.test_existing_events_file_blocks_both_outputs_without_force tests.test_workload.WorkloadTests.test_existing_manifest_blocks_both_outputs_without_force tests.test_workload.WorkloadTests.test_force_explicitly_replaces_both_output_files -v` | PASS — 3 focused output-safety tests passed. |
| `python -m compileall -q demo tests` | PASS — exit code 0, không có lỗi cú pháp. |
| `python -m demo.workload --scenario timeout_retry --events C:\Users\Admin\AppData\Local\Temp\opencode\phase0-groundtruth-timeout.jsonl` | PASS — HTTP 504; CLI in ground truth; 12 JSONL events và `.run.json` manifest được ghi, đọc lại và join qua `run_id`. |
| CLI collision smoke dùng subprocess với argv `['python', '-m', 'demo.workload', '--scenario', 'baseline', '--events', '<temp>\run.jsonl']`, sau đó gọi lại với thêm `--force` | PASS — test Python subprocess/tempdir đặt sentinel riêng ở từng output path; mặc định CLI thoát lỗi, sentinel giữ nguyên và output còn lại không xuất hiện; force ghi cả hai output, join qua `run_id`. |
| PowerShell here-string piped to `python -` chạy script schema bên dưới | PASS — schema hợp lệ; event cả 5 scenario validate. `jsonschema` là package sẵn có trong môi trường, không được thêm vào repo. |
| `git status --short --branch` | BLOCKED — thư mục làm việc không phải Git repository. Không commit/push. |

Schema validation script đã chạy:

```powershell
@'
import json
import jsonschema
from demo.workload import SCENARIOS, run_scenario
schema = json.load(open('demo/telemetry.schema.json', encoding='utf-8'))
jsonschema.Draft202012Validator.check_schema(schema)
validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
for scenario_id in SCENARIOS:
    for event in run_scenario(scenario_id)['events']:
        validator.validate(event)
print('PASS: schema and all five scenario event sets')
'@ | python -
```

## 6. Khó khăn, giới hạn và chưa kiểm tra

- Trong quá trình phát triển, timeout client ban đầu quá ngắn khiến latency scenario bị timeout; cấu hình sau cùng tách gateway deadline khỏi timeout orders→inventory. Bộ test hiện tại qua trên môi trường nêu trên.
- Các service chạy cùng process; chưa kiểm tra process crash, network partition thật, container hoặc deployment độc lập.
- Dependency failure là phản hồi 503 mô phỏng, không phải inventory process bị dừng.
- Timing chỉ phục vụ scenario local; chưa benchmark và không đảm bảo trên phần cứng/môi trường khác.
- Force mode stage nội dung trước, sau đó replace từng file riêng; cặp hai file không phải một giao dịch atomic trước sự cố process/hệ điều hành giữa hai lần replace.
- Chưa kiểm tra Python 3.10/phiên bản khác, CI, Docker/Compose, Kubernetes, OpenTelemetry backend, load/recovery, persistence hay observability integrations.
- Không thể dùng Git để kiểm tra diff/status vì workspace hiện không có `.git` metadata.

## 7. Trạng thái implementation, review và owner acceptance

| Trạng thái | Kết luận |
|---|---|
| Implementation | **Complete** — Phase 0 artifacts và kiểm tra nêu trên đã hoàn tất. |
| Architect review | **Passed after fixes** — các findings về ground truth/run IDs và output overwrite đã được xử lý; Architect xác nhận review passed sau fixes. |
| Project Owner acceptance | **Pending** — chưa có quyết định nghiệm thu từ Project Owner. |

Không có ngày nghiệm thu được ghi vì chưa được cung cấp/xác nhận. Tại thời điểm hoàn tất báo cáo Phase 0, Phase 1 chưa bắt đầu; trạng thái hiện tại được theo dõi trong `description.md` và [`docs/PHASE_1_REPORT.md`](PHASE_1_REPORT.md).
