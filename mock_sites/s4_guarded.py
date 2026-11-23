"""s4_guarded (8804): JS challenge cấp cookie, honeypot ẩn, giới hạn 10 request/phút/IP, chặn navigator.webdriver.

Các lớp chặn:
1. User-Agent chứa "HeadlessChrome" -> 403 ngay ở trang đầu.
2. Trang đầu là JS challenge: tính hash từ nonce, gửi kèm navigator.webdriver lên /_challenge.
   webdriver = true hoặc hash sai -> 403. Đúng -> cấp cookie `bench_pass` và tải lại trang.
3. POST /book không có cookie hợp lệ -> 403.
4. Trường honeypot `website` (ẩn khỏi màn hình) có giá trị -> 400, không lưu đơn.
5. Quá 10 request/phút/IP (không tính /_bench/*) -> 429.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from html import escape

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from mock_sites.common import Store, client_ip, make_app, page, read_fields, validate_booking

RATE_LIMIT = 10
RATE_WINDOW_S = 60.0
COOKIE = "bench_pass"
SECRET = secrets.token_bytes(32)

store = Store()
blocks: list[dict] = []
hits: dict[str, deque] = defaultdict(deque)


def _reset_blocks() -> None:
    blocks.clear()


app = make_app("s4_guarded", store, on_reset=_reset_blocks)


def _sign(value: str) -> str:
    return hmac.new(SECRET, value.encode(), hashlib.sha256).hexdigest()[:24]


def _pow(nonce: str) -> int:
    h = 0
    for ch in nonce:
        h = (h * 31 + ord(ch)) % 1_000_000_007
    return h


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _block(request: Request, reason: str) -> None:
    blocks.append({"reason": reason, "path": request.url.path, "ua": request.headers.get("user-agent", ""),
                   "at": time.time()})


def _has_pass(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _sign("pass:" + _client_ip(request)))


def _blocked_page(reason: str, status: int = 403) -> HTMLResponse:
    resp = page("Truy cập bị chặn", f'<h1>Truy cập bị chặn</h1><div class="err" id="blocked">'
                                    f'Hệ thống phát hiện truy cập tự động ({escape(reason)}).</div>')
    resp.status_code = status
    return resp


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if path.startswith("/_bench") or path == "/favicon.ico":
        return await call_next(request)
    ip = _client_ip(request)
    now = time.monotonic()
    q = hits[ip]
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        _block(request, "rate_limit")
        resp = _blocked_page("quá nhiều yêu cầu, thử lại sau 1 phút", 429)
        resp.headers["Retry-After"] = str(int(RATE_WINDOW_S - (now - q[0])) + 1)
        return resp
    q.append(now)
    return await call_next(request)


@app.post("/_bench/reset_rate")
async def reset_rate() -> dict:
    """Xóa bộ đếm rate limit. Chỉ dùng cho harness/kiểm thử, không phải một phần của site."""
    hits.clear()
    return {"ok": True}


@app.get("/_bench/blocks")
async def get_blocks() -> list[dict]:
    """Các lần bị chặn kể từ lần reset gần nhất (lý do: headless_ua, webdriver, bad_challenge, no_cookie,
    honeypot, rate_limit)."""
    return blocks


CHALLENGE_JS = """
(async () => {
  const nonce = '__NONCE__';
  let h = 0;
  for (const c of nonce) h = (h * 31 + c.charCodeAt(0)) % 1000000007;
  const r = await fetch('/_challenge', {method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({nonce, answer: h, webdriver: navigator.webdriver === true})});
  if (r.ok) { location.reload(); return; }
  document.body.innerHTML = '<h1>Truy cập bị chặn</h1><div class="err" id="blocked">' +
    'Hệ thống phát hiện trình duyệt tự động.</div>';
})();
"""

FORM = """
<h1>Phố Cổ Grill — Đặt bàn</h1>
<form method="post" action="/book" autocomplete="off">
  <label for="date">Ngày</label><input id="date" name="date" type="date" required>
  <label for="time">Giờ</label><input id="time" name="time" type="time" required>
  <label for="party_size">Số người</label>
  <input id="party_size" name="party_size" type="number" min="1" max="20" value="2" required>
  <label for="name">Họ tên</label><input id="name" name="name" type="text" required>
  <label for="phone">Số điện thoại</label><input id="phone" name="phone" type="tel" required>
  <div style="position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden" aria-hidden="true">
    <label for="website">Website</label>
    <input id="website" name="website" type="text" tabindex="-1" autocomplete="off">
  </div>
  <button type="submit" id="submit">Đặt bàn</button>
</form>
"""


@app.get("/")
async def index(request: Request):
    if "HeadlessChrome" in request.headers.get("user-agent", ""):
        _block(request, "headless_ua")
        return _blocked_page("headless")
    if _has_pass(request):
        return page("Đặt bàn — Phố Cổ Grill", FORM)
    raw = secrets.token_hex(8)
    nonce = f"{raw}.{_sign('nonce:' + raw)[:12]}"
    return page("Đang kiểm tra trình duyệt…", "<p>Đang kiểm tra trình duyệt của bạn…</p>",
                CHALLENGE_JS.replace("__NONCE__", nonce))


@app.post("/_challenge")
async def challenge(request: Request):
    try:
        data = await request.json()
    except ValueError:
        data = {}
    nonce = str(data.get("nonce", ""))
    raw, _, sig = nonce.partition(".")
    if data.get("webdriver") is not False:
        _block(request, "webdriver")
        return JSONResponse({"ok": False}, status_code=403)
    if not raw or not hmac.compare_digest(sig, _sign("nonce:" + raw)[:12]) or data.get("answer") != _pow(nonce):
        _block(request, "bad_challenge")
        return JSONResponse({"ok": False}, status_code=403)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, _sign("pass:" + _client_ip(request)), httponly=True, samesite="lax", max_age=3600)
    return resp


@app.post("/book")
async def book(request: Request):
    if not _has_pass(request):
        _block(request, "no_cookie")
        return _blocked_page("thiếu cookie xác minh")
    fields = await read_fields(request)
    if fields.get("website", "").strip():
        _block(request, "honeypot")
        resp = page("Lỗi", '<h1>Không đặt được</h1><div class="err">Yêu cầu không hợp lệ.</div>')
        resp.status_code = 400
        return resp
    booking, err = validate_booking(fields)
    if err:
        return page("Lỗi", f'<h1>Không đặt được</h1><div class="err">{escape(err)}</div><p><a href="/">Quay lại</a></p>')
    store.add(**booking)
    b = {k: escape(str(v)) for k, v in booking.items()}
    return page(
        "Đã đặt bàn",
        f'<h1>Đặt bàn thành công</h1><div class="ok" id="confirmation">'
        f'Bàn {b["party_size"]} người, ngày {b["date"]} lúc {b["time"]}, tên {b["name"]}, SĐT {b["phone"]}.</div>',
    )
