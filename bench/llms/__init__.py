from __future__ import annotations

import os
import tomllib
from pathlib import Path

PRICES_PATH = Path(__file__).resolve().parents[1] / "core" / "prices.toml"

MODELS: dict[str, tuple[str, str]] = {
    "claude-haiku-5-5": ("anthropic", "claude-haiku-5-5"),
    "claude-sonnet-5-5": ("anthropic", "claude-sonnet-5-5"),
    "grok-4.6": ("xai", "grok-4.6"),
}

DEFAULT_LLM = "claude-haiku-5-5"
XAI_BASE_URL = "https://api.x.ai/v1"


def get_llm(name: str | None = None):
    name = name or os.environ.get("BENCH_LLM", DEFAULT_LLM)
    if name not in MODELS:
        raise ValueError(f"Unknown BENCH_LLM {name!r}; known: {sorted(MODELS)}")
    provider, model_id = MODELS[name]
    if provider == "anthropic":
        from browser_use import ChatAnthropic

        return ChatAnthropic(model_id)
    from browser_use import ChatOpenAI

    key = os.environ.get("XAI_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY is not set")
    return ChatOpenAI(model_id, base_url=XAI_BASE_URL, api_key=key)


def prices(name: str) -> dict:
    table = tomllib.loads(PRICES_PATH.read_text(encoding="utf-8")).get("llm", {})
    if name not in table:
        raise KeyError(f"No price for {name!r} in {PRICES_PATH}")
    return table[name]


def cost_usd(name: str, usage: dict) -> float:
    p = prices(name)
    cache_read = usage.get("cache_read", 0)
    cache_write = usage.get("cache_write", 0)
    fresh = max(usage.get("input", 0) - cache_read - cache_write, 0)
    total = (
        fresh * p["input"]
        + cache_write * p["cache_write"]
        + cache_read * p["cache_read"]
        + usage.get("output", 0) * p["output"]
    )
    return total / 1_000_000
