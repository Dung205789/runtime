"""Tiện ích dùng chung cho các provider."""

from __future__ import annotations

import asyncio
import os
import socket
from importlib import metadata

import httpx
from dotenv import load_dotenv

load_dotenv(override=False)

DEFAULT_SESSION_TIMEOUT_S = 600  # đủ cho 1 lượt 300 s + dư; bài giữ phiên 900 s tự truyền timeout_s lớn hơn


class ProviderSkipped(RuntimeError):
    """Không chạy được runtime này vì thiếu điều kiện (khóa API, Docker, tunnel…). Ghi outcome = "skipped"."""


def require_env(key: str, provider: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ProviderSkipped(f"{provider}: thiếu {key} trong .env")
    return val


def session_timeout_s(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    return int(os.environ.get("BENCH_SESSION_TIMEOUT_S", DEFAULT_SESSION_TIMEOUT_S))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_json_version(base: str, timeout: float = 30.0, proc=None) -> dict:
    """Chờ endpoint /json/version của Chrome trả lời. Trả JSON đó (có trường "Browser")."""
    deadline = asyncio.get_running_loop().time() + timeout
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=2.0) as c:
        while asyncio.get_running_loop().time() < deadline:
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"Chrome thoát sớm, mã {proc.returncode}")
            try:
                r = await c.get(base + "/json/version")
                if r.status_code == 200:
                    return r.json()
            except httpx.HTTPError as e:
                last = e
            await asyncio.sleep(0.1)
    raise TimeoutError(f"{base}/json/version không trả lời sau {timeout}s ({last})")


def lib_versions() -> dict:
    out = {}
    for pkg in ("browser-use", "playwright", "httpx"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def raise_for_status(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        body = r.text[:300].replace("\n", " ")
        if r.status_code in (401, 403):
            raise ProviderSkipped(f"{what}: khóa API bị từ chối (HTTP {r.status_code}): {body}")
        raise RuntimeError(f"{what}: HTTP {r.status_code}: {body}")
