# Kết quả tạm thời — trục LLM & cache (24/11/2026)

**Bài đo đang chạy, chưa phải số cuối.** Sinh bởi `python -m bench.llm.combo_report`, chỉ đọc `combo.jsonl` (5 web nhà hàng thật, dừng trước nút đặt).

- CPU máy rất cao trong lúc đo (RPA khác chạy song song): so sánh tương đối được, số giây tuyệt đối chưa dùng làm số chính thức.
- Claude vòng 3 và một phần vòng 4 chạy lệch giờ với các cách khác; so sánh sạch nhất là vòng 1-2.
- Mỗi web tối đa 5 lượt; p95 tính trên lượt gộp.
- Chi phí sinh script ở bảng hòa vốn chưa gồm các lượt hỏng do lỗi harness.
- Dòng có `versions.void` hoặc `versions.invalid` trong dữ liệu là lượt bị loại, giữ lại để đối chiếu.

Số lượt đã có theo (cách, model): cold/claude-haiku-5-5 vòng 1: 5, cold/claude-haiku-5-5 vòng 2: 5, cold/claude-haiku-5-5 vòng 3: 5, cold/claude-haiku-5-5 vòng 4: 5, cold/claude-haiku-5-5 vòng 5: 2, cold/gemini-3.5-flash-lite vòng 1: 5, cold/gemini-3.5-flash-lite vòng 2: 5, cold/gemini-3.5-flash-lite vòng 3: 5, cold/gemini-3.5-flash-lite vòng 4: 5, cold/gemini-3.5-flash-lite vòng 5: 1, direct/none vòng 1: 5, direct/none vòng 2: 5, direct/none vòng 3: 5, direct/none vòng 4: 5, direct/none vòng 5: 2, replay/none vòng 1: 5, replay/none vòng 2: 5, replay/none vòng 3: 5, replay/none vòng 4: 5, replay/none vòng 5: 2

## Thời gian (s), chỉ lượt thành công

| Cách | n thành công/tổng | p50 | p95 | $/lượt TB | $/thành công | bước p50 | cpu TB |
|---|---|---|---|---|---|---|---|
| Claude Haiku chay | 21/22 {'wrong_data': 1} | 45.8 | 83.5 | 0.0040 | 0.0042 | 7 | 93 |
| Gemini flash-lite chay | 14/21 {'failed': 5, 'wrong_data': 2} | 90.6 | 126.0 | 0.0312 | 0.0468 | 18 | 81 |
| Replay qua browser-use | 22/22 {} | 22.9 | 40.1 | 0.0000 | 0.0000 | 0 | 96 |
| Script chạy thẳng, Chrome mở sẵn | 22/22 {} | 8.5 | 16.4 | 0.0000 | 0.0000 | 0 | 93 |

## p50 theo web (s), vòng 1-2 (mọi cách cùng có)

| Web | Claude Haiku chay | Gemini flash-lite chay | Replay qua browser-use | Script chạy thẳng, Chrome mở sẵn |
|---|---|---|---|---|
| lauphan | 77.8, 38.7 | 110.1, 78.7 | 21.7, 17.0 | 9.2, 5.9 |
| tong | 38.4, 41.2 | 85.7, 93.6 | 38.4, 30.6 | 14.0, 8.4 |
| chaoxian | 34.3, 48.3 | 124.3✗failed, 108.6 | 10.5, 22.3 | 4.4, 6.0 |
| lauwang | 91.1✗wrong_data, 61.3 | 91.0, 118.7 | 21.6, 23.3 | 3.5, 19.9 |
| kingbbq | 45.8, 34.7 | 65.7, 54.6 | 21.7, 21.1 | 10.5, 12.1 |

## Phân rã thời gian (TB, lượt thành công; s)

| Cách | mở Chrome (ngoài total) | total | khởi động agent | LLM | số lần gọi LLM | phần còn lại |
|---|---|---|---|---|---|---|
| Claude Haiku chay | 9.9 | 52.4 | 13.9 | 18.8 | 7.7 | 19.6 |
| Gemini flash-lite chay | 6.0 | 90.6 | 14.0 | 66.0 | 17.4 | 10.6 |
| Replay qua browser-use | 7.1 | 26.1 | 11.7 | 0.0 | 0.0 | 14.4 |

Replay: cell script TB 14.4s; nav load TB 6.2s
Chạy thẳng: script TB 8.5s; nav load TB 4.6s

## Độ đúng khi đổi dữ liệu (chạy thẳng)

| Web | đúng | từ chối | điền sai mà không báo | lỗi có báo |
|---|---|---|---|---|
| lauphan | 10 | 2 | 0 | 0 |
| tong | 6 | 4 | 0 | 0 |
| chaoxian | 10 | 2 | 0 | 0 |
| lauwang | 11 | 1 | 0 | 0 |
| kingbbq | 11 | 1 | 0 | 0 |
- lauphan c11 blocked: RuntimeError: UNAVAILABLE: không có giờ 18:15 (line 154) sai=['name', 'phone', 'time']
- lauphan c12 blocked: RuntimeError: UNAVAILABLE: không có giờ 03:00 (line 154) sai=['name', 'phone', 'time']
- tong c03 blocked: RuntimeError: UNAVAILABLE: không có lựa chọn đúng cho giờ (line 73) sai=['name', 'phone', 'time']
- tong c07 blocked: RuntimeError: UNAVAILABLE: không có lựa chọn đúng cho giờ (line 73) sai=['name', 'phone', 'time']
- tong c11 blocked: RuntimeError: UNAVAILABLE: không có lựa chọn đúng cho giờ (line 73) sai=['name', 'phone', 'time']
- tong c12 blocked: RuntimeError: UNAVAILABLE: không có lựa chọn đúng cho giờ (line 73) sai=['name', 'phone', 'time']
- chaoxian c11 blocked: RuntimeError: UNAVAILABLE: không có giờ 18:15 (line 41) sai=['name', 'phone', 'time']
- chaoxian c12 blocked: RuntimeError: UNAVAILABLE: không có giờ 03:00 (line 41) sai=['name', 'phone', 'time']
- lauwang c12 blocked: RuntimeError: UNAVAILABLE: giờ 03:00 (NOOPT) (line 56) sai=['name', 'phone', 'time']
- kingbbq c12 blocked: RuntimeError: UNAVAILABLE: không có giờ khớp chính xác (line 42) sai=['time']

## Cache hỏng

| Web | phát hiện (s) | kết quả script | Claude cứu (s) | kết quả | $ |
|---|---|---|---|---|---|
| lauphan | 9.5 | failed Error: CDPSession.send: Protocol error (DOM.describeNode): C | 47.8 | success | 0.0027 |
| tong | 11.8 | blocked RuntimeError: UNAVAILABLE: không thấy ô số điện thoại (line  | 43.1 | success | 0.0028 |
| chaoxian | 6.4 | failed RuntimeError: JS error: TypeError: Cannot read properties of | 42.0 | success | 0.0033 |
| lauwang | 8.1 | blocked RuntimeError: UNAVAILABLE: không tìm thấy ô số điện thoại (l | 129.3 | failed | 0.0132 |
| kingbbq | 16.9 | failed RuntimeError: JS error: TypeError: Cannot read properties of | 60.7 | success | 0.0037 |

## Hòa vốn (so với Haiku chay)

| Web | học + sinh/sửa $ | s | tiết kiệm $/lượt | tiết kiệm s/lượt | N$ | Ngiây |
|---|---|---|---|---|---|---|
| lauphan | 0.0089 | 109 | 0.0031 | 53.7 | 3 | 3 |
| tong | 0.0296 | 346 | 0.0031 | 30.5 | 10 | 12 |
| chaoxian | 0.0089 | 158 | 0.0034 | 36.2 | 3 | 5 |
| lauwang | 0.0129 | 132 | 0.0061 | 65.4 | 3 | 3 |
| kingbbq | 0.0132 | 145 | 0.0040 | 37.8 | 4 | 4 |

## An toàn
POST được qua: ['chaoxian.com.vn/dat-ban #loadCosoInfo', 'lauphan.com/dat-ban #loadCosoInfo', 'tong.com.vn/dat-ban #loadCosoInfo']
Lượt có dữ liệu khách bị chặn: []
Chi phí combo: {'claude-haiku-5-5': 0.1946, 'none': 0.0, 'gemini-3.5-flash-lite': 0.655}
