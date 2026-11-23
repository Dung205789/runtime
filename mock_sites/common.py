"""Phần dùng chung cho 5 mock site: kho đơn, endpoint /_bench/*, khung HTML, kiểm tra dữ liệu."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

CSS = """
body{font-family:system-ui,Arial,sans-serif;max-width:560px;margin:32px auto;padding:0 16px;color:#222}
h1{font-size:1.4rem}label{display:block;margin:12px 0 4px;font-weight:600}
input,select{width:100%;padding:8px;font-size:1rem;box-sizing:border-box}
button{padding:10px 16px;font-size:1rem;margin-top:16px;cursor:pointer}
.ok{background:#e6f7e6;border:1px solid #6c6;padding:12px;margin-top:16px}
.err{background:#fde8e8;border:1px solid #c66;padding:12px;margin-top:16px}
"""


class Store:
    """Kho đơn trong bộ nhớ của một site."""

    def __init__(self) -> None:
        self.bookings: list[dict] = []

    def add(self, date: str, time: str, party_size: int, name: str, phone: str) -> dict:
        rec = {
            "date": date,
            "time": time,
            "party_size": party_size,
            "name": name,
            "phone": phone,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.bookings.append(rec)
        return rec

    def clear(self) -> None:
        self.bookings.clear()


def page(title: str, body: str, script: str = "") -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{CSS}</style></head>
<body>{body}<script>{script}</script></body></html>"""
    )


def from_tunnel(request: Request) -> bool:
    return "cf-connecting-ip" in request.headers


def client_ip(request: Request) -> str:
    """IP thật của trình duyệt. Qua tunnel thì kết nối tới từ cloudflared (127.0.0.1), IP thật nằm ở Cf-Connecting-IP."""
    if ip := request.headers.get("cf-connecting-ip"):
        return ip.strip()
    return request.client.host if request.client else "unknown"


def make_app(title: str, store: Store, on_reset=None) -> FastAPI:
    """Tạo app FastAPI có sẵn các endpoint kiểm tra bắt buộc."""
    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def bench_local_only(request: Request, call_next):
        # Request đi qua Cloudflare tunnel luôn có header Cf-Connecting-IP. Endpoint /_bench/* chỉ cho harness
        # gọi trực tiếp qua 127.0.0.1, để người ngoài có URL tunnel không đọc/xóa được đơn hay lấy OTP.
        if request.url.path.startswith("/_bench") and from_tunnel(request):
            return JSONResponse({"error": "bench endpoints are local-only"}, status_code=403)
        return await call_next(request)

    @app.post("/_bench/reset")
    async def reset() -> dict:
        store.clear()
        if on_reset:
            on_reset()
        return {"ok": True}

    @app.get("/_bench/bookings")
    async def bookings() -> list[dict]:
        return store.bookings

    return app


async def read_fields(request: Request) -> dict[str, str]:
    """Đọc body dạng JSON hoặc x-www-form-urlencoded (không cần python-multipart)."""
    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        data = json.loads(raw or b"{}")
        return {k: str(v) for k, v in data.items()}
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def validate_booking(f: dict[str, str]) -> tuple[dict | None, str | None]:
    """Trả (đơn đã chuẩn hóa, None) hoặc (None, thông báo lỗi)."""
    date = f.get("date", "").strip()
    time = f.get("time", "").strip()
    name = f.get("name", "").strip()
    phone = f.get("phone", "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None, "Ngày không hợp lệ (cần YYYY-MM-DD)."
    if not re.fullmatch(r"\d{2}:\d{2}", time):
        return None, "Giờ không hợp lệ (cần HH:MM)."
    try:
        party = int(f.get("party_size", ""))
    except ValueError:
        return None, "Số người không hợp lệ."
    if not 1 <= party <= 20:
        return None, "Số người phải từ 1 đến 20."
    if not name:
        return None, "Thiếu tên."
    if len(re.sub(r"\D", "", phone)) < 9:
        return None, "Số điện thoại không hợp lệ."
    return {"date": date, "time": time, "party_size": party, "name": name, "phone": phone}, None


def error_json(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


def time_slots(start_h: int = 11, end_h: int = 21, step_min: int = 15) -> list[str]:
    out = []
    t = start_h * 60
    while t <= end_h * 60 + 30:
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += step_min
    return out
