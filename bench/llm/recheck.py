"""Chạy lại các ca đổi dữ liệu khách (CHECKS của combo) với script cache hiện tại. Không gọi LLM, $0.

Cùng đường chạy `direct` của combo (Chrome local + lớp chặn gửi đơn), nhưng ghi vào file riêng
để không lẫn với đợt đo 24/11 trong combo.jsonl.

    uv run python -m bench.llm.recheck real_lauwang real_lauphan real_kingbbq
Kết quả: results/llm/real/recheck_<ngày>.jsonl (versions.kind = "recheck", versions.script = v1/v2)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from bench.llm import combo
from bench.llm import real as R
from bench.llm.combo import CHECKS, Direct, load_script

OUT = Path(f"results/llm/real/recheck_{dt.date.today():%Y%m%d}.jsonl")


async def run_site(site: str) -> None:
    st = load_script(site)
    ver = "v2" if st.get("script_v1") else "v1"
    async with Direct() as d:
        for c in CHECKS:
            if c.alt_branch and not st.get("alt_branch"):
                continue
            r = await d.run(site, st["script"], c, st["alt_branch"] if c.alt_branch else None, "recheck", 1)
            r.versions["script"] = ver


def main() -> int:
    proof = Path("results/llm/real/guard_proof_direct.json")
    digest = hashlib.sha256(Path("bench/llm/guard.py").read_bytes() + Path("bench/llm/direct_worker.py").read_bytes()).hexdigest()
    if not proof.exists() or json.loads(proof.read_text()).get("sha256") != digest:
        print("TỪ CHỐI: đường chạy trực tiếp chưa được kiểm chứng; chạy python -m bench.llm.guard_check_direct")
        return 4
    combo.OUT = OUT
    orig = combo.append_record

    def tag(path, rec):
        rec.versions["script"] = "v2" if load_script(rec.site).get("script_v1") else "v1"
        orig(path, rec)

    combo.append_record = tag
    for s in sys.argv[1:] or list(R.SITES):
        try:
            asyncio.run(run_site(s))
        except Exception as e:
            print("LỖI", s, type(e).__name__, str(e)[:200], flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
