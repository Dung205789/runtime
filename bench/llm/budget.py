from __future__ import annotations

import json
import os
from pathlib import Path

RESULTS = Path("results/llm")

DEFAULT_RESERVE_USD = {
    "claude-haiku-5-5": 0.05,
    "claude-sonnet-5-5": 0.60,
    "grok-4.6": 0.30,
}


def records(root: Path = RESULTS) -> list[dict]:
    out: list[dict] = []
    for f in sorted(root.rglob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            out.extend(json.loads(line) for line in fh if line.strip())
    return out


def cap_usd() -> float:
    return float(os.environ.get("BENCH_LLM_BUDGET_USD", "1.80"))


def spent_usd(recs: list[dict] | None = None) -> float:
    return sum(r.get("llm_cost_usd", 0.0) for r in (recs if recs is not None else records()))


def reserve_usd(model: str, recs: list[dict] | None = None) -> float:
    seen = [r["llm_cost_usd"] for r in (recs if recs is not None else records()) if r.get("model") == model and r.get("llm_cost_usd")]
    if seen:
        return max(seen) * 1.5
    return DEFAULT_RESERVE_USD.get(model, 0.60)


def check(model: str) -> tuple[bool, str]:
    recs = records()
    spent, reserve, cap = spent_usd(recs), reserve_usd(model, recs), cap_usd()
    msg = f"spent ${spent:.4f} + reserve ${reserve:.4f} for {model} vs cap ${cap:.2f}"
    return spent + reserve <= cap, msg
