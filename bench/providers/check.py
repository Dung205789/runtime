"""Kiểm tra nhanh các provider (không dùng LLM): `uv run python -m bench.providers.check [runtime ...]`.

Với mỗi runtime:
1. start() -> có cdp_url (đo session_create_ms).
2. Playwright nối CDP, mở s1_simple qua site_url_for() (đo first_page_ms). Cloud chưa có tunnel thì chỉ mở about:blank.
3. browser_use.Browser(cdp_url=...) start()/stop(): browser-use nối được qua CDP.
4. stop(); với chrome_local thì đếm tiến trình Chrome còn sót của profile tạm.
Thiếu khóa API / Docker -> skipped. Đây là kiểm tra khói cho M2, chưa phải số đo của M3.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
from playwright.async_api import async_playwright

from bench.providers import RUNTIMES, ProviderSkipped, get_provider, lib_versions, site_url_for

ROOT = Path(__file__).resolve().parents[2]


def port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def leftover_chrome(profile_marker: str) -> int:
    n = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if "chrome" in (p.info["name"] or "").lower() and profile_marker in " ".join(p.info["cmdline"] or []):
                n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return n


async def check(runtime: str, pw) -> dict:
    row: dict = {"runtime": runtime}
    try:
        provider = get_provider(runtime)
        t0 = time.perf_counter()
        handle = await provider.start()
    except ProviderSkipped as e:
        return {**row, "outcome": "skipped", "detail": str(e)}
    except Exception as e:  # noqa: BLE001
        return {**row, "outcome": "crashed", "detail": f"start(): {type(e).__name__}: {e}"}
    row["session_create_ms"] = round((time.perf_counter() - t0) * 1000)
    row["live_view"] = bool(handle.live_view_url)
    try:
        browser = await pw.chromium.connect_over_cdp(handle.cdp_url)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            url = site_url_for(runtime, "s1_simple")
        except ProviderSkipped:
            url = "about:blank"
        await page.goto(url, timeout=30_000)
        row["first_page_ms"] = round((time.perf_counter() - t0) * 1000)
        row["page"] = url if url == "about:blank" else await page.title()
        row["ua"] = await page.evaluate("navigator.userAgent")
        row["webdriver"] = await page.evaluate("navigator.webdriver")
        await browser.close()  # chỉ ngắt kết nối CDP, không đóng trình duyệt

        from browser_use import Browser

        bu = Browser(cdp_url=handle.cdp_url)
        await bu.start()
        await bu.stop()
        row["browser_use_cdp"] = True
        row["outcome"] = "ok"
    except Exception as e:  # noqa: BLE001
        row["outcome"] = "failed"
        row["detail"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
    finally:
        try:
            await provider.stop(handle)
        except Exception as e:  # noqa: BLE001
            row["detail"] = (row.get("detail", "") + f" | stop(): {e}").strip(" |")
    row["versions"] = getattr(provider, "versions", {})
    if runtime == "chrome_local":
        await asyncio.sleep(1)
        row["orphans"] = leftover_chrome("bench-chrome-")
    return row


async def main(runtimes: list[str]) -> int:
    server = None
    if not port_open(8801):
        server = subprocess.Popen([sys.executable, "-m", "mock_sites.serve"], cwd=ROOT, stdout=subprocess.DEVNULL)
        for _ in range(100):
            if port_open(8805):
                break
            await asyncio.sleep(0.2)
    try:
        async with async_playwright() as pw:
            rows = [await check(r, pw) for r in runtimes]
    finally:
        if server:
            server.terminate()
            server.wait(10)
    print("thư viện:", lib_versions())
    bad = 0
    for r in rows:
        print(f"\n[{r['outcome'].upper()}] {r['runtime']}")
        for k, v in r.items():
            if k not in ("runtime", "outcome"):
                print(f"    {k}: {v}")
        bad += r["outcome"] in ("failed", "crashed") or r.get("orphans", 0) > 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or list(RUNTIMES))))
