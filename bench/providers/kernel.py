"""kernel: trình duyệt Kernel (onkernel) qua REST.

Tài liệu (tra 2026-11-23): https://www.kernel.sh/docs/browsers/create-a-browser , OpenAPI https://api.onkernel.com/spec.json
- POST https://api.onkernel.com/browsers, header `Authorization: Bearer <KERNEL_API_KEY>`.
  `headless` mặc định false (headful mới có Live View). `timeout_seconds` mặc định 60, tối thiểu 10.
  Trả `session_id`, `cdp_ws_url` (token JWT nằm sẵn trong query), `browser_live_view_url` (mặc định tương tác được).
- Xóa: DELETE /browsers/{session_id} (204). browser.close() của Playwright không xóa phiên.
"""

from __future__ import annotations

import httpx

from bench.core.contract import BrowserHandle
from bench.providers._util import raise_for_status, require_env, session_timeout_s

API = "https://api.onkernel.com"


class Kernel:
    name = "kernel"

    def __init__(self, timeout_s: int | None = None, headless: bool = False) -> None:
        self.api_key = require_env("KERNEL_API_KEY", self.name)
        self.timeout_s = session_timeout_s(timeout_s)
        self.headless = headless
        self.versions: dict = {"api": API}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=60)

    async def start(self) -> BrowserHandle:
        body = {"headless": self.headless, "timeout_seconds": self.timeout_s}
        async with self._client() as c:
            r = await c.post("/browsers", json=body)
        raise_for_status(r, "kernel tạo trình duyệt")
        b = r.json()
        return BrowserHandle(provider=self.name, cdp_url=b["cdp_ws_url"], live_view_url=b.get("browser_live_view_url"),
                             session_id=b["session_id"])

    async def stop(self, handle: BrowserHandle) -> None:
        async with self._client() as c:
            r = await c.delete(f"/browsers/{handle.session_id}")
        if r.status_code != 404:  # 404: đã hết hạn/đã xóa
            raise_for_status(r, "kernel xóa trình duyệt")

    async def released(self, handle: BrowserHandle) -> tuple[bool, str]:
        """Sau stop(): GET /browsers/{id} phải trả 404."""
        async with self._client() as c:
            r = await c.get(f"/browsers/{handle.session_id}")
        return r.status_code == 404, f"HTTP {r.status_code}"
