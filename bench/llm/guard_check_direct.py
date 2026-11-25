from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from bench.llm import combo, devsite
from bench.llm.combo import BASE, Direct, head
from bench.llm.guard_check import READS, SUBMITS
from bench.llm.run import start_devsite

CODE = """
for how in ("click", "submit", "fetch", "xhr", "popup"):
    for nm, ph in (("Khach Thu Nghiem", "0000000000"), ("Khách Thử Nghiệm", "0912345678")):
        goto_url("http://127.0.0.1:8899/"); wait_for_load()
        js("(()=>{const s=(i,v)=>document.querySelector('[name='+i+']').value=v;s('date','2026-12-18');s('time','20:00');s('party_size','2');s('name','%s');s('phone','%s')})()" % (nm, ph))
        b = "date=2026-12-18&time=20:00&party_size=2&name=x&phone=1"
        if how == "click":
            r = js("(()=>{const r=document.querySelector('button').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()"); click_at_xy(*r)
        elif how == "submit":
            js("document.querySelector('form').submit()")
        elif how == "popup":
            js("(()=>{const f=document.querySelector('form');f.target='_blank';f.submit()})()")
        elif how == "fetch":
            js("fetch('/book',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:'%s'});1" % b)
        else:
            js("(()=>{const x=new XMLHttpRequest();x.open('POST','/book');x.setRequestHeader('content-type','application/x-www-form-urlencoded');x.send('%s')})()" % b)
        time.sleep(1)
"""


async def go(guarded: bool):
    devsite.state["bookings"].clear()
    async with Direct() as d:
        if not guarded:
            await d.ctx.unroute_all()
        res = await d.send(json.dumps({"code": head(BASE, None) + CODE}), 200)
        blocked = len(d.guard.blocked)
        await d.send("close", 30)
    return len(devsite.state["bookings"]), blocked, res["err"]


def main() -> int:
    start_devsite()
    ctl = asyncio.run(go(False))
    got = asyncio.run(go(True))
    print("control", ctl, "guarded", got, "cases", len(SUBMITS), len(READS))
    ok = ctl[0] >= 8 and got[0] == 0 and got[1] >= ctl[0] and ctl[2] is None and got[2] is None
    if ok:
        dg = hashlib.sha256(Path("bench/llm/guard.py").read_bytes() + Path("bench/llm/direct_worker.py").read_bytes()).hexdigest()
        Path("results/llm/real/guard_proof_direct.json").write_text(json.dumps({"sha256": dg, "control": ctl[0], "guarded": got[0], "blocked": got[1]}))
    print("DIRECT GUARD PROOF", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
