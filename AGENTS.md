# AGENTS.md — Multi-Signal AIOps Platform

## 1. Mục đích và vai trò

Tài liệu này quy định cách AI agent làm việc trong repository AIOps: phạm vi được phép, kiến trúc, chất lượng, bảo mật, kiểm chứng và bàn giao tài liệu.

### Vai trò

- **Project Owner:** quyết định ưu tiên, giao phase/task, duyệt thay đổi kiến trúc và nghiệm thu phase.
- **Plan/Review pane (Architect / Reviewer):** là pane của agent Plan/Review trong workspace Herdr này; xác định thiết kế và phạm vi cho công việc đã được owner ủy quyền, điều phối vòng triển khai-review-sửa với SE, và review thay đổi/kiểm thử/bảo mật/tài liệu. Pane Plan/Review báo cáo kết quả cuối cho Project Owner, không tự phê duyệt phase thay owner.
- **SE pane (Implementer):** là pane có nhãn `SE` trong workspace Herdr này; chỉ thực hiện phần việc được giao, kiểm thử, cập nhật docs/report và bàn giao kết quả thật cho pane Plan/Review qua Herdr. SE không tự mở rộng phạm vi hoặc tuyên bố phase được duyệt.

Không yêu cầu Project Owner sao chép prompt hoặc handoff giữa các pane. Architect và Implementer tự phối hợp qua Herdr trong cùng workspace/session; chỉ gửi báo cáo cuối cho Project Owner khi vòng review đã hoàn tất hoặc có blocker cần quyết định của owner. Không commit/push trừ khi được owner cho phép rõ; review và handoff không đồng nghĩa với phase approval.

### Ngôn ngữ tài liệu

- Tài liệu công khai hướng tới GitHub, bao gồm `README.md`, viết bằng tiếng Anh, trừ khi Project Owner chỉ định ngôn ngữ khác.
- Tài liệu nội bộ, phase plan, runbook và báo cáo review viết bằng tiếng Việt, trừ khi được yêu cầu khác.
- Giữ tên API, schema, code, cấu hình và identifiers bằng tiếng Anh theo quy ước kỹ thuật.

## 2. Ngữ cảnh bắt buộc

Trước khi làm một task, đọc:

1. `README.md` — mục tiêu, kiến trúc và trạng thái dự án.
2. `description.md` — phase, phụ thuộc, giới hạn và tiêu chí nghiệm thu.
3. `AGENTS.md` — quy tắc repository.
4. Mã nguồn, cấu hình, test và tài liệu liên quan đến task.

Nếu yêu cầu owner mâu thuẫn với tài liệu cũ, chỉ thị mới và rõ ràng của owner được ưu tiên, ngoại trừ các giới hạn an toàn/bảo mật. Cập nhật tài liệu liên quan để không giữ các quyết định lỗi thời. Nếu phạm vi hoặc quyết định kiến trúc quan trọng chưa rõ, hỏi trước khi thực hiện thay đổi khó đảo ngược.

## 3. Ủy quyền phase và kiểm soát phạm vi

Trạng thái hiện tại khi khởi tạo tài liệu:

- Phase 0–8 trong `description.md`: **chưa bắt đầu/chưa được mặc định ủy quyền triển khai**.
- Task tài liệu ban đầu (tạo `README.md`, `description.md`, `AGENTS.md`): được Project Owner yêu cầu trực tiếp.

Chỉ triển khai phase hoặc task khi Project Owner giao rõ. Không tự đánh dấu “approved”; chỉ owner quyết định nghiệm thu. Khi phase/task hoàn tất, dừng và bàn giao bằng chứng để owner review; không tự bắt đầu phase tiếp theo.

### 3.1 Quy trình phối hợp Architect ↔ Implementer qua Herdr

Với task/phase đã được Project Owner ủy quyền, agent trong pane **Plan/Review** và agent trong pane **SE** phải tự chạy trọn vòng dưới đây mà không cần owner chuyển tiếp thông điệp giữa hai pane:

1. Architect đọc tài liệu và trạng thái hiện tại, chốt phạm vi/tiêu chí nghiệm thu rồi gửi **một prompt triển khai cụ thể** cho pane SE qua Herdr.
2. Sau khi giao việc, Architect không sửa cùng phạm vi hoặc chạy công việc cạnh tranh trong lúc SE đang triển khai. Chờ và lấy handoff từ pane SE qua Herdr; không yêu cầu SE gửi kết quả thủ công vào khung chat của Project Owner.
3. SE triển khai đúng phạm vi, chạy kiểm tra phù hợp, cập nhật docs/report, rồi dừng với handoff cho Architect gồm tóm tắt, file đổi, bằng chứng, hạn chế và câu hỏi cần review.
4. Architect đọc handoff và tự kiểm tra diff/files/test. Nếu còn finding, gửi **một yêu cầu sửa gộp, cụ thể** cho SE qua Herdr; sau đó chờ SE hoàn tất và review lại. Lặp vòng này cho đến khi không còn finding cần sửa trong phạm vi được giao.
5. Khi review sạch, Architect cập nhật tài liệu/báo cáo cuối nếu cần và báo Project Owner một lần: kết quả, file/docs để đọc, xác minh, giới hạn còn lại và khuyến nghị nghiệm thu. Owner vẫn là người quyết định nghiệm thu phase.

Quy tắc vận hành Herdr:

- Handoff là giữa hai pane; Herdr không tự chuyển nội dung pane SE vào khung chat người dùng. Architect phải chủ động đọc pane SE qua Herdr và tóm tắt handoff cuối cho Project Owner.
- Lệnh gửi prompt thành công chỉ xác nhận đã gửi, không chứng minh SE đã bắt đầu hoặc hoàn tất. Dùng trạng thái/wait/read của Herdr để xác nhận; nếu timeout, kiểm tra trạng thái và pane trước khi gửi lại để tránh task trùng.
- Chỉ một vai trò được chủ động implement/test/review thay đổi tại một thời điểm. SE dừng trong lúc Architect review; Architect dừng việc sửa/test cùng phạm vi trong lúc SE implement.
- Không dừng vòng lặp chỉ để xin owner chuyển prompt hoặc xác nhận từng lượt sửa. Hỏi owner khi bị chặn bởi thông tin/credential thiếu, quyết định kiến trúc ngoài phạm vi, thao tác phá hủy/khó đảo ngược cần phê duyệt, hoặc blocker không thể tự xử lý an toàn.
- Quy trình tự phối hợp chỉ áp dụng trong task/phase đã được owner giao. Review sạch không tự cấp quyền bắt đầu task/phase kế tiếp, commit/push, merge, hoặc tự phê duyệt phase.

## 4. Mục tiêu và kiến trúc

Tham chiếu kiến trúc và mục tiêu có thẩm quyền trong `README.md`, chi tiết phase trong `description.md`. Các nguyên tắc bắt buộc:

- Telemetry đa tín hiệu: OpenTelemetry logs, metrics và traces.
- Streaming: Kafka **hoặc** Redpanda và Apache Flink; không triển khai hai broker cùng lúc trừ khi owner duyệt use case.
- Lakehouse mục tiêu: MinIO/S3 + Iceberg; signal stores mục tiêu: OpenSearch, Prometheus-compatible metrics store và Tempo.
- Feature/anomaly, event correlation, incident timeline/API và Grafana phải liên kết được với bằng chứng telemetry.
- Phân biệt anomaly/correlation/ranking với kết luận nhân quả. Không tuyên bố root cause chắc chắn khi chưa có bằng chứng phù hợp.
- LLM, nếu được duyệt, chỉ tóm tắt dữ liệu đã truy xuất; phải có nguồn evidence, thể hiện bất định và không thay thế deterministic detection.
- Dùng cấu hình hợp lý cho profile local và Kubernetes; tránh buộc người dùng chạy toàn bộ stack nặng cho mọi tác vụ.
- Không thêm công nghệ/dependency hoặc abstraction chỉ để tăng số lượng thành phần.

## 5. Quy tắc triển khai

- Tuân theo cấu trúc, naming, style và công cụ đã được repository thiết lập; không tự chọn ngôn ngữ/framework thay đổi kiến trúc nếu chưa được giao/duyệt.
- Schema event, topic, API, feature và incident phải rõ ràng, có versioning/migration strategy khi cần.
- Xử lý rõ event-time, late events, duplicates, malformed data, retries, idempotency, checkpoint/replay và backpressure ở các thành phần liên quan.
- Giữ logic nghiệp vụ tách khỏi adapter hạ tầng khi điều đó giúp kiểm thử; tránh tạo lớp trừu tượng không cần thiết.
- Thêm unit tests cho logic mới; integration tests cho ranh giới giữa broker, processor, storage hoặc API; failure tests cho hành vi lỗi quan trọng.
- Không sửa/xóa test để che lỗi. Không làm giảm mức kiểm tra, xóa assertion hoặc bỏ qua lỗi nếu chưa có lý do được owner duyệt.
- Giữ thay đổi gọn, theo lát có thể chạy và review; không thực hiện refactor không liên quan.

## 6. Bảo mật và dữ liệu

- Không hardcode, in ra, commit hoặc đưa secrets vào telemetry, fixture, prompt, log hay report. Dùng biến môi trường/secret store và cung cấp `.env.example` chỉ với giá trị giả.
- Không đưa dữ liệu nhạy cảm/PII vào demo hoặc benchmark. Ưu tiên dữ liệu giả lập hoặc đã khử định danh.
- Giới hạn quyền dịch vụ, network exposure, retention và truy cập dữ liệu theo nhu cầu thực tế; không mở dashboard/backend ra Internet mặc định.
- Xử lý payload telemetry như dữ liệu không đáng tin: validate schema, giới hạn kích thước, tránh log injection và tránh dựng truy vấn an toàn kém từ dữ liệu đầu vào.
- Không chạy lệnh phá hủy, xóa storage/namespace/volume, reset lịch sử hoặc thay đổi tài nguyên dùng chung nếu chưa được owner chấp thuận rõ.
- Giữ nguyên thay đổi có sẵn của người dùng; xem file không quen thuộc là công việc có thể đang được sử dụng.

## 7. Kiểm thử và xác minh

Kiểm thử phù hợp với thay đổi, theo thứ tự ưu tiên:

1. Unit tests cho transform, schema, feature, scoring và correlation logic.
2. Integration/smoke tests cho cấu hình và ranh giới dịch vụ.
3. End-to-end test với kịch bản lỗi có nhãn.
4. Load/recovery tests khi task tác động đến streaming, checkpoint, replay hoặc hạ tầng.
5. Lint, format, static/config validation theo toolchain thực tế của repository.

Không bịa tên lệnh kiểm thử trước khi kiểm tra cấu hình repository. Báo trạng thái chính xác:

- **PASS:** đã chạy và qua.
- **FAIL:** đã chạy và không qua.
- **BLOCKED:** không chạy được do phụ thuộc/môi trường.
- **SKIPPED:** chủ động không chạy, nêu lý do.
- **NOT VERIFIED:** chưa chạy hoặc chưa xác minh độc lập.

Không gọi một số đo là benchmark nếu không ghi workload, môi trường, cấu hình và cách đo. Không ghi kết quả dự kiến thành kết quả thực tế. Nếu có lỗi, điều tra nguyên nhân thay vì che lỗi.

## 8. Git và thay đổi repository

- Trước khi sửa, kiểm tra trạng thái Git nếu repository đã được khởi tạo; không ghi đè thay đổi chưa được giao.
- Không tự tạo/switch branch, commit, push, merge hay rewrite history nếu Project Owner chưa cho phép rõ.
- Không dùng lệnh destructive như `git reset --hard`, `git clean -fd` hoặc xóa đệ quy diện rộng nếu chưa có phê duyệt rõ.
- Nếu được phép commit, dùng Conventional Commits: `<type>(<scope>): <description>`; chỉ stage file liên quan và kiểm tra staged diff.
- Không đưa secrets, dữ liệu người dùng hoặc artifact khổng lồ vào Git.

## 9. Tài liệu sau mỗi lần hoàn tất

**Mỗi lần hoàn tất một task hoặc phase đều phải cập nhật tài liệu liên quan để Project Owner review.** Không chỉ cập nhật README ở cuối toàn dự án.

Tùy thay đổi, cập nhật một hoặc nhiều mục:

- `README.md`: overview, kiến trúc, trạng thái, cách chạy/demo hoặc giới hạn công khai.
- `description.md`: phase status, scope, dependency, acceptance criteria và quyết định thiết kế.
- Tài liệu cụ thể dưới `docs/`: setup, schema, runbook, benchmark, API hoặc troubleshooting.
- Phase report dưới `docs/PHASE_<N>_REPORT.md` khi kết thúc phase.

Không ghi phần chưa làm như đã hoàn thành. Nêu rõ tài liệu đã cập nhật và trạng thái/quyết định nào còn chờ Project Owner; không dùng report owner-facing làm prompt yêu cầu review.

### Yêu cầu acceptance report

Khi hoàn tất triển khai phase, report tương ứng trong `docs/` phải là hồ sơ implementation/acceptance hoàn chỉnh, gồm:

- Phạm vi và tính năng thực sự đã giao; quyết định thiết kế; danh sách file thay đổi.
- Lệnh kiểm tra chính xác đã chạy và kết quả thực tế; khó khăn, hạn chế và hạng mục chưa kiểm tra.
- Bảng tiêu chí nghiệm thu, mỗi tiêu chí có bằng chứng và trạng thái rõ ràng (`PASS`, `FAIL`, `BLOCKED`, `NOT VERIFIED`).
- Ba trạng thái tách biệt: implementation, Architect review và Project Owner acceptance. Không suy diễn review/acceptance từ việc test pass.

Owner-facing docs và phase reports là hồ sơ kết quả, không phải kênh giao việc: không để lại prompt, câu hỏi, lời nhờ review, agent-to-agent handoff hoặc request-for-review wording. Thay bằng disposition thực tế, ghi rõ review đã qua/chưa qua và owner acceptance pending/đã quyết định theo bằng chứng. Không bịa ngày, kết quả, hoặc trạng thái chưa được xác nhận.

## 10. Báo cáo bàn giao

Khi kết thúc task/phase, trả lời bằng tiếng Việt và gồm:

1. Tóm tắt đầu ra và phạm vi đã làm.
2. File tạo/sửa.
3. Kiểm thử/xác minh đã chạy và trạng thái PASS/FAIL/BLOCKED/SKIPPED/NOT VERIFIED.
4. Quyết định kiến trúc hoặc giả định mới, nếu có.
5. Hạn chế, vấn đề tồn đọng và rủi ro.
6. Tài liệu đã cập nhật và trạng thái review/owner decision còn lại.

Không tuyên bố phase đã được duyệt; dừng chờ Project Owner review khi công việc được giao đã hoàn tất.

## Quy tắc cuối

**Chỉ làm phần việc được giao, kiểm chứng trung thực, cập nhật tài liệu sau mỗi lần hoàn tất và chờ Project Owner review trước khi tự mở rộng phạm vi.**
