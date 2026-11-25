# Kết quả — trục LLM & cache (24/11/2026)

Sinh bởi `python -m bench.llm.combo_report`, chỉ đọc `combo.jsonl` (5 web nhà hàng thật, dừng trước nút đặt). Đủ 5 vòng.

- CPU máy rất cao trong lúc đo (RPA khác chạy song song): so sánh tương đối được, số giây tuyệt đối chưa dùng làm số chính thức.
- Thời gian của Claude, Gemini, replay không gồm mở Chrome. `direct` chạy trên Chrome vừa có một lượt `warm` cùng web (trình duyệt đã có cache tĩnh); `warm` là lượt đầu trên Chrome mới mở.
- Claude vòng 3 và một phần vòng 4 chạy lệch giờ; vòng 1-2 chạy xen kẽ. Đợt đo bị gián đoạn 339 phút trong vòng 5.
- `versions.unscored`: lượt lỗi API, hoặc Lẩu Wang mà harness không đọc được ô select của widget; không tính đúng hay sai. `versions.void`/`invalid`: lượt bị loại.
- Chi phí sinh script ở bảng hòa vốn chưa gồm các lượt hỏng do lỗi harness.
- Mỗi web 5 lượt; p95 tính trên lượt gộp.

## Thời gian (s), chỉ lượt thành công

| Cách | n thành công/tổng | p50 | p95 | $/lượt TB | $/thành công | bước p50 | cpu TB |
|---|---|---|---|---|---|---|---|
| Claude Haiku chay | 23/23 {}; không chấm: {'form reader could not read the widget selects': 2} | 45.1 | 83.5 | 0.0041 | 0.0045 | 6 | 93 |
| Gemini flash-lite chay | 14/16 {'failed': 1, 'wrong_data': 1}; không chấm: {'form reader could not read the widget selects': 2, 'api error': 6} | 90.6 | 126.0 | 0.0289 | 0.0496 | 18 | 78 |
| Replay qua browser-use | 25/25 {}; không chấm: {} | 22.6 | 40.1 | 0.0000 | 0.0000 | 0 | 95 |
| Script chạy thẳng, Chrome mở sẵn | 25/25 {}; không chấm: {} | 8.5 | 16.4 | 0.0000 | 0.0000 | 0 | 92 |

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
| Claude Haiku chay | 9.4 | 51.0 | 13.6 | 18.4 | 7.6 | 19.0 |
| Gemini flash-lite chay | 6.0 | 90.6 | 14.0 | 66.0 | 17.4 | 10.6 |
| Replay qua browser-use | 6.7 | 24.6 | 10.9 | 0.0 | 0.0 | 13.7 |

Replay: cell script TB 13.7s; nav load TB 6.0s
Chạy thẳng: script TB 8.2s; nav load TB 4.4s

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
| chaoxian | 0.0089 | 158 | 0.0032 | 35.7 | 3 | 5 |
| lauwang | 0.0129 | 132 | 0.0061 | 66.6 | 3 | 2 |
| kingbbq | 0.0132 | 145 | 0.0038 | 35.2 | 4 | 5 |

## An toàn
POST được qua: ['chaoxian.com.vn/dat-ban #loadCosoInfo', 'lauphan.com/dat-ban #loadCosoInfo', 'tong.com.vn/dat-ban #loadCosoInfo']
Lượt có dữ liệu khách bị chặn: []
Chi phí combo: {'claude-haiku-5-5': 0.2097, 'none': 0.0, 'gemini-3.5-flash-lite': 0.6946}
