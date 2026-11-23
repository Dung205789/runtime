from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

from bench.core.contract import REPS_PER_CELL, load_tasks
from bench.llm import budget
from bench.llm.devsite import DEV_PORT
from bench.llm.runner import DEV_TASKS, base_url, run_one
from bench.llms import MODELS

MODES = ("none", "session", "actions")


def start_devsite() -> None:
    import uvicorn

    from bench.llm.devsite import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=DEV_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{DEV_PORT}/_bench/bookings", timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("devsite did not start")


def done_counts() -> Counter:
    c: Counter = Counter()
    for r in budget.records():
        if r.get("outcome") == "skipped":
            continue
        c[(r["model"], r["cache_mode"], r["task_id"], r["warmup"])] += 1
    return c


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m bench.llm.run")
    p.add_argument("--models", default="claude-haiku-5-5", help="comma list: " + ",".join(MODELS))
    p.add_argument("--modes", default="none", help="comma list: none,session,actions")
    p.add_argument("--tasks", default="", help="comma list of task ids (default: all)")
    p.add_argument("--reps", type=int, default=REPS_PER_CELL - 1, help="measured reps per cell, warm-up excluded")
    p.add_argument("--no-warmup", action="store_true")
    p.add_argument("--dev", action="store_true", help="use the built-in dev site instead of mock_sites")
    p.add_argument("--plan", action="store_true", help="print what would run and the budget estimate, spend nothing")
    return p.parse_args()


async def main() -> int:
    load_dotenv(".env")
    a = parse()
    models = [m for m in a.models.split(",") if m]
    modes = [m for m in a.modes.split(",") if m]
    bad = [m for m in models if m not in MODELS] + [m for m in modes if m not in MODES]
    if bad:
        print(f"unknown: {bad}")
        return 2
    tasks = DEV_TASKS if a.dev else load_tasks()
    if a.tasks:
        keep = set(a.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in keep]

    if a.dev:
        start_devsite()
    elif not a.plan:
        if not Path("mock_sites/READY").exists():
            print("mock_sites/READY chưa có: chạy --dev để thử harness, hoặc merge origin/main khi Agent 1 xong M1")
            return 2
        for site in sorted({t.site for t in tasks}):
            try:
                httpx.get(base_url(site) + "/_bench/bookings", timeout=3).raise_for_status()
            except httpx.HTTPError as e:
                print(f"{site} không chạy ({e}); bật bằng: uv run python -m mock_sites.serve")
                return 2

    out = Path("results/llm") / f"{date.today():%Y%m%d}_{'dev' if a.dev else 'matrix'}.jsonl"
    done = done_counts()
    queue = []
    for model in models:
        for mode in modes:
            for t in tasks:
                if not a.no_warmup and done[(model, mode, t.task_id, True)] == 0:
                    queue.append((t, model, mode, 0, True))
                have = done[(model, mode, t.task_id, False)]
                for rep in range(have + 1, a.reps + 1):
                    queue.append((t, model, mode, rep, False))

    recs = budget.records()
    est = sum(budget.reserve_usd(m, recs) / 1.5 for _, m, _, _, _ in queue)
    print(f"{len(queue)} lượt cần chạy · đã tiêu ${budget.spent_usd(recs):.4f} / trần ${budget.cap_usd():.2f} · ước tính thêm ≈ ${est:.3f}")
    if a.plan:
        for t, m, mode, rep, w in queue[:40]:
            print(f"  {m} {mode} {t.task_id} rep={rep}{' warmup' if w else ''}")
        return 0

    for t, model, mode, rep, warm in queue:
        ok, msg = budget.check(model)
        if not ok:
            print(f"DỪNG vì ngân sách: {msg}")
            return 3
        r = await run_one(t, model, mode, rep, warm, out)
        print(
            f"{model} {mode} {t.task_id} rep={rep}{' W' if warm else ''} → {r.outcome} · "
            f"{(r.total_ms or 0) / 1000:.1f}s · {r.steps} bước · ${r.llm_cost_usd:.4f} · "
            f"in {r.tokens_in} (cache đọc {r.tokens_cache_read}) out {r.tokens_out}"
            + (f" · {r.error[:120]}" if r.error else "")
        )
    print(f"xong · tổng đã tiêu ${budget.spent_usd():.4f}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
