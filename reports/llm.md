# Báo cáo trục LLM & cache

Sinh tự động bởi `uv run python -m bench.llm.report` ngày 25/11/2026 từ `results/llm/`. Không có số nhập tay.

- **Trục chính: 5 web nhà hàng thật**, dừng trước nút đặt, sau lớp chặn gửi đơn (`bench/llm/guard.py`). Dữ liệu: `results/llm/real/combo.jsonl`. Mock site chỉ là phụ lục (mục 7).
- Runtime: Chrome local (`bench/llm/chrome.py`, cùng cờ với `chrome_local` cộng 3 cờ chống che cửa sổ). Mỗi web 5 vòng; p95 tính nearest-rank trên lượt gộp, nên gần bằng giá trị lớn nhất.
- Tổng đã tiêu cho trục LLM (mọi file trong `results/llm/`): **$1.7093**.
- Lượt `void` (hết hạn mức API) bị loại. Lượt `unscored` (lỗi API, hoặc harness không đọc được ô select ở Lẩu Wang) không tính đúng/sai, nhưng **vẫn tính tiền** vào $/success.

## 1. Cổng loại (`cache_mode = none`, web thật)

| Model | Lượt (chấm được) | Success ≥ 80% | 0 wrong_data | Không chấm được | Dừng đúng ở OTP (mock s5) | Kết quả |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | 25 (23) | ✅ 23/23 (100%) | ✅ 0 | 2 (trong đó ghi `wrong_data`: 2) | ✅ 10/10 | **qua** |
| gemini-3.5-flash-lite | 24 (16) | ✅ 14/16 (88%) | ❌ 1 | 8 (trong đó ghi `wrong_data`: 2) | — chưa đo | loại |

- ⚠️ `claude-haiku-5-5` qua cổng theo cách chấm hiện tại. Nếu tính cả 2 lượt Lẩu Wang mà harness ghi `wrong_data` nhưng không đọc được ô select (form đọc ra thiếu ô giờ và ô cơ sở), thì **trượt cổng 0 wrong_data**. Xem mục 8.

## 2. Chấm điểm (model qua cổng)

| Model | $/success | p95 | Success | Điểm $/success (40) | Điểm p95 (35) | Điểm success (25) | Tổng |
|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | $0.0045 | 83.5 s | 100% | 100 | 100 | 100 | **100.0** |
| gemini-3.5-flash-lite (loại ở cổng) | $0.0496 | 126.0 s | 88% | — | — | — | — |

**Model thắng: `claude-haiku-5-5`.** Chỉ 1 model qua cổng nên điểm mặc định 100.

## 3. Chế độ cache

Trên web thật, `actions` là **cache quy trình**: từ một lượt `none` thành công, sinh một script Playwright có tham số (`results/llm/real/scripts/`). Lượt sau chạy script, **không gọi LLM**; script tự từ chối (`UNAVAILABLE`) khi không khớp được dữ liệu, lúc đó mới gọi LLM chạy chay.

| Cách | Success | $/lượt | p50 | p95 | Chênh success so với `none` |
|---|---|---|---|---|---|
| `none` — claude-haiku-5-5 chạy chay | 23/23 (100%) | $0.0041 | 45.1 s | 83.5 s | — |
| `actions` — script qua browser-use | 25/25 (100%) | $0.0000 | 22.6 s | 40.1 s | +0 điểm % |
| `actions` — script chạy thẳng trên CDP | 25/25 (100%) | $0.0000 | 8.5 s | 16.4 s | +0 điểm % |

**Chế độ cache thắng: `actions` — script chạy thẳng trên CDP** (rẻ nhất mà success không thấp hơn `none` quá 5 điểm %; hòa tiền thì lấy p95 thấp hơn).

- Đổi dữ liệu khách (ngày/giờ/số người khác) trên script: 48/58 đúng, 10 script tự từ chối (báo `UNAVAILABLE`, chuyển sang LLM), **0 điền sai mà không báo**.
- Thử cache hỏng: script phát hiện lỗi 5/5; claude-haiku-5-5 chạy chay cứu được 4/5.
- `session` (nạp lại cookie): chưa đo trên web thật.

**Điểm hòa vốn** `N* = chi phí học ÷ (chi phí lượt none − chi phí lượt cache)`, theo từng web:

| Web | Chi phí học + sinh script | Tiết kiệm $/lượt | N* (lượt) |
|---|---|---|---|
| lauphan | $0.0089 | $0.0031 | **3** |
| tong | $0.0296 | $0.0031 | **10** |
| chaoxian | $0.0089 | $0.0032 | **3** |
| lauwang | $0.0129 | $0.0061 | **3** |
| kingbbq | $0.0132 | $0.0038 | **4** |

## 4. Các lượt `wrong_data` và sai ở trường nào

| Model | Web | Vòng | Cách | Trường sai | Được chấm? |
|---|---|---|---|---|---|
| claude-haiku-5-5 | lauwang | 1 | cold | time | không — form reader could not read the widget selects |
| gemini-3.5-flash-lite | tong | 3 | cold | time | có |
| gemini-3.5-flash-lite | lauwang | 3 | cold | time | không — form reader could not read the widget selects |
| claude-haiku-5-5 | lauwang | 5 | cold | time | không — form reader could not read the widget selects |
| gemini-3.5-flash-lite | lauwang | 5 | cold | time | không — form reader could not read the widget selects |

Mọi lượt `wrong_data` đều sai ở trường **giờ**. Đây là rủi ro chính cho module đặt bàn phía sau.

## 5. Kết luận cho Agent 1 (M4) và pipeline

- Model thắng: **`claude-haiku-5-5`** (`get_llm()` mặc định trỏ vào model này).
- Chế độ cache thắng: **`actions` — script chạy thẳng trên CDP**, cùng LLM chạy chay khi script từ chối hoặc lỗi.
- Xét lại khi: có model mới, giá đổi trên 30%, success thật dưới 80%, hoặc có key Gemini/xAI để đo đủ ứng viên.

## 6. Chi tiết web thật

Sinh bởi `bench.llm.combo_report`, cùng dữ liệu.

### Thời gian (s), chỉ lượt thành công

| Cách | n thành công/tổng | p50 | p95 | $/lượt TB | $/thành công | bước p50 | cpu TB |
|---|---|---|---|---|---|---|---|
| Claude Haiku chay | 23/23 {}; không chấm: {'form reader could not read the widget selects': 2} | 45.1 | 83.5 | 0.0041 | 0.0045 | 6 | 93 |
| Gemini flash-lite chay | 14/16 {'failed': 1, 'wrong_data': 1}; không chấm: {'form reader could not read the widget selects': 2, 'api error': 6} | 90.6 | 126.0 | 0.0289 | 0.0496 | 18 | 78 |
| Replay qua browser-use | 25/25 {}; không chấm: {} | 22.6 | 40.1 | 0.0000 | 0.0000 | 0 | 95 |
| Script chạy thẳng, Chrome mở sẵn | 25/25 {}; không chấm: {} | 8.5 | 16.4 | 0.0000 | 0.0000 | 0 | 92 |

### p50 theo web (s), vòng 1-2 (mọi cách cùng có)

| Web | Claude Haiku chay | Gemini flash-lite chay | Replay qua browser-use | Script chạy thẳng, Chrome mở sẵn |
|---|---|---|---|---|
| lauphan | 77.8, 38.7 | 110.1, 78.7 | 21.7, 17.0 | 9.2, 5.9 |
| tong | 38.4, 41.2 | 85.7, 93.6 | 38.4, 30.6 | 14.0, 8.4 |
| chaoxian | 34.3, 48.3 | 124.3✗failed, 108.6 | 10.5, 22.3 | 4.4, 6.0 |
| lauwang | 91.1✗wrong_data, 61.3 | 91.0, 118.7 | 21.6, 23.3 | 3.5, 19.9 |
| kingbbq | 45.8, 34.7 | 65.7, 54.6 | 21.7, 21.1 | 10.5, 12.1 |

### Phân rã thời gian (TB, lượt thành công; s)

| Cách | mở Chrome (ngoài total) | total | khởi động agent | LLM | số lần gọi LLM | phần còn lại |
|---|---|---|---|---|---|---|
| Claude Haiku chay | 9.4 | 51.0 | 13.6 | 18.4 | 7.6 | 19.0 |
| Gemini flash-lite chay | 6.0 | 90.6 | 14.0 | 66.0 | 17.4 | 10.6 |
| Replay qua browser-use | 6.7 | 24.6 | 10.9 | 0.0 | 0.0 | 13.7 |

Replay: cell script TB 13.7s; nav load TB 6.0s
Chạy thẳng: script TB 8.2s; nav load TB 4.4s

### Độ đúng khi đổi dữ liệu (chạy thẳng)

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

### Cache hỏng

| Web | phát hiện (s) | kết quả script | Claude cứu (s) | kết quả | $ |
|---|---|---|---|---|---|
| lauphan | 9.5 | failed Error: CDPSession.send: Protocol error (DOM.describeNode): C | 47.8 | success | 0.0027 |
| tong | 11.8 | blocked RuntimeError: UNAVAILABLE: không thấy ô số điện thoại (line  | 43.1 | success | 0.0028 |
| chaoxian | 6.4 | failed RuntimeError: JS error: TypeError: Cannot read properties of | 42.0 | success | 0.0033 |
| lauwang | 8.1 | blocked RuntimeError: UNAVAILABLE: không tìm thấy ô số điện thoại (l | 129.3 | failed | 0.0132 |
| kingbbq | 16.9 | failed RuntimeError: JS error: TypeError: Cannot read properties of | 60.7 | success | 0.0037 |

### Hòa vốn (so với Haiku chay)

| Web | học + sinh/sửa $ | s | tiết kiệm $/lượt | tiết kiệm s/lượt | N$ | Ngiây |
|---|---|---|---|---|---|---|
| lauphan | 0.0089 | 109 | 0.0031 | 53.7 | 3 | 3 |
| tong | 0.0296 | 346 | 0.0031 | 30.5 | 10 | 12 |
| chaoxian | 0.0089 | 158 | 0.0032 | 35.7 | 3 | 5 |
| lauwang | 0.0129 | 132 | 0.0061 | 66.6 | 3 | 2 |
| kingbbq | 0.0132 | 145 | 0.0038 | 35.2 | 4 | 5 |

### An toàn
POST được qua: ['chaoxian.com.vn/dat-ban #loadCosoInfo', 'lauphan.com/dat-ban #loadCosoInfo', 'tong.com.vn/dat-ban #loadCosoInfo']
Lượt có dữ liệu khách bị chặn: []
Chi phí combo: {'claude-haiku-5-5': 0.2097, 'none': 0.0, 'gemini-3.5-flash-lite': 0.6946}

## 7. Phụ lục: mock site (23/11, trước khi đổi hướng)

| Model | Cache | Task | Lượt | Success | wrong_data | $/lượt | p50 | p95 | Bước p50 |
|---|---|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | `actions` | 4 | 20 | 20/20 | 0 | $0.0042 | 69.2 s | 97.9 s | 7 |
| claude-haiku-5-5 | `none` | 10 | 50 | 50/50 | 0 | $0.0068 | 49.5 s | 103.8 s | 13 |

`actions` trên mock site là bản cũ (gợi ý code đưa vào prompt, LLM vẫn chạy), dừng sau 4/10 task khi chuyển sang web thật.

## 8. Chưa kiểm chứng

- **2 lượt `claude-haiku-5-5` (lauwang, vòng 1, 5)**: harness ghi `wrong_data` (sai time), nhưng xếp `unscored` vì bộ đọc form không đọc được widget. **Chưa chứng minh** model đã chọn đúng. Cần chụp màn hình hoặc đọc lại widget ở lần đo sau.
- **2 lượt `gemini-3.5-flash-lite` (lauwang, vòng 3, 5)**: harness ghi `wrong_data` (sai time), nhưng xếp `unscored` vì bộ đọc form không đọc được widget. **Chưa chứng minh** model đã chọn đúng. Cần chụp màn hình hoặc đọc lại widget ở lần đo sau.
- Sonnet 5.5 chưa đo trên web thật; Grok chưa đo (không có credit xAI). Lượt lỗi API (không chấm): {'claude-haiku-5-5': 0, 'gemini-3.5-flash-lite': 6}.
- Mỗi web chỉ 5 vòng (hợp đồng gốc: 11), ngân sách $1,80; p95 gần bằng max.
- CPU máy đo rất cao lúc đo (có RPA khác chạy song song, máy Windows): số giây chỉ dùng để so sánh tương đối.
- Lượt `none` không đi tới bước OTP trên web thật; cổng OTP lấy từ mock `s5_otp`.
- Chưa thử gửi đơn thật (cố ý). Bước bấm nút đặt và OTP của nhà hàng thật chưa được đo.
