# Đề xuất đổi hợp đồng

Mỗi đề xuất ghi theo mẫu dưới đây, rồi dừng lại để người dùng duyệt. Chưa duyệt thì vẫn làm theo hợp đồng hiện tại.

```text
## <ngày> — <Agent 1|2> — <tiêu đề>
- Đổi gì:
- Vì sao:
- Ảnh hưởng tới agent kia:
- Trạng thái: chờ duyệt | đã duyệt | từ chối
```

## 2026-11-23 — Agent 2 — Ngân sách thật chỉ có $2, đo Claude trước

- **Thay đổi:**
  - Trần chi phí LLM giảm từ $25/model xuống **$1,80 cho toàn bộ trục LLM** (đặt bằng biến `BENCH_LLM_BUDGET_USD`). Harness sẽ tự dừng nếu `số đã tiêu + dự phòng cho lượt kế tiếp` vượt trần.
  - Grok để sau, chỉ chạy khi có credit xAI.
  - Ma trận Claude rút gọn như sau:

| Model | Chế độ | Task | Số lượt |
|---|---|---|---|
| Haiku 5.5 | `none` | 10 task | 1 warm-up + 5 lượt |
| Haiku 5.5 | `actions` | 10 task | 1 warm-up + 5 lượt |
| Haiku 5.5 | `session` | 2 task của `s4_guarded` | 1 warm-up + 5 lượt |
| Sonnet 5.5 | `none` | 10 task | 1 lượt, không warm-up |

- **Lý do:** Lượt thử trên dev site tốn $0,0013–0,0017 cho Haiku. Mock site khó hơn, ước tính mỗi lượt tốn gấp 2–4 lần. Nếu chạy đủ ma trận cũ (990 lượt), riêng Sonnet đã tốn hơn $5.
- **Ảnh hưởng đến Agent 1:** không có. Riêng p95 của trục LLM chỉ dựa trên 5 lượt mỗi ô, nên trong báo cáo phải ghi rõ là p95 thực chất gần bằng giá trị lớn nhất.
- **Trạng thái:** đã duyệt (người dùng, 25/11).

## 2026-11-23 — Agent 2 — Định nghĩa lại `cache_mode = "actions"`

- **Thay đổi:** browser-use 1.0.8 đã bỏ `rerun_history` / `load_and_rerun`, vì agent của bản này viết Python chạy thẳng trên CDP. Vì vậy `actions` giờ có nghĩa là: lấy các cell Python của một lượt `none` thành công (cùng site, nhưng là task khác) và đưa vào system prompt làm gợi ý. LLM vẫn được gọi, nhưng cần ít bước hơn. Code đã học được lưu ở `results/llm/cache/`.
- **Lý do:** thư viện không còn cách nào chạy lại action mà không gọi LLM.
- **Ảnh hưởng đến Agent 1:** không có.
- **Trạng thái:** đã duyệt (người dùng, 25/11). Trên web thật, `actions` được thay bằng cache quy trình (mục cuối); hợp đồng mục 7 ghi theo nghĩa mới.

## 2026-11-23 — Chốt chung — Định dạng `/_bench/otp` và bắt buộc tắt telemetry

- **Thay đổi:**
  - `GET /_bench/otp` trả về `{"otp": "123456"}`. Nếu chưa có OTP thì trả `{"otp": null}`.
  - Mọi lượt đo có dùng browser-use phải đặt `ANONYMIZED_TELEMETRY=false`.
- **Lý do:** telemetry gửi URL đã truy cập ra ngoài. Lượt đầu (có telemetry) mất 88 giây, lượt sau (tắt) 23 giây, nhưng lượt đầu còn dính nạp thư viện lần đầu, nên **chưa chứng minh được** telemetry là nguyên nhân.
- **Ảnh hưởng đến Agent 1:** **có.**
  - Mock site `s5_otp` phải trả OTP đúng định dạng trên.
  - Khi đo runtime bằng browser-use nên tắt telemetry; mức ảnh hưởng tới thời gian chưa đo.
- **Trạng thái:** đã duyệt (người dùng, 25/11). Đã ghi vào mục 1 và mục 5 của hợp đồng.

## 2026-11-24 — Agent 2 — Cờ Chrome chống che cửa sổ

- **Thay đổi (đề xuất cho `chrome_local`):** thêm `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, `--disable-background-timer-throttling`.
- **Lý do:** trên máy của Agent 2, cửa sổ Chrome bị coi là bị che, tab thành `hidden` và click theo tọa độ bị bỏ qua: 12/12 lần thử trượt, thêm cờ thì không trượt. Chưa rõ máy của Agent 1 có bị không.
- **Ảnh hưởng tới Agent 1:** **có.** Agent 1 thêm 3 cờ này vào `bench/providers/chrome_local.py` (Agent 2 không sửa file của Agent 1). Đến lúc đó Agent 2 vẫn dùng `bench/llm/chrome.py` riêng.
- **Trạng thái:** đã duyệt (người dùng, 25/11).

## 2026-11-24 — Agent 2 — Đổi hướng theo yêu cầu người dùng

- Dừng mock site; đo trên 5 web nhà hàng thật, dừng trước nút đặt; thay Grok bằng Gemini; thêm cache quy trình (script không gọi LLM).
- Mọi lượt web thật chạy sau lớp chặn gửi đơn (`bench/llm/guard.py`); lệnh từ chối chạy nếu hash lớp chặn chưa có bằng chứng kiểm chứng.
- **Trạng thái:** đã duyệt (người dùng, 25/11). Đã sửa mục 4, 5, 7, 8 của hợp đồng. Trục runtime vẫn đo trên mock site.
