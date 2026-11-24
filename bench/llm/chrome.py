from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import psutil

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def chrome_path() -> str:
    explicit = os.environ.get("CHROME_PATH")
    if explicit:
        return explicit
    for p in CANDIDATES:
        if Path(p).exists():
            return p
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    raise FileNotFoundError("Chrome not found; set CHROME_PATH")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class LocalChrome:
    proc: subprocess.Popen
    cdp_url: str
    profile_dir: Path
    temp_profile: bool
    create_ms: float

    def peak_rss_mb(self) -> float:
        try:
            root = psutil.Process(self.proc.pid)
            procs = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return 0.0
        total = 0
        for p in procs:
            try:
                total += p.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return total / 2**20

    def close_gracefully(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(self.cdp_url)
            b.new_browser_cdp_session().send("Browser.close")
        self.proc.wait(15)

    def stop(self) -> None:
        if not self.temp_profile:
            try:
                self.close_gracefully()
            except Exception:
                pass
        try:
            root = psutil.Process(self.proc.pid)
            procs = [*root.children(recursive=True), root]
        except psutil.NoSuchProcess:
            procs = []
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=10)
        if self.temp_profile:
            shutil.rmtree(self.profile_dir, ignore_errors=True)


def launch(profile_dir: Path | None = None, headless: bool | None = None, timeout_s: float = 30) -> LocalChrome:
    if headless is None:
        headless = os.environ.get("BENCH_CHROME_HEADLESS", "") == "1"
    temp = profile_dir is None
    profile = Path(tempfile.mkdtemp(prefix="bench-chrome-")) if temp else profile_dir.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    port = free_port()
    args = [
        chrome_path(),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=Translate",
        "--window-size=1280,900",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        *(["--headless=new"] if headless else []),
        "about:blank",
    ]
    t0 = time.perf_counter()
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/json/version", timeout=1).status_code == 200:
                return LocalChrome(proc, url, profile, temp, (time.perf_counter() - t0) * 1000)
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    LocalChrome(proc, url, profile, temp, 0).stop()
    raise RuntimeError(f"Chrome did not expose CDP on {url} within {timeout_s}s")
