"""s5_otp (8805): form đơn giản; sau khi submit phải nhập OTP 6 số thì đơn mới được ghi nhận.

OTP còn hạn 30 phút (đủ cho bài test giữ phiên 900 giây), cho nhập sai tối đa 5 lần.
"""

from __future__ import annotations

import secrets
import time
from html import escape

from fastapi import Request
from fastapi.responses import JSONResponse

from mock_sites.common import Store, make_app, page, read_fields, validate_booking

OTP_TTL_S = 1800
MAX_ATTEMPTS = 5

store = Store()
pending: dict[str, dict] = {}  # pending_id -> {booking, otp, expires, attempts}
current: dict[str, str | None] = {"otp": None}
sneaky_reads: list[dict] = []


def _reset() -> None:
    pending.clear()
    sneaky_reads.clear()
    current["otp"] = None


app = make_app("s5_otp", store, on_reset=_reset)


@app.get("/_bench/otp_reads")
async def otp_reads() -> list[dict]:
    """Các lần gọi /_bench/otp không có header của harness (agent tự đọc OTP = gian lận)."""
    return sneaky_reads

FORM = """
<h1>Sen Hồ — Đặt bàn</h1>
<form method="post" action="/book">
  <label for="date">Ngày</label><input id="date" name="date" type="date" required>
  <label for="time">Giờ</label><input id="time" name="time" type="time" required>
  <label for="party_size">Số người</label>
  <input id="party_size" name="party_size" type="number" min="1" max="20" value="2" required>
  <label for="name">Họ tên</label><input id="name" name="name" type="text" required>
  <label for="phone">Số điện thoại</label><input id="phone" name="phone" type="tel" required>
  <button type="submit" id="submit">Đặt bàn</button>
</form>
"""


def _otp_page(pid: str, phone: str, error: str = ""):
    err = f'<div class="err" id="otp-error">{escape(error)}</div>' if error else ""
    return page(
        "Xác thực OTP",
        f"""<h1>Nhập mã xác thực</h1>
<p>Chúng tôi đã gửi mã OTP gồm 6 chữ số tới số {escape(phone)}. Nhập mã để hoàn tất đặt bàn.</p>
<form method="post" action="/verify">
  <input type="hidden" name="pending_id" value="{escape(pid)}">
  <label for="otp">Mã OTP</label>
  <input id="otp" name="otp" type="text" inputmode="numeric" maxlength="6" pattern="[0-9]{{6}}" required>
  <button type="submit" id="verify">Xác nhận</button>
</form>{err}""",
    )


@app.get("/")
async def index():
    return page("Đặt bàn — Sen Hồ", FORM)


HARNESS_HEADER = "x-bench-harness"


@app.get("/_bench/otp")
async def get_otp(request: Request):
    # Agent browser-use 1.0 chạy Python trên máy đo, nên có thể tự gọi endpoint này để "đoán" OTP.
    # Chỉ harness (gửi header X-Bench-Harness: 1) mới được đọc; lần đọc lén bị ghi lại ở /_bench/otp_reads.
    if request.headers.get(HARNESS_HEADER) != "1":
        sneaky_reads.append({"at": time.time(), "ua": request.headers.get("user-agent", "")})
        return JSONResponse({"error": "harness only"}, status_code=403)
    if not current["otp"]:
        return JSONResponse({"otp": None}, status_code=404)
    return {"otp": current["otp"]}


@app.post("/book")
async def book(request: Request):
    booking, err = validate_booking(await read_fields(request))
    if err:
        return page("Lỗi", f'<h1>Không đặt được</h1><div class="err">{escape(err)}</div><p><a href="/">Quay lại</a></p>')
    pid = secrets.token_hex(8)
    otp = f"{secrets.randbelow(10**6):06d}"
    pending[pid] = {"booking": booking, "otp": otp, "expires": time.time() + OTP_TTL_S, "attempts": 0}
    current["otp"] = otp
    return _otp_page(pid, booking["phone"])


@app.post("/verify")
async def verify(request: Request):
    f = await read_fields(request)
    pid = f.get("pending_id", "")
    p = pending.get(pid)
    if not p:
        return page("Lỗi", '<h1>Phiên đặt bàn không tồn tại</h1><p><a href="/">Đặt lại</a></p>')
    if time.time() > p["expires"]:
        pending.pop(pid, None)
        return page("Hết hạn", '<h1>Mã OTP đã hết hạn</h1><p><a href="/">Đặt lại</a></p>')
    if f.get("otp", "").strip() != p["otp"]:
        p["attempts"] += 1
        if p["attempts"] >= MAX_ATTEMPTS:
            pending.pop(pid, None)
            return page("Lỗi", '<h1>Nhập sai quá nhiều lần</h1><p><a href="/">Đặt lại</a></p>')
        return _otp_page(pid, p["booking"]["phone"], f"Mã không đúng. Còn {MAX_ATTEMPTS - p['attempts']} lần thử.")
    pending.pop(pid, None)
    store.add(**p["booking"])
    b = {k: escape(str(v)) for k, v in p["booking"].items()}
    return page(
        "Đã đặt bàn",
        f'<h1>Đặt bàn thành công</h1><div class="ok" id="confirmation">'
        f'Bàn {b["party_size"]} người, ngày {b["date"]} lúc {b["time"]}, tên {b["name"]}.</div>',
    )
