from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

import httpx

from bench.core.contract import (
    MAX_RUN_SECONDS,
    MAX_STEPS,
    BenchTask,
    CacheMode,
    Expected,
    RunRecord,
    grade,
    machine_info,
    now_iso,
    site_url,
)
from bench.llm import chrome
from bench.llm.devsite import DEV_PORT
from bench.llms import cost_usd, get_llm

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_NO_UPDATE_CHECK", "1")

PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
CACHE_DIR = Path("results/llm/cache")
PROFILE_DIR = Path("profiles/llm")
MAX_CONTEXT_CHARS = 300_000

DEV_TASKS = [
    BenchTask(
        "d01",
        "dev",
        "Đặt giúp mình bàn 2 người tối 12/12/2026 lúc 19:00, tên Nguyễn An, SĐT 0901234567.",
        Expected("2026-12-12", "19:00", 2, "Nguyễn An", "0901234567"),
        False,
    ),
    BenchTask(
        "d03",
        "dev",
        "Book a table for 4 on 2026-12-20 at 12:30 under Tran Binh, phone 0912 345 678.",
        Expected("2026-12-20", "12:30", 4, "Tran Binh", "0912345678"),
        False,
    ),
    BenchTask(
        "d02",
        "dev_otp",
        "Đặt bàn 4 người trưa 21/12/2026 lúc 12:00, tên Trịnh Quân, SĐT 0955666777.",
        Expected("2026-12-21", "12:00", 4, "Trịnh Quân", "0955666777"),
        True,
    ),
]


def base_url(site: str) -> str:
    if site.startswith("dev"):
        return f"http://127.0.0.1:{DEV_PORT}"
    return site_url(site)


def entry_url(site: str) -> str:
    if site == "dev_otp":
        return f"{base_url(site)}/?otp=1"
    return base_url(site) + "/"


def human_delay_s() -> float:
    return float(os.environ.get("BENCH_HUMAN_DELAY_S", "20"))


@dataclass
class HumanState:
    asked: int = 0
    wait_ms: float = 0.0
    questions: list[str] = field(default_factory=list)


HARNESS_HEADERS = {"X-Bench-Harness": "1"}


def read_otp(site: str) -> str | None:
    try:
        r = httpx.get(base_url(site) + "/_bench/otp", headers=HARNESS_HEADERS, timeout=5)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return r.text.strip() or None
    if isinstance(data, dict):
        for k in ("otp", "code", "value"):
            if data.get(k):
                return str(data[k])
        return None
    return str(data) if data else None


def make_tools(site: str, human: HumanState):
    from browser_use import Tools

    tools = Tools()

    @tools.action("Hỏi khách thông tin mà chỉ khách có, ví dụ mã OTP vừa gửi về điện thoại. Trả về câu trả lời của khách.")
    async def ask_human(question: str) -> str:
        human.asked += 1
        human.questions.append(question[:200])
        t0 = time.perf_counter()
        await asyncio.sleep(human_delay_s())
        answer = read_otp(site)
        human.wait_ms += (time.perf_counter() - t0) * 1000
        return answer or "Khách không có thông tin này."

    return tools


def python_cells(messages) -> list[str]:
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    cells: list[str] = []
    for m in messages:
        if not isinstance(m, ModelResponse):
            continue
        for part in m.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == "python":
                code = part.args_as_dict().get("code")
                if code:
                    cells.append(code)
    return cells


def cache_path(model: str, task: BenchTask) -> Path:
    return CACHE_DIR / model / f"{task.site}__{task.task_id}.json"


def save_code_cache(model: str, task: BenchTask, cells: list[str], record: RunRecord) -> None:
    p = cache_path(model, task)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task.task_id,
        "site": task.site,
        "expected": task.expected.__dict__,
        "cells": cells,
        "learn_cost_usd": record.llm_cost_usd,
        "learn_ms": record.total_ms,
        "learn_steps": record.steps,
        "run_id": record.run_id,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def find_code_cache(model: str, task: BenchTask) -> dict | None:
    d = CACHE_DIR / model
    if not d.exists():
        return None
    for p in sorted(d.glob(f"{task.site}__*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if data["task_id"] != task.task_id:
            return data
    return None


def code_hint(cache: dict) -> str:
    code = "\n\n# --- next cell ---\n\n".join(cache["cells"])
    e = cache["expected"]
    return (
        "Bạn đã đặt bàn thành công trên đúng trang này trước đó, cho một khách khác "
        f"(ngày {e['date']}, giờ {e['time']}, {e['party_size']} người, tên {e['name']}, SĐT {e['phone']}). "
        "Dưới đây là các cell Python đã chạy lần đó. Hãy dùng lại cách làm này, thay bằng dữ liệu của khách hiện tại, "
        "gộp thành ít cell nhất có thể, và vẫn kiểm tra kết quả như thường.\n\n```python\n" + code + "\n```"
    )


async def run_one(
    task: BenchTask,
    model: str,
    cache_mode: CacheMode,
    rep: int,
    warmup: bool,
    out: Path,
    axis: str = "llm",
) -> RunRecord:
    from browser_use import Agent, Browser

    from bench.core.contract import append_record

    rec = RunRecord(
        run_id=uuid.uuid4().hex[:12],
        axis=axis,
        task_id=task.task_id,
        site=task.site,
        provider="chrome_local",
        model=model,
        cache_mode=cache_mode,
        rep=rep,
        warmup=warmup,
        outcome="failed",
        started_at=now_iso(),
        machine=machine_info(),
        versions={"browser_use": version("browser-use"), "pydantic_ai": version("pydantic-ai-slim")},
    )
    hint = None
    if cache_mode == "actions":
        cache = find_code_cache(model, task)
        if cache is None:
            rec.outcome, rec.error = "skipped", "no code cache from another successful task on this site"
            append_record(out, rec)
            return rec
        hint = code_hint(cache)
        rec.versions["cache_from"] = cache["run_id"]

    httpx.post(base_url(task.site) + "/_bench/reset", timeout=10).raise_for_status()
    if task.site == "s4_guarded":
        httpx.post(base_url(task.site) + "/_bench/reset_rate", timeout=10).raise_for_status()
    profile = PROFILE_DIR / model / task.site if cache_mode == "session" else None
    human = HumanState()
    browser_proc = None
    agent = None
    result = None
    peak = 0.0
    llm = get_llm(model)
    llm.pydantic_model()
    t0 = time.perf_counter()
    try:
        browser_proc = chrome.launch(profile_dir=profile)
        rec.session_create_ms = browser_proc.create_ms
        agent = Agent(
            PROMPT.format(url=entry_url(task.site), instruction=task.instruction),
            llm,
            browser=Browser(cdp_url=browser_proc.cdp_url),
            tools=make_tools(task.site, human),
            extend_system_message=hint,
            judge=False,
            highlight_actions=False,
            max_context_chars=MAX_CONTEXT_CHARS,
        )

        async def sample() -> None:
            nonlocal peak
            while True:
                peak = max(peak, browser_proc.peak_rss_mb())
                await asyncio.sleep(0.5)

        sampler = asyncio.create_task(sample())
        try:
            result = await agent.run(max_steps=MAX_STEPS, timeout=MAX_RUN_SECONDS + human_delay_s() * 3)
        finally:
            sampler.cancel()
    except Exception as e:
        rec.outcome, rec.error = "crashed", f"{type(e).__name__}: {e}"[:500]
    finally:
        rec.total_ms = (time.perf_counter() - t0) * 1000
        if agent is not None:
            try:
                await agent.close()
            except Exception:
                pass
        if browser_proc is not None:
            browser_proc.stop()

    rec.peak_pss_mb = round(peak, 1) or None
    rec.human_wait_ms = human.wait_ms
    if result is not None:
        u = dict(result.usage)
        rec.steps = result.steps
        rec.tokens_in = u.get("input", 0)
        rec.tokens_out = u.get("output", 0)
        rec.tokens_cache_read = u.get("cache_read", 0)
        rec.tokens_cache_write = u.get("cache_write", 0)
        rec.llm_cost_usd = cost_usd(model, u)
        rec.versions["bu_cost_usd"] = result.cost_usd
        rec.versions["bu_status"] = result.status
        rec.versions["agent_loop_s"] = round(result.duration_s, 2)
        rec.versions["final_text"] = (result.text or "")[:300]
        if result.error:
            rec.error = result.error[:500]

    if rec.outcome != "crashed":
        bookings = httpx.get(base_url(task.site) + "/_bench/bookings", timeout=10).json()
        rec.outcome = grade(task, bookings)
        if rec.outcome == "failed" and result is not None and result.status in ("timeout", "max_steps"):
            rec.outcome = "timeout"
        if rec.outcome == "wrong_data":
            rec.versions["bookings"] = bookings
        if task.site == "s4_guarded" and rec.outcome != "success":
            try:
                rec.versions["s4_blocks"] = httpx.get(base_url(task.site) + "/_bench/blocks", timeout=10).json()[-5:]
            except (httpx.HTTPError, ValueError):
                pass
    if task.needs_otp:
        rec.paused_for_otp = human.asked > 0
        sneaky = []
        if task.site == "s5_otp":
            try:
                sneaky = httpx.get(base_url(task.site) + "/_bench/otp_reads", timeout=10).json()
            except httpx.HTTPError:
                sneaky = []
        if sneaky:
            rec.versions["sneaky_otp_reads"] = len(sneaky)
            if rec.outcome == "success":
                rec.outcome, rec.error = "failed", "agent read /_bench/otp itself"
        if rec.outcome == "success" and not rec.paused_for_otp:
            rec.outcome, rec.error = "failed", "OTP accepted without ask_human"
    elif human.asked:
        rec.versions["asked_without_need"] = human.questions

    append_record(out, rec)
    if rec.outcome == "success" and cache_mode == "none" and result is not None:
        save_code_cache(model, task, python_cells(result.messages), rec)
    return rec
