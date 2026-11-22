# Brief cho Agent 2 — LLM và cache

Đọc `docs/00_CONTRACT.md` trước khi làm bất cứ việc gì. Mọi chỗ trong brief này đều tuân theo hợp đồng đó. Chỉ ghi vào các thư mục thuộc quyền Agent 2 (mục 2 của hợp đồng). Không sửa `bench/core/`, `tasks/`, `mock_sites/` hay bất cứ thứ gì của Agent 1.

## Mục tiêu

Đo các LLM chạy trong browser-use khi **chưa cache**, so sánh Claude với Grok. Đo thêm các chế độ cache `session` và `actions` để biết cache tiết kiệm được bao nhiêu và khi nào thì có lời. Từ đó chọn ra LLM và chế độ cache tốt nhất theo mục 10 của hợp đồng, rồi giao `get_llm()` cho các module sau.

## Mốc và PR

Mỗi mốc ứng với 1 PR vào `main` và 1 lần cập nhật `docs/status/agent2.md`. Quy trình git xem ở `AGENTS.md`.

| Mốc | Nội dung | Phụ thuộc |
|---|---|---|
| **M1** | Adapter LLM + `get_llm()` + giá LLM (Bước 1) | Không. Làm ngay |
| **M2** | Harness chạy được 1 lượt hoàn chỉnh trên `s1_simple` (Bước 2) | Cần `mock_sites/READY` có trên `main`. Kiểm tra bằng `git fetch && git merge origin/main`. Trong lúc chờ, test harness trên một trang HTML tạm trong `bench/llm/` |
| **M3** | Chạy ma trận + `reports/llm.md` (Bước 3–4). Ghi rõ model thắng và chế độ cache thắng vào status | Mở khóa M4 của Agent 1 |

## Thứ tự làm

### Bước 1 — Adapter LLM (`bench/llms/`), làm trong lúc chờ `mock_sites/READY`

- Viết hàm `get_llm(name)`. Hàm đọc biến `BENCH_LLM` và trả về object chat model mà `browser_use.Agent` nhận được.
- Trước khi viết, kiểm tra bản browser-use đã cài: thư viện đang cung cấp lớp nào cho Anthropic, và lớp nào gọi được endpoint tương thích OpenAI (xAI dùng `https://api.x.ai/v1`). Ghi phiên bản vào `versions`.
- Bật prompt caching của Anthropic nếu browser-use hỗ trợ. Nếu không hỗ trợ thì ghi rõ vào báo cáo.
- Lấy số token từ usage mà API trả về, gồm cả `cache_read` và `cache_write`. Không ước lượng token.
- Ghi giá LLM vào `bench/core/prices.toml` dưới khóa `[llm.<tên>]`, kèm ngày tra và URL. Đây là ngoại lệ duy nhất được ghi vào `bench/core/`, và chỉ được ghi ở khóa `llm.*`.
- Nếu `grok-4.6` chưa mở quyền truy cập thì dùng model Grok GA mới nhất có trên `docs.x.ai`, ghi rõ tên model.
- Tùy chọn: thêm cột tham khảo `claude-native`, gọi thẳng Messages API với `browser_toolset_20260801` và chạy trên cùng CDP. Chỉ làm khi các phần chính đã xong.

### Bước 2 — Harness (`bench/llm/`)

- Agent đặt bàn dùng chung một system prompt cho mọi model. Prompt đặt ở `bench/llm/prompt.md`. Có tool `ask_human` theo mục 6 của hợp đồng.
- Trước mỗi lượt: gọi `POST /_bench/reset`. Sau mỗi lượt: gọi `GET /_bench/bookings`, rồi dùng `grade()` để chấm.
- Runtime cố định là `chrome_local`. Import `bench.providers.get_provider` của Agent 1. Nếu module đó chưa có thì tự mở Chrome tạm trong `bench/llm/`, rồi chuyển sang dùng provider khi Agent 1 xong.
- Lệnh chạy: `uv run python -m bench.llm.run`. Có resume, và dừng khi chạm trần $25 cho mỗi model.

### Bước 3 — Ma trận đo

| Chế độ | Ứng viên | Task | Số lượt |
|---|---|---|---|
| `none` | 3 model | 10 task | 11 lượt mỗi ô |
| `session` | 3 model | 10 task | 11 lượt mỗi ô |
| `actions` | 3 model | 10 task | 11 lượt mỗi ô |

- **`session`**: lấy `storage_state` từ một lượt `none` thành công của cùng site, rồi nạp vào trước khi chạy.
- **`actions`**: lấy lịch sử action từ một lượt `none` thành công của **cùng task nhưng với dữ liệu khác** (ví dụ: dùng t01 để chạy t02). Thay giá trị ngày, giờ, số người, tên, SĐT vào chỗ tương ứng rồi chạy lại. Bước nào lỗi thì mới gọi LLM. Ghi lại số bước phải gọi LLM.
- Ghi lại **chi phí học**: tổng token và thời gian của lượt `none` đã dùng để tạo cache.
- Nếu ngân sách không đủ, ưu tiên chạy theo thứ tự: `none` cho mọi model → `actions` → `session`.

### Bước 4 — Báo cáo `reports/llm.md`

- Cổng loại cho từng model: success ≥ 80%, 0 lượt `wrong_data`, dừng đúng ở bước OTP.
- Bảng p50/p95 thời gian, số bước, token (tách phần cache_read), $/success, chia theo model × chế độ.
- Bảng điểm theo trọng số, kèm model thắng và chế độ cache thắng.
- **Điểm hòa vốn** cho mỗi model: `N* = chi phí học ÷ (chi phí lượt none − chi phí lượt có cache)`.
- Liệt kê các lượt `wrong_data`, ghi rõ sai trường nào. Đây là thông tin quan trọng nhất cho module agent đặt bàn ở phía sau.
- Có mục **"Chưa kiểm chứng"**.
- Đặt mặc định của `get_llm()` thành model thắng. Ghi chế độ cache thắng vào `reports/llm.md`, để Agent 1 dùng cho bước kiểm tra chéo.

## Xong khi

- Mọi ô trong ma trận có đủ 11 lượt, hoặc có lý do dừng (`skipped`, hoặc hết ngân sách).
- Mọi số trong `reports/llm.md` đều sinh ra từ JSONL bằng script. Không có số nào nhập tay.
- Báo cho người dùng biết là đã xong, để Agent 1 chạy kiểm tra chéo.

## Luật

- Không bịa số. Model nào bị lỗi API thì ghi lỗi đó, không bỏ qua lượt.
- Không chạy trên site đặt bàn thật.
- Không commit nếu người dùng chưa yêu cầu.
- Muốn đổi hợp đồng thì ghi vào `docs/CHANGES.md` rồi dừng lại, hỏi người dùng.
