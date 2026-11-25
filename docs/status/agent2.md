# Trạng thái — Agent 2 (LLM & cache)

Cập nhật 2026-11-25.

- **Đang làm:** không có. M3 đã xong.
- **Mốc đã xong:**
  - M1: `bench/llms/get_llm()` (Haiku, Sonnet, Gemini, Grok), giá LLM trong `bench/core/prices.toml`.
  - M2: harness mock site (`bench.llm.run`), lớp chặn gửi đơn, harness web thật (`bench.llm.real`, `bench.llm.combo`).
  - M3: đo trên 5 web nhà hàng thật (5 vòng), mock site làm phụ lục. Báo cáo `reports/llm.md`, sinh lại bằng `uv run python -m bench.llm.report`.
- **Kết quả, cho Agent 1 làm M4:**
  - **Model thắng: `claude-haiku-5-5`.** Đây là mặc định của `get_llm()`. Gemini flash-lite bị loại vì có 1 lượt `wrong_data`.
  - **Chế độ cache thắng: `actions`**, nghĩa mới: cache quy trình, tức script chạy thẳng không gọi LLM, và gọi Haiku chạy chay khi script từ chối. Trên web thật: 25/25 lượt đúng, p50 8,5 s, so với Haiku chạy chay p50 45,1 s và $0,0041/lượt. Hòa vốn sau 3–10 lượt mỗi web.
  - Rủi ro: 2 lượt Haiku ở Lẩu Wang chưa chấm được ô giờ (xem mục 8 của báo cáo).
- **Excel + ảnh (25/11):** `results/llm/real/llm_web.xlsx`, mỗi web 1 sheet, kèm ảnh từng bước. Sinh lại bằng `uv run python -m bench.llm.shots --reps N` (chạy lại script cache, không gọi LLM, sau lớp chặn), rồi `uv run --with openpyxl --with pillow python -m bench.llm.excel`.
- **Script cache v2 (25/11):** ảnh lộ 3 lỗi của script v1 do Haiku sinh. Đã sửa tay (bản cũ giữ ở `script_v1`):
  - Lẩu Phan: giờ có lúc bị đặt lại sau khi điền. v2 chờ ô Giờ đứng yên rồi mới kết thúc.
  - King BBQ: chọn nhà hàng khi danh sách chưa tải xong (v1 từ chối 3/9 lần). v2 chờ danh sách tải xong: 5/5.
  - Lẩu Wang: ô hiển thị không đổi. v2 chọn qua widget: 5/5, ô hiển thị đúng.
  - Ca đổi dữ liệu với v2 (`bench.llm.recheck`): 0 lần điền sai.
  - Số đo 24/11 vẫn là của v1; v2 chưa đo lại thời gian và chi phí theo quy trình combo.
- **Bị chặn bởi:** không có. Đã tiêu: Claude $1,01 / $1,80, Gemini $0,69 / $1,00. Sonnet chưa đo vì ước tính khoảng $1 cho 10 lượt, vượt phần còn lại.
- **Agent 1 cần biết:**
  - Hợp đồng đã sửa (người dùng duyệt 25/11): trục LLM đo trên web thật, Gemini thay Grok, 5 vòng mỗi ô, `actions` = cache quy trình. Xem `docs/CHANGES.md`.
  - Đã duyệt thêm 3 cờ Chrome chống che cửa sổ cho `chrome_local`. Việc này của Agent 1, vì file nằm trong `bench/providers/`.
  - M4 trên mock site: script cache hiện chỉ có cho 5 web thật (`results/llm/real/scripts/`); `bench.llm.real` chỉ biết 5 web đó. Trên mock site chưa có công cụ sinh script, nên kiểm tra chéo trên mock site chỉ chạy được `none`, hoặc `actions` bản cũ (gợi ý code, `bench.llm.run --modes actions`).
