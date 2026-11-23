"""LLM cố định cho trục runtime: claude-haiku-5-5 (hợp đồng mục 4).

Dùng `bench.llms.get_llm()` của Agent 2 nếu đã có; chưa có thì tạo ChatAnthropic của browser-use trực tiếp.
browser-use 1.0.8 tự bật prompt cache của Anthropic (agent/loop.py: settings['cache'] = True).

Giá dùng để tính llm_cost_usd lấy từ trang chính thức (dưới đây). Khi Agent 2 ghi `[llm.claude-haiku-5-5]` vào
bench/core/prices.toml thì dùng giá ở đó.
Lưu ý: genai-prices (browser-use dùng để tính result.cost_usd) ghi giá input của Haiku 5.5 là $0.50/MTok, khác
trang chính thức ($0.10/MTok) — không dùng result.cost_usd.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

FIXED_MODEL = "claude-haiku-5-5"

# https://platform.claude.com/docs/en/about-claude/pricing , tra 2026-11-23, prompt <= 100k token. USD / 1 triệu token.
OFFICIAL_PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125,
                         "source": "https://platform.claude.com/docs/en/about-claude/pricing", "checked": "2026-11-23"},
}
PRICES_TOML = Path(__file__).resolve().parents[1] / "core" / "prices.toml"


def get_fixed_llm(name: str = FIXED_MODEL):
    try:
        from bench.llms import get_llm  # của Agent 2
    except ImportError:
        from browser_use import ChatAnthropic

        return ChatAnthropic(name), "browser_use.ChatAnthropic"
    return get_llm(name), "bench.llms.get_llm"


def preflight(model: str = FIXED_MODEL) -> str | None:
    """Gọi thử 1 request rất nhỏ (max_tokens=1) để chắc API còn credit và key đúng.

    Trả về None nếu ổn, hoặc chuỗi lỗi (không chứa key). Lỗi mạng tạm thời không tính là hỏng.
    """
    import os

    import httpx

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return "thiếu ANTHROPIC_API_KEY"
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=30,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]})
    except httpx.HTTPError:
        return None
    if r.status_code in (400, 401, 402, 403):
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:200]
        return f"HTTP {r.status_code}: {msg[:200]}"
    return None


def price_table(model: str) -> dict:
    try:
        llm = tomllib.loads(PRICES_TOML.read_text(encoding="utf-8")).get("llm", {})
    except (OSError, tomllib.TOMLDecodeError):
        llm = {}
    p = llm.get(model)
    if p and all(k in p for k in ("input", "output", "cache_read", "cache_write")):
        return {**p, "from": "prices.toml"}
    return {**OFFICIAL_PRICES[model], "from": "bench/runtime/llm.py"}


def llm_cost(model: str, usage: dict) -> float:
    """usage của browser-use: 'input' ĐÃ gồm cache_read và cache_write (genai-prices cộng dồn)."""
    p = price_table(model)
    cr, cw = usage.get("cache_read", 0), usage.get("cache_write", 0)
    fresh = max(0, usage.get("input", 0) - cr - cw)
    return (fresh * p["input"] + cr * p["cache_read"] + cw * p["cache_write"] + usage.get("output", 0) * p["output"]) / 1e6
