"""Các phép đo của Agent 1 (brief, Bước 3), ngoài lượt đặt bàn đơn lẻ ở booking.py.

cold        start() -> CDP (session_create_ms) và -> s1_simple tải xong (first_page_ms). Không dùng LLM.
concurrent  N phiên song song (tài nguyên ở mức 3 và 5; ổn định: 50 lượt ở mức 3). Mỗi lúc một site chỉ có một
            lượt chạy (vì /_bench/reset xóa đơn của cả site), nên N ≤ 5.
hold        Giữ phiên: t09 (s5_otp), người trả OTP sau 900 s, xem phiên còn chạy tiếp được không.
antibot     3 trang kiểm tra bot, chỉ đọc: chụp ảnh + lưu chữ trên trang vào results/runtime/antibot/.
            (Phần "10 lượt trên s4_guarded" lấy từ lượt đặt t07/t08 trong phase booking.)
liveview    Có URL Live View không; mở URL đó ở một trình duyệt khác, gõ vào ô OTP của s5, kiểm tra giá trị
            thật sự đổi trong phiên; đo độ trễ từ lúc gõ đến lúc giá trị đổi.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from bench.core.contract import BenchTask, RunRecord, append_record, load_tasks, machine_info, now_iso, site_url
from bench.providers import ProviderSkipped, get_provider, lib_versions, site_url_for
from bench.runtime.booking import LLMTransient, LLMUnavailable, _check_released, run_booking

NET_RETRIES, NET_WAIT_S = 5, 60  # mạng tới API LLM rớt: chờ rồi chạy lại lượt đó (giống run.py)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "runtime"
HOLD_WAIT_S = 900
HOLD_SESSION_TIMEOUT_S = 1200
STEEL_LAUNCH_MAX_S = 900
ANTIBOT_PAGES = {
    "browserscan": "https://www.browserscan.net/bot-detection",
    "creepjs": "https://abrahamjuliot.github.io/creepjs/",
    "nowsecure": "https://nowsecure.nl",
}


def tasks() -> list[BenchTask]:
    return load_tasks(ROOT / "tasks" / "tasks.json")


async def _first_page(pw, handle, url: str):
    browser = await pw.chromium.connect_over_cdp(handle.cdp_url)
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(url, wait_until="load", timeout=60_000)
    return browser, page


# ---------------------------------------------------------------- cold start
async def cold(rt: str, reps: int, out: Path, start_rep: int = 0) -> list[RunRecord]:
    provider = get_provider(rt)
    url = site_url_for(rt, "s1_simple")
    recs = []
    async with async_playwright() as pw:
        for rep in range(start_rep, reps):
            rec = RunRecord(run_id=uuid.uuid4().hex[:12], axis="runtime", task_id="cold", site="s1_simple",
                            provider=rt, model="-", cache_mode="none", rep=rep, warmup=(rep == 0), outcome="success",
                            started_at=now_iso(), machine=machine_info(), versions=lib_versions())
            t0 = time.perf_counter()
            handle = None
            try:
                handle = await provider.start()
                rec.session_create_ms = round((time.perf_counter() - t0) * 1000, 1)
                browser, _ = await _first_page(pw, handle, url)
                rec.first_page_ms = round((time.perf_counter() - t0) * 1000, 1)
                await browser.close()
            except ProviderSkipped as e:
                rec.outcome, rec.error = "skipped", str(e)
            except Exception as e:  # noqa: BLE001
                rec.outcome, rec.error = "crashed", f"{type(e).__name__}: {e}"[:500]
            finally:
                if handle:
                    with contextlib.suppress(Exception):
                        await provider.stop(handle)
                    await _check_released(provider, handle, rec)
                rec.total_ms = round((time.perf_counter() - t0) * 1000, 1)
            rec.versions.update({f"provider_{k}": v for k, v in getattr(provider, "versions", {}).items()})
            append_record(out, rec)
            recs.append(rec)
            print(f"cold {rt:17s} rep{rep:<2d} {rec.outcome:8s} create={rec.session_create_ms}ms "
                  f"first_page={rec.first_page_ms}ms" + (f" | {rec.error[:120]}" if rec.error else ""), flush=True)
    return recs


# ---------------------------------------------------------------- N phiên song song
async def concurrent(rt: str, conc: int, runs: int, out: Path, already: int = 0, provider=None) -> list[RunRecord]:
    if conc > 5:
        raise ValueError("tối đa 5 phiên song song (mỗi site chỉ một lượt một lúc)")
    provider = provider or get_provider(rt)
    # Xếp xen kẽ theo site (t01, t03, t05, t07, t09, t02, …) để N lượt liền nhau thuộc N site khác nhau,
    # nhờ vậy chạy được N phiên cùng lúc thật (mỗi site chỉ một lượt một lúc).
    by_site: dict[str, list[BenchTask]] = {}
    for t in tasks():
        by_site.setdefault(t.site, []).append(t)
    order = [ts[k] for k in range(max(map(len, by_site.values()))) for ts in by_site.values() if k < len(ts)]
    todo = [(i, order[i % len(order)]) for i in range(already, runs)]
    peak_running = [0, 0]  # [đang chạy, đỉnh]
    busy: set[str] = set()
    cond = asyncio.Condition()
    recs: list[RunRecord] = []
    retries: dict[int, int] = {}

    async def worker() -> None:
        while True:
            async with cond:
                while True:
                    if not todo:
                        return
                    j = next((k for k, (_, t) in enumerate(todo) if t.site not in busy), None)
                    if j is not None:
                        i, t = todo.pop(j)
                        busy.add(t.site)
                        peak_running[0] += 1
                        peak_running[1] = max(peak_running[1], peak_running[0])
                        break
                    await cond.wait()
            try:
                try:
                    rec = await run_booking(provider, t, rep=i, concurrency=conc, out=out)
                except LLMUnavailable:
                    todo.clear()  # các worker khác không nhận lượt mới
                    raise
                except LLMTransient as e:
                    retries[i] = retries.get(i, 0) + 1
                    if retries[i] > NET_RETRIES:
                        todo.clear()
                        raise LLMUnavailable(f"mạng tới API LLM rớt {retries[i]} lần liền: {e}") from e
                    print(f"!!! c{conc} #{i}: mạng tới API LLM rớt; chờ {NET_WAIT_S} s rồi xếp lại lượt này", flush=True)
                    await asyncio.sleep(NET_WAIT_S)
                    async with cond:
                        todo.insert(0, (i, t))
                    continue
                recs.append(rec)
                print(f"c{conc} {rt:17s} #{i:<3d} {t.task_id} {rec.outcome:10s} t={(rec.total_ms or 0) / 1000:.0f}s "
                      f"peak={rec.peak_pss_mb}MB" + (f" | {rec.error[:120]}" if rec.error else ""), flush=True)
            finally:
                async with cond:
                    busy.discard(t.site)
                    peak_running[0] -= 1
                    cond.notify_all()

    await asyncio.gather(*(worker() for _ in range(conc)))
    print(f"số phiên chạy cùng lúc tối đa: {peak_running[1]}", flush=True)
    return recs


# ---------------------------------------------------------------- giữ phiên 900 s
async def hold(rt: str, out: Path) -> RunRecord:
    t09 = next(t for t in tasks() if t.task_id == "t09")
    provider = get_provider(rt, timeout_s=HOLD_SESSION_TIMEOUT_S)
    rec = await run_booking(provider, t09, rep=0, out=None, human_delay=HOLD_WAIT_S)
    if rt == "steel_cloud" and rec.outcome == "crashed" and "start()" in (rec.error or ""):
        # Gói Launch: phiên tối đa 15 phút. Nếu API từ chối timeout 20 phút thì thử lại với mức tối đa của gói.
        first_err = rec.error
        provider = get_provider(rt, timeout_s=STEEL_LAUNCH_MAX_S)
        rec = await run_booking(provider, t09, rep=0, out=None, human_delay=HOLD_WAIT_S)
        rec.error = "; ".join(filter(None, [f"timeout {HOLD_SESSION_TIMEOUT_S}s bị từ chối ({first_err[:200]}), "
                                            f"thử lại với {STEEL_LAUNCH_MAX_S}s", rec.error]))[:800]
    rec.task_id = "hold_t09"
    rec.versions["hold_wait_s"] = HOLD_WAIT_S
    append_record(out, rec)
    print(f"hold {rt:17s} {rec.outcome:10s} chờ người={rec.human_wait_ms / 1000:.0f}s"
          + (f" | {rec.error[:200]}" if rec.error else ""), flush=True)
    return rec


# ---------------------------------------------------------------- 3 trang kiểm tra bot (chỉ đọc)
async def antibot_pages(rt: str) -> dict:
    provider = get_provider(rt)
    folder = RESULTS / "antibot"
    folder.mkdir(parents=True, exist_ok=True)
    summary = {}
    handle = await provider.start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(handle.cdp_url)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            for name, url in ANTIBOT_PAGES.items():
                info = {"runtime": rt, "page": name, "url": url, "checked_at": now_iso()}
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    info["http_status"] = resp.status if resp else None
                    await page.wait_for_timeout(15_000)  # các trang này chạy kiểm tra bằng JS vài giây
                    info["title"] = await page.title()
                    info["text"] = (await page.evaluate("document.body ? document.body.innerText : ''"))[:6000]
                    info["webdriver"] = await page.evaluate("navigator.webdriver")
                    info["user_agent"] = await page.evaluate("navigator.userAgent")
                    await page.screenshot(path=str(folder / f"{rt}_{name}.png"), full_page=True, timeout=30_000)
                    info["screenshot"] = f"results/runtime/antibot/{rt}_{name}.png"
                except Exception as e:  # noqa: BLE001
                    info["error"] = f"{type(e).__name__}: {e}"[:300]
                (folder / f"{rt}_{name}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), "utf-8")
                summary[name] = info.get("error") or info.get("title")
                print(f"antibot {rt:17s} {name:12s} {summary[name]}", flush=True)
            await browser.close()
    finally:
        await provider.stop(handle)
    return summary


# ---------------------------------------------------------------- Live View
VIEWER_TARGET_JS = """
() => {
  const els = [...document.querySelectorAll('canvas, video, img, iframe')]
    .map(e => ({e, r: e.getBoundingClientRect()}))
    .filter(x => x.r.width > 200 && x.r.height > 150);
  els.sort((a, b) => b.r.width * b.r.height - a.r.width * a.r.height);
  if (!els.length) return null;
  const {e, r} = els[0];
  if (e.tabIndex < 0) e.tabIndex = 0;
  e.focus();
  return {tag: e.tagName, x: r.x, y: r.y, w: r.width, h: r.height};
}
"""


async def _fill_until_otp(page) -> None:
    await page.fill("#date", "2026-12-18")
    await page.fill("#time", "20:00")
    await page.fill("#party_size", "2")
    await page.fill("#name", "Live View Test")
    await page.fill("#phone", "0922111000")
    await page.click("#submit")
    await page.wait_for_selector("#otp", timeout=30_000)
    await page.focus("#otp")


async def _wait_value(page, timeout_s: float = 8.0) -> tuple[str, float | None]:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        v = await page.input_value("#otp")
        if v:
            return v, (time.perf_counter() - t0) * 1000
        await asyncio.sleep(0.1)
    return "", None


async def liveview(rt: str) -> dict:
    provider = get_provider(rt)
    folder = RESULTS / "liveview"
    folder.mkdir(parents=True, exist_ok=True)
    info: dict = {"runtime": rt, "checked_at": now_iso(), "has_url": False, "typed_ok": False,
                  "provider_versions": getattr(provider, "versions", {})}
    async with httpx.AsyncClient() as http:
        await http.post(site_url("s5_otp") + "/_bench/reset")
    handle = await provider.start()
    try:
        info["has_url"] = bool(handle.live_view_url)
        if not handle.live_view_url:
            info["note"] = "runtime không cấp URL Live View"
            return info
        async with async_playwright() as pw:
            browser, page = await _first_page(pw, handle, site_url_for(rt, "s5_otp"))
            await _fill_until_otp(page)
            remote_vp = await page.evaluate("({w: innerWidth, h: innerHeight, iw: innerWidth, ih: innerHeight, "
                                            "ow: outerWidth, oh: outerHeight, sx: screenX, sy: screenY, "
                                            "sw: screen.width, sh: screen.height})")
            otp_box = await page.locator("#otp").bounding_box()
            viewer_browser = await pw.chromium.launch(headless=True)
            vpage = await viewer_browser.new_page(viewport={"width": 1400, "height": 1000})
            ws_frames, console_errors = [0], []
            vpage.on("websocket", lambda w: w.on("framereceived", lambda _f: ws_frames.__setitem__(0, ws_frames[0] + 1)))
            vpage.on("console", lambda m: console_errors.append(m.text[:160]) if m.type == "error" else None)
            try:
                await vpage.goto(handle.live_view_url, wait_until="load", timeout=60_000)
                await vpage.wait_for_timeout(8000)
                info["viewer_ws_frames"] = ws_frames[0]  # 0 = khung xem không nhận được dữ liệu nào qua WebSocket
                info["viewer_console_errors"] = console_errors[:5]
                await vpage.screenshot(path=str(folder / f"{rt}_viewer.png"))
                target = await vpage.evaluate(VIEWER_TARGET_JS)
                info["viewer_element"] = target
                # Cách 1: chỉ bàn phím (ô OTP trong phiên đang được focus sẵn)
                await vpage.keyboard.type("4821", delay=80)
                value, lat = await _wait_value(page)
                method = "bàn phím, ô OTP đã focus sẵn"
                # Cách 2 và 3: bấm vào vị trí ô OTP trên khung hình rồi gõ. Có loại Live View truyền cả màn hình
                # (gồm thanh tab/địa chỉ, ví dụ Kernel), có loại chỉ truyền vùng trang (viewport).
                if not value and target and otp_box:
                    cx, cy = otp_box["x"] + otp_box["width"] / 2, otp_box["y"] + otp_box["height"] / 2
                    m = remote_vp
                    candidates = []
                    if m.get("sw") and m.get("sh"):  # theo cả màn hình
                        candidates.append(("cả màn hình", m["sw"], m["sh"],
                                           m["sx"] + (m["ow"] - m["iw"]) / 2 + cx, m["sy"] + (m["oh"] - m["ih"]) + cy))
                    candidates.append(("chỉ vùng trang", m["w"], m["h"], cx, cy))
                    for label, fw, fh, px, py in candidates:
                        s = min(target["w"] / fw, target["h"] / fh)
                        ox = target["x"] + (target["w"] - fw * s) / 2
                        oy = target["y"] + (target["h"] - fh * s) / 2
                        await vpage.mouse.click(ox + px * s, oy + py * s)
                        await vpage.wait_for_timeout(500)
                        await vpage.keyboard.type("4821", delay=80)
                        value, lat = await _wait_value(page)
                        method = f"bấm vào ô OTP trên khung xem (quy đổi {label}) rồi gõ"
                        if value:
                            break
                info.update(typed_ok=bool(value), typed_value=value, method=method,
                            input_latency_ms=round(lat, 1) if lat else None)
                await vpage.screenshot(path=str(folder / f"{rt}_viewer_after.png"))
                if not value:
                    info["note"] = ("không tự động gõ được qua Live View; cần kiểm tra bằng tay (mở URL, bấm vào ô OTP, "
                                    "gõ thử). Chưa kiểm chứng.")
            finally:
                await viewer_browser.close()
                await browser.close()
    finally:
        await provider.stop(handle)
        (folder / f"{rt}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), "utf-8")
        print(f"liveview {rt:17s} có URL={info['has_url']} gõ được={info['typed_ok']} "
              f"trễ={info.get('input_latency_ms')}ms {info.get('note', '')}", flush=True)
    return info
