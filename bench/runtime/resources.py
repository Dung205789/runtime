"""Lấy mẫu tài nguyên mỗi 500 ms trong một lượt, giữ giá trị đỉnh.

- chrome_local: cây tiến trình Chrome của phiên (pid = handle.session_id). Windows: USS; Linux: PSS; macOS: USS.
- steel_selfhost: PSS của riêng các tiến trình Chromium trong container (SteelChromeSampler), cùng phạm vi với
  chrome_local. Ghi thêm PSS cả container vào versions['container_pss_peak_mb']. Cách cũ (docker stats cả container,
  có server Node.js và page cache): đặt BENCH_STEEL_MEM=docker_stats.
- cloud: chỉ đo phía client = tiến trình Python của harness + các tiến trình con (daemon browser-use).
CPU: tổng thời gian CPU (user + system) của các tiến trình được theo dõi trong lượt.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
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


# Chạy trong container (Linux): mỗi tiến trình in "pid comm pss_kB utime stime" (utime/stime tính bằng tick).
_PROC_SCRIPT = (
    'for p in /proc/[0-9]*; do [ -r "$p/smaps_rollup" ] || continue; '
    'c=$(cat "$p/comm" 2>/dev/null); '
    'k=$(awk \'/^Pss:/{print $2}\' "$p/smaps_rollup" 2>/dev/null); '
    't=$(awk \'{print $14, $15}\' "$p/stat" 2>/dev/null); '
    'echo "${p#/proc/} $c $k $t"; done'
)


class SteelChromeSampler:
    """steel_selfhost: PSS của riêng các tiến trình Chromium trong container (bỏ server Node.js, nginx, page cache).

    Cùng cách đo với chrome_local (bộ nhớ của trình duyệt, không tính phần phụ trợ), để so RAM công bằng.
    Ghi thêm PSS của mọi tiến trình trong container (`extra`) để đối chiếu.
    """

    CHROME = ("chrom",)  # chromium, chrome_crashpad…

    def __init__(self, container: str) -> None:
        self.container = container
        self.scope = f"PSS các tiến trình Chromium trong container {container}"
        self.peak_mb = 0.0
        self.extra: dict = {}
        self._all_peak = 0.0
        self._cpu: dict[int, float] = {}
        self._cpu0: dict[int, float] = {}
        self._tick = 100
        self._task: asyncio.Task | None = None

    def _sample(self) -> None:
        r = subprocess.run(["docker", "exec", self.container, "sh", "-c", _PROC_SCRIPT],
                           capture_output=True, text=True, timeout=20)
        chrome = total = 0.0
        for ln in r.stdout.splitlines():
            parts = ln.split()
            if len(parts) < 5 or not parts[2].isdigit():
                continue
            pid, comm, pss_kb = int(parts[0]), parts[1], int(parts[2])
            total += pss_kb / 1024
            if comm.startswith(self.CHROME):
                chrome += pss_kb / 1024
                with contextlib.suppress(ValueError):
                    self._cpu[pid] = max(self._cpu.get(pid, 0.0), (int(parts[3]) + int(parts[4])) / self._tick)
        self.peak_mb = max(self.peak_mb, chrome)
        self._all_peak = max(self._all_peak, total)

    async def _loop(self) -> None:
        while True:
            await asyncio.to_thread(self._sample)  # mỗi lần docker exec ~0.3–1 s
            await asyncio.sleep(INTERVAL_S)

    @property
    def cpu_s(self) -> float | None:
        if not self._cpu:
            return None
        return round(sum(max(0.0, v - self._cpu0.get(pid, 0.0)) for pid, v in self._cpu.items()), 3)

    async def __aenter__(self):
        await asyncio.to_thread(self._sample)
        self._cpu0 = dict(self._cpu)
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._sample)
        self.extra = {"container_pss_peak_mb": round(self._all_peak, 1), "mem_method": "chromium_pss_in_container"}


def sampler_for(provider_name: str, handle: BrowserHandle):
    if provider_name == "chrome_local":
        return ProcessTreeSampler(int(handle.session_id))
    if provider_name == "steel_selfhost":
        from bench.providers.steel_selfhost import API_PORT0, CONTAINER_PREFIX, PORT_STEP

        port = urlsplit(handle.cdp_url).port or API_PORT0
        name = f"{CONTAINER_PREFIX}{(port - API_PORT0) // PORT_STEP}"
        if os.environ.get("BENCH_STEEL_MEM", "chromium") == "docker_stats":  # cách đo cũ (cả container)
            return DockerSampler(name)
        return SteelChromeSampler(name)
    return ProcessTreeSampler(os.getpid(), scope=f"phía client: Python harness + tiến trình con ({MEM_METRIC})")
