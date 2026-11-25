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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from bench.llm import real as R  # sets the network block and loads .env first

import psutil
from playwright.async_api import async_playwright

from bench.core.contract import RunRecord, append_record, machine_info, now_iso
from bench.llm import budget, chrome
from bench.llm.guard import GUEST_EMAIL, GUEST_NAME, GUEST_PHONE, SubmitGuard
from bench.llm.runner import MAX_CONTEXT_CHARS, save_transcript
from bench.llms import cost_usd, get_llm

OUT = Path("results/llm/real/combo.jsonl")
SCRIPTS = Path("results/llm/real/scripts")
HAIKU = "claude-haiku-5-5"
BRANCH_FIELDS = {
    "real_lauphan": "selectCoso", "real_chaoxian": "selectCoso", "real_tong": "selectCoso", "real_lauwang": "address", "real_kingbbq": "inputRestaurant",
}
PHONE_FIELDS = ["sdtOrder", "phone", "inputPhone"]
SAFE_ENV = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PASSWORD", k, re.I)}


@dataclass(frozen=True)
class Case:
    cid: str
    party: int
    hhmm: str
    day: int = 1
    name: str = GUEST_NAME
    alt_branch: bool = False


BASE = Case("B", 3, "18:00")
TRAIN = [Case("T1", 4, "20:00"), Case("T2", 2, "19:00", 2, "Khách Thử Nghiệm", True)]
CHECKS = [
    Case("c01", 2, "18:00"), Case("c02", 5, "19:30"), Case("c03", 8, "11:30"), Case("c04", 6, "20:30"),
    Case("c05", 2, "18:30", 2), Case("c06", 4, "19:00", 2), Case("c07", 3, "12:00", 2, "Khách Thử Nghiệm Ánh"),
    Case("c08", 2, "19:00", 1, "Nguyễn Thử Nghiệm"), Case("c09", 4, "18:00", 1, GUEST_NAME, True),
    Case("c10", 7, "20:00", 2, "Khách Thử Nghiệm", True), Case("c11", 2, "18:15"), Case("c12", 2, "03:00"),
]

COMPILE = """Viết MỘT script Python ổn định, KHÔNG dùng LLM, điền form đặt bàn tại {url}. Biến có sẵn: PARTY (int), HHMM ("HH:MM"), DATE_ISO ("YYYY-MM-DD"), DATE_DMY ("dd/mm/yyyy"), DAY_OFFSET (1 = ngày mai, 2 = ngày kia), NAME, PHONE, EMAIL, BRANCH (chuỗi tên chi nhánh cần chọn, hoặc None thì dùng chi nhánh trong code cũ).
Helper có sẵn (đồng bộ): goto_url(url), wait_for_load(), js(expr) trả giá trị JSON (nhiều câu lệnh thì dùng IIFE), cdp(method, **params), click_at_xy(x, y), type_text(text), press_key(key), wait_for_element(selector).
Yêu cầu:
- Trang ĐÃ được mở sẵn và đang tải: KHÔNG gọi goto_url/new_tab; chỉ chờ form xuất hiện.
- Ngắn gọn, dưới 130 dòng, không viết hàm thừa.
- Tự import time, json, re nếu cần. Chờ bằng vòng lặp 0.1-0.2 giây, tối đa 15 giây; không sleep dài.
- Với select: tìm option khớp CHÍNH XÁC yêu cầu, gán value, dispatch input và change (bubbles). Nếu trang dùng widget bọc select thì vẫn gán select gốc. Nếu chọn chi nhánh/ngày/số người làm tải lại danh sách giờ thì chọn chúng TRƯỚC và chờ danh sách giờ mới ổn định rồi mới chọn giờ.
- Ô ngày có thể là select ghi "Ngày mai", "Ngày kia" hoặc ngày cụ thể. Ô không tồn tại (ví dụ email) thì bỏ qua.
- Nếu không có đúng giờ, đúng số người, đúng ngày hoặc đúng chi nhánh được yêu cầu, hoặc option bị disabled: raise RuntimeError("UNAVAILABLE: ...") ngay khi chắc chắn. KHÔNG chọn giá trị gần đúng.
- Cuối cùng đọc lại value thật của mọi ô và raise RuntimeError("MISMATCH: ...") nếu lệch.
CẤM: bấm hoặc gọi nút gửi, submit form, fetch, XMLHttpRequest, subprocess, đọc/ghi file, thư viện mạng.
Chỉ trả về code trong một khối ```python.

Danh sách ô trên trang (JSON):
{fields}

Các cell một agent đã chạy thành công ({party} người, {time}, ngày mai):
{code}
{feedback}"""

MUTATE = """(() => {
  const names = %s;
  const fix = () => { for (const n of names) for (const e of document.querySelectorAll('input#' + n + ',input[name="' + n + '"]')) { e.id = 'lienhe_x1'; e.name = 'lienhe_x1'; } };
  document.addEventListener('DOMContentLoaded', () => { fix(); new MutationObserver(fix).observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['id', 'name']}); });
})();""" % json.dumps(PHONE_FIELDS)

SNAP = """() => ({
  vals: [...document.querySelectorAll('input,select,textarea')].filter(e => e.type !== 'hidden' && e.value).map(e => [e.name || e.id || e.type, e.type === 'checkbox' || e.type === 'radio' ? (e.checked ? 'checked' : '') : (e.selectedOptions && e.selectedOptions[0] ? (e.selectedOptions[0].text.trim() || e.value) : e.value)]).filter(x => x[1]).slice(0, 40),
  nav: (() => { const n = performance.getEntriesByType('navigation')[0]; return n ? {dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd} : null; })()
})"""

LLM_LOG: list[tuple[float, float]] = []


def patch(model) -> None:
    cls = type(model)
    if getattr(cls, "_timed", False):
        return
    cls._timed = True
    o_req, o_stream = cls.request, cls.request_stream

    async def request(self, *a, **k):
        t = time.perf_counter()
        try:
            return await o_req(self, *a, **k)
        finally:
            LLM_LOG.append((t, time.perf_counter()))

    @asynccontextmanager
    async def request_stream(self, *a, **k):
        t = time.perf_counter()
        async with o_stream(self, *a, **k) as r:
            try:
                yield r
            finally:
                LLM_LOG.append((t, time.perf_counter()))

    cls.request, cls.request_stream = request, request_stream


def day(c: Case) -> dt.date:
    return dt.date.today() + dt.timedelta(days=c.day)


def check(vals: list, c: Case, branch: str | None) -> dict:
    base = R.check_form(vals, c.party, c.hhmm)
    texts = [str(v).strip() for _, v in vals]
    d = day(c)
    dates = {f"{d:%d/%m/%Y}", f"{d.day}/{d.month}/{d.year}", f"{d:%Y-%m-%d}", f"{d:%d-%m-%Y}", {1: "ngày mai", 2: "ngày kia"}[c.day]}
    base["date"] = any(t.lower() in dates for t in texts)
    base["name"] = any(t == c.name for t in texts)
    if branch:
        base["branch"] = any(t == branch for t in texts)
    return base


def head(c: Case, branch: str | None, site: str | None = None, script: str = "") -> str:
    d = day(c)
    v = dict(PARTY=c.party, HHMM=c.hhmm, DATE_ISO=d.isoformat(), DATE_DMY=f"{d:%d/%m/%Y}", DAY_OFFSET=c.day, NAME=c.name, PHONE=GUEST_PHONE, EMAIL=GUEST_EMAIL, BRANCH=branch)
    opened = "goto_url(" in script or "new_tab(" in script
    go = "" if site is None or opened else f"new_tab({R.SITES[site]!r}); wait_for_load()\n"
    return "import time, json, re\n" + "\n".join(f"{k}={x!r}" for k, x in v.items()) + "\n" + go


def load_script(site: str) -> dict:
    f = SCRIPTS / f"{site}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def record(site, model, kind, c: Case, rep, **kw) -> RunRecord:
    r = RunRecord(
        run_id=uuid.uuid4().hex[:12], axis="llm", task_id=f"{site}:{c.cid}", site=site, provider="chrome_local", model=model,
        cache_mode="none" if kind in ("cold", "failover") else "actions", rep=rep, warmup=False, outcome="failed", started_at=now_iso(),
        machine=machine_info(), versions={"suite": "combo", "kind": kind, "case": c.cid, **kw},
    )
    psutil.cpu_percent(None)
    return r


def finish(r: RunRecord) -> RunRecord:
    r.versions["cpu_pct"] = psutil.cpu_percent(None)
    r.versions["rpa"] = rpa_running()
    append_record(OUT, r)
    v = r.versions
    bad = [k for k, x in (v.get("check") or {}).items() if not x]
    print(
        f"{v['kind']:9s} {r.model[:16]:16s} {r.site[5:]:9s} {v['case']:3s} r{r.rep} → {r.outcome:10s} {(r.total_ms or 0) / 1000:6.1f}s",
        f"${r.llm_cost_usd:.4f}", ("sai:" + ",".join(bad)) if bad else "", f"cpu {v['cpu_pct']:.0f}", (r.error or v.get("err") or "")[:170], flush=True,
    )
    return r


def rpa_running() -> int:
    n = 0
    for p in psutil.process_iter(["cmdline"]):
        try:
            n += "run_site.py" in " ".join(p.info["cmdline"] or [])
        except psutil.Error:
            pass
    return n


def guard_fields(r: RunRecord, g: SubmitGuard) -> None:
    v = r.versions
    v["guard_allowed_posts"] = sorted(set(g.allowed_posts))
    v["guard_submit_attempts"] = sum(x["why"] in ("guest data leaving the page", "identity fields in body") for x in g.blocked)
    if v["guard_submit_attempts"]:
        v["guard_hits"] = [x for x in g.blocked if x["why"] in ("guest data leaving the page", "identity fields in body")][:5]


async def best_snap(ctx) -> dict:
    best = {"vals": [], "nav": None}
    for pg in ctx.pages:
        for fr in pg.frames:
            try:
                d = await asyncio.wait_for(fr.evaluate(SNAP), 4)
            except Exception:
                continue
            if len(d["vals"]) > len(best["vals"]):
                best = d
    return best


class Direct:
    async def __aenter__(self):
        self.c = chrome.launch(headless=False)
        self.pw = await async_playwright().start()
        self.b = await self.pw.chromium.connect_over_cdp(self.c.cdp_url)
        self.ctx = self.b.contexts[0]
        self.guard = SubmitGuard()
        await self.guard.install(self.ctx)
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "bench.llm.direct_worker", self.c.cdp_url, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=SAFE_ENV, limit=2**20,
        )
        await asyncio.wait_for(self.proc.stdout.readline(), 60)
        return self

    async def send(self, text: str, timeout: float) -> dict:
        self.proc.stdin.write((text + "\n").encode())
        await self.proc.stdin.drain()
        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        if not line:
            raise RuntimeError("direct worker exited")
        return json.loads(line)

    async def run(self, site: str, script: str, c: Case, branch: str | None, kind: str, rep: int) -> RunRecord:
        self.guard.blocked.clear()
        self.guard.allowed_posts.clear()
        r = record(site, "none", kind, c, rep, branch=branch)
        t0 = time.perf_counter()
        res = await self.send(json.dumps({"code": head(c, branch, site, script) + script}), 150)
        r.total_ms = (time.perf_counter() - t0) * 1000
        s = await best_snap(self.ctx)
        r.steps = 0
        v = r.versions
        v["script_ms"], v["err"], v["out"], v["form"], v["nav"] = res["ms"], res["err"], res["out"], s["vals"], s["nav"]
        v["check"] = check(s["vals"], c, branch)
        ok = all(v["check"].values())
        if res["err"]:
            r.outcome = "blocked" if "UNAVAILABLE" in res["err"] else "failed"
        else:
            r.outcome = "success" if ok else "wrong_data"
        guard_fields(r, self.guard)
        await self.send("close", 30)
        return finish(r)

    async def __aexit__(self, *a):
        try:
            self.proc.kill()
        except ProcessLookupError:
            pass
        await self.pw.stop()
        await asyncio.to_thread(self.c.stop)


async def agent_run(site: str, model: str, c: Case, rep: int, kind: str, script: str | None = None, branch: str | None = None, mutate: bool = False) -> RunRecord:
    from browser_use import Agent, Browser

    r = record(site, model if script is None else "none", kind, c, rep, mutated=mutate)
    v = r.versions
    LLM_LOG.clear()
    t_begin = time.perf_counter()
    ch = chrome.launch(headless=False)
    r.session_create_ms = ch.create_ms
    g, result, agent, cells = SubmitGuard(), None, None, {"n": 0, "out": "", "t": 0.0}
    navs: list[float] = []
    snap = {"vals": [], "nav": None}
    try:
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(ch.cdp_url)
            ctx = b.contexts[0]
            await g.install(ctx)
            if mutate:
                await ctx.add_init_script(MUTATE)
            host = R.SITES[site].split("/")[2]
            ctx.on("request", lambda q: navs.append(time.perf_counter()) if q.is_navigation_request() and host in q.url else None)
            v["attach_ms"] = (time.perf_counter() - t_begin) * 1000 - ch.create_ms
            if script is not None:
                from pydantic_ai.messages import ModelResponse, ToolCallPart
                from pydantic_ai.models.function import FunctionModel

                async def scripted(messages, info):
                    cells["n"] += 1
                    if cells["n"] == 1:
                        cells["t"] = time.perf_counter()
                        return ModelResponse(parts=[ToolCallPart("python", {"code": head(c, branch, site, script) + script})])
                    v["cell_ms"] = (time.perf_counter() - cells["t"]) * 1000
                    for m in messages:
                        for part in m.parts:
                            if type(part).__name__ == "ToolReturnPart" and part.tool_name == "python":
                                cells["out"] = str(part.content)[:1200]
                    return ModelResponse(parts=[ToolCallPart("finish", {"result": '{"status": "ready"}', "success": True})])

                llm = FunctionModel(scripted)
            else:
                llm = get_llm(model)
                patch(llm.pydantic_model())
            prompt = R.PROMPT.format(url=R.SITES[site], party=c.party, date=f"{day(c):%d/%m/%Y}", time=c.hhmm, name=c.name, phone=GUEST_PHONE, email=GUEST_EMAIL)
            t0 = time.perf_counter()
            try:
                agent = Agent(prompt, llm, browser=Browser(cdp_url=ch.cdp_url, keep_alive=True), judge=False, highlight_actions=False, max_context_chars=MAX_CONTEXT_CHARS)
                result = await agent.run(max_steps=R.STEPS, timeout=R.SECONDS)
            except Exception as e:
                r.outcome, r.error = "crashed", f"{type(e).__name__}: {e}"[:400]
            r.total_ms = (time.perf_counter() - t0) * 1000
            snap = await best_snap(ctx)
            if agent:
                await agent.close()
    finally:
        await asyncio.to_thread(ch.stop)
    v["llm_ms"] = sum(e - s for s, e in LLM_LOG) * 1000
    v["llm_calls"] = len(LLM_LOG)
    first = LLM_LOG[0][0] if LLM_LOG else cells["t"]
    v["agent_start_ms"] = (first - t0) * 1000 if first else None
    v["first_nav_ms"] = (navs[0] - t0) * 1000 if navs else None
    v["nav"], v["form"] = snap["nav"], snap["vals"]
    if result is not None:
        txt = result.text or ""
        m = re.search(r'"status"\s*:\s*"(\w+)"', txt)
        v["agent_status"], v["final_text"] = (m.group(1) if m else result.status), txt[:400]
        if script is None:
            u = dict(result.usage)
            r.steps, r.tokens_in, r.tokens_out = result.steps, u["input"], u["output"]
            r.tokens_cache_read, r.tokens_cache_write = u["cache_read"], u["cache_write"]
            r.llm_cost_usd = cost_usd(model, u)
        else:
            r.steps, v["out"] = 0, cells["out"][:500]
        save_transcript(r.run_id, result.messages)
        v["check"] = check(snap["vals"], c, branch)
        if v["agent_status"] == "ready":
            r.outcome = "success" if all(v["check"].values()) else "wrong_data"
            if script is not None and "Error:" in cells["out"]:
                r.outcome = "failed"
        elif v["agent_status"] in ("blocked", "unavailable"):
            r.outcome = "blocked"
    guard_fields(r, g)
    if r.outcome == "success" and v["guard_submit_attempts"]:
        r.outcome, r.error = "failed", "guest data was sent and blocked by the guard"
    return finish(r)


async def train(site: str, d: Direct) -> None:
    if load_script(site).get("trained") or load_script(site).get("v") == 2:
        return
    from pydantic_ai import Agent as PAgent

    learned = json.loads(R.cache_file(HAIKU, site).read_text(encoding="utf-8"))
    pg = await d.ctx.new_page()
    await pg.goto(R.SITES[site], wait_until="domcontentloaded", timeout=40000)
    await pg.wait_for_timeout(6000)
    fields = await pg.evaluate(R.FIELDS_JS)
    f = BRANCH_FIELDS[site]
    opts = await pg.evaluate("n => { const e = document.getElementById(n) || document.querySelector('select[name=\"' + n + '\"]'); return e ? [...e.options].filter(o => o.value && !o.disabled).map(o => o.text.trim()) : []; }", f)
    await pg.close()
    branches = [o for o in opts if not re.search(r"chọn", o, re.I)]
    st = {"v": 2, "site": site, "branches": branches[:12], "alt_branch": branches[1] if len(branches) > 1 else None, "attempts": [], "cost_usd": 0.0, "learn_cost_usd": learned["learn_cost_usd"], "learn_ms": learned["learn_ms"], "trained": False}
    feedback, t0 = "", time.perf_counter()
    for attempt in range(1, 5):
        ok, msg = budget.check(HAIKU)
        if not ok:
            print("DỪNG ngân sách", msg)
            return
        q = COMPILE.format(url=R.SITES[site], party=learned["party"], time=learned["time"], fields=json.dumps(fields, ensure_ascii=False)[:6000], code="\n# ---- cell ----\n".join(learned["cells"]), feedback=feedback)
        tc = time.perf_counter()
        try:
            res = await PAgent(get_llm(HAIKU).pydantic_model()).run(q, model_settings={"max_tokens": 20000})
        except Exception as e:
            cr = record(site, HAIKU, "compile", TRAIN[0], attempt)
            cr.outcome, cr.error, cr.llm_cost_usd = "failed", f"{type(e).__name__}: {e}"[:200], 0.012
            cr.versions["cost_is_estimate"] = True
            st["cost_usd"] += 0.012
            finish(cr)
            continue
        u = res.usage() if callable(res.usage) else res.usage
        m = re.search(r"```(?:python)?\s*\n(.*?)```", res.output, re.S)
        code = m.group(1) if m else ""
        cr = record(site, HAIKU, "compile", TRAIN[0], attempt)
        cr.total_ms = (time.perf_counter() - tc) * 1000
        cr.llm_cost_usd = cost_usd(HAIKU, {"input": u.input_tokens, "output": u.output_tokens, "cache_read": u.cache_read_tokens, "cache_write": u.cache_write_tokens})
        cr.tokens_in, cr.tokens_out = u.input_tokens, u.output_tokens
        st["cost_usd"] += cr.llm_cost_usd
        bad = R.FORBIDDEN.findall(code) if code else ["no code"]
        cr.outcome = "failed" if bad else "success"
        cr.error = f"forbidden: {bad[:3]}" if bad else None
        finish(cr)
        if bad:
            feedback = f"\nScript trước bị từ chối vì chứa: {bad[:3]}. Viết lại không dùng các thứ đó."
            continue
        notes = []
        for c in TRAIN:
            br = st["alt_branch"] if c.alt_branch else None
            r = await d.run(site, code, c, br, "train", attempt)
            if r.outcome not in ("success", "blocked"):
                notes.append(f"Ca {c.party} người, {c.hhmm}, DAY_OFFSET={c.day}, BRANCH={br!r}, NAME={c.name!r}: lỗi={r.versions['err']} in ra={r.versions['out'][-300:]} đúng/sai={r.versions['check']} form={r.versions['form']}")
            elif r.outcome == "blocked":
                st["attempts"].append(f"{attempt}:{c.cid}:unavailable")
        good = not notes and not all(f"{attempt}:{c.cid}:unavailable" in st["attempts"] for c in TRAIN)
        if good:
            st["script"], st["trained"] = code, True
            break
        st["script"] = code
        feedback = "\nScript trước:\n" + code + "\n\nKết quả chạy thử:\n" + ("\n".join(notes) or "Cả hai ca đều báo UNAVAILABLE, kiểm tra lại cách tìm option.") + "\nSửa lại toàn bộ script."
    st["compiles"], st["train_ms"] = attempt, (time.perf_counter() - t0) * 1000
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    (SCRIPTS / f"{site}.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print("TRAINED", site, st["trained"], "lần:", attempt, f"${st['cost_usd']:.4f}", f"{st['train_ms'] / 1000:.0f}s", flush=True)


def seen() -> set:
    if not OUT.exists():
        return set()
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    return {(r["versions"]["kind"], r["model"], r["site"], r["versions"]["case"], r["rep"], bool(r["versions"].get("mutated"))) for r in rows if r["outcome"] != "crashed" and not r["versions"].get("void")}


def gemini() -> str | None:
    import httpx

    key = os.environ.get("GEMINI_API_KEY", "")
    for m in ("gemini-3.8-flash", "gemini-3.5-flash-lite"):
        good = 0
        for _ in range(3):
            try:
                q = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", headers={"x-goog-api-key": key}, json={"contents": [{"parts": [{"text": "ok"}]}]}, timeout=20)
                good += q.status_code == 200
                print("gemini probe", m, q.status_code, flush=True)
            except httpx.HTTPError as e:
                print("gemini probe", m, type(e).__name__, flush=True)
        if good == 3:
            return m
    return None


async def wait_idle(max_min: float) -> bool:
    end = time.monotonic() + max_min * 60
    calm = 0
    while time.monotonic() < end:
        cpu = await asyncio.to_thread(psutil.cpu_percent, 10)
        calm = calm + 1 if cpu < 45 and not rpa_running() else 0
        if calm >= 3:
            return True
        await asyncio.sleep(20)
    return False


async def phase1() -> None:
    done = seen()
    for s in R.SITES:
        try:
            async with Direct() as d:
                await train(s, d)
        except Exception as e:
            print("LỖI train", s, type(e).__name__, str(e)[:200], flush=True)
    async with Direct() as d:
        for s in R.SITES:
            st = load_script(s)
            if not st.get("script"):
                continue
            for c in CHECKS:
                if c.alt_branch and not st["alt_branch"]:
                    continue
                if ("check", "none", s, c.cid, 1, False) not in done:
                    try:
                        await d.run(s, st["script"], c, st["alt_branch"] if c.alt_branch else None, "check", 1)
                    except Exception as e:
                        print("LỖI check", s, c.cid, type(e).__name__, str(e)[:200], flush=True)
                        return
    for s in R.SITES:
        st = load_script(s)
        if not st.get("script") or ("failover", HAIKU, s, "B", 1, True) in done:
            continue
        async with Direct() as d:
            await d.ctx.add_init_script(MUTATE)
            det = await d.run(s, st["script"], BASE, None, "detect", 1)
        ok, msg = budget.check(HAIKU)
        if not ok:
            print("DỪNG ngân sách", msg)
            return
        if det.outcome != "success":
            await agent_run(s, HAIKU, BASE, 1, "failover", mutate=True)


async def phase2(reps: int, busy_ok: bool) -> None:
    gm = gemini()
    print("gemini model:", gm, flush=True)
    for rep in range(1, reps + 1):
        for s in R.SITES:
            done = seen()
            st = load_script(s)
            for kind, model in (("cold", HAIKU), ("cold", gm), ("replay", "none"), ("direct", "none")):
                if model and model in os.environ.get("COMBO_SKIP", "").split(","):
                    continue
                if model is None or (kind, model, s, "B", rep, False) in done:
                    continue
                if not busy_ok and rpa_running():
                    print("RPA chạy lại, tạm chờ máy rảnh", flush=True)
                    if not await wait_idle(180):
                        print("HẾT THỜI GIAN CHỜ máy rảnh", flush=True)
                        return
                try:
                    if kind == "cold":
                        ok, msg = budget.check(model)
                        if not ok:
                            print("DỪNG ngân sách", model, msg, flush=True)
                            continue
                        await agent_run(s, model, BASE, rep, "cold")
                    elif st.get("script") and kind == "replay":
                        await agent_run(s, "none", BASE, rep, "replay", script=st["script"])
                    elif st.get("script"):
                        async with Direct() as d:
                            await d.run(s, st["script"], Case("W", 2, "19:00"), None, "warm", rep)
                            await d.run(s, st["script"], BASE, None, "direct", rep)
                except Exception as e:
                    print("LỖI", kind, model, s, type(e).__name__, str(e)[:200], flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="1,2")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--wait-min", type=float, default=180)
    ap.add_argument("--busy-ok", action="store_true")
    a = ap.parse_args()
    proof = Path("results/llm/real/guard_proof.json")
    digest = hashlib.sha256(Path("bench/llm/guard.py").read_bytes()).hexdigest()
    if not proof.exists() or json.loads(proof.read_text()).get("sha256") != digest:
        print("TỪ CHỐI: guard.py chưa được kiểm chứng")
        return 4
    proof2 = Path("results/llm/real/guard_proof_direct.json")
    digest2 = hashlib.sha256(Path("bench/llm/guard.py").read_bytes() + Path("bench/llm/direct_worker.py").read_bytes()).hexdigest()
    if not proof2.exists() or json.loads(proof2.read_text()).get("sha256") != digest2:
        print("TỪ CHỐI: đường chạy trực tiếp chưa được kiểm chứng; chạy python -m bench.llm.guard_check_direct")
        return 4
    if "1" in a.phase:
        try:
            await phase1()
        except Exception as e:
            print("LỖI pha 1", type(e).__name__, str(e)[:300], flush=True)
    if "2" in a.phase:
        if not a.busy_ok:
            print("chờ máy rảnh...", flush=True)
            if not await wait_idle(a.wait_min):
                print("HẾT THỜI GIAN CHỜ: máy vẫn bận, chưa đo pha 2", flush=True)
                return 5
        await phase2(a.reps, a.busy_ok)
    print("XONG", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
