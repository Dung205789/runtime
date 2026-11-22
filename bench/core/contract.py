from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

Axis = Literal["runtime", "llm", "cross"]
CacheMode = Literal["none", "session", "actions"]
Outcome = Literal["success", "wrong_data", "failed", "timeout", "crashed", "blocked", "skipped"]

SITE_PORTS: dict[str, int] = {
    "s1_simple": 8801,
    "s2_wizard": 8802,
    "s3_spa": 8803,
    "s4_guarded": 8804,
    "s5_otp": 8805,
}

MAX_STEPS = 40
MAX_RUN_SECONDS = 300
REPS_PER_CELL = 11
LLM_BUDGET_USD = 25.0


def site_url(site: str) -> str:
    return f"http://127.0.0.1:{SITE_PORTS[site]}"


@dataclass(frozen=True)
class BrowserHandle:
    provider: str
    cdp_url: str
    live_view_url: str | None = None
    session_id: str | None = None


class BrowserProvider(Protocol):
    name: str

    async def start(self) -> BrowserHandle: ...

    async def stop(self, handle: BrowserHandle) -> None: ...


@dataclass(frozen=True)
class Expected:
    date: str
    time: str
    party_size: int
    name: str
    phone: str


@dataclass(frozen=True)
class BenchTask:
    task_id: str
    site: str
    instruction: str
    expected: Expected
    needs_otp: bool


@dataclass
class RunRecord:
    run_id: str
    axis: Axis
    task_id: str
    site: str
    provider: str
    model: str
    cache_mode: CacheMode
    rep: int
    warmup: bool
    outcome: Outcome
    started_at: str
    total_ms: float | None = None
    session_create_ms: float | None = None
    first_page_ms: float | None = None
    human_wait_ms: float = 0.0
    steps: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    llm_cost_usd: float = 0.0
    browser_cost_usd: float = 0.0
    peak_pss_mb: float | None = None
    cpu_s: float | None = None
    concurrency: int = 1
    paused_for_otp: bool | None = None
    error: str | None = None
    machine: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def machine_info() -> dict:
    import psutil

    return {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "python": platform.python_version(),
        "host": os.environ.get("BENCH_MACHINE_LABEL", platform.node()),
    }


def append_record(path: Path, rec: RunRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_tasks(path: Path = Path("tasks/tasks.json")) -> list[BenchTask]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        BenchTask(
            task_id=t["task_id"],
            site=t["site"],
            instruction=t["instruction"],
            expected=Expected(**t["expected"]),
            needs_otp=t["needs_otp"],
        )
        for t in raw
    ]


def grade(task: BenchTask, bookings: list[dict]) -> Outcome:
    if not bookings:
        return "failed"
    e = task.expected
    ok = [
        b
        for b in bookings
        if b.get("date") == e.date
        and b.get("time") == e.time
        and int(b.get("party_size", -1)) == e.party_size
        and b.get("name", "").strip().lower() == e.name.lower()
        and "".join(ch for ch in str(b.get("phone", "")) if ch.isdigit()) == e.phone
    ]
    if len(bookings) == 1 and len(ok) == 1:
        return "success"
    return "wrong_data"
