"""Lấy mẫu tài nguyên mỗi 500 ms trong một lượt, giữ giá trị đỉnh.

- chrome_local: cây tiến trình Chrome của phiên (pid = handle.session_id). Windows: USS; Linux: PSS; macOS: USS.
- steel_selfhost: `docker stats` của container phục vụ phiên (bộ nhớ container, có cả server API của Steel).
- cloud: chỉ đo phía client = tiến trình Python của harness + các tiến trình con (daemon browser-use).
CPU: tổng thời gian CPU (user + system) của các tiến trình được theo dõi trong lượt.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
from urllib.parse import urlsplit

import psutil

from bench.core.contract import BrowserHandle

INTERVAL_S = 0.5
MEM_METRIC = "PSS" if sys.platform.startswith("linux") else "USS"


def _proc_mem_mb(p: psutil.Process) -> float:
    info = p.memory_full_info()
    return (getattr(info, "pss", None) or info.uss) / 2**20


class ProcessTreeSampler:
    def __init__(self, root_pid: int, include_root: bool = True, scope: str = "") -> None:
        self.root_pid, self.include_root = root_pid, include_root
        self.scope = scope or f"cây tiến trình pid {root_pid} ({MEM_METRIC})"
        self.peak_mb = 0.0
        self._cpu: dict[int, float] = {}
        self._task: asyncio.Task | None = None

    def _sample(self) -> None:
        try:
            root = psutil.Process(self.root_pid)
            procs = ([root] if self.include_root else []) + root.children(recursive=True)
        except psutil.NoSuchProcess:
            return
        total = 0.0
        for p in procs:
            try:
                total += _proc_mem_mb(p)
                t = p.cpu_times()
                self._cpu[p.pid] = max(self._cpu.get(p.pid, 0.0), t.user + t.system)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.peak_mb = max(self.peak_mb, total)

    async def _loop(self) -> None:
        while True:
            await asyncio.to_thread(self._sample)
            await asyncio.sleep(INTERVAL_S)

    @property
    def cpu_s(self) -> float | None:
        return round(sum(self._cpu.values()), 3) if self._cpu else None

    async def __aenter__(self):
        self._sample()
        self._cpu0 = dict(self._cpu)
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        # CPU trong lượt = CPU hiện tại − CPU lúc bắt đầu (với tiến trình đã có sẵn từ trước, ví dụ Python của harness)
        for pid, v in getattr(self, "_cpu0", {}).items():
            if pid in self._cpu:
                self._cpu[pid] = max(0.0, self._cpu[pid] - v)


class DockerSampler:
    def __init__(self, container: str) -> None:
        self.container = container
        self.scope = f"docker stats của container {container}"
        self.peak_mb = 0.0
        self.cpu_s = None  # docker stats chỉ cho % CPU tức thời, không cho tổng thời gian CPU
        self._task: asyncio.Task | None = None

    def _sample(self) -> None:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.container],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        if not out:
            return
        used = out.split("/")[0].strip()  # ví dụ "438.1MiB"
        units = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1024, "MB": 1, "GB": 1024, "B": 1 / 2**20}
        for u, f in units.items():
            if used.endswith(u):
                with contextlib.suppress(ValueError):
                    self.peak_mb = max(self.peak_mb, float(used[: -len(u)]) * f)
                break

    async def _loop(self) -> None:
        while True:
            await asyncio.to_thread(self._sample)  # mỗi lần gọi docker stats mất ~1–2 s, nên thực tế thưa hơn 500 ms
            await asyncio.sleep(INTERVAL_S)

    async def __aenter__(self):
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def sampler_for(provider_name: str, handle: BrowserHandle):
    if provider_name == "chrome_local":
        return ProcessTreeSampler(int(handle.session_id))
    if provider_name == "steel_selfhost":
        from bench.providers.steel_selfhost import API_PORT0, CONTAINER_PREFIX, PORT_STEP

        port = urlsplit(handle.cdp_url).port or API_PORT0
        return DockerSampler(f"{CONTAINER_PREFIX}{(port - API_PORT0) // PORT_STEP}")
    import os

    return ProcessTreeSampler(os.getpid(), scope=f"phía client: Python harness + tiến trình con ({MEM_METRIC})")
