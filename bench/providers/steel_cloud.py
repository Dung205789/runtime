"""steel_cloud: Steel Cloud qua REST.

Tài liệu (tra 2026-11-23): https://steel.dev/docs/reference/api/sessions , https://steel.dev/docs/control/cdp
- POST https://api.steel.dev/v1/sessions, header `steel-api-key`. `timeout` tính bằng ms (tối thiểu 15000;
  tối đa theo gói: Launch 15 phút, Scale 1 giờ). Trả 201 với `id`, `websocketUrl` (CDP, có sẵn token phiên),
  `debugUrl` (Live View, mặc định cho người xem gõ/bấm được).
- Đóng CDP không giải phóng phiên: phải gọi POST /v1/sessions/{id}/release.
"""

from __future__ import annotations

import httpx

from bench.core.contract import BrowserHandle
from bench.providers._util import raise_for_status, require_env, session_timeout_s

API = "https://api.steel.dev/v1"


class SteelCloud:
    name = "steel_cloud"

    def __init__(self, timeout_s: int | None = None, use_proxy: bool = False) -> None:
        self.api_key = require_env("STEEL_API_KEY", self.name)
        self.timeout_s = session_timeout_s(timeout_s)
        self.use_proxy = use_proxy
        self.versions: dict = {"api": API}
        self.last_session: dict = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, headers={"steel-api-key": self.api_key}, timeout=60)

    async def start(self) -> BrowserHandle:
        body = {
            "timeout": self.timeout_s * 1000,
            "useProxy": self.use_proxy,
            "solveCaptcha": False,
            "headless": False,
            "dimensions": {"width": 1280, "height": 900},
        }
        async with self._client() as c:
            r = await c.post("/sessions", json=body)
        raise_for_status(r, "steel_cloud tạo phiên")
        s = r.json()
        self.last_session = {k: s.get(k) for k in ("id", "status", "browserMode", "timeout", "proxySource")}
        return BrowserHandle(provider=self.name, cdp_url=s["websocketUrl"], live_view_url=s.get("debugUrl"),
                             session_id=s["id"])

    async def stop(self, handle: BrowserHandle) -> None:
        async with self._client() as c:
            r = await c.post(f"/sessions/{handle.session_id}/release")
        raise_for_status(r, "steel_cloud giải phóng phiên")

    async def released(self, handle: BrowserHandle) -> tuple[bool, str]:
        """Sau stop(): GET /v1/sessions/{id} phải có status khác "live" (tài liệu: live | released | failed)."""
        async with self._client() as c:
            r = await c.get(f"/sessions/{handle.session_id}")
        status = r.json().get("status") if r.status_code == 200 else f"HTTP {r.status_code}"
        return status != "live", f"status={status}"
