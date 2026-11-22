# Brief cho Agent 1 — Runtime trình duyệt

Đọc `docs/00_CONTRACT.md` trước khi làm bất cứ việc gì. Mọi chỗ trong brief này đều tuân theo hợp đồng đó. Bạn chỉ ghi vào các thư mục thuộc quyền của Agent 1 (mục 2 của hợp đồng). Không sửa `bench/core/`, `tasks/`, hay bất kỳ thứ gì của Agent 2.

## Mục tiêu

Đo 4–5 runtime trình duyệt theo 4 nhóm: tài nguyên, tính toán, thời gian, khả dụng. Chọn ra runtime tốt nhất theo tiêu chí ở mục 10 của hợp đồng. Giao lại adapter để các module sau dùng. Cuối cùng chạy kiểm tra chéo và viết `reports/DECISION.md`.

## Mốc và PR

Mỗi mốc gồm 1 PR vào `main` và 1 lần cập nhật `docs/status/agent1.md`. Quy trình git ở `AGENTS.md`.

| Mốc | Nội dung | Mở khóa cho |
|---|---|---|
| **M1** | Mock site + `mock_sites/READY` (Bước 1). **Làm nhanh nhất có thể**, vì Agent 2 đang chờ | Agent 2 bắt đầu đo |
| **M2** | Provider + `get_provider()` (Bước 2) | Agent 2 thay Chrome tạm bằng provider |
| **M3** | Đo runtime + `reports/runtime.md` (Bước 3–4) | — |
| **M4** | Kiểm tra chéo + `DECISION.md` (Bước 5). Chỉ bắt đầu khi `docs/status/agent2.md` ghi M3 đã xong | Các module sau trong pipeline |

## Thứ tự làm

### Bước 1 — Mock site (làm trước tiên, vì Agent 2 cần dùng)

- Dựng 5 site trong `mock_sites/` bằng FastAPI. Mỗi site là một app, chạy đúng cổng và đúng hành vi như bảng ở mục 5 của hợp đồng. Phải có các endpoint `/_bench/*`.
- Viết một lệnh chạy cả 5 site: `uv run python -m mock_sites.serve`.
- Kiểm tra lại: dùng Playwright viết script điền form, chạy **đúng 1 lượt** cho mỗi task trong `tasks/tasks.json`, rồi kiểm tra `grade()` ra `success`.
- Với `s4_guarded`, chứng minh có chặn thật: Chrome headless mặc định, không vá gì, phải bị chặn.
- Xong thì tạo file `mock_sites/READY`, trong đó ghi lệnh chạy. Agent 2 sẽ đợi file này.

### Bước 2 — Provider

- Tạo `bench/providers/`, mỗi runtime một file. Mỗi file implement `BrowserProvider` (start/stop, trả về `BrowserHandle`).
- Tạo `get_provider()`: đọc biến `BENCH_RUNTIME`, trả provider tương ứng.
- Các runtime cần làm:
  - `chrome_local`: Chrome cài trên máy, mở bằng `--remote-debugging-port`, dùng profile tạm.
  - `steel_selfhost`: Docker image `steel-browser`. Tra README trên GitHub `steel-dev/steel-browser` để lấy cổng API, cổng CDP và Live View. Không đoán.
  - `steel_cloud`, `browser_use_cloud`, `kernel`: dùng SDK hoặc REST chính thức. Tra tài liệu hiện hành trước khi viết.
- Kiểm tra cài đặt browser-use, xem bản hiện tại nối CDP bằng cách nào: `Browser(cdp_url=...)` hay tên khác. Ghi số phiên bản vào `versions`.
- Runtime nào thiếu khóa API thì ghi `skipped`.

### Bước 3 — Đo (`bench/runtime/`)

| Phép đo | Cách làm |
|---|---|
| Cold start | Đo `session_create_ms` (gọi `start()` đến khi có CDP) và `first_page_ms` (đến khi `s1_simple` load xong). Mỗi runtime 11 lần |
| Một lượt đặt đầy đủ | Agent browser-use với LLM cố định `claude-haiku-5-5`, `cache_mode = none`, chạy 10 task × 11 lần |
| Tài nguyên | Lấy mẫu mỗi 500 ms, lấy giá trị đỉnh. Linux dùng PSS; Windows dùng USS (ghi rõ trong `machine`); Docker dùng `docker stats`. Với cloud thì chỉ đo phía client và ghi rõ như vậy. Đo ở mức 1, 3 và 5 phiên song song, ghi vào `concurrency` |
| Ổn định | 50 lượt ở mức 3 phiên song song; đếm số phiên chết hoặc treo, đếm tiến trình mồ côi còn sót sau `stop()` |
| Giữ phiên | Mở phiên trên `s5_otp`, chờ 900 giây (`BENCH_HUMAN_DELAY_S=900`), rồi xem phiên có chạy tiếp được không |
| Anti-bot | Chạy 10 lượt trên `s4_guarded`, cộng với 3 trang kiểm tra ở mục 5 của hợp đồng (chỉ đọc). Chụp ảnh kết quả lưu vào `results/runtime/antibot/` |
| Live View | Xem runtime có URL Live View không. Mở URL đó trong trình duyệt khác và gõ được vào ô OTP thì tính là có. Đo độ trễ hiển thị nếu đo được |
| Chi phí | Cloud tính theo giá trong `prices.toml`. Self-host và local quy theo giá một VPS tương đương có cùng RAM đỉnh; ghi rõ đây là **ước tính** |

- Lệnh chạy: `uv run python -m bench.runtime.run`. Có resume: ô nào đã đủ số lượt thì bỏ qua.
- Ghi log đúng `RunRecord`, đặt ở `results/runtime/`.

### Bước 4 — Báo cáo `reports/runtime.md`

- Bảng p50/p95 cho mỗi chỉ số, kết quả cổng loại, bảng điểm theo trọng số.
- Ghi rõ số nào là số đo thật, số nào là ước tính.
- Có mục **"Chưa kiểm chứng"**.

### Bước 5 — Kiểm tra chéo và quyết định (làm sau khi `reports/llm.md` của Agent 2 đã có)

- Chạy runtime thắng với LLM thắng và chế độ cache thắng: 10 task × 11 lần, ghi vào `results/cross/`.
- Viết `bench/report.py`: đọc toàn bộ JSONL, tính lại cổng loại và điểm. Không nhập số bằng tay.
- Viết `reports/DECISION.md` theo mục 11 của hợp đồng.
- Cập nhật mặc định của `get_provider()` thành runtime thắng.

## Xong khi

- `mock_sites/READY` đã có, và 10/10 task đều `success` bằng script.
- Mọi ô đo đủ 11 lượt, hoặc có lý do `skipped`.
- Chạy `uv run python -m bench.report` sinh lại đúng bảng số trong `DECISION.md`.

## Luật

- Không bịa số. Không ước lượng thay cho số đo được.
- Không submit đặt bàn lên site thật.
- Không commit nếu người dùng chưa yêu cầu.
- Cần đổi hợp đồng thì ghi vào `docs/CHANGES.md`, rồi dừng lại hỏi người dùng.
