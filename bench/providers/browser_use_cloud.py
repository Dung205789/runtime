"""browser_use_cloud: trình duyệt của Browser Use Cloud qua REST.

Nguồn: chính code browser-use 1.0.8 đã cài (browser_use/browser/browser.py, hàm _cloud/_create/_stop_now):
- POST https://api.browser-use.com/api/v4/browsers, header `X-Browser-Use-API-Key`.
  Body: proxyCountryCode (null = không proxy), timeout (phút, 1–240), browserScreenWidth/Height.
  Trả `id`, `cdpUrl`, `liveUrl` (ai có link đều điều khiển được trình duyệt).
- Dừng (kết thúc tính tiền): PATCH /browsers/{id} với {"action": "stop"}.
"""

from __future__ import annotations

import math

import httpx

from bench.core.contract import BrowserHandle
from bench.providers._util import raise_for_status, require_env, session_timeout_s

API = "https://api.browser-use.com/api/v4"


class BrowserUseCloud:
    name = "browser_use_cloud"

    def __init__(self, timeout_s: int | None = None, proxy_country: str | None = None) -> None:
        self.api_key = require_env("BROWSER_USE_API_KEY", self.name)
        self.timeout_min = max(1, min(240, math.ceil(session_timeout_s(timeout_s) / 60)))
        self.proxy_country = proxy_country
        self.versions: dict = {"api": API}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, headers={"X-Browser-Use-API-Key": self.api_key}, timeout=120)

    async def start(self) -> BrowserHandle:
        body = {"proxyCountryCode": self.proxy_country, "timeout": self.timeout_min,
                "browserScreenWidth": 1280, "browserScreenHeight": 900}
        async with self._client() as c:
            r = await c.post("/browsers", json=body)
        raise_for_status(r, "browser_use_cloud tạo trình duyệt")
        b = r.json()
        return BrowserHandle(provider=self.name, cdp_url=b["cdpUrl"], live_view_url=b.get("liveUrl"),
                             session_id=b["id"])

    async def stop(self, handle: BrowserHandle) -> None:
        async with self._client() as c:
            r = await c.patch(f"/browsers/{handle.session_id}", json={"action": "stop"})
        raise_for_status(r, "browser_use_cloud dừng trình duyệt")

    async def released(self, handle: BrowserHandle) -> tuple[bool | None, str]:
        """Sau stop(): đọc GET /browsers/{id}. Tài liệu không liệt kê các giá trị status, nên ghi nguyên văn;
        chỉ coi là còn chạy khi status là một từ rõ nghĩa 'đang chạy'."""
        async with self._client() as c:
            r = await c.get(f"/browsers/{handle.session_id}")
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        status = str(r.json().get("status"))
        running = status.lower() in {"active", "running", "live", "started", "starting"}
        return (not running), f"status={status}"
