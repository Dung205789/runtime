# Hợp đồng chung — Module chọn runtime & LLM

Module này đo các lựa chọn, chọn ra **một tổ hợp runtime + LLM + chế độ cache**, rồi các module sau trong pipeline dùng theo. Hai agent làm song song:

- **Agent 1 — Runtime**: brief ở `docs/AGENT_1_RUNTIME.md`
- **Agent 2 — LLM & cache**: brief ở `docs/AGENT_2_LLM.md`

Mọi thứ trong file này **đã chốt**. Không agent nào tự sửa. Cần đổi thì ghi đề xuất vào `docs/CHANGES.md` và báo người kia, không sửa thẳng.

---

## 1. Môi trường

- Python 3.12, quản lý bằng `uv`. Dependency chung ở `pyproject.toml`.
- Khóa API để trong `.env` (mẫu ở `.env.example`). Không hard-code khóa, không commit `.env`.
- Thiếu khóa của một ứng viên thì ghi `outcome = "skipped"` kèm lý do. **Không bịa số.**
- Mỗi file kết quả ghi cấu hình máy đo (CPU, RAM, OS) qua `machine_info()` trong `bench/core/contract.py`.

## 2. Phân quyền thư mục

| Thư mục / file | Chủ | Người kia được |
|---|---|---|
| `bench/core/`, `tasks/tasks.json`, `docs/00_CONTRACT.md` | Chốt chung | Chỉ đọc |
| `mock_sites/` | Agent 1 | Chỉ đọc, chạy |
| `bench/providers/`, `bench/runtime/`, `results/runtime/`, `reports/runtime.md` | Agent 1 | Chỉ đọc, import `bench.providers` |
| `bench/llms/`, `bench/llm/`, `results/llm/`, `reports/llm.md` | Agent 2 | Chỉ đọc, import `bench.llms` |
| `results/cross/`, `reports/DECISION.md`, `bench/report.py` | Agent 1 (làm sau cùng) | Đọc, góp ý |
| `docs/status/agent1.md` / `docs/status/agent2.md` | Agent 1 / Agent 2 | Chỉ đọc |
| `bench/core/prices.toml` | Agent 1 ghi khóa `runtime.*`, Agent 2 ghi khóa `llm.*` | — |
| `pyproject.toml`, `uv.lock` | Cả hai, chỉ được **thêm** dependency | Không xóa dependency của người kia |

## 3. Interface dùng chung

Định nghĩa ở `bench/core/contract.py`:

- `BrowserProvider` có `start() -> BrowserHandle` và `stop(handle)`. `BrowserHandle.cdp_url` là thứ browser-use dùng để nối vào.
- Chọn provider bằng biến `BENCH_RUNTIME` (mặc định `chrome_local`). Chọn LLM bằng biến `BENCH_LLM` (mặc định `claude-haiku-5-5`).
- Các module sau trong pipeline chỉ gọi `bench.providers.get_provider()` và `bench.llms.get_llm()`. Đổi lựa chọn chỉ cần đổi biến môi trường.

## 4. Ứng viên

**Runtime (Agent 1):** `chrome_local`, `steel_selfhost` (Docker), `steel_cloud`, `browser_use_cloud`, `kernel` (tùy chọn, làm nếu còn thời gian).

**LLM (Agent 2):** chạy trong browser-use. Ứng viên: `claude-sonnet-5-5`, `claude-haiku-5-5`, `grok-4.6`. Nếu `grok-4.6` chưa mở quyền truy cập thì dùng model Grok GA mới nhất và ghi rõ tên. Tùy chọn thêm: Claude gọi trực tiếp `browser_toolset_20260801`, dùng làm cột tham khảo.

**Biến cố định khi đo** (để tách biến):

- Agent 1 đo runtime với LLM cố định là `claude-haiku-5-5`.
- Agent 2 đo LLM với runtime cố định là `chrome_local`.

## 5. Bộ task và mock site

Không chạy lặp trên web nhà hàng thật, vì sẽ tạo đơn rác. Đo trên **5 mock site** chạy local. Mức độ khó của chúng đại diện cho các loại site mà các module sau sẽ gặp:

| Site | Cổng | Độ khó |
|---|---|---|
| `s1_simple` | 8801 | Form một trang, input ngày/giờ native |
| `s2_wizard` | 8802 | 3 bước, date picker JS tự viết (không phải `<input type=date>`), chọn khung giờ bằng nút |
| `s3_spa` | 8803 | SPA, khung giờ tải bằng `fetch` sau khi chọn ngày, có độ trễ ngẫu nhiên 300–1500 ms, có modal cookie che form |
| `s4_guarded` | 8804 | Cần cookie từ JS challenge, có trường honeypot ẩn, giới hạn 10 request/phút/IP, chặn `navigator.webdriver = true` |
| `s5_otp` | 8805 | Form đơn giản, sau khi submit đòi OTP 6 số |

**Endpoint kiểm tra** (site nào cũng phải có):

- `POST /_bench/reset`: xóa sạch đơn đã nhận.
- `GET /_bench/bookings`: trả danh sách đơn dạng JSON `[{date, time, party_size, name, phone, created_at}]`.
- `GET /_bench/otp`: trả OTP hiện tại (chỉ `s5_otp`).

**Chấm kết quả** (do harness làm, không để LLM tự báo):

- `success`: có đúng 1 đơn, và mọi trường khớp `expected`.
- `wrong_data`: có đơn nhưng sai trường. Đây là **lỗi nghiêm trọng nhất**.
- `failed`: không có đơn.

Bộ task cố định ở `tasks/tasks.json`: 10 task, mỗi site 2 task. Câu lệnh viết như tin nhắn chatbot gửi sang.

Ngoài mock site, Agent 1 đo anti-bot **chỉ đọc, không submit** trên 3 trang: `https://www.browserscan.net/bot-detection`, `https://abrahamjuliot.github.io/creepjs/`, `https://nowsecure.nl`.

## 6. OTP / người trong vòng lặp

- Agent đặt bàn có tool `ask_human(question) -> str`.
- Harness tự trả lời bằng cách gọi `GET /_bench/otp` sau `BENCH_HUMAN_DELAY_S` giây. Mặc định là 20 giây. Bài test giữ phiên dùng 900 giây.
- `paused_for_otp = true` nếu agent gọi `ask_human` trước khi OTP được nhập. Nếu agent tự đoán OTP hoặc bỏ qua bước này thì task tính là `failed`.

## 7. Cache: 3 chế độ, tách riêng với prompt cache

| `cache_mode` | Nghĩa |
|---|---|
| `none` | Profile trắng, agent không có gì lưu sẵn. Đây là "chưa cache" |
| `session` | Dùng lại `storage_state` (cookie, localStorage) từ một lượt thành công trước đó |
| `actions` | Chạy lại lịch sử action đã ghi từ lượt thành công. Chỉ gọi LLM khi bước chạy lại bị lỗi |

**Prompt cache của API** luôn **bật** ở mọi cấu hình, vì thực tế sẽ dùng như vậy. Ghi riêng các cột `tokens_cache_read` / `tokens_cache_write`. Đây không phải `cache_mode`.

## 8. Quy trình đo

- Mỗi ô (ứng viên × task × chế độ) chạy **11 lần**. Lần đầu là warm-up (`warmup = true`) và bị loại khỏi thống kê.
- Báo **p50 và p95**, không báo trung bình đơn thuần.
- Chi phí tính trên **lượt thành công**: `$/success = tổng chi phí mọi lượt ÷ số lượt success`.
- Giới hạn mỗi lượt: tối đa 40 bước, tối đa 300 giây (không tính thời gian chờ người). Vượt giới hạn thì `timeout`.
- Ngân sách LLM: mỗi model tối đa **$25** cho toàn bộ đợt đo. Chạm trần thì dừng và ghi lại đã chạy được bao nhiêu ô.
- Giá lấy từ trang chính thức, ghi vào `bench/core/prices.toml` kèm ngày tra và URL nguồn. Agent 1 ghi giá runtime, Agent 2 ghi giá LLM.

## 9. Log

Mỗi lượt chạy ghi **một dòng JSONL**, theo `RunRecord` trong `bench/core/contract.py`. Dùng `append_record()`, không tự chế format. File đặt ở `results/<axis>/<YYYYMMDD>_<tên>.jsonl`.

## 10. Tiêu chí chọn

**Bước 1 — Cổng loại.** Trượt một cổng là bị loại, không cần tính điểm.

| Trục | Cổng |
|---|---|
| Runtime | browser-use nối được qua CDP; 0 phiên mất trong 50 lượt chạy ở mức 3 phiên song song; phiên còn sống sau 15 phút chờ; vượt được `s4_guarded` ≥ 8/10 |
| LLM (với `cache_mode = none`) | Tỷ lệ success ≥ 80% trên cả 10 task; **0 lượt `wrong_data`**; `paused_for_otp` đúng 100% trên `s5_otp` |

**Bước 2 — Chấm điểm** các ứng viên còn lại. Mỗi chỉ số được quy về 0–100 trong nhóm ứng viên (tốt nhất 100, kém nhất 0, nội suy tuyến tính), rồi nhân trọng số:

| Runtime | Trọng số | LLM | Trọng số |
|---|---|---|---|
| p95 thời gian một lượt đặt | 35 | $/success | 40 |
| $ cho 1.000 lượt đặt | 30 | p95 thời gian một lượt | 35 |
| RAM PSS/phiên (cloud: đo phía client) | 15 | Tỷ lệ success | 25 |
| p95 cold start (tạo phiên → trang đầu) | 10 | | |
| Có Live View dùng được cho khách | 10 | | |

- Hai ứng viên chênh nhau dưới 5 điểm thì chọn cái **đơn giản hơn để vận hành**, theo thứ tự ưu tiên: local, rồi self-host, rồi cloud.
- **Chế độ cache:** chọn chế độ rẻ nhất mà tỷ lệ success không thấp hơn `none` quá 5 điểm phần trăm. Báo cáo nêu **điểm hòa vốn**: site cần được đặt bao nhiêu lần thì làm cache có lời.

## 11. Đầu ra cuối giao cho pipeline

1. `reports/DECISION.md`: tổ hợp được chọn, bảng điểm, lý do, điều kiện để xét lại (ví dụ: có model mới, giá đổi trên 30%, tỷ lệ success thật dưới 80%).
2. `bench.providers.get_provider()` và `bench.llms.get_llm()` chạy được với lựa chọn thắng, mặc định trỏ vào lựa chọn đó.
3. Chạy lại được toàn bộ bằng `uv run python -m bench.runtime.run`, `uv run python -m bench.llm.run`, `uv run python -m bench.report`.
