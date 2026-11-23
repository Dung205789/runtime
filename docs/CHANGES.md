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
- **Trạng thái:** đã duyệt (người dùng, 23/11).

## 2026-11-23 — Agent 2 — Định nghĩa lại `cache_mode = "actions"`

- **Thay đổi:** browser-use 1.0.8 đã bỏ `rerun_history` / `load_and_rerun`, vì agent của bản này viết Python chạy thẳng trên CDP. Vì vậy `actions` giờ có nghĩa là: lấy các cell Python của một lượt `none` thành công (cùng site, nhưng là task khác) và đưa vào system prompt làm gợi ý. LLM vẫn được gọi, nhưng cần ít bước hơn. Code đã học được lưu ở `results/llm/cache/`.
- **Lý do:** thư viện không còn cách nào chạy lại action mà không gọi LLM.
- **Ảnh hưởng đến Agent 1:** không có.
- **Trạng thái:** đã duyệt. Đã cập nhật mục 7 của hợp đồng.

## 2026-11-23 — Chốt chung — Định dạng `/_bench/otp` và bắt buộc tắt telemetry

- **Thay đổi:**
  - `GET /_bench/otp` trả về `{"otp": "123456"}`. Nếu chưa có OTP thì trả `{"otp": null}`.
  - Mọi lượt đo có dùng browser-use phải đặt `ANONYMIZED_TELEMETRY=false`.
- **Lý do:** Khi bật telemetry, một lượt chạy trên dev site mất 88 giây, trong khi vòng lặp agent chỉ mất 10 giây. Sau khi tắt telemetry, cùng lượt đó còn 13–23 giây.
- **Ảnh hưởng đến Agent 1:** **có.**
  - Mock site `s5_otp` phải trả OTP đúng định dạng trên.
  - Khi đo runtime bằng browser-use phải tắt telemetry, nếu không số thời gian sẽ bị đội lên khoảng 70 giây.
- **Trạng thái:** đã chốt. Đã cập nhật mục 1 và mục 5 của hợp đồng.
