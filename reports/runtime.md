# Báo cáo runtime trình duyệt (M3 — Agent 1)

Đo ngày 23/11/2026 trên 5 runtime: Chrome cài trên máy (`chrome_local`), Steel tự host bằng Docker (`steel_selfhost`), Steel Cloud, Browser Use Cloud và Kernel. Mọi lượt dùng agent browser-use 1.0.8 với LLM cố định `claude-haiku-5-5`, `cache_mode = none` (profile trắng), trên 5 mock site của repo. Tổng cộng 910 lượt đo, chưa tính 10 lượt pilot.

Các bảng số trong file này do `uv run python -m bench.runtime.report` tính lại từ `results/runtime/*.jsonl`, không nhập tay. Chạy lại lệnh đó sẽ ghi đè các bảng (khối `AUTO`), phần chữ giữ nguyên.

## 1. Tóm tắt

**Local (Chrome vs Steel self-host):** hai runtime ngang nhau về tốc độ, độ ổn định và chi phí, cả hai đều thành công 100%. Chrome nhẹ hơn rõ. Đo cùng một cách (chỉ tính trình duyệt), Chrome khoảng 220 MB mỗi phiên, còn Chromium của Steel 350–530 MB. Tính cả container Steel thì khoảng 830 MB mỗi phiên. Hai runtime khác nhau ở các điểm sau:
- **Live View:** Steel self-host có Live View gõ được. Image gốc của Steel bị lỗi, harness dùng image đã vá 1 dòng (mục 5). Chrome không có Live View.
- **Anti-bot:** trang kiểm tra bot BrowserScan nhận ra Steel self-host là robot, còn Chrome qua.

**Cloud (Steel Cloud vs Browser Use Cloud vs Kernel):**
- Steel Cloud nhanh nhất và rẻ nhất trong ba runtime cloud, nhưng **trượt bài giữ phiên 15 phút** vì gói miễn phí (Launch) giới hạn mỗi phiên 15 phút.
- Kernel nhanh gần bằng Steel Cloud, nhưng tiền trình duyệt đắt gấp khoảng 5 lần.
- Browser Use Cloud chậm nhất và có 1 lượt bị chặn trên site chống bot.
- Cả ba runtime cloud đều có Live View gõ được.

**Theo thang điểm của hợp đồng (mục 10):** `chrome_local` đứng đầu với 88,9/100, `steel_selfhost` thứ hai với 84,0. Hai runtime cloud qua cổng loại đứng sau xa: Browser Use 39,0, Kernel 36,6.
- Hai runtime đầu chênh 4,9 điểm, sát ngưỡng 5 điểm. Theo hợp đồng thì chọn runtime đơn giản hơn để vận hành, tức `chrome_local`.
- Steel self-host thua ở RAM. Kết quả này vẫn giữ sau khi đo lại công bằng, chỉ tính trình duyệt (mục 4). Nếu bỏ chỉ số RAM, Steel self-host được 98,8, hơn Chrome khoảng 12 điểm, và thắng nhờ Live View.
- Vì vậy cần nhóm trả lời hai câu hỏi:
  1. Có cần Live View cho khách gõ OTP không? Chrome không có sẵn, phải tự dựng.
  2. Có chấp nhận dùng image Steel tự vá không? Bản vá chỉ 1 dòng, nhưng phải giữ cho tới khi Steel sửa lỗi.
- Quyết định cuối nằm ở `reports/DECISION.md` (M4), sau khi kiểm tra chéo với LLM thắng của Agent 2.

**Lưu ý khi đọc số của cloud:** máy đo nằm xa trình duyệt cloud. Mỗi lệnh CDP giữa máy đo và trình duyệt cloud mất khoảng 240 ms, so với khoảng 2 ms khi chạy local (mục 3). Thời gian lượt đặt của cloud vì thế dài hơn local khoảng 2,5 lần. Phần lớn chênh lệch đó do khoảng cách mạng, không phải do bản thân trình duyệt. So sánh **giữa ba runtime cloud với nhau** vẫn công bằng, vì độ trễ của chúng gần bằng nhau (235–251 ms).

## 2. Đo như thế nào

| Phép đo | Cách làm | Số lượt mỗi runtime |
|---|---|---|
| Cold start | `start()` → có CDP (tạo phiên) → trang `s1_simple` tải xong | 11 (lượt đầu là warm-up) |
| Lượt đặt bàn | 10 task × 11 lượt, 1 phiên; chấm bằng `/_bench/bookings`, không để LLM tự báo | 110 |
| Song song | 50 lượt ở mức 3 phiên, 10 lượt ở mức 5 phiên | 60 |
| Giữ phiên | Trên `s5_otp`, agent hỏi OTP, khách trả lời sau 900 s, rồi agent làm tiếp | 1 |
| Anti-bot | 20 lượt đặt trên `s4_guarded` (lấy từ lượt đặt bàn), cộng 3 trang kiểm tra bot, chỉ đọc | 20 + 3 |
| Live View | Mở URL Live View trong một trình duyệt khác, bấm vào ô OTP và gõ | 1 |
| Độ trễ mạng | 20 lệnh CDP và 10 lần tải trang, không dùng LLM | 1 đợt |

- Lượt warm-up (lượt 0) bị loại khỏi thống kê. Mọi chỉ số báo p50 và p95.
- "Thời gian lượt đặt" không tính 20 s giả lập khách gửi OTP.
- Runtime cloud truy cập mock site (chạy trên máy đo) qua Cloudflare Quick Tunnel. Endpoint chấm điểm `/_bench/*` bị chặn khi đi qua tunnel, nên agent không đọc lén được.
- Máy đo: Windows 11, AMD 12 nhân, 31 GB RAM. Agent browser-use chạy trên máy đo cho mọi runtime.

## 3. Thời gian

<!-- AUTO:time -->
| Runtime | Success (1 phiên) | Lượt đặt p50 | Lượt đặt p95 | Bước p50 | Tạo phiên p50 | Tạo phiên p95 | Cold start p50 | Cold start p95 |
|---|---|---|---|---|---|---|---|---|
| `chrome_local` | 100/100 | 22 s | 37 s | 10 | 0.40 s | 0.43 s | 0.55 s | 0.63 s |
| `steel_selfhost` | 100/100 | 26 s | 35 s | 10 | 0.78 s | 0.81 s | 0.97 s | 1.00 s |
| `steel_cloud` | 100/100 | 56 s | 76 s | 10 | 0.82 s | 1.98 s | 3.31 s | 5.32 s |
| `browser_use_cloud` | 99/100 | 71 s | 106 s | 11 | 1.26 s | 1.37 s | 4.69 s | 5.01 s |
| `kernel` | 100/100 | 57 s | 79 s | 10 | 0.95 s | 0.99 s | 3.37 s | 3.52 s |
<!-- /AUTO:time -->

- **Cold start** là thời gian từ lúc tạo phiên đến khi trang đầu tải xong. Local dưới 1 s. Cloud 3–5 s, trong đó phần lớn là tải trang qua tunnel.
- Hai runtime local mất 22–26 s mỗi lượt. Steel self-host chậm hơn khoảng 4 s ở p50, có thể vì mỗi lượt khởi động trên một container mới. Ở p95 thì Steel lại nhanh hơn (35 s so với 37 s). Ba runtime cloud mất 56–71 s, dù số bước của agent gần như nhau (10–11 bước).

**Độ trễ mạng, đo riêng để giải thích chênh lệch:**

<!-- AUTO:latency -->
| Runtime | CDP máy đo ↔ trình duyệt, ms (p50 / p95) | Trình duyệt → mock site, TTFB ms (p50 / p95) | Đường tới mock site | Lượt đặt p50 (để đối chiếu) |
|---|---|---|---|---|
| `chrome_local` | 2 / 5 | 1 / 2 | localhost | 22 s |
| `steel_selfhost` | 2 / 2 | 2 / 2 | localhost | 26 s |
| `steel_cloud` | 235 / 242 | 264 / 441 | qua tunnel | 56 s |
| `browser_use_cloud` | 251 / 316 | 270 / 556 | qua tunnel | 71 s |
| `kernel` | 243 / 267 | 265 / 586 | qua tunnel | 57 s |

HTTP từ máy đo: localhost p50 1 ms; qua tunnel p50 107 ms, p95 180 ms. Đo lúc 2026-11-23T15:04 UTC.
<!-- /AUTO:latency -->

- Mỗi bước, agent gửi nhiều lệnh CDP: chụp màn hình, lấy DOM, bấm, gõ. Với local mỗi lệnh mất khoảng 2 ms, với cloud khoảng 240 ms. Riêng tunnel chỉ ảnh hưởng lúc tải trang và gọi `fetch`, mỗi lần khoảng 100–260 ms.
- **Ước tính:** chênh lệch khoảng 34 s mỗi lượt giữa cloud và local, chia cho khoảng 10 bước, ra khoảng 3,4 s mỗi bước, tương đương khoảng 14 lượt đi-về mạng mỗi bước. Phép tính này chỉ để thấy cỡ độ lớn, không phải số đo trực tiếp.
- **Khi chạy thật:** nếu server chạy agent đặt cùng vùng với trình duyệt cloud, độ trễ CDP sẽ giảm mạnh, và thời gian cloud có thể gần với local. Điều này **chưa kiểm chứng** (mục 9).

Thời gian p50 theo từng task, đơn vị giây:

<!-- AUTO:per_task -->
| Runtime (giây, p50) | t01 | t02 | t03 | t04 | t05 | t06 | t07 | t08 | t09 | t10 |
|---|---|---|---|---|---|---|---|---|---|---|
| `chrome_local` | 17 | 17 | 22 | 19 | 34 | 31 | 20 | 19 | 30 | 22 |
| `steel_selfhost` | 22 | 21 | 24 | 25 | 31 | 33 | 24 | 24 | 30 | 26 |
| `steel_cloud` | 54 | 59 | 52 | 48 | 53 | 53 | 60 | 55 | 62 | 72 |
| `browser_use_cloud` | 76 | 81 | 67 | 66 | 48 | 62 | 55 | 84 | 92 | 89 |
| `kernel` | 49 | 59 | 50 | 49 | 53 | 58 | 56 | 59 | 70 | 66 |
<!-- /AUTO:per_task -->

## 4. Tài nguyên

<!-- AUTO:resources -->
| Runtime | RAM đỉnh MB, 1 phiên (p50 / p95) | 3 song song | 5 song song | CPU p50 / lượt | Đo cái gì |
|---|---|---|---|---|---|
| `chrome_local` | 218 / 227 | 215 / 225 | 184 / 230 | 7.2 s | USS cây tiến trình Chrome của phiên |
| `steel_selfhost` | 531 / 538 | 403 / 424 | 348 / 359 | 4.5 s | PSS các tiến trình Chromium trong container (cả container, có Node.js: p50 832 MB) |
| `steel_cloud` | 417 / 428 | 535 / 571 | 675 / 676 | 7.2 s | phía client: Python harness + tiến trình con |
| `browser_use_cloud` | 420 / 455 | 524 / 557 | 665 / 696 | 11.0 s | phía client: Python harness + tiến trình con |
| `kernel` | 404 / 418 | 539 / 552 | 689 / 693 | 7.6 s | phía client: Python harness + tiến trình con |
<!-- /AUTO:resources -->

**RAM của trình duyệt chỉ đo được ở local.**
- `chrome_local` đo USS của cả cây tiến trình Chrome của phiên. Windows không có PSS, nên dùng USS theo brief.
- `steel_selfhost` đo PSS của riêng các tiến trình Chromium trong container, không tính server Node.js, nginx và page cache. Như vậy cùng phạm vi với Chrome local.
  - Ở mức 1 phiên, mỗi lượt dùng một container mới. Ở mức 3 và 5 phiên, cả loạt container được tạo mới ở đầu bước, rồi mỗi container phục vụ nhiều lượt liền.
  - Chromium của Steel nặng hơn Chrome local:
    - Lượt đầu trên container mới: khoảng 530 MB.
    - Các lượt sau trên cùng container: 350–420 MB.
    - Chrome local: khoảng 220 MB.
  - Cả container (thêm Node.js của Steel) khoảng 830 MB mỗi phiên. Steel self-host chỉ giữ được 1 phiên mỗi container, nên N phiên cần N container, tức cần khoảng N × 830 MB.
  - Chênh USS/PSS: Chrome local đo USS trên Windows, Steel đo PSS trên Linux. PSS lớn hơn USS một ít, do có tính phần thư viện dùng chung. Khoảng chênh này nhỏ hơn nhiều so với mức chênh 130–310 MB ở trên.
  - Lần đo đầu dùng `docker stats` cho cả container, nên bị đội lên (khoảng 870 MB). Số cũ lưu ở `results/runtime/archive/`. Lượt đặt bàn, chạy 3 phiên và 5 phiên song song của Steel self-host đã đo lại toàn bộ theo cách mới. Cách cũ vẫn chạy được bằng `BENCH_STEEL_MEM=docker_stats`.

**Cloud chỉ đo được phía client:** tiến trình Python của harness cùng các tiến trình con. Không có số RAM của trình duyệt trên cloud.
- Ở mức 3 và 5 phiên, các phiên dùng chung một tiến trình Python. Số đo khi đó là tổng của cả tiến trình, không phải RAM mỗi phiên.
- Vì vậy không so RAM cloud với RAM local được. Hợp đồng vẫn chấm điểm RAM cloud theo số phía client, và điều này có lợi cho cloud. Mục 8 có thêm một bảng điểm bỏ RAM để đối chiếu.

**CPU:** phạm vi đo khác nhau giữa các runtime.
- `chrome_local` đo CPU của Chrome, khoảng 7 s mỗi lượt. `steel_selfhost` đo CPU của Chromium trong container, khoảng 4,5 s.
- Ba runtime cloud đo CPU của harness phía client: Steel Cloud và Kernel khoảng 7 s, Browser Use khoảng 11 s.

Vì phạm vi khác nhau, không so CPU giữa local và cloud. Cũng chỉ nên so CPU giữa Chrome và Steel ở mức đại khái: một bên chạy Windows có giao diện, một bên chạy Linux trong container.

## 5. Khả dụng

### Ổn định

<!-- AUTO:stability -->
| Runtime | 3 song song: success | phiên mất (crashed) | timeout | 5 song song: success | Lượt p50 ở 3 song song | ở 5 song song | Mồ côi sau stop() / số lần kiểm |
|---|---|---|---|---|---|---|---|
| `chrome_local` | 50/50 | 0 | 0 | 10/10 | 22 s | 26 s | 0 / 182 |
| `steel_selfhost` | 50/50 | 0 | 0 | 10/10 | 25 s | 27 s | 0 / 182 |
| `steel_cloud` | 50/50 | 0 | 0 | 10/10 | 54 s | 58 s | 0 / 182 |
| `browser_use_cloud` | 50/50 | 0 | 0 | 10/10 | 68 s | 95 s | 0 / 182 |
| `kernel` | 50/50 | 0 | 0 | 10/10 | 57 s | 75 s | 0 / 182 |
<!-- /AUTO:stability -->

- Không runtime nào mất phiên. Sau mỗi `stop()` đều kiểm tra lại, và không còn tiến trình hay phiên mồ côi.
- Ở mức 5 phiên song song, Browser Use và Kernel chậm đi rõ (p50 tăng từ 68 lên 95 s và từ 57 lên 75 s). Ba runtime còn lại gần như không đổi.
- Giới hạn song song của gói đang dùng:

  | Runtime | Gói | Số phiên song song tối đa |
  |---|---|---|
  | Kernel | Developer | 5 |
  | Steel Cloud | Launch | 10 |
  | Browser Use | khi chưa nạp tiền | 10 |

### Giữ phiên 15 phút và Live View

- Giữ phiên: 4/5 runtime đạt.
- **Steel Cloud trượt.**
  - API của gói Launch không nhận `timeout` quá 900 000 ms, tức 15 phút tính từ lúc tạo phiên.
  - Phần agent điền form cộng với 900 s chờ OTP đã vượt 15 phút, nên sau khi chờ, trình duyệt đã bị đóng ("The browser is gone").
  - Đây là **giới hạn của gói**, không phải lỗi trình duyệt. Gói Scale ($250/tháng) cho phiên dài 1 giờ, nhưng chưa thử.

<!-- AUTO:liveview -->
| Runtime | Live View | Trễ từ lúc gõ đến khi trang nhận | Khung hình nhận được |
|---|---|---|---|
| `chrome_local` | không có URL Live View | — | — |
| `steel_selfhost` | có, gõ được vào ô OTP | 4 ms | 19 |
| `steel_cloud` | có, gõ được vào ô OTP | 235 ms | 2 |
| `browser_use_cloud` | có, gõ được vào ô OTP | 235 ms | 37 |
| `kernel` | có, gõ được vào ô OTP | 265 ms | 12 |
<!-- /AUTO:liveview -->

- **Live View của `steel_selfhost`:** image gốc (`ghcr.io/steel-dev/steel-browser`, build 21/11/2026) bị lỗi, khung xem không nhận hình nào. Kết quả của image gốc lưu ở `results/runtime/liveview/steel_selfhost_stock.json`.
  - **Nguyên nhân là lỗi trong server Steel:** phần chia luồng websocket chỉ nhận đường `/v1/sessions/cast`, còn hàm xử lý lại tìm mã phiên trong đường `/v1/sessions/{id}/cast`. Hai phần không khớp nhau, nên lần nào cũng báo "Cast Session cast not found" rồi đóng kết nối.
  - **Đã sửa:**
    - Provider giờ mặc định dùng image `bench-steel-browser:liveview-fix`. Image này build từ đúng bản gốc (ghim theo digest) và chỉ vá 1 dòng trong `casting.handler.js`; xem `bench/providers/steel_patch/Dockerfile`.
    - `up()` tự build image này nếu máy chưa có.
    - Muốn quay về image gốc thì đặt `STEEL_SELFHOST_IMAGE=ghcr.io/steel-dev/steel-browser`.
  - **Kết quả sau khi sửa:** gõ OTP qua Live View chạy được, 19 khung hình. Bảng trên và bảng điểm dùng kết quả này.
  - Bản vá chỉ đụng phần Live View. Các phép đo khác của Steel self-host chạy trên image gốc trước khi vá.
- `chrome_local` không có Live View sẵn. Muốn khách tự nhập OTP qua trình duyệt thì phải tự dựng thêm (ví dụ noVNC hoặc CDP screencast).

### Anti-bot

<!-- AUTO:antibot -->
| Runtime | s4_guarded success | BrowserScan | CreepJS | nowsecure.nl | navigator.webdriver | Hệ điều hành trong UA |
|---|---|---|---|---|---|---|
| `chrome_local` | 20/20 | Normal | like headless 25% · headless 0% · stealth 0% | ô Turnstile chờ bấm | false | Windows NT 10.0 |
| `steel_selfhost` | 20/20 | Robot | like headless 75% · headless 33% · stealth 20% | ô Turnstile chờ bấm | false | X11 |
| `steel_cloud` | 20/20 | Normal | like headless 56% · headless 0% · stealth 0% | ô Turnstile chờ bấm | false | X11 |
| `browser_use_cloud` | 19/20 | Normal | like headless 31% · headless 0% · stealth 0% | ô Turnstile chờ bấm | false | Macintosh |
| `kernel` | 20/20 | Normal | like headless 38% · headless 0% · stealth 0% | ô Turnstile chờ bấm | false | X11 |
<!-- /AUTO:antibot -->

- `s4_guarded` (mock site có JS challenge, honeypot, giới hạn tần suất và chặn `navigator.webdriver`): mọi runtime đều qua cổng 80%. Browser Use có 1 lượt bị chặn vì thiếu cookie challenge (`no_cookie`).
- **BrowserScan nhận `steel_selfhost` là "Robot"**, ở mục Navigator. CreepJS cũng cho nó 33% headless và 20% stealth. Các runtime khác đều "Normal" và 0% headless. Steel self-host vẫn qua `s4_guarded`, nhưng trên site thật có chống bot mạnh thì đây là rủi ro.
- nowsecure.nl hiện ô Cloudflare Turnstile chờ bấm ở **cả 5 runtime**. Harness chỉ đọc, không bấm, nên trang này không phân biệt được các runtime.
- Ảnh chụp ở `results/runtime/antibot/`.

## 6. Chi phí

<!-- AUTO:cost -->
| Runtime | Phiên p50 (gồm chờ OTP) | LLM / 1.000 lượt | Trình duyệt / 1.000 lượt | Tổng / 1.000 lượt | Nguồn giá trình duyệt | Token đọc từ prompt cache |
|---|---|---|---|---|---|---|
| `chrome_local` | 23 s | 3.58 $ | 0.07 $ | 3.64 $ | ước tính: Hetzner CX23 (2 vCPU, 4 GB, €0.0096/giờ) | 88% |
| `steel_selfhost` | 26 s | 3.62 $ | 0.08 $ | 3.70 $ | ước tính: Hetzner CX23 (2 vCPU, 4 GB, €0.0096/giờ) | 88% |
| `steel_cloud` | 57 s | 3.37 $ | 1.71 $ | 5.07 $ | giá dịch vụ (prices.toml) | 88% |
| `browser_use_cloud` | 72 s | 4.99 $ | 1.82 $ | 6.81 $ | giá dịch vụ (prices.toml) | 88% |
| `kernel` | 57 s | 4.33 $ | 8.22 $ | 12.55 $ | giá dịch vụ (prices.toml) | 85% |
<!-- /AUTO:cost -->

- Công thức: `$/1.000 lượt = (tổng chi phí LLM + trình duyệt của mọi lượt) ÷ số lượt success × 1.000`, trên 100 lượt 1 phiên không tính warm-up. LLM tính theo token thật, giá trang chính thức của Haiku 5.5. Prompt cache luôn bật.
- Giá trình duyệt cloud lấy từ `bench/core/prices.toml` (nguồn và ngày tra ghi trong file):

  | Runtime | Giá | Cách tính |
  |---|---|---|
  | Steel Cloud | $0.10/giờ | theo giây |
  | Browser Use | $0.06/giờ | theo phút, tối thiểu 1 phút |
  | Kernel | $0.48/giờ, chế độ headful | theo giây |

  Kernel đắt vì dùng headful để có Live View.
- **Local và self-host là số ƯỚC TÍNH:**
  - Lấy gói VPS nhỏ nhất có RAM ≥ RAM đỉnh p95 của một phiên: Hetzner CX23, 4 GB, €0,0096/giờ chưa VAT ([hetzner.com/cloud/cost-optimized](https://www.hetzner.com/cloud/cost-optimized), tra 23/11/2026). Đổi €1 ≈ $1,10.
  - Nhân với thời gian phiên p50, tức là giả định VPS luôn bận. Thực tế VPS chạy liên tục tốn khoảng €5,99/tháng cho một máy, dù ít khách.
  - Trang Hetzner đang báo gói này hết hàng.
- Ở cả 5 runtime, LLM chiếm phần lớn chi phí, trừ Kernel. LLM của Browser Use đắt hơn khoảng 50% so với Steel Cloud, vì agent đi nhiều bước hơn và tốn nhiều token hơn trên runtime này.
- **Steel Cloud chạy thật gần như chắc chắn cần gói Scale:** để có phiên dài hơn 15 phút và hơn 10 phiên song song. Tức là thêm **$250/tháng cố định**, chưa tính vào bảng trên.

## 7. Steel Cloud: có cần mua gói Scale không

Khi bỏ qua cổng loại (bảng tham khảo ở mục 8), Steel Cloud là runtime cloud tốt nhất, xếp thứ 3 sau hai runtime local. Đề xuất:
- Nếu nhóm chọn **local hoặc self-host**: không cần mua Scale.
- Chỉ khi nhóm **bắt buộc dùng cloud** (ví dụ cần Live View có sẵn và không muốn vận hành server) thì mới đáng mua Scale 1 tháng, để đo lại bài giữ phiên trước khi chốt.

## 8. Cổng loại và bảng điểm (theo hợp đồng mục 10)

<!-- AUTO:gates -->
| Runtime | Nối CDP | 0 phiên mất ở 3 song song | Giữ phiên 15' | s4_guarded ≥ 80% | Kết quả |
|---|---|---|---|---|---|
| `chrome_local` | đạt (10/10) | đạt (0 mất / 50) | đạt (900 s) | đạt (20/20) | **qua** |
| `steel_selfhost` | đạt (10/10) | đạt (0 mất / 50) | đạt (900 s) | đạt (20/20) | **qua** |
| `steel_cloud` | đạt (10/10) | đạt (0 mất / 50) | **trượt** (900 s) | đạt (20/20) | loại |
| `browser_use_cloud` | đạt (10/10) | đạt (0 mất / 50) | đạt (900 s) | đạt (19/20) | **qua** |
| `kernel` | đạt (10/10) | đạt (0 mất / 50) | đạt (900 s) | đạt (20/20) | **qua** |
<!-- /AUTO:gates -->

- "Nối CDP" tính trên 10 lượt cold start không tính warm-up. Thực tế lượt warm-up cũng thành công, tức 11/11.
- "s4_guarded ≥ 80%": hợp đồng ghi "≥ 8/10". Bench chạy 2 task × 10 lượt trên `s4_guarded`, nên tính theo tỷ lệ.

Mỗi chỉ số được quy về 0–100 trong nhóm, tốt nhất 100, kém nhất 0. Các chỉ số dùng để chấm:
- p95 lượt đặt.
- $/1.000 lượt.
- RAM đỉnh p95 ở mức 1 phiên.
- p95 cold start.
- Live View: 100 nếu gõ được, 0 nếu không.

<!-- AUTO:scores -->
**Chính thức (theo hợp đồng mục 10, chỉ runtime qua cổng loại)**

| Runtime | p95 lượt đặt (35) | $/1.000 (30) | RAM/phiên (15) | p95 cold start (10) | Live View (10) | Tổng /100 |
|---|---|---|---|---|---|---|
| `chrome_local` | 97 | 100 | 100 | 100 | 0 | **88.9** |
| `steel_selfhost` | 100 | 99 | 0 | 91 | 100 | **84.0** |
| `browser_use_cloud` | 0 | 64 | 27 | 0 | 100 | **33.3** |
| `kernel` | 38 | 0 | 38 | 34 | 100 | **32.4** |

**Tham khảo: cả 5 runtime, bỏ qua cổng loại**

| Runtime | p95 lượt đặt (35) | $/1.000 (30) | RAM/phiên (15) | p95 cold start (10) | Live View (10) | Tổng /100 |
|---|---|---|---|---|---|---|
| `chrome_local` | 97 | 100 | 100 | 100 | 0 | **88.9** |
| `steel_selfhost` | 100 | 99 | 0 | 92 | 100 | **84.0** |
| `steel_cloud` | 42 | 84 | 35 | 0 | 100 | **55.0** |
| `browser_use_cloud` | 0 | 64 | 27 | 7 | 100 | **34.0** |
| `kernel` | 38 | 0 | 38 | 39 | 100 | **32.8** |

**Tham khảo: cả 5 runtime, bỏ RAM (RAM cloud chỉ đo phía client nên không so được với local)** — tổng quy lại trên 85 điểm trọng số còn lại.

| Runtime | p95 lượt đặt (35) | $/1.000 (30) | RAM/phiên (15) | p95 cold start (10) | Live View (10) | Tổng /100 |
|---|---|---|---|---|---|---|
| `steel_selfhost` | 100 | 99 | — | 92 | 100 | **98.8** |
| `chrome_local` | 97 | 100 | — | 100 | 0 | **86.9** |
| `steel_cloud` | 42 | 84 | — | 0 | 100 | **58.5** |
| `browser_use_cloud` | 0 | 64 | — | 7 | 100 | **35.3** |
| `kernel` | 38 | 0 | — | 39 | 100 | **31.8** |
<!-- /AUTO:scores -->

## 9. Chưa kiểm chứng

- **Thời gian cloud khi agent đặt cùng vùng với trình duyệt cloud.** Mọi số cloud ở đây đo từ một máy cách trình duyệt cloud khoảng 240 ms. Chạy thật trên server cùng vùng có thể nhanh hơn nhiều.
- **Steel Cloud trên gói Scale.** Chưa thử bài giữ phiên với phiên dài 1 giờ.
- **Live View của `steel_selfhost` qua mạng.** Mới thử trên máy local: người xem và container cùng một máy. Chưa thử khi khách xem từ xa. Cũng chưa kiểm tra bản Steel mới hơn đã sửa lỗi này chưa.
- **RAM thật của trình duyệt cloud.** Không đo được, chỉ có số phía client.
- **Chi phí local và self-host.** Đây là ước tính theo giá VPS, chưa chạy thật trên VPS. Cũng chưa đo Chrome headful dưới Xvfb trên Linux. Phải dùng headful, vì headless bị `s4_guarded` chặn.
- **Anti-bot trên site thật.** `s4_guarded` là mock site. Kết quả trên Cloudflare Turnstile hay reCAPTCHA thật chưa biết.
- **Ảnh hưởng của LLM khác.** Toàn bộ đo bằng Haiku 5.5. Kiểm tra chéo với LLM thắng của Agent 2 làm ở M4.

## 10. Chạy lại

```bash
uv run python -m bench.runtime.run all         # toàn bộ ma trận, có resume
uv run python -m bench.runtime.latency         # độ trễ mạng (không dùng LLM)
uv run python -m bench.runtime.report          # tính lại các bảng trong file này
```

Dữ liệu gốc nằm trong `results/runtime/`:
- `*_cold.jsonl`, `*_booking.jsonl`, `*_c3.jsonl`, `*_c5.jsonl`, `*_hold.jsonl`
- `latency.json`
- `liveview/`, `antibot/`
