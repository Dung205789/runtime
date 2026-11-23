"""steel_selfhost: Steel Browser tự host bằng Docker.

README (tra 2026-11-23): https://github.com/steel-dev/steel-browser
- Image: ghcr.io/steel-dev/steel-browser. REST ở cổng 3000 (/v1/...), health: GET /v1/health. UI: /ui

Đã kiểm chứng trên container thật (image ghcr.io/steel-dev/steel-browser:latest, 2026-11-23):
- POST /v1/sessions trả `id`, `status`, `websocketUrl` = "ws://localhost:3000/" (không chứa id phiên),
  `debugUrl` = "http://localhost:3000/v1/sessions/debug", `debuggerUrl`, `sessionViewerUrl`, `userAgent`…
- POST /v1/sessions/{id}/release trả 200.
- Trường `timeout` gửi lên bị bỏ qua (phản hồi luôn `timeout: 0`).
- **Mỗi container chỉ giữ 1 phiên**: tạo phiên thứ 2 thì phiên thứ nhất chuyển sang `released`.
  Vì vậy muốn N phiên song song thì chạy N container (lệnh `up N`), provider cấp mỗi phiên một container rảnh.
- Trình duyệt trong container mở được mock site qua host.docker.internal dù mock site chỉ nghe 127.0.0.1
  (Docker Desktop chuyển tiếp về loopback của máy).

Lệnh tiện ích:
    uv run python -m bench.providers.steel_selfhost up [N]   # chạy N container (mặc định 1), cổng 3000, 3010, 3020…
    uv run python -m bench.providers.steel_selfhost probe    # tạo 1 phiên, in phản hồi, giải phóng
    uv run python -m bench.providers.steel_selfhost down     # xóa mọi container bench-steel-*
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx

from bench.core.contract import BrowserHandle
from bench.providers._util import ProviderSkipped, raise_for_status, session_timeout_s

IMAGE = "ghcr.io/steel-dev/steel-browser"
CONTAINER_PREFIX = "bench-steel-"
API_PORT0, CDP_PORT0, PORT_STEP = 3000, 9223, 10


def container_ports(i: int) -> tuple[int, int]:
    return API_PORT0 + PORT_STEP * i, CDP_PORT0 + PORT_STEP * i


def base_urls() -> list[str]:
    """Danh sách container. STEEL_SELFHOST_URLS (cách nhau dấu phẩy) > STEEL_SELFHOST_N > 1 container ở cổng 3000."""
    if raw := os.environ.get("STEEL_SELFHOST_URLS", "").strip():
        return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    n = int(os.environ.get("STEEL_SELFHOST_N", "1"))
    return [f"http://localhost:{container_ports(i)[0]}" for i in range(n)]


def _rehost(url: str | None, base: str) -> str | None:
    """Container luôn tự báo localhost:3000; đổi host:port thành của container thật."""
    if not url:
        return url
    u, b = urlsplit(url), urlsplit(base)
    return urlunsplit((u.scheme, b.netloc, u.path, u.query, u.fragment))


class SteelSelfHost:
    name = "steel_selfhost"

    def __init__(self, timeout_s: int | None = None, bases: list[str] | None = None) -> None:
        self.bases = bases or base_urls()
        self.timeout_s = session_timeout_s(timeout_s)  # container bỏ qua, giữ để cùng giao diện với cloud
        self.versions: dict = {"image": IMAGE, "containers": len(self.bases)}
        self.last_response: dict = {}
        self._free: list[str] = list(self.bases)
        self._busy: dict[str, str] = {}  # session_id -> base
        self._released_at: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    async def _healthy(c: httpx.AsyncClient) -> bool:
        try:
            return (await c.get("/v1/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def start(self) -> BrowserHandle:
        async with self._lock:
            if not self._free:
                raise RuntimeError(f"steel_selfhost: cả {len(self.bases)} container đều đang bận (mỗi container chỉ "
                                   f"giữ 1 phiên). Chạy thêm bằng `up N` và đặt STEEL_SELFHOST_N=N")
            base = self._free.pop(0)
        try:
            async with httpx.AsyncClient(base_url=base, timeout=60) as c:
                if not await self._healthy(c):
                    raise ProviderSkipped(f"steel_selfhost: {base}/v1/health không trả lời. Bật Docker Desktop rồi chạy "
                                          "`uv run python -m bench.providers.steel_selfhost up`")
                r = await c.post("/v1/sessions", json={"dimensions": {"width": 1280, "height": 900}})
            raise_for_status(r, "steel_selfhost tạo phiên")
            s = r.json()
        except BaseException:
            async with self._lock:
                self._free.insert(0, base)
            raise
        self.last_response = s
        self._busy[s["id"]] = base
        return BrowserHandle(provider=self.name, cdp_url=_rehost(s["websocketUrl"], base),
                             live_view_url=_rehost(s.get("debugUrl"), base), session_id=s["id"])

    async def stop(self, handle: BrowserHandle) -> None:
        base = self._busy.pop(handle.session_id or "", None)
        if base is None:
            return
        try:
            async with httpx.AsyncClient(base_url=base, timeout=60) as c:
                r = await c.post(f"/v1/sessions/{handle.session_id}/release")
            raise_for_status(r, "steel_selfhost giải phóng phiên")
        finally:
            self._released_at[handle.session_id or ""] = base
            async with self._lock:
                self._free.append(base)

    async def released(self, handle: BrowserHandle) -> tuple[bool, str]:
        """Sau stop(): GET /v1/sessions/{id} phải có status khác "live"."""
        base = self._released_at.pop(handle.session_id or "", None)
        if not base:
            return True, "không rõ container"
        async with httpx.AsyncClient(base_url=base, timeout=30) as c:
            r = await c.get(f"/v1/sessions/{handle.session_id}")
        status = r.json().get("status") if r.status_code == 200 else f"HTTP {r.status_code}"
        return status != "live", f"status={status}"


def up(n: int) -> int:
    for i in range(n):
        api, cdp = container_ports(i)
        name = f"{CONTAINER_PREFIX}{i}"
        subprocess.call(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rc = subprocess.call(["docker", "run", "-d", "--name", name, "-p", f"{api}:3000", "-p", f"{cdp}:9223", IMAGE])
        if rc:
            return rc
        print(f"{name}: http://localhost:{api}")
    print(f"Đặt STEEL_SELFHOST_N={n} để provider dùng cả {n} container.")
    return 0


def down() -> int:
    names = subprocess.run(["docker", "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}", "--format", "{{.Names}}"],
                           capture_output=True, text=True).stdout.split()
    return subprocess.call(["docker", "rm", "-f", *names]) if names else 0


async def _probe() -> None:
    p = SteelSelfHost()
    h = await p.start()
    print(json.dumps(p.last_response, indent=2, ensure_ascii=False))
    print("handle:", h)
    await p.stop(h)
    print("đã giải phóng phiên")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "up":
        sys.exit(up(int(sys.argv[2]) if len(sys.argv) > 2 else 1))
    if cmd == "down":
        sys.exit(down())
    asyncio.run(_probe())
