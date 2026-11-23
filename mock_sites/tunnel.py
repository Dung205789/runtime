"""Mở Cloudflare Quick Tunnel cho 5 mock site, để trình duyệt cloud truy cập được: `uv run python -m mock_sites.tunnel`.

- Cần mock site đang chạy (`uv run python -m mock_sites.serve`) và cloudflared
  (tmp/tools/cloudflared.exe, hoặc biến CLOUDFLARED_PATH, hoặc cloudflared trong PATH).
- Mỗi site một tunnel, URL ngẫu nhiên dạng https://<chữ-ngẫu-nhiên>.trycloudflare.com, đổi mỗi lần mở.
- URL được ghi vào tmp/public_urls.json; bench.providers.site_url_for() đọc file này cho runtime cloud.
- /_bench/* bị chặn (403) khi đi qua tunnel; harness vẫn gọi qua 127.0.0.1.
- Ctrl-C để đóng tunnel; file tmp/public_urls.json bị xóa khi đóng.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from bench.core.contract import SITE_PORTS, site_url

ROOT = Path(__file__).resolve().parent.parent
URLS_FILE = ROOT / "tmp" / "public_urls.json"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared() -> str:
    for c in (os.environ.get("CLOUDFLARED_PATH", ""), str(ROOT / "tmp" / "tools" / "cloudflared.exe"),
              str(ROOT / "tmp" / "tools" / "cloudflared")):
        if c and Path(c).exists():
            return c
    if found := shutil.which("cloudflared"):
        return found
    sys.exit("Không tìm thấy cloudflared. Tải từ https://github.com/cloudflare/cloudflared/releases vào tmp/tools/.")


def open_tunnel(exe: str, port: int) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace")
    found: list[str] = []

    def reader() -> None:  # đọc stderr liên tục, để buffer không đầy làm treo cloudflared
        for line in proc.stderr:
            if not found and (m := URL_RE.search(line)):
                found.append(m.group(0))

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.time() + 60
    while not found and time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"cloudflared cho cổng {port} thoát sớm, mã {proc.returncode}")
        time.sleep(0.2)
    if not found:
        proc.kill()
        raise TimeoutError(f"cloudflared cho cổng {port} không in URL sau 60s")
    return proc, found[0]


def wait_reachable(url: str, timeout: float = 90.0) -> bool:
    """Tunnel sẵn sàng khi /_bench/bookings qua tunnel trả 403 của mock site (cũng là kiểm tra lớp chặn)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url + "/_bench/bookings", timeout=10)
            if r.status_code == 403 and "local-only" in r.text:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def main() -> int:
    for site in SITE_PORTS:
        try:
            httpx.get(site_url(site) + "/_bench/bookings", timeout=3)
        except httpx.HTTPError:
            sys.exit(f"{site} chưa chạy. Chạy `uv run python -m mock_sites.serve` trước.")
    exe = find_cloudflared()
    procs: list[subprocess.Popen] = []
    urls: dict[str, str] = {}
    try:
        for site, port in SITE_PORTS.items():
            proc, url = open_tunnel(exe, port)
            procs.append(proc)
            urls[site] = url
            print(f"{site:12s} {url}", flush=True)
        bad = [s for s, u in urls.items() if not wait_reachable(u)]
        if bad:
            print(f"Tunnel chưa truy cập được: {', '.join(bad)}", flush=True)
            return 1
        URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        URLS_FILE.write_text(json.dumps(urls, indent=2), encoding="utf-8")
        print(f"Đã sẵn sàng. URL ghi ở {URLS_FILE.relative_to(ROOT)}. Ctrl-C để đóng.", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("Một tunnel đã thoát; đóng tất cả.", flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        URLS_FILE.unlink(missing_ok=True)
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
