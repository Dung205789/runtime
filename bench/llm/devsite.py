from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

DEV_PORT = 8899

app = FastAPI()
state: dict = {"bookings": [], "pending": None, "otp": None}

FORM = """<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Nhà hàng Dev</title></head><body>
<h1>Đặt bàn — Nhà hàng Dev</h1>
<form method="post" action="/book">
<label>Ngày <input type="date" name="date" required></label><br>
<label>Giờ <input type="time" name="time" required></label><br>
<label>Số người <input type="number" name="party_size" min="1" max="20" required></label><br>
<label>Họ tên <input type="text" name="name" required></label><br>
<label>Số điện thoại <input type="tel" name="phone" required></label><br>
<input type="hidden" name="need_otp" value="{need_otp}">
<button type="submit">Đặt bàn</button>
</form></body></html>"""

OTP_FORM = """<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Xác nhận OTP</title></head><body>
<h1>Nhập mã OTP</h1><p>Chúng tôi đã gửi mã 6 số tới số điện thoại của bạn.</p>
<form method="post" action="/otp"><label>Mã OTP <input type="text" name="code" required></label>
<button type="submit">Xác nhận</button></form></body></html>"""

DONE = """<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Thành công</title></head><body>
<h1>Đặt bàn thành công</h1><p>Mã đặt bàn: {ref}</p></body></html>"""


def _commit(b: dict) -> str:
    b["created_at"] = datetime.now(timezone.utc).isoformat()
    state["bookings"].append(b)
    return f"DEV{len(state['bookings']):04d}"


@app.get("/", response_class=HTMLResponse)
def index(otp: int = 0) -> str:
    return FORM.replace("{need_otp}", str(otp))


@app.post("/book", response_class=HTMLResponse)
def book(
    date: str = Form(...),
    time: str = Form(...),
    party_size: int = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    need_otp: int = Form(0),
) -> str:
    b = {"date": date, "time": time, "party_size": party_size, "name": name, "phone": phone}
    if need_otp:
        state["pending"], state["otp"] = b, f"{random.randint(0, 999999):06d}"
        return OTP_FORM
    return DONE.format(ref=_commit(b))


@app.post("/otp", response_class=HTMLResponse)
def otp(code: str = Form(...)) -> str:
    if state["pending"] is None or code.strip() != state["otp"]:
        return "<h1>Mã OTP sai</h1>" + OTP_FORM
    ref = _commit(state["pending"])
    state["pending"], state["otp"] = None, None
    return DONE.format(ref=ref)


@app.post("/_bench/reset")
def reset() -> dict:
    state.update(bookings=[], pending=None, otp=None)
    return {"ok": True}


@app.get("/_bench/bookings")
def bookings() -> list[dict]:
    return state["bookings"]


@app.get("/_bench/otp")
def current_otp() -> dict:
    return {"otp": state["otp"]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=DEV_PORT, log_level="warning")
