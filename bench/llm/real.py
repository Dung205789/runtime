from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import uuid
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
os.environ.update(
    HTTP_PROXY="http://127.0.0.1:9",
    HTTPS_PROXY="http://127.0.0.1:9",
    NO_PROXY="api.anthropic.com,generativelanguage.googleapis.com,127.0.0.1,localhost",
)

import psutil
from playwright.async_api import async_playwright

from bench.core.contract import RunRecord, append_record, machine_info, now_iso
from bench.llm import budget, chrome
from bench.llm.guard import GUEST_EMAIL, GUEST_NAME, GUEST_PHONE, SubmitGuard
from bench.llm.runner import MAX_CONTEXT_CHARS, python_cells, save_transcript
from bench.llms import cost_usd, get_llm

SUITE = "vn5b"
OUT = Path("results/llm/real/real.jsonl")
CACHE = Path("results/llm/real/cache")
SITES = {
    "real_lauphan": "https://lauphan.com/dat-ban?type=lauphan",
    "real_tong": "https://tong.com.vn/dat-ban",
    "real_chaoxian": "https://chaoxian.com.vn/dat-ban",
    "real_lauwang": "https://lauwang.vn/dat-ban/",
    "real_kingbbq": "https://kingbbq.vn/dat-ban/",
}
VARIANTS = {"A": (2, "19:00"), "B": (3, "18:00"), "C": (4, "20:00")}
STEPS, SECONDS = 30, 300
FORBIDDEN = re.compile(r"fetch\(|XMLHttpRequest|\.submit\(|requestSubmit|subprocess|http_get|urllib|socket|httpx|requests\.|open\(|eval\(|exec\(|__import__")

PROMPT = """Bạn là agent đặt bàn đang chạy THỬ trên web thật: {url}
Mục tiêu: điền form đặt bàn (chi nhánh bất kỳ): {party} người, ngày mai ({date}), giờ {time}, tên {name}, SĐT {phone}, email {email} nếu form có ô email.
DỪNG NGAY khi form đã điền xong và chỉ còn nút gửi/xác nhận cuối cùng. TUYỆT ĐỐI KHÔNG bấm nút đó, không yêu cầu OTP, không đăng nhập, không thanh toán.
Một lớp bảo vệ chặn việc gửi đơn. Nếu trang không chạy tiếp vì bị chặn, hãy báo lại; đừng tìm cách vượt.
Nếu gặp CAPTCHA hoặc trang chống bot: dừng và báo, không giải. Chỉ thao tác trên giao diện web, không gọi HTTP trực tiếp, không dùng script để gửi form.
Trước khi kết thúc, để nguyên trang đã điền trên màn hình. Kết thúc bằng JSON:
{{"status": "ready" | "blocked" | "unavailable" | "guarded" | "failed", "reason": "<ngắn gọn>", "final_button": "<chữ trên nút cuối, nếu thấy>"}}"""

HINT = """Lần trước bạn đã điền xong chính form này cho {party} người, giờ {time}. Dưới đây là các cell Python đã chạy. Dùng lại cách làm đó với dữ liệu của lần này, gộp thành ít cell nhất có thể, rồi kiểm tra giá trị các ô.

```python
{code}
```"""

COMPILE = """Dưới đây là các cell Python (helper browser-harness: goto_url, wait_for_load, js, cdp, click_at_xy, type_text, press_key, wait_for_element) mà một agent đã chạy để điền form đặt bàn tại {url} cho {party} người, giờ {time}, ngày mai ({date}), tên {name}, SĐT {phone}, email {email}.
Viết lại thành MỘT script Python ổn định, không cần LLM, dùng các biến có sẵn: PARTY (int), HHMM (chuỗi "HH:MM"), DATE_ISO, DATE_DMY ("dd/mm/yyyy"), NAME, PHONE, EMAIL.
Yêu cầu: mở trang; chờ phần tử bằng vòng lặp ngắn (tối đa 15 giây, mỗi lần 0.2 giây) thay vì sleep dài; chọn chi nhánh như bản cũ; với select thì tìm option theo nội dung/giá trị ứng với biến, gán value rồi dispatch input và change; chờ danh sách giờ tải xong trước khi chọn giờ; điền các ô; cuối cùng raise nếu giá trị các ô không đúng. js(expr) trả về giá trị JSON, muốn nhiều câu lệnh thì dùng IIFE.
CẤM: bấm hoặc gọi nút gửi, submit form, fetch, XMLHttpRequest, http_get, subprocess, đọc/ghi file, thư viện mạng.
Ô không tồn tại trên trang (ví dụ email) thì bỏ qua. Ô ngày có thể là select ghi "Ngày mai". Đừng tự khẳng định tên ô: dựa vào code và danh sách ô thật bên dưới.
Chỉ trả về code Python trong một khối ```python.

Danh sách ô trên trang:
{fields}

Code cũ:
{code}
{feedback}"""

SNAP_JS = """() => ({
  url: location.href,
  vals: [...document.querySelectorAll('input,select,textarea')]
    .filter(e => e.type !== 'hidden' && e.value)
    .map(e => [e.name || e.id || e.placeholder || e.type,
      e.type === 'checkbox' || e.type === 'radio' ? (e.checked ? 'checked' : '')
        : (e.selectedOptions && e.selectedOptions[0] ? e.selectedOptions[0].text : e.value)])
    .filter(x => x[1]).slice(0, 40)
})"""


def tomorrow() -> dt.date:
    return dt.date.today() + dt.timedelta(days=1)


def check_form(vals: list, party: int, hhmm: str) -> dict:
    texts = [str(v).strip() for _, v in vals]
    d = tomorrow()
    dates = {f"{d:%d/%m/%Y}", f"{d.day}/{d.month}/{d.year}", f"{d:%Y-%m-%d}", f"{d:%d-%m-%Y}", "ngày mai"}
    hh, mm = hhmm.split(":")
    joined = any(re.match(rf"^{hh}\s*[:hH]\s*{mm}", t) for t in texts)
    split = any(re.match(rf"^{hh}\s*H?$", t) for t in texts) and any(re.match(rf"^{mm}\D*$", t) for t in texts)
    return {
        "name": any(t.lower() == GUEST_NAME.lower() for t in texts),
        "phone": any(re.sub(r"\D", "", t) == GUEST_PHONE for t in texts),
        "party": any(re.match(rf"^0*{party}(\s*(người|khách).*)?$", t, re.I) for t in texts),
        "time": joined or split,
        "date": any(t.lower() in dates for t in texts),
    }


def cache_file(model: str, site: str) -> Path:
    return CACHE / model / f"{site}.json"


async def compile_script(model: str, site: str, learned: dict) -> dict:
    from pydantic_ai import Agent as PAgent

    f = cache_file(model, site)
    t0 = time.perf_counter()
    prompt = COMPILE.format(
        url=SITES[site], party=learned["party"], time=learned["time"], date=f"{tomorrow():%d/%m/%Y}", name=GUEST_NAME,
        phone=GUEST_PHONE, email=GUEST_EMAIL, code="\n\n# ---- cell ----\n".join(learned["cells"]),
        fields=learned.get("fields", "(chưa có)"), feedback=learned.get("feedback", ""),
    )
    r = await PAgent(get_llm(model).pydantic_model()).run(prompt, model_settings={"max_tokens": 12000})
    u = r.usage() if callable(r.usage) else r.usage
    m = re.search(r"```(?:python)?\s*\n(.*?)```", r.output, re.S)
    code = m.group(1) if m else ""
    learned["script"] = code if code and not FORBIDDEN.search(code) else ""
    learned["script_rejected"] = [] if learned["script"] else (FORBIDDEN.findall(code) or ["no code"])
    learned["compile_ms"] = learned.get("compile_ms", 0) + (time.perf_counter() - t0) * 1000
    learned["compiles"] = learned.get("compiles", 0) + 1
    learned["last_compile_cost"] = cost_usd(
        model, {"input": u.input_tokens, "output": u.output_tokens, "cache_read": u.cache_read_tokens, "cache_write": u.cache_write_tokens}
    )
    learned["compile_cost_usd"] = learned.get("compile_cost_usd", 0) + learned["last_compile_cost"]
    f.write_text(json.dumps(learned, ensure_ascii=False, indent=1), encoding="utf-8")
    return learned


async def run_site(site: str, model: str, mode: str, variant: str, rep: int) -> RunRecord:
    from browser_use import Agent, Browser

    party, hhmm = VARIANTS[variant]
    rec = RunRecord(
        run_id=uuid.uuid4().hex[:12], axis="llm", task_id=f"{site}:{variant}", site=site, provider="chrome_local", model=model,
        cache_mode="actions" if mode == "replay" else mode, rep=rep, warmup=False, outcome="failed", started_at=now_iso(),
        machine=machine_info(), versions={"browser_use": version("browser-use"), "suite": SUITE, "mode": mode, "variant": variant},
    )
    v = rec.versions
    learned = json.loads(cache_file(model, site).read_text(encoding="utf-8")) if mode != "none" and cache_file(model, site).exists() else None
    if mode != "none" and learned is None:
        rec.outcome, rec.error = "skipped", "no successful cold run to learn from"
        append_record(OUT, rec)
        return rec
    if mode == "replay":
        if not learned.get("script"):
            rec.outcome, rec.error = "failed", f"replay script rejected: {learned.get('script_rejected', [])[:3]}"
            append_record(OUT, rec)
            return rec

    last: dict | None = None
    snap_ms = 0.0
    guard, result, agent = SubmitGuard(), None, None
    box = {"n": 0, "out": ""}
    shots = Path("results/llm/real/shots")
    shots.mkdir(parents=True, exist_ok=True)
    c = chrome.launch(headless=False)
    rec.session_create_ms = c.create_ms
    psutil.cpu_percent(None)
    try:
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(c.cdp_url)
            await guard.install(b.contexts[0])

            async def snap(shot: bool = False) -> None:
                nonlocal last
                best = None
                for pg in b.contexts[0].pages:
                    for fr in pg.frames:
                        try:
                            d = await asyncio.wait_for(fr.evaluate(SNAP_JS), 3)
                        except Exception:
                            continue
                        if d["vals"] and (best is None or len(d["vals"]) > len(best["vals"])):
                            best = d
                    if shot and pg.url.startswith("http"):
                        try:
                            await pg.screenshot(path=str(shots / f"{site}_{rec.run_id}.png"), timeout=4000)
                        except Exception:
                            pass
                if best:
                    last = best

            async def watch() -> None:
                while True:
                    await asyncio.sleep(2)
                    await snap()

            async def scripted(messages, info):
                nonlocal snap_ms
                from pydantic_ai.messages import ModelResponse, ToolCallPart

                box["n"] += 1
                if box["n"] == 1:
                    d = tomorrow()
                    head = (
                        "import time, json, re\n"
                        f"PARTY={party!r}; HHMM={hhmm!r}; DATE_ISO={d.isoformat()!r}; DATE_DMY={f'{d:%d/%m/%Y}'!r}; "
                        f"NAME={GUEST_NAME!r}; PHONE={GUEST_PHONE!r}; EMAIL={GUEST_EMAIL!r}\n"
                    )
                    return ModelResponse(parts=[ToolCallPart("python", {"code": head + learned["script"]})])
                for m in messages:
                    for part in m.parts:
                        if type(part).__name__ == "ToolReturnPart" and part.tool_name == "python":
                            box["out"] = str(part.content)[:1500]
                t = time.perf_counter()
                await snap(True)
                snap_ms += (time.perf_counter() - t) * 1000
                return ModelResponse(parts=[ToolCallPart("finish", {"result": '{"status": "ready", "reason": "replay"}', "success": True})])

            kw = {}
            if mode == "replay":
                from pydantic_ai.models.function import FunctionModel

                llm = FunctionModel(scripted)
            else:
                llm = get_llm(model)
                llm.pydantic_model()
            if mode == "actions":
                kw["extend_system_message"] = HINT.format(
                    party=learned["party"], time=learned["time"], code="\n\n# ---- cell ----\n".join(learned["cells"])
                )
            prompt = PROMPT.format(
                url=SITES[site], party=party, date=f"{tomorrow():%d/%m/%Y}", time=hhmm, name=GUEST_NAME, phone=GUEST_PHONE, email=GUEST_EMAIL
            )
            watcher = asyncio.create_task(watch())
            t0 = time.perf_counter()
            try:
                agent = Agent(
                    prompt, llm, browser=Browser(cdp_url=c.cdp_url, keep_alive=True), judge=False, highlight_actions=False,
                    max_context_chars=MAX_CONTEXT_CHARS, **kw,
                )
                result = await agent.run(max_steps=STEPS, timeout=SECONDS)
            except Exception as e:
                rec.outcome, rec.error = "crashed", f"{type(e).__name__}: {e}"[:400]
            finally:
                rec.total_ms = (time.perf_counter() - t0) * 1000 - snap_ms
                watcher.cancel()
                await snap(True)
                if agent:
                    await agent.close()
    finally:
        await asyncio.to_thread(c.stop)

    v["load_end"] = {"cpu_pct": psutil.cpu_percent(None), "ram_free_gb": round(psutil.virtual_memory().available / 2**30, 1)}
    v["agent_status"] = None
    if result is not None:
        txt = result.text or ""
        m = re.search(r'"status"\s*:\s*"(\w+)"', txt)
        v["final_text"], v["agent_status"] = txt[:500], m.group(1) if m else result.status
        v["agent_loop_s"] = round(result.duration_s, 1)
        rec.steps = 0 if mode == "replay" else result.steps
        if mode != "replay":
            u = dict(result.usage)
            rec.tokens_in, rec.tokens_out = u["input"], u["output"]
            rec.tokens_cache_read, rec.tokens_cache_write = u["cache_read"], u["cache_write"]
            rec.llm_cost_usd = cost_usd(model, u)
        else:
            v["replay_out"] = box["out"][:400]
        save_transcript(rec.run_id, result.messages)
        vals = last["vals"] if last else []
        v["form"] = vals
        v["check"] = check_form(vals, party, hhmm)
        if v["agent_status"] == "ready" and all(v["check"].values()):
            rec.outcome = "success"
        elif v["agent_status"] == "ready":
            rec.outcome = "wrong_data"
        elif v["agent_status"] == "blocked":
            rec.outcome = "blocked"
    noise = ("google", "facebook", "doubleclick", "tiktok", "analytics", "oncustomer")
    v["guard_blocked"] = [x for x in guard.blocked if not any(k in x["url"] for k in noise)][-20:]
    v["guard_submit_attempts"] = sum(x["why"] in ("guest data leaving the page", "identity fields in body") for x in guard.blocked)
    v["guard_allowed_posts"] = sorted(set(guard.allowed_posts))
    if rec.outcome == "success" and v["guard_submit_attempts"]:
        rec.outcome, rec.error = "failed", "guest data was sent and blocked by the guard"
    append_record(OUT, rec)
    if rec.outcome == "success" and mode == "none" and variant == "A" and not cache_file(model, site).exists():
        f = cache_file(model, site)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps(
                {"site": site, "party": party, "time": hhmm, "cells": python_cells(result.messages), "learn_cost_usd": rec.llm_cost_usd,
                 "learn_ms": rec.total_ms, "run_id": rec.run_id}, ensure_ascii=False, indent=1,
            ),
            encoding="utf-8",
        )
    return rec


FIELDS_JS = """() => [...document.querySelectorAll('input,select,textarea')].filter(e => e.type !== 'hidden').map(e => ({tag: e.tagName, type: e.type, id: e.id, name: e.name, placeholder: e.placeholder || '', visible: !!e.offsetParent, options: e.options ? [...e.options].slice(0, 14).map(o => o.value + '|' + o.text) : undefined}))"""


async def read_fields(site: str) -> str:
    c = chrome.launch(headless=False)
    try:
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(c.cdp_url)
            await SubmitGuard().install(b.contexts[0])
            pg = b.contexts[0].pages[0]
            await pg.goto(SITES[site], wait_until="domcontentloaded", timeout=40000)
            await pg.wait_for_timeout(5000)
            return json.dumps(await pg.evaluate(FIELDS_JS), ensure_ascii=False)[:6000]
    finally:
        await asyncio.to_thread(c.stop)


async def train_replay(site: str, model: str) -> None:
    f = cache_file(model, site)
    if not f.exists():
        return
    learned = json.loads(f.read_text(encoding="utf-8"))
    if learned.get("trained") is not None:
        return
    for k in ("script", "compile_ms", "compile_cost_usd", "compiles", "feedback"):
        learned.pop(k, None)
    learned["fields"] = await read_fields(site)
    t0 = time.perf_counter()
    for attempt in range(1, 4):
        learned = await compile_script(model, site, learned)
        r = await run_site(site, model, "replay", "C", attempt)
        v = r.versions
        print("  train", site[5:], attempt, r.outcome, v.get("check"), (v.get("replay_out") or r.error or "")[-200:], flush=True)
        if r.outcome == "success":
            learned["trained"] = True
            break
        learned["feedback"] = (
            "\nScript trước đó:\n" + learned.get("script", "") + "\n\nChạy thử (4 người, 20:00) bị lỗi. Kết quả:\n" + (v.get("replay_out") or r.error or "")[-1200:]
            + f"\nÔ đúng/sai: {v.get('check')}\nGiá trị form lúc dừng: {v.get('form')}\nHãy sửa lại toàn bộ script."
        )
    else:
        learned["trained"] = False
    learned["train_ms"] = (time.perf_counter() - t0) * 1000
    f.write_text(json.dumps(learned, ensure_ascii=False, indent=1), encoding="utf-8")


def done(model: str) -> set:
    if not OUT.exists():
        return set()
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    return {
        (r["site"], r["versions"]["mode"], r["versions"]["variant"], r["rep"])
        for r in rows
        if r["versions"].get("suite") == SUITE and r["model"] == model and r["outcome"] not in ("skipped", "crashed")
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--sites", default=",".join(SITES))
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--learn-only", action="store_true")
    ap.add_argument("--modes", default="none,actions,replay")
    a = ap.parse_args()
    proof = Path("results/llm/real/guard_proof.json")
    digest = hashlib.sha256(Path("bench/llm/guard.py").read_bytes()).hexdigest()
    if not proof.exists() or json.loads(proof.read_text()).get("sha256") != digest:
        print("TỪ CHỐI: guard.py chưa được kiểm chứng; chạy python -m bench.llm.guard_check")
        return 4
    sites = a.sites.split(",")
    queue = [(s, "none", "A", 1) for s in sites]
    if not a.learn_only:
        for r in range(1, a.rounds + 1):
            for s in sites:
                queue += [(s, "none", "B", r), (s, "actions", "B", r), (s, "replay", "B", r)]
    modes = a.modes.split(",")
    queue = [q for q in queue if q[1] in modes or q[2] == "A"]
    seen = done(a.model)
    for s, mode, variant, rep in queue:
        if (s, mode, variant, rep) in seen:
            continue
        ok, msg = budget.check(a.model)
        if not ok:
            print("DỪNG ngân sách", msg)
            return 3
        if mode == "replay":
            await train_replay(s, a.model)
        r = await run_site(s, a.model, mode, variant, rep)
        v = r.versions
        bad = [k for k, x in (v.get("check") or {}).items() if not x]
        print(
            a.model, s[5:], mode, variant, rep, "→", r.outcome, v.get("agent_status"), f"{(r.total_ms or 0) / 1000:.1f}s", r.steps,
            f"${r.llm_cost_usd:.4f}", "sai:" + ",".join(bad) if bad else "", "| gửi bị chặn:", v.get("guard_submit_attempts"),
            "cpu", (v.get("load_end") or {}).get("cpu_pct"), "|", (r.error or "")[:200], flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
