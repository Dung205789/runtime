from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, unquote_plus, urlsplit

from playwright.async_api import BrowserContext, Route, WebSocketRoute

GUEST_NAME = "Khach Thu Nghiem"
GUEST_PHONE = "0000000000"
GUEST_EMAIL = "benchmark@example.invalid"
MARKERS = ("khach thu nghiem", "thu nghiem", GUEST_PHONE, "000000000", "example.invalid")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
UNSAFE_GET = re.compile(r"otp|sms|/hold|/lock|createorder|/booking/process", re.I)
IDENT_KEY = re.compile(r"phone|sdt|mobile|name|hoten|(?:^|[-_\[])tel|mail", re.I)
IDENT_JSON = re.compile(
    r'"[^"]{0,30}(?:phone|sdt|mobile|nameorder|fullname|hoten|customer_?name|your-name|mail)[^"]{0,20}"\s*:\s*"[^"]+', re.I
)
IDENT_PART = re.compile(
    r'name="[^"]{0,30}(?:phone|sdt|mobile|name|hoten|tel|mail)[^"]{0,20}"\r?\n(?:[^\r\n]+\r?\n)*\r?\n[^\r\n-]+', re.I
)

READ_HOSTS = {"lauphan.com", "tong.com.vn", "chaoxian.com.vn"}


def is_known_read(url: str) -> bool:
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc not in READ_HOSTS or u.path != "/dat-ban":
        return False
    actions = [v for k, vs in parse_qs(u.query).items() if k.endswith("javax.portlet.action") for v in vs]
    return actions == ["loadCosoInfo"]


def carries_identity(body: str) -> bool:
    flat = body.replace('\\"', '"')
    if IDENT_JSON.search(flat) or IDENT_PART.search(body):
        return True
    if "=" in body and not body.lstrip().startswith(("{", "[", "--")):
        return any(v.strip() and IDENT_KEY.search(k) for k, v in parse_qsl(body))
    return False


class SubmitGuard:
    def __init__(self) -> None:
        self.blocked: list[dict] = []
        self.allowed_posts: list[str] = []

    def verdict(self, method: str, url: str, body: str) -> str | None:
        text = unquote_plus(url + " " + body).lower()
        if any(m in text for m in MARKERS):
            return "guest data leaving the page"
        path = urlsplit(url).path
        if method in SAFE_METHODS:
            return "unsafe GET" if UNSAFE_GET.search(path + "?" + urlsplit(url).query) and method == "GET" else None
        if method != "POST" or body == "<unreadable>":
            return "state-changing request"
        if carries_identity(body):
            return "identity fields in body"
        if not is_known_read(url):
            return "POST not on allowlist"
        return None

    async def handle(self, route: Route) -> None:
        req = route.request
        try:
            raw = req.post_data_buffer
            body = raw.decode("utf-8", "replace") if raw else ""
        except Exception:
            body = "<unreadable>"
        why = self.verdict(req.method, req.url, body)
        u = urlsplit(req.url)
        where = f"{u.netloc}{u.path}"[:160] + (" #" + u.query.rsplit("action=", 1)[1][:40] if "action=" in u.query else "")
        if why:
            self.blocked.append({"why": why, "method": req.method, "url": where})
            await route.abort()
            return
        if req.method not in SAFE_METHODS:
            self.allowed_posts.append(where)
        await route.continue_()

    async def close_ws(self, ws: WebSocketRoute) -> None:
        self.blocked.append({"why": "websocket", "method": "WS", "url": ws.url[:160]})
        await ws.close()

    async def install(self, context: BrowserContext) -> None:
        await context.add_init_script(
            "if(navigator.serviceWorker){navigator.serviceWorker.register=()=>Promise.reject(new Error('disabled'))};"
            "navigator.sendBeacon=()=>false;"
        )
        await context.route("**/*", self.handle)
        await context.route_web_socket("**/*", self.close_ws)
