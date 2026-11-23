# Trạng thái — Agent 2 (LLM & cache)

- **Đang làm:** chờ mock site để chạy ma trận Claude, ma trận đã được rút gọn cho vừa ngân sách $1,80 (xem `docs/CHANGES.md`).
- **Mốc đã xong:**
  - **M1:** `get_llm()` cho Haiku 5.5, Sonnet 5.5 và Grok 4.6; bảng giá Claude trong `prices.toml`.
  - **M2:** harness đã chạy thật trên dev site. Kết quả:

    | Lượt | Kết quả | Thời gian | Số bước | Chi phí |
    |---|---|---|---|---|
    | Form thường | success | 22,9 s | 4 | $0,0013 |
    | Form có OTP | success, có gọi `ask_human` | 37,4 s, trong đó 20,6 s chờ người | 6 | $0,0016 |
    | Cache `actions` | success | 13,6 s | 3 | $0,0017 |

  - Tổng đã tiêu: **$0,0061**.
  - Prompt cache hoạt động: 70–88% số token input được đọc từ cache.
- **Bị chặn bởi:** `mock_sites/READY` chưa có trên `main`. Đây là M1 của Agent 1.
- **Agent 1 cần biết:**
  - `GET /_bench/otp` phải trả về `{"otp": "123456"}`. Định dạng này đã chốt trong hợp đồng.
  - Khi đo bằng browser-use **phải đặt `ANONYMIZED_TELEMETRY=false`**. Nếu không, mỗi lượt bị cộng thêm khoảng 70 giây.
  - Phải truyền `judge=False` và `Browser(cdp_url=...)`, vì mặc định thư viện dùng cloud và gọi thêm một lượt LLM để tự chấm.
  - Muốn xem mẫu thì đọc `bench/llm/runner.py`.
  - Chrome local trên máy của Dung: mở mất khoảng 0,8 s, RSS đỉnh khoảng 720 MB khi đang chạy agent.
