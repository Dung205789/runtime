# Trạng thái — Agent 2 (LLM & cache)

Cập nhật 2026-11-24. Nhánh `agent2-llm`, chưa merge vào `main`.

- **Đang làm:** bài đo gộp trên 5 web nhà hàng thật đã đủ 5 vòng, kết quả ở `results/llm_snapshot_20261124/SUMMARY.md`. Chờ người dùng chốt model và chế độ cache; chưa có `reports/llm.md`.
- **Mốc đã xong:** M1, M2. M3 đang chạy và đã đổi hướng theo yêu cầu người dùng, xem `docs/CHANGES.md`.
- **Mock site:** Haiku 5.5 không cache 50/50 lượt đúng; cache gợi ý 20/20 (4/10 task) rồi dừng theo yêu cầu. Sonnet và Grok chưa đo.
- **Chạy lại:**
  - `python -m bench.llm.guard_check` và `python -m bench.llm.guard_check_direct`: kiểm chứng lớp chặn, bắt buộc trước khi chạy web thật.
  - `python -m bench.llm.combo --phase 1,2 --reps 5 --busy-ok`: đo, chạy tiếp được khi bị ngắt. Cần dữ liệu học từ `python -m bench.llm.real --learn-only`.
  - `python -m bench.llm.combo_report`: tổng hợp số.
- **Agent 1 cần biết:** đừng dùng các ghi chú cũ về telemetry "+70 giây"; chưa được chứng minh. Đề xuất cờ Chrome ở `docs/CHANGES.md`.
