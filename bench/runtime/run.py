"""Đo runtime: `uv run python -m bench.runtime.run [phase] [tùy chọn]`.

Phase (mặc định `all` = chạy hết, lần lượt từng runtime, có resume):
    pilot       10 task × 1 lượt (mặc định chrome_local), để xem chi phí thật. Không dùng cho thống kê.
    cold        11 lần start() -> CDP -> s1_simple tải xong. Không dùng LLM.
    booking     10 task × 11 lượt (lượt 0 là warm-up), 1 phiên.
    c3          50 lượt ở mức 3 phiên song song (tài nguyên mức 3 + phép đo ổn định).
    c5          10 lượt ở mức 5 phiên song song (tài nguyên mức 5).
    hold        Giữ phiên 900 s trên s5_otp (t09).
    antibot     3 trang kiểm tra bot (chỉ đọc), chụp ảnh vào results/runtime/antibot/.
    liveview    Kiểm tra Live View gõ được vào ô OTP.
    all         cold, booking, c3, c5, hold, antibot, liveview cho mỗi runtime.

Tùy chọn: --runtime a,b   --tasks t01,t02 (pilot/booking)   --reps N   --name tên
Tự bật mock site; runtime cloud thì tự mở tunnel (và đóng khi xong); steel_selfhost tự dựng đủ container.
Kết quả: results/runtime/<YYYYMMDD>_<phase>.jsonl — chạy lại thì dùng tiếp file cũ cùng tên (resume).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import statistics
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

from bench.core.contract import REPS_PER_CELL, SITE_PORTS, load_tasks
from bench.providers import CLOUD, PUBLIC_URLS_FILE, RUNTIMES, ProviderSkipped, get_provider
from bench.runtime import phases
from bench.runtime.booking import LLMUnavailable, run_booking
from bench.runtime.llm import preflight
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "runtime"
ORDER = ["cold", "booking", "c3", "c5", "hold", "antibot", "liveview"]
CONC = {"c3": (3, 50), "c5": (5, 10)}
LLM_PHASES = {"pilot", "booking", "c3", "c5", "hold"}


def port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def result_file(name: str) -> Path:
    """Dùng tiếp file <ngày>_<name>.jsonl mới nhất nếu có (để resume qua đêm), không thì tạo theo ngày hôm nay."""
    existing = sorted(RESULTS.glob(f"*_{name}.jsonl"))
    return existing[-1] if existing else RESULTS / f"{date.today():%Y%m%d}_{name}.jsonl"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


class Infra:
    """Mock site, tunnel và container Steel; bật khi cần, tắt khi xong."""

    def __init__(self) -> None:
        self.server = self.tunnel = None

    async def sites(self) -> None:
        if all(port_open(p) for p in SITE_PORTS.values()):
            return
        self.server = subprocess.Popen([sys.executable, "-m", "mock_sites.serve"], cwd=ROOT, stdout=subprocess.DEVNULL)
        for _ in range(150):
            if all(port_open(p) for p in SITE_PORTS.values()):
                return
            await asyncio.sleep(0.2)
        raise RuntimeError("mock site không bật được")

    async def ensure_tunnel(self) -> None:
        if PUBLIC_URLS_FILE.exists() and await self._tunnel_ok():
            return
        self.close_tunnel()
        PUBLIC_URLS_FILE.unlink(missing_ok=True)
        log = (ROOT / "tmp" / "tunnel.log").open("w", encoding="utf-8")
        self.tunnel = subprocess.Popen([sys.executable, "-m", "mock_sites.tunnel"], cwd=ROOT, stdout=log,
                                       stderr=subprocess.STDOUT)
        for _ in range(300):
            if PUBLIC_URLS_FILE.exists():
                print("tunnel đã mở", flush=True)
                return
            if self.tunnel.poll() is not None:
                break
            await asyncio.sleep(1)
        raise RuntimeError("tunnel không mở được, xem tmp/tunnel.log")

    async def _tunnel_ok(self) -> bool:
        urls = json.loads(PUBLIC_URLS_FILE.read_text(encoding="utf-8"))
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                for u in urls.values():
                    r = await c.get(u + "/_bench/bookings")
                    if r.status_code != 403:
                        return False
            return True
        except httpx.HTTPError:
            return False

    def close_tunnel(self) -> None:
        if self.tunnel:
            self.tunnel.terminate()
            try:
                self.tunnel.wait(15)
            except subprocess.TimeoutExpired:
                self.tunnel.kill()
            self.tunnel = None
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True) if sys.platform == "win32" \
            else subprocess.run(["pkill", "-f", "cloudflared tunnel"], capture_output=True)
        PUBLIC_URLS_FILE.unlink(missing_ok=True)

    @staticmethod
    def steel_containers(n: int) -> None:
        from bench.providers.steel_selfhost import container_ports, up

        def healthy(i: int) -> bool:
            try:
                return httpx.get(f"http://localhost:{container_ports(i)[0]}/v1/health", timeout=3).status_code == 200
            except httpx.HTTPError:
                return False

        if all(healthy(i) for i in range(n)):
            return
        up(n)
        for _ in range(60):
            if all(healthy(i) for i in range(n)):
                return
            import time

            time.sleep(1)
        raise RuntimeError(f"không dựng được {n} container Steel")

    def close(self) -> None:
        self.close_tunnel()
        if self.server:
            self.server.terminate()
            self.server.wait(10)


def line(rec) -> str:
    return (f"{rec.provider:17s} {rec.task_id} rep{rec.rep:<2d} {rec.outcome:10s} steps={rec.steps} "
            f"t={(rec.total_ms or 0) / 1000:.0f}s (chờ người {rec.human_wait_ms / 1000:.0f}s) tok_in={rec.tokens_in} "
            f"cache_r={rec.tokens_cache_read} out={rec.tokens_out} llm=${rec.llm_cost_usd:.4f} "
            f"br=${rec.browser_cost_usd:.4f} peak={rec.peak_pss_mb}MB" + (f"  | {rec.error[:160]}" if rec.error else ""))


async def booking_phase(rt: str, task_ids, reps: int, out: Path) -> list:
    tasks = [t for t in load_tasks(ROOT / "tasks" / "tasks.json") if not task_ids or t.task_id in task_ids]
    done = Counter((r["task_id"]) for r in load(out) if r["provider"] == rt and r["concurrency"] == 1)
    provider = get_provider(rt)
    recs = []
    for rep in range(reps):
        for t in tasks:
            if done[t.task_id] > rep:
                continue
            rec = await run_booking(provider, t, rep=rep, warmup=(rep == 0 and reps > 1), out=out)
            recs.append(rec)
            print(line(rec), flush=True)
    return recs


async def run_phase(phase: str, rt: str, infra: Infra, a) -> None:
    out = result_file(a.name or phase)
    rows = [r for r in load(out) if r["provider"] == rt]
    if phase == "pilot":
        summarize(await booking_phase(rt, a.task_ids, a.reps or 1, out))
    elif phase == "booking":
        summarize(await booking_phase(rt, a.task_ids, a.reps or REPS_PER_CELL, out))
    elif phase == "cold":
        reps = a.reps or REPS_PER_CELL
        if len(rows) < reps:
            await phases.cold(rt, reps, out, start_rep=len(rows))
    elif phase in CONC:
        conc, runs = CONC[phase]
        runs = a.reps or runs
        done = len([r for r in rows if r["concurrency"] == conc])
        if done < runs:
            provider = None
            if rt == "steel_selfhost":  # 1 phiên = 1 container
                infra.steel_containers(conc)
                from bench.providers.steel_selfhost import container_ports

                provider = get_provider(rt, bases=[f"http://localhost:{container_ports(i)[0]}" for i in range(conc)])
            summarize(await phases.concurrent(rt, conc, runs, out, already=done, provider=provider))
    elif phase == "hold":
        if not rows:
            await phases.hold(rt, out)
    elif phase == "antibot":
        if not (RESULTS / "antibot" / f"{rt}_nowsecure.json").exists():
            await phases.antibot_pages(rt)
    elif phase == "liveview":
        if not (RESULTS / "liveview" / f"{rt}.json").exists():
            await phases.liveview(rt)


def summarize(records: list) -> None:
    ran = [r for r in records if r.outcome != "skipped"]
    if not ran:
        return
    cost = [r.llm_cost_usd for r in ran]
    secs = [(r.total_ms - r.human_wait_ms) / 1000 for r in ran if r.total_ms]
    print(f"--- {len(ran)} lượt: {dict(Counter(r.outcome for r in ran))}; LLM tổng ${sum(cost):.4f}, "
          f"trung vị ${statistics.median(cost):.4f}/lượt; thời gian trung vị {statistics.median(secs):.0f}s "
          f"(không tính chờ người)" if secs else "", flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", nargs="?", default="all", choices=["pilot", *ORDER, "all"])
    ap.add_argument("--runtime", default="")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--reps", type=int, default=0)
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    a.task_ids = [x for x in a.tasks.split(",") if x] or None
    runtimes = [x for x in a.runtime.split(",") if x] or (["chrome_local"] if a.phase == "pilot" else list(RUNTIMES))
    plan = ORDER if a.phase == "all" else [a.phase]
    if sys.platform == "win32":  # giữ máy không tự ngủ khi đang đo (hết tác dụng khi tiến trình thoát)
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    if set(plan) & LLM_PHASES:
        load_dotenv(ROOT / ".env")
        if err := preflight():
            print(f"!!! Claude API không dùng được ({err}). Nạp credit / sửa key rồi chạy lại.", flush=True)
            return 2
    infra = Infra()
    try:
        await infra.sites()
        for rt in runtimes:
            try:
                get_provider(rt)
            except ProviderSkipped as e:
                print(f"[skip] {rt}: {e}", flush=True)
                continue
            if rt in CLOUD:
                await infra.ensure_tunnel()
            else:
                infra.close_tunnel()  # không để tunnel mở khi không cần
            if rt == "steel_selfhost":
                infra.steel_containers(1)
            for phase in plan:
                print(f"\n===== {rt} / {phase}", flush=True)
                try:
                    await run_phase(phase, rt, infra, a)
                except LLMUnavailable:
                    raise  # hết credit / sai key: dừng cả đợt, không ghi lượt hỏng
                except Exception as e:  # noqa: BLE001 — một phase lỗi không làm dừng cả đêm đo
                    print(f"!!! {rt}/{phase} lỗi: {type(e).__name__}: {e}", flush=True)
            if rt == "steel_selfhost":  # tắt container để không chiếm RAM khi đo runtime sau
                from bench.providers.steel_selfhost import down

                down()
    except LLMUnavailable as e:
        print(f"\n!!! DỪNG: Claude API không dùng được (hết credit hoặc sai key). Lượt hỏng KHÔNG được ghi.\n    {e}\n"
              "    Nạp credit rồi chạy lại cùng lệnh: phần đã xong được bỏ qua.", flush=True)
        return 2
    finally:
        infra.close()
    print("\nxong. Kết quả ở results/runtime/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
