"""chrome_local: Chrome cài trên máy, mở bằng --remote-debugging-port, profile tạm mỗi phiên.

Mặc định chạy có giao diện (headful), vì Chrome headless gửi UA "HeadlessChrome" và bị s4_guarded chặn.
Đặt BENCH_CHROME_HEADLESS=1 nếu muốn headless.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from bench.core.contract import BrowserHandle
from bench.providers._util import free_port, wait_json_version

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH", "").strip()
    for c in [env, *CANDIDATES]:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chrome"):
        if found := shutil.which(name):
            return found
    raise RuntimeError("Không tìm thấy Chrome. Đặt biến CHROME_PATH.")


class ChromeLocal:
    name = "chrome_local"

    def __init__(self, headless: bool | None = None, executable: str | None = None,
                 extra_args: tuple[str, ...] = (), timeout_s: int | None = None) -> None:
        # timeout_s: chỉ để cùng giao diện với runtime cloud; Chrome local không tự hết hạn phiên.
        if headless is None:
            headless = os.environ.get("BENCH_CHROME_HEADLESS", "") == "1"
        self.headless = headless
        self.executable = executable or find_chrome()
        self.extra_args = extra_args
        self._sessions: dict[str, tuple[subprocess.Popen, Path]] = {}
        self._leftover: dict[str, int] = {}  # session_id -> số tiến trình Chrome còn sót sau stop()
        self.versions: dict = {}

    async def start(self) -> BrowserHandle:
        port = free_port()
        profile = Path(tempfile.mkdtemp(prefix="bench-chrome-"))
        args = [
            self.executable,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-features=Translate",
            "--window-size=1280,900",
            *(["--headless=new"] if self.headless else []),
            *self.extra_args,
            "about:blank",
        ]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        base = f"http://127.0.0.1:{port}"
        try:
            info = await wait_json_version(base, proc=proc)
        except Exception:
            await asyncio.to_thread(self._kill, proc, profile)
            raise
        self.versions = {"chrome": info.get("Browser"), "headless": self.headless}
        sid = str(proc.pid)
        self._sessions[sid] = (proc, profile)
        return BrowserHandle(provider=self.name, cdp_url=base, live_view_url=None, session_id=sid)

    async def stop(self, handle: BrowserHandle) -> None:
        item = self._sessions.pop(handle.session_id or "", None)
        if item:
            await asyncio.to_thread(self._kill, *item)  # không chặn event loop khi chạy nhiều phiên song song
            await asyncio.sleep(0.5)
            self._leftover[handle.session_id] = await asyncio.to_thread(self._count_leftover, item[1])

    async def released(self, handle: BrowserHandle) -> tuple[bool, str]:
        """Sau stop(): không còn tiến trình Chrome nào dùng profile tạm của phiên."""
        n = self._leftover.pop(handle.session_id or "", 0)
        return n == 0, f"{n} tiến trình Chrome còn sót" if n else "sạch"

    @staticmethod
    def _count_leftover(profile: Path) -> int:
        n = 0
        for p in psutil.process_iter(["cmdline"]):
            try:
                if str(profile) in " ".join(p.info["cmdline"] or []):
                    n += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return n

    @staticmethod
    def _kill(proc: subprocess.Popen, profile: Path) -> None:
        try:
            children = psutil.Process(proc.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
        _, alive = psutil.wait_procs(children, timeout=5)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        for _ in range(20):  # Windows giữ khóa file profile thêm một lúc sau khi Chrome thoát
            shutil.rmtree(profile, ignore_errors=True)
            if not profile.exists():
                break
            time.sleep(0.25)
