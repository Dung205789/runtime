"""Chụp từng bước khi chạy lại script cache quy trình trên 5 web thật (không gọi LLM, $0).

Dùng đúng đường chạy `direct` của combo: Chrome local + lớp chặn gửi đơn ở tiến trình cha,
script chạy trong worker nối CDP. Ca đo: BASE (3 người, 18:00, ngày mai, khách giả).
Từ chối chạy nếu bằng chứng kiểm chứng lớp chặn không khớp hash của guard.py + direct_worker.py.

    uv run python -m bench.llm.shots            # cả 5 web
    uv run python -m bench.llm.shots real_tong  # một web
Ảnh: results/llm/real/shots/<site>/NN.png, bước: results/llm/real/shots/<site>/steps.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from bench.llm import combo
from bench.llm.combo import BASE, SAFE_ENV, Direct, best_snap, check, guard_fields, head, load_script
from bench.llm import real as R

OUT = Path("results/llm/real/shots")


class ShotDirect(Direct):
    async def __aenter__(self):
        await super().__aenter__()
        try:
            self.proc.kill()
        except ProcessLookupError:
            pass
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "bench.llm.shot_worker", self.c.cdp_url, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=SAFE_ENV, limit=2**24,
        )
        await asyncio.wait_for(self.proc.stdout.readline(), 60)
        return self


async def shoot(site: str) -> dict:
    st = load_script(site)
    if not st.get("script"):
        return {"site": site, "error": "chưa có script cache"}
    out_dir = OUT / site
    for f in out_dir.glob("*.png"):
        f.unlink()
    async with ShotDirect() as d:
        code = head(BASE, None, site, st["script"]) + st["script"]
        res = await d.send(json.dumps({"code": code, "out_dir": str(out_dir)}), 240)
        snap = await best_snap(d.ctx)
        rec = combo.record(site, "none", "shots", BASE, 1)
        guard_fields(rec, d.guard)
        await d.send("close", 30)
        blocked = list(d.guard.blocked)
    chk = check(snap["vals"], BASE, None)
    result = {
        "site": site, "url": R.SITES[site], "case": {"party": BASE.party, "time": BASE.hhmm, "day": "ngày mai", "name": BASE.name},
        "ms": res["ms"], "err": res["err"], "steps": res["steps"], "form": snap["vals"], "check": chk,
        "outcome": ("blocked" if res["err"] and "UNAVAILABLE" in res["err"] else "failed") if res["err"] else ("success" if all(chk.values()) else "wrong_data"),
        "guard_blocked": blocked, "guard_allowed_posts": rec.versions["guard_allowed_posts"],
        "guard_submit_attempts": rec.versions["guard_submit_attempts"],
    }
    (out_dir / "steps.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main() -> int:
    proof = Path("results/llm/real/guard_proof_direct.json")
    digest = hashlib.sha256(Path("bench/llm/guard.py").read_bytes() + Path("bench/llm/direct_worker.py").read_bytes()).hexdigest()
    if not proof.exists() or json.loads(proof.read_text()).get("sha256") != digest:
        print("TỪ CHỐI: đường chạy trực tiếp chưa được kiểm chứng; chạy python -m bench.llm.guard_check_direct")
        return 4
    sites = sys.argv[1:] or list(R.SITES)
    for s in sites:
        try:
            r = asyncio.run(shoot(s))
        except Exception as e:
            print(s, "LỖI", type(e).__name__, str(e)[:200], flush=True)
            continue
        print(s, r.get("outcome"), f"{len(r.get('steps', []))} ảnh", (r.get("err") or "")[:120], "chặn:", len(r.get("guard_blocked", [])),
              "gửi dữ liệu khách bị chặn:", r.get("guard_submit_attempts"), flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
