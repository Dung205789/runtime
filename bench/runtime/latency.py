"""Đo độ trễ mạng để tách phần "do cách đo" khỏi thời gian lượt đặt của runtime cloud. Không dùng LLM.

    uv run python -m bench.runtime.latency [--runtime a,b] [--n 20]

Với mỗi runtime đo 2 thứ:
1. CDP round-trip: máy đo (nơi chạy agent browser-use) -> trình duyệt -> máy đo, bằng `Runtime.evaluate("1")`.
   Mỗi bước agent gửi nhiều lệnh CDP (chụp màn hình, lấy DOM, bấm, gõ), nên đây là phần chi phối thời gian lượt đặt.
2. Trình duyệt -> mock site: TTFB của trang s1_simple theo Navigation Timing (responseStart − requestStart).
   Cloud đi qua Cloudflare Quick Tunnel về máy đo; local đi thẳng localhost.
Ngoài ra đo máy đo -> tunnel -> máy đo bằng HTTP GET, để thấy riêng phần tunnel.

Ghi ra results/runtime/latency.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from bench.core.contract import machine_info, site_url
from bench.providers import CLOUD, RUNTIMES, get_provider, lib_versions, site_url_for
from bench.runtime.report import pct

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "runtime" / "latency.json"


def summary(xs: list[float]) -> dict:
    return {"n": len(xs), "p50_ms": round(pct(xs, .5), 1), "p95_ms": round(pct(xs, .95), 1),
            "min_ms": round(min(xs), 1)}


async def measure(rt: str, n: int, pw) -> dict:
    provider = get_provider(rt)
    url = site_url_for(rt, "s1_simple")
    handle = await provider.start()
    try:
        browser = await pw.chromium.connect_over_cdp(handle.cdp_url)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await cdp.send("Runtime.evaluate", {"expression": "1"})  # làm nóng
        rtt = []
        for _ in range(n):
            t = time.perf_counter()
            await cdp.send("Runtime.evaluate", {"expression": "1"})
            rtt.append((time.perf_counter() - t) * 1000)
        ttfb, goto = [], []
        for _ in range(max(5, n // 2)):
            t = time.perf_counter()
            await page.goto(url, wait_until="load", timeout=60_000)
            goto.append((time.perf_counter() - t) * 1000)
            nav = await page.evaluate("(() => { const e = performance.getEntriesByType('navigation')[0];"
                                      " return e.responseStart - e.requestStart; })()")
            ttfb.append(nav)
        await browser.close()
    finally:
        await provider.stop(handle)
    return {"cdp_rtt": summary(rtt), "site_ttfb_from_browser": summary(ttfb), "goto_from_harness": summary(goto),
            "via_tunnel": rt in CLOUD}


async def tunnel_from_harness(n: int) -> dict:
    local, public = site_url("s1_simple"), site_url_for("steel_cloud", "s1_simple")
    out = {}
    async with httpx.AsyncClient(timeout=30) as c:
        for name, u in (("localhost", local), ("qua_tunnel", public)):
            await c.get(u)
            xs = []
            for _ in range(n):
                t = time.perf_counter()
                await c.get(u)
                xs.append((time.perf_counter() - t) * 1000)
            out[name] = summary(xs)
    return out


async def main() -> None:
    from bench.runtime.run import Infra

    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default="")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    rts = [x for x in a.runtime.split(",") if x] or list(RUNTIMES)
    infra = Infra()
    res = {"checked_at": datetime.now(timezone.utc).isoformat(), "machine": machine_info(), "versions": lib_versions(),
           "runtimes": {}}
    try:
        await infra.sites()
        if any(r in CLOUD for r in rts):
            await infra.ensure_tunnel()
            res["harness_http"] = await tunnel_from_harness(a.n)
            print("harness HTTP:", res["harness_http"], flush=True)
        if "steel_selfhost" in rts:
            infra.steel_containers(1)
        async with async_playwright() as pw:
            for rt in rts:
                try:
                    res["runtimes"][rt] = await measure(rt, a.n, pw)
                except Exception as e:  # noqa: BLE001
                    res["runtimes"][rt] = {"error": f"{type(e).__name__}: {e}"[:300]}
                print(rt, res["runtimes"][rt], flush=True)
    finally:
        if "steel_selfhost" in rts:
            from bench.providers.steel_selfhost import down

            down()
        infra.close()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ghi {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
