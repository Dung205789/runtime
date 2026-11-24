"""Một lượt đặt bàn đầy đủ: runtime (provider) + agent browser-use + LLM cố định, chấm bằng grade().

Dòng chảy một lượt (hợp đồng mục 5, 6, 8):
1. POST /_bench/reset (s4: cả /_bench/reset_rate, để lượt trước không ăn vào hạn mức 10 request/phút của lượt sau).
2. provider.start() -> session_create_ms.
3. Agent browser-use (judge=False: harness tự chấm, không tốn thêm 1 lần gọi LLM), tool `ask_human`.
4. Chấm: GET /_bench/bookings -> grade(). Thêm luật: task cần OTP mà agent không hỏi -> failed;
   agent tự đọc /_bench/otp -> failed; vượt 40 bước / 300 s (không tính chờ người) -> timeout;
   s4 có log chặn mà không có đơn -> blocked.
5. provider.stop(); tính chi phí LLM theo token thật và chi phí trình duyệt theo giá trong prices.toml.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import shutil
import time
import tomllib
import uuid
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")  # không gửi telemetry của browser-use

import httpx

from bench.core.contract import (MAX_RUN_SECONDS, MAX_STEPS, BenchTask, BrowserProvider, RunRecord, append_record,
                                 grade, machine_info, now_iso, site_url)
from bench.providers import ProviderSkipped, lib_versions, site_url_for
from bench.runtime.llm import FIXED_MODEL, get_fixed_llm, llm_cost, price_table
from bench.runtime.resources import MEM_METRIC, sampler_for

ROOT = Path(__file__).resolve().parents[2]
PROMPT = (Path(__file__).with_name("prompt.md")).read_text(encoding="utf-8")
PRICES = ROOT / "bench" / "core" / "prices.toml"
HARNESS_HEADER = {"X-Bench-Harness": "1"}
NO_OTP_REPLY = "Mình chưa nhận được mã OTP nào. Nếu trang chưa gửi mã thì bạn cứ làm tiếp bước trước đó."
OTHER_REPLY = "Mình không có thêm thông tin nào khác, bạn cứ làm theo đúng yêu cầu ban đầu nhé."


class LLMUnavailable(RuntimeError):
    """API LLM không dùng được (hết credit, sai key). Lượt đó KHÔNG được ghi; cả đợt đo phải dừng."""


LLM_FATAL = ("credit balance is too low", "ModelQuotaExceeded", "authentication_error", "invalid x-api-key")


def llm_fatal(text: str | None) -> bool:
    return bool(text) and any(s in text for s in LLM_FATAL)


def human_delay_s() -> float:
    return float(os.environ.get("BENCH_HUMAN_DELAY_S", "20"))


class HumanLoop:
    """Người trong vòng lặp giả lập (mục 6): chờ BENCH_HUMAN_DELAY_S giây rồi trả OTP hiện tại của site."""

    def __init__(self, http: httpx.AsyncClient, local_base: str, delay_s: float) -> None:
        self.http, self.base, self.delay_s = http, local_base, delay_s
        self.questions: list[str] = []
        self.otp_given = False
        self.wait_s = 0.0

    async def ask(self, question: str) -> str:
        self.questions.append(question[:300])
        t = time.perf_counter()
        await asyncio.sleep(self.delay_s)
        reply = OTHER_REPLY
        with contextlib.suppress(httpx.HTTPError):
            r = await self.http.get(self.base + "/_bench/otp", headers=HARNESS_HEADER)
            if r.status_code == 200 and (otp := r.json().get("otp")):
                self.otp_given = True
                reply = f"Mã OTP là {otp}"
            elif r.status_code == 404:
                reply = NO_OTP_REPLY
        self.wait_s += time.perf_counter() - t
        return reply


def build_task(task: BenchTask, url: str) -> str:
    return f"Tin nhắn của khách: \"{task.instruction}\"\n\nTrang đặt bàn của nhà hàng: {url}"


def browser_cost(provider: str, seconds: float) -> float:
    """Giá trình duyệt cloud theo prices.toml. chrome_local / steel_selfhost: 0 (chi phí VPS ước tính tính ở báo cáo)."""
    try:
        p = tomllib.loads(PRICES.read_text(encoding="utf-8")).get("runtime", {}).get(provider)
    except (OSError, tomllib.TOMLDecodeError):
        p = None
    if not p:
        return 0.0
    if provider == "browser_use_cloud":  # theo phút, tối thiểu 1 phút
        return max(1, math.ceil(seconds / 60)) * p["usd_per_browser_hour"] / 60
    if provider == "kernel":
        return seconds * p["usd_per_second_headful"]
    return math.ceil(seconds) * p["usd_per_browser_hour"] / 3600  # steel_cloud: theo giây, làm tròn lên


async def run_booking(provider: BrowserProvider, task: BenchTask, *, axis: str = "runtime", rep: int = 0,
                      warmup: bool = False, concurrency: int = 1, out: Path | None = None,
                      model: str = FIXED_MODEL, human_delay: float | None = None) -> RunRecord:
    rec = RunRecord(run_id=uuid.uuid4().hex[:12], axis=axis, task_id=task.task_id, site=task.site,
                    provider=provider.name, model=model, cache_mode="none", rep=rep, warmup=warmup,
                    outcome="failed", started_at=now_iso(), concurrency=concurrency,
                    machine={**machine_info(), "mem_metric": MEM_METRIC})
    llm, llm_src = get_fixed_llm(model)
    rec.versions = {**lib_versions(), "llm_adapter": llm_src, "llm_price_from": price_table(model)["from"]}
    local = site_url(task.site)
    workspace = ROOT / "tmp" / "agent_ws" / rec.run_id
    handle = None

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            await http.post(local + "/_bench/reset")
            if task.site == "s4_guarded":
                await http.post(local + "/_bench/reset_rate")
            target = site_url_for(provider.name, task.site)
        except ProviderSkipped as e:
            rec.outcome, rec.error = "skipped", str(e)
            return _write(rec, out)
        except httpx.HTTPError as e:
            rec.outcome, rec.error = "crashed", f"mock site không chạy: {e}"
            return _write(rec, out)

        human = HumanLoop(http, local, human_delay if human_delay is not None else human_delay_s())
        from browser_use import Agent, Browser, Tools

        tools = Tools()

        @tools.action("Hỏi khách một câu và chờ khách trả lời (ví dụ xin mã OTP mà trang vừa gửi). "
                      "Trả về câu trả lời của khách.")
        async def ask_human(question: str) -> str:
            return await human.ask(question)

        t0 = time.perf_counter()
        try:
            handle = await provider.start()
        except ProviderSkipped as e:
            rec.outcome, rec.error = "skipped", str(e)
            return _write(rec, out)
        except Exception as e:  # noqa: BLE001
            rec.outcome, rec.error = "crashed", f"start(): {type(e).__name__}: {e}"[:500]
            return _write(rec, out)
        rec.session_create_ms = round((time.perf_counter() - t0) * 1000, 1)
        rec.versions.update({f"provider_{k}": v for k, v in getattr(provider, "versions", {}).items()})

        result = None
        sampler = sampler_for(provider.name, handle)
        browser = Browser(cdp_url=handle.cdp_url)
        try:
            agent = Agent(build_task(task, target), llm=llm, browser=browser, tools=tools,
                          extend_system_message=PROMPT, judge=False, workspace=workspace)
            async with sampler:
                result = await agent.run(max_steps=MAX_STEPS, timeout=MAX_RUN_SECONDS + 5 * human.delay_s)
        except Exception as e:  # noqa: BLE001
            rec.outcome, rec.error = "crashed", f"agent: {type(e).__name__}: {e}"[:500]
        finally:
            with contextlib.suppress(Exception):
                await browser.stop()
            session_s = time.perf_counter() - t0
            try:
                await provider.stop(handle)
            except Exception as e:  # noqa: BLE001
                rec.error = ((rec.error or "") + f" | stop(): {type(e).__name__}: {e}").strip(" |")[:500]
            await _check_released(provider, handle, rec)
            shutil.rmtree(workspace, ignore_errors=True)

        if llm_fatal(rec.error) or (result is not None and llm_fatal(result.error)):
            raise LLMUnavailable(f"{provider.name} {task.task_id} rep{rep}: "
                                 + ((result.error if result is not None else None) or rec.error or "")[:300])

        rec.total_ms = round(session_s * 1000, 1)
        rec.human_wait_ms = round(human.wait_s * 1000, 1)
        rec.peak_pss_mb = round(sampler.peak_mb, 1) if sampler.peak_mb else None
        rec.cpu_s = sampler.cpu_s
        rec.machine["mem_scope"] = sampler.scope
        rec.browser_cost_usd = round(browser_cost(provider.name, session_s), 6)
        if task.needs_otp:
            rec.paused_for_otp = human.otp_given

        if result is not None:
            u = dict(result.usage)
            rec.steps = result.steps
            rec.tokens_in, rec.tokens_out = u.get("input", 0), u.get("output", 0)
            rec.tokens_cache_read, rec.tokens_cache_write = u.get("cache_read", 0), u.get("cache_write", 0)
            rec.llm_cost_usd = round(llm_cost(model, u), 6)
            rec.versions["agent_status"] = result.status
            if result.error:
                rec.error = result.error[:500]

        if rec.outcome != "crashed":
            rec.outcome = await _judge(http, local, task, rec, result, human)
    return _write(rec, out)


async def _judge(http: httpx.AsyncClient, local: str, task: BenchTask, rec: RunRecord, result, human: HumanLoop):
    bookings = (await http.get(local + "/_bench/bookings")).json()
    outcome = grade(task, bookings)
    notes = []
    if task.needs_otp:
        sneaky = (await http.get(local + "/_bench/otp_reads")).json()
        if sneaky:
            notes.append(f"agent tự đọc /_bench/otp {len(sneaky)} lần")
            outcome = "failed" if outcome == "success" else outcome
        if outcome == "success" and not human.otp_given:
            notes.append("đặt được mà không hỏi OTP")
            outcome = "failed"
    active_s = (rec.total_ms - rec.human_wait_ms) / 1000 if rec.total_ms is not None else 0
    over = (result is not None and result.status in ("timeout", "max_steps")) or active_s > MAX_RUN_SECONDS
    if over and outcome != "wrong_data":
        notes.append(f"vượt giới hạn ({result.status if result else '?'}, {active_s:.0f}s không tính chờ người)")
        outcome = "timeout"
    if outcome == "failed" and task.site == "s4_guarded":
        blocks = (await http.get(local + "/_bench/blocks")).json()
        if blocks:
            notes.append("bị chặn: " + ", ".join(sorted({b["reason"] for b in blocks})))
            outcome = "blocked"
    if outcome == "wrong_data":
        notes.append("đơn nhận được: " + str(bookings)[:300])
    if human.questions:
        notes.append(f"ask_human x{len(human.questions)}")
    if notes:
        rec.error = "; ".join(filter(None, [rec.error, *notes]))[:800]
    return outcome


async def _check_released(provider, handle, rec: RunRecord) -> None:
    """Phép đo ổn định: sau stop() phiên/tiến trình phải được giải phóng. Ghi vào versions['after_stop']."""
    check = getattr(provider, "released", None)
    if check is None:
        return
    try:
        ok, detail = await check(handle)
    except Exception as e:  # noqa: BLE001
        ok, detail = None, f"không kiểm tra được: {type(e).__name__}: {e}"[:200]
    rec.versions["after_stop"] = detail
    rec.versions["after_stop_clean"] = ok
    if ok is False:
        rec.error = "; ".join(filter(None, [rec.error, f"MỒ CÔI sau stop(): {detail}"]))[:800]


def _write(rec: RunRecord, out: Path | None) -> RunRecord:
    if out is not None:
        append_record(out, rec)
    return rec
