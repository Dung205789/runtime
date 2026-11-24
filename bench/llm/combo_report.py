from __future__ import annotations

import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROWS = [json.loads(x) for x in Path("results/llm/real/combo.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
ROWS = [r for r in ROWS if not r["versions"].get("void")]
SITES = ["real_lauphan", "real_tong", "real_chaoxian", "real_lauwang", "real_kingbbq"]


def pct(x, q):
    x = sorted(x)
    return x[max(0, math.ceil(q * len(x)) - 1)] if x else None


def f(x, d=1):
    return "—" if x is None else f"{x:.{d}f}"


def rows(kind, model=None, site=None):
    return [r for r in ROWS if r["versions"]["kind"] == kind and (model is None or r["model"].startswith(model)) and (site is None or r["site"] == site)]


def main() -> int:
    L = []
    groups = [("Claude Haiku chay", "cold", "claude"), ("Gemini flash-lite chay", "cold", "gemini"), ("Replay qua browser-use", "replay", None), ("Script chạy thẳng, Chrome mở sẵn", "direct", None)]
    L.append("## Thời gian (s), chỉ lượt thành công\n\n| Cách | n thành công/tổng | p50 | p95 | $/lượt TB | $/thành công | bước p50 | cpu TB |\n|---|---|---|---|---|---|---|---|")
    for name, kind, m in groups:
        a = rows(kind, m)
        ok = [r for r in a if r["outcome"] == "success"]
        t = [r["total_ms"] / 1000 for r in ok]
        cost = sum(r["llm_cost_usd"] for r in a)
        if a:
            L.append(f"| {name} | {len(ok)}/{len(a)} {dict(Counter(r['outcome'] for r in a if r['outcome'] != 'success'))} | {f(pct(t, .5))} | {f(pct(t, .95))} | {cost / len(a):.4f} | {cost / max(1, len(ok)):.4f} | {pct([r['steps'] for r in ok], .5)} | {st.mean(r['versions']['cpu_pct'] for r in a):.0f} |")
    L.append("\n## p50 theo web (s), vòng 1-2 (mọi cách cùng có)\n\n| Web | " + " | ".join(g[0] for g in groups) + " |\n|---|---|---|---|---|")
    for s in SITES:
        c = []
        for _, kind, m in groups:
            a = [r for r in rows(kind, m, s) if r["rep"] <= 2]
            c.append(", ".join(f"{r['total_ms'] / 1000:.1f}{'' if r['outcome'] == 'success' else '✗' + r['outcome']}" for r in a))
        L.append(f"| {s[5:]} | " + " | ".join(c) + " |")
    L.append("\n## Phân rã thời gian (TB, lượt thành công; s)\n\n| Cách | mở Chrome (ngoài total) | total | khởi động agent | LLM | số lần gọi LLM | phần còn lại |\n|---|---|---|---|---|---|---|")
    for name, kind, m in groups[:3]:
        a = [r for r in rows(kind, m) if r["outcome"] == "success"]
        if not a:
            continue
        av = lambda k: st.mean((r["versions"].get(k) or 0) for r in a) / 1000
        tot = st.mean(r["total_ms"] for r in a) / 1000
        L.append(f"| {name} | {st.mean(r['session_create_ms'] for r in a) / 1000:.1f} | {tot:.1f} | {av('agent_start_ms'):.1f} | {av('llm_ms'):.1f} | {st.mean(r['versions']['llm_calls'] for r in a):.1f} | {tot - av('agent_start_ms') - av('llm_ms'):.1f} |")
    rp = [r for r in rows("replay") if r["outcome"] == "success"]
    if rp:
        L.append(f"\nReplay: cell script TB {st.mean(r['versions'].get('cell_ms') or 0 for r in rp) / 1000:.1f}s; nav load TB {st.mean((r['versions'].get('nav') or {}).get('load') or 0 for r in rp) / 1000:.1f}s")
    dr = [r for r in rows("direct") if r["outcome"] == "success"]
    if dr:
        L.append(f"Chạy thẳng: script TB {st.mean(r['versions']['script_ms'] for r in dr) / 1000:.1f}s; nav load TB {st.mean((r['versions'].get('nav') or {}).get('load') or 0 for r in dr) / 1000:.1f}s")
    L.append("\n## Độ đúng khi đổi dữ liệu (chạy thẳng)\n\n| Web | đúng | từ chối | điền sai mà không báo | lỗi có báo |\n|---|---|---|---|---|")
    for s in SITES:
        c = Counter(r["outcome"] for r in rows("check", None, s))
        L.append(f"| {s[5:]} | {c['success']} | {c['blocked']} | {c['wrong_data']} | {c['failed']} |")
    for r in rows("check"):
        if r["outcome"] != "success":
            v = r["versions"]
            L.append(f"- {r['site'][5:]} {v['case']} {r['outcome']}: {(v['err'] or '')[:170]} sai={[k for k, x in v['check'].items() if not x]}")
    L.append("\n## Cache hỏng\n\n| Web | phát hiện (s) | kết quả script | Claude cứu (s) | kết quả | $ |\n|---|---|---|---|---|---|")
    for s in SITES:
        d, a = rows("detect", None, s), rows("failover", None, s)
        if d:
            L.append(f"| {s[5:]} | {d[-1]['total_ms'] / 1000:.1f} | {d[-1]['outcome']} {(d[-1]['versions']['err'] or '')[:60]} | {a[-1]['total_ms'] / 1000 if a else 0:.1f} | {a[-1]['outcome'] if a else '—'} | {a[-1]['llm_cost_usd'] if a else 0:.4f} |")
    L.append("\n## Hòa vốn (so với Haiku chay)\n\n| Web | học + sinh/sửa $ | s | tiết kiệm $/lượt | tiết kiệm s/lượt | N$ | Ngiây |\n|---|---|---|---|---|---|---|")
    for s in SITES:
        p = Path(f"results/llm/real/scripts/{s}.json")
        if not p.exists():
            continue
        z = json.loads(p.read_text(encoding="utf-8"))
        cold = [r for r in rows("cold", "claude", s) if r["outcome"] == "success"]
        di = [r for r in rows("direct", None, s) if r["outcome"] == "success"]
        if not cold or not di:
            continue
        cd, sd = st.mean(r["llm_cost_usd"] for r in cold), st.mean(r["total_ms"] for r in cold) / 1000 - st.mean(r["total_ms"] for r in di) / 1000
        tc, ts = z["learn_cost_usd"] + z["cost_usd"], (z["learn_ms"] + z["train_ms"]) / 1000
        L.append(f"| {s[5:]} | {tc:.4f} | {ts:.0f} | {cd:.4f} | {sd:.1f} | {math.ceil(tc / cd)} | {math.ceil(ts / sd)} |")
    L.append("\n## An toàn")
    L.append(f"POST được qua: {sorted(set(x for r in ROWS for x in r['versions'].get('guard_allowed_posts', [])))}")
    L.append(f"Lượt có dữ liệu khách bị chặn: {[(r['site'], r['versions']['kind'], r['model'], r['versions'].get('guard_hits')) for r in ROWS if r['versions'].get('guard_submit_attempts')]}")
    tot = defaultdict(float)
    for r in ROWS:
        tot[r["model"]] += r["llm_cost_usd"]
    L.append(f"Chi phí combo: { {k: round(v, 4) for k, v in tot.items()} }")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
