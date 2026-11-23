"""Kiểm tra mock site bằng Playwright, không dùng LLM: `uv run python -m mock_sites.verify`.

1. Bật 5 site (trừ khi có --no-serve).
2. Chứng minh s4_guarded chặn thật:
   a. Chromium headless mặc định của Playwright, không vá gì -> phải bị chặn.
   b. Cùng headless nhưng đổi User-Agent (bỏ chữ HeadlessChrome) -> vẫn phải bị chặn vì navigator.webdriver = true.
3. Mở Chrome cài trên máy bằng --remote-debugging-port, nối qua CDP, điền form đúng 1 lượt cho mỗi task trong
   tasks/tasks.json, rồi chấm bằng grade(). Phải ra success cả 10/10.
4. Kiểm tra thêm các lớp chặn của s4: honeypot và rate limit.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.async_api import Page, async_playwright

from bench.core.contract import BenchTask, grade, load_tasks, site_url

ROOT = Path(__file__).resolve().parent.parent
CDP_PORT = 9333
CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    found = shutil.which("google-chrome") or shutil.which("chrome")
    if not found:
        sys.exit("Không tìm thấy Chrome. Đặt biến CHROME_PATH.")
    return found


def wait_port(port: int, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"cổng {port} không mở sau {timeout}s")


# ---------- điền form theo từng site ----------

async def fill_s1(page: Page, t: BenchTask) -> None:
    e = t.expected
    await page.goto(site_url(t.site))
    await page.fill("#date", e.date)
    await page.fill("#time", e.time)
    await page.fill("#party_size", str(e.party_size))
    await page.fill("#name", e.name)
    await page.fill("#phone", e.phone)
    await page.click("#submit")
    await page.wait_for_selector("#confirmation")


async def fill_s2(page: Page, t: BenchTask) -> None:
    e = t.expected
    y, m, _ = e.date.split("-")
    await page.goto(site_url(t.site))
    await page.select_option("#party", str(e.party_size))
    await page.click("#date-display")
    target = f"Tháng {int(m)} / {y}"
    for _ in range(24):
        if (await page.text_content("#month-title")) == target:
            break
        await page.click("#next-month")
    await page.click(f'.day[data-date="{e.date}"]')
    await page.click("#next1")
    await page.click(f'.slot[data-time="{e.time}"]')
    await page.click("#next2")
    await page.fill("#name", e.name)
    await page.fill("#phone", e.phone)
    await page.click("#confirm")
    await page.wait_for_selector("#confirmation")


async def fill_s3(page: Page, t: BenchTask) -> None:
    e = t.expected
    await page.goto(site_url(t.site))
    await page.wait_for_selector("#cookie-accept", state="visible")
    await page.click("#cookie-accept")
    await page.fill("#date", e.date)
    await page.click(f'.slot[data-time="{e.time}"]')  # chờ fetch trả khung giờ
    await page.select_option("#party", str(e.party_size))
    await page.fill("#name", e.name)
    await page.fill("#phone", e.phone)
    await page.click("#submit")
    await page.wait_for_selector("#confirmation")


async def fill_s4(page: Page, t: BenchTask) -> None:
    e = t.expected
    await page.goto(site_url(t.site))
    await page.wait_for_selector("#name")  # sau khi JS challenge cấp cookie và tải lại
    await page.fill("#date", e.date)
    await page.fill("#time", e.time)
    await page.fill("#party_size", str(e.party_size))
    await page.fill("#name", e.name)
    await page.fill("#phone", e.phone)
    await page.click("#submit")
    await page.wait_for_selector("#confirmation")


async def fill_s5(page: Page, t: BenchTask) -> None:
    e = t.expected
    await page.goto(site_url(t.site))
    await page.fill("#date", e.date)
    await page.fill("#time", e.time)
    await page.fill("#party_size", str(e.party_size))
    await page.fill("#name", e.name)
    await page.fill("#phone", e.phone)
    await page.click("#submit")
    await page.wait_for_selector("#otp")
    async with httpx.AsyncClient() as c:
        otp = (await c.get(site_url(t.site) + "/_bench/otp", headers={"X-Bench-Harness": "1"})).json()["otp"]
    await page.fill("#otp", otp)
    await page.click("#verify")
    await page.wait_for_selector("#confirmation")


FILLERS = {"s1_simple": fill_s1, "s2_wizard": fill_s2, "s3_spa": fill_s3, "s4_guarded": fill_s4, "s5_otp": fill_s5}


# ---------- các bước kiểm tra ----------

async def check_s4_blocks_headless(pw, http: httpx.AsyncClient) -> list[tuple[str, bool, str]]:
    s4 = site_url("s4_guarded")
    out = []
    await http.post(s4 + "/_bench/reset")
    await http.post(s4 + "/_bench/reset_rate")

    browser = await pw.chromium.launch(headless=True)
    try:
        # a. headless mặc định, không vá gì
        page = await browser.new_page()
        resp = await page.goto(s4)
        await page.wait_for_timeout(1500)
        blocked = await page.locator("#blocked").count() > 0 and await page.locator("#name").count() == 0
        out.append(("s4 chặn Chromium headless mặc định", blocked, f"HTTP {resp.status if resp else '?'}"))
        await page.context.close()

        # b. đổi UA để qua lớp 1, vẫn phải bị chặn bởi navigator.webdriver
        ctx = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"))
        page = await ctx.new_page()
        await page.goto(s4)
        await page.wait_for_timeout(1500)
        blocked = await page.locator("#blocked").count() > 0 and await page.locator("#name").count() == 0
        out.append(("s4 chặn headless đã đổi UA (navigator.webdriver = true)", blocked, ""))
        await ctx.close()
    finally:
        await browser.close()

    reasons = sorted({b["reason"] for b in (await http.get(s4 + "/_bench/blocks")).json()})
    out.append(("s4 ghi nhận lý do chặn", {"headless_ua", "webdriver"} <= set(reasons), ", ".join(reasons)))
    await http.post(s4 + "/_bench/reset")
    await http.post(s4 + "/_bench/reset_rate")
    return out


async def run_tasks(browser, tasks: list[BenchTask], http: httpx.AsyncClient) -> list[tuple[str, bool, str]]:
    out = []
    for t in tasks:
        base = site_url(t.site)
        await http.post(base + "/_bench/reset")
        if t.site == "s4_guarded":
            await http.post(base + "/_bench/reset_rate")
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.set_default_timeout(15_000)
        err = ""
        try:
            await FILLERS[t.site](page, t)
        except Exception as ex:  # noqa: BLE001
            err = f"{type(ex).__name__}: {str(ex).splitlines()[0]}"
        finally:
            await ctx.close()
        bookings = (await http.get(base + "/_bench/bookings")).json()
        outcome = grade(t, bookings)
        out.append((f"{t.task_id} {t.site}", outcome == "success", outcome + (f" ({err})" if err else "")))
    return out


async def check_s4_extra(browser, http: httpx.AsyncClient) -> list[tuple[str, bool, str]]:
    s4 = site_url("s4_guarded")
    out = []

    # honeypot: qua challenge bình thường, nhưng điền trường ẩn `website`
    await http.post(s4 + "/_bench/reset")
    await http.post(s4 + "/_bench/reset_rate")
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page.set_default_timeout(15_000)
    await page.goto(s4)
    await page.wait_for_selector("#name")
    for sel, val in [("#date", "2026-12-15"), ("#time", "19:00"), ("#party_size", "2"),
                     ("#name", "Bot Test"), ("#phone", "0900000000")]:
        await page.fill(sel, val)
    await page.evaluate("document.getElementById('website').value = 'http://spam.example'")
    async with page.expect_navigation():
        await page.click("#submit")
    stored = (await http.get(s4 + "/_bench/bookings")).json()
    await ctx.close()
    out.append(("s4 honeypot có giá trị -> không lưu đơn", stored == [], f"{len(stored)} đơn"))

    # rate limit: 11 request liền nhau từ cùng IP, request thứ 11 phải bị 429
    await http.post(s4 + "/_bench/reset_rate")
    codes = [(await http.get(s4 + "/")).status_code for _ in range(11)]
    out.append(("s4 rate limit 10 request/phút", codes[:10] == [200] * 10 and codes[10] == 429,
                f"mã trả về: {codes}"))
    await http.post(s4 + "/_bench/reset_rate")
    await http.post(s4 + "/_bench/reset")
    return out


async def main(serve: bool) -> int:
    server = None
    if serve:
        server = subprocess.Popen([sys.executable, "-m", "mock_sites.serve"], cwd=ROOT)
    profile = Path(tempfile.mkdtemp(prefix="bench-verify-"))
    chrome = None
    results: list[tuple[str, bool, str]] = []
    try:
        for port in (8801, 8802, 8803, 8804, 8805):
            wait_port(port)
        async with httpx.AsyncClient(timeout=10) as http, async_playwright() as pw:
            results += await check_s4_blocks_headless(pw, http)

            chrome = subprocess.Popen([
                find_chrome(), f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank",
            ])
            wait_port(CDP_PORT)
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            try:
                results += await run_tasks(browser, load_tasks(ROOT / "tasks" / "tasks.json"), http)
                results += await check_s4_extra(browser, http)
            finally:
                await browser.close()
    finally:
        if chrome:
            chrome.terminate()
            try:
                chrome.wait(10)
            except subprocess.TimeoutExpired:
                chrome.kill()
        if server:
            server.terminate()
            server.wait(10)
        shutil.rmtree(profile, ignore_errors=True)

    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} kiểm tra đạt")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-serve", action="store_true", help="site đã chạy sẵn, không tự bật")
    sys.exit(asyncio.run(main(serve=not ap.parse_args().no_serve)))
