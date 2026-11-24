"""Tính bảng số cho reports/runtime.md từ results/runtime/ — không nhập số bằng tay.

    uv run python -m bench.runtime.report            # ghi lại các khối AUTO trong reports/runtime.md
    uv run python -m bench.runtime.report --print    # chỉ in ra màn hình

Trong reports/runtime.md, mỗi bảng nằm giữa `<!-- AUTO:<tên> -->` và `<!-- /AUTO:<tên> -->`; phần chữ ngoài các khối
đó viết tay và không bị ghi đè.

Quy ước (theo hợp đồng mục 8, 10):
- Bỏ lượt warm-up (rep 0) khỏi thống kê. Báo p50 và p95 (nội suy tuyến tính, như numpy mặc định).
- Thời gian một lượt đặt = total_ms − human_wait_ms (không tính 20 s giả lập khách gửi OTP).
- $/1.000 lượt = (tổng LLM + tổng trình duyệt của mọi lượt) ÷ số lượt success × 1.000.
  chrome_local / steel_selfhost cộng thêm chi phí VPS ƯỚC TÍNH (bảng VPS ở dưới).
- Điểm: mỗi chỉ số quy về 0–100 trong nhóm (tốt nhất 100, kém nhất 0, nội suy tuyến tính), nhân trọng số.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results" / "runtime"
REPORT = ROOT / "reports" / "runtime.md"
RUNTIMES = ["chrome_local", "steel_selfhost", "steel_cloud", "browser_use_cloud", "kernel"]
LOCAL = {"chrome_local", "steel_selfhost"}
S4_TASKS = {"t07", "t08"}
WEIGHTS = {"p95_time": 35, "usd_1000": 30, "ram": 15, "p95_cold": 10, "liveview": 10}

# VPS dùng để ƯỚC TÍNH chi phí chrome_local / steel_selfhost (brief: "quy theo giá một VPS tương đương có cùng RAM
# đỉnh"). Gói nhỏ nhất có RAM >= RAM đỉnh p95 của một phiên; tính tiền = giá theo giờ × thời gian phiên p50, tức là
# giả định VPS luôn bận (lạc quan). Nguồn và ngày tra ghi ở reports/runtime.md.
# Giá: https://www.hetzner.com/cloud/cost-optimized , tra 2026-11-23, EUR chưa VAT (trang báo đang hết hàng).
# Đổi sang USD theo tỷ giá ~1.10 USD/EUR (tra 2026-11-23, trung bình giữa các trang tỷ giá) — số ước tính.
EUR_USD = 1.10
VPS_PLANS = [  # (tên, RAM GB, USD/giờ)
    ("Hetzner CX23 (2 vCPU, 4 GB, €0.0096/giờ)", 4, 0.0096 * EUR_USD),
    ("Hetzner CX33 (4 vCPU, 8 GB, €0.0144/giờ)", 8, 0.0144 * EUR_USD),
]


def load(name: str) -> list[dict]:
    rows = []
    for f in sorted(RES.glob(f"*_{name}.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows


def pct(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def f(x, nd=1, unit=""):
    return "—" if x is None else f"{x:,.{nd}f}{unit}"


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def active_s(r: dict) -> float | None:
    return None if r["total_ms"] is None else (r["total_ms"] - (r["human_wait_ms"] or 0)) / 1000


def vps_for(peak_mb: float | None):
    if peak_mb is None:
        return None
    return next((p for p in VPS_PLANS if p[1] * 1024 >= peak_mb), VPS_PLANS[-1])


def collect() -> dict:
    cold, booking, c3, c5, hold = (load(n) for n in ("cold", "booking", "c3", "c5", "hold"))
    allrows = cold + booking + c3 + c5 + hold
    D: dict = {}
    for rt in RUNTIMES:
        d: dict = {}
        cr = [r for r in cold if r["provider"] == rt and not r["warmup"]]
        d["cold_n"], d["cold_ok"] = len(cr), sum(r["outcome"] == "success" for r in cr)
        d["create_p50"], d["create_p95"] = (pct([r["session_create_ms"] for r in cr], q) for q in (.5, .95))
        d["first_p50"], d["first_p95"] = (pct([r["first_page_ms"] for r in cr], q) for q in (.5, .95))

        b = [r for r in booking if r["provider"] == rt and r["concurrency"] == 1 and not r["warmup"]]
        d["b_n"], d["b_out"] = len(b), Counter(r["outcome"] for r in b)
        d["b_ok"] = d["b_out"]["success"]
        t = [active_s(r) for r in b]
        d["t_p50"], d["t_p95"] = pct(t, .5), pct(t, .95)
        d["steps_p50"] = pct([r["steps"] for r in b], .5)
        d["bcreate_p50"], d["bcreate_p95"] = (pct([r["session_create_ms"] for r in b], q) for q in (.5, .95))
        llm, br = sum(r["llm_cost_usd"] for r in b), sum(r["browser_cost_usd"] for r in b)
        d["llm_per_ok"] = llm / d["b_ok"] if d["b_ok"] else None
        d["br_per_ok"] = br / d["b_ok"] if d["b_ok"] else None
        d["session_s_p50"] = pct([r["total_ms"] / 1000 for r in b if r["total_ms"]], .5)
        d["tok_in_p50"] = pct([r["tokens_in"] for r in b], .5)
        d["cache_ratio"] = (sum(r["tokens_cache_read"] for r in b) / sum(r["tokens_in"] for r in b)) if b else None
        per_task = defaultdict(list)
        for r in b:
            per_task[r["task_id"]].append(active_s(r))
        d["per_task_p50"] = {k: pct(v, .5) for k, v in sorted(per_task.items())}
        s4 = [r for r in b if r["task_id"] in S4_TASKS]
        d["s4_n"], d["s4_ok"] = len(s4), sum(r["outcome"] == "success" for r in s4)
        d["otp_ok"] = sum(1 for r in b if r["site"] == "s5_otp" and r["paused_for_otp"])
        d["otp_n"] = sum(1 for r in b if r["site"] == "s5_otp")
        d["fail_notes"] = [f'{r["task_id"]} rep{r["rep"]}: {r["outcome"]} ({(r["error"] or "")[:80]})'
                           for r in b if r["outcome"] != "success"]

        for name, rows, conc in (("c1", b, 1), ("c3", c3, 3), ("c5", c5, 5)):
            rr = [r for r in rows if r["provider"] == rt and r["concurrency"] == conc]
            d[f"{name}_n"], d[f"{name}_ok"] = len(rr), sum(r["outcome"] == "success" for r in rr)
            d[f"{name}_ram_p50"], d[f"{name}_ram_p95"] = (pct([r["peak_pss_mb"] for r in rr], q) for q in (.5, .95))
            d[f"{name}_cpu_p50"] = pct([r["cpu_s"] for r in rr], .5)
            d[f"{name}_t_p50"], d[f"{name}_t_p95"] = (pct([active_s(r) for r in rr], q) for q in (.5, .95))
            d[f"{name}_scope"] = next((r["machine"].get("mem_scope") for r in rr if r["machine"].get("mem_scope")), "")
        c3r = [r for r in c3 if r["provider"] == rt]
        d["c3_lost"] = sum(r["outcome"] == "crashed" for r in c3r)
        d["c3_timeout"] = sum(r["outcome"] == "timeout" for r in c3r)

        mine = [r for r in allrows if r["provider"] == rt]
        d["orphans"] = sum(r["versions"].get("after_stop_clean") is False for r in mine)
        d["orphan_checked"] = sum(r["versions"].get("after_stop_clean") is not None for r in mine)
        d["runs_total"] = len(mine)

        h = [r for r in hold if r["provider"] == rt]
        d["hold"] = h[-1]["outcome"] if h else None
        d["hold_err"] = (h[-1]["error"] or "")[:200] if h else ""
        d["hold_wait_s"] = h[-1]["human_wait_ms"] / 1000 if h and h[-1]["human_wait_ms"] else None

        lv = RES / "liveview" / f"{rt}.json"
        d["lv"] = json.loads(lv.read_text(encoding="utf-8")) if lv.exists() else None

        ab = {}
        for page in ("browserscan", "creepjs", "nowsecure"):
            p = RES / "antibot" / f"{rt}_{page}.json"
            if p.exists():
                ab[page] = json.loads(p.read_text(encoding="utf-8"))
        d["ab"] = ab

        # chi phí VPS ước tính (chỉ local / self-host)
        d["vps"] = vps_for(d["c1_ram_p95"]) if rt in LOCAL else None
        d["vps_per_ok"] = (d["vps"][2] * d["session_s_p50"] / 3600) if d["vps"] and d["session_s_p50"] else 0.0
        if d["b_ok"]:
            d["usd_1000"] = (d["llm_per_ok"] + d["br_per_ok"] + d["vps_per_ok"]) * 1000
            d["usd_1000_browser"] = (d["br_per_ok"] + d["vps_per_ok"]) * 1000
        else:
            d["usd_1000"] = d["usd_1000_browser"] = None
        D[rt] = d
    return D


def gates(d: dict) -> dict:
    return {
        "cdp": d["cold_n"] > 0 and d["cold_ok"] == d["cold_n"],
        "c3_lost0": d["c3_n"] >= 50 and d["c3_lost"] == 0,
        "hold": d["hold"] == "success",
        "s4": d["s4_n"] > 0 and d["s4_ok"] / d["s4_n"] >= 0.8,
    }


def scores(D: dict, cands: list[str], use_ram: bool = True) -> dict:
    metric = {
        "p95_time": lambda d: d["t_p95"],
        "usd_1000": lambda d: d["usd_1000"],
        "ram": lambda d: d["c1_ram_p95"],
        "p95_cold": lambda d: d["first_p95"],
        "liveview": lambda d: 1.0 if (d["lv"] or {}).get("typed_ok") else 0.0,
    }
    higher_better = {"liveview"}
    w = {k: v for k, v in WEIGHTS.items() if use_ram or k != "ram"}
    total_w = sum(w.values())
    out = {rt: {"total": 0.0} for rt in cands}
    for k, wt in w.items():
        vals = {rt: metric[k](D[rt]) for rt in cands}
        lo, hi = min(vals.values()), max(vals.values())
        for rt, v in vals.items():
            if hi == lo:
                s = 100.0
            elif k in higher_better:
                s = (v - lo) / (hi - lo) * 100
            else:
                s = (hi - v) / (hi - lo) * 100
            out[rt][k] = s
            out[rt]["total"] += s * wt / total_w
    return out


# ---------------------------------------------------------------- các khối bảng

def blk_gates(D):
    rows = []
    for rt in RUNTIMES:
        d, g = D[rt], gates(D[rt])
        ok = lambda b: "đạt" if b else "**trượt**"
        rows.append([f"`{rt}`", f'{ok(g["cdp"])} ({d["cold_ok"]}/{d["cold_n"]})',
                     f'{ok(g["c3_lost0"])} ({d["c3_lost"]} mất / {d["c3_n"]})',
                     f'{ok(g["hold"])}' + (f' ({d["hold_wait_s"]:.0f} s)' if d["hold_wait_s"] else ""),
                     f'{ok(g["s4"])} ({d["s4_ok"]}/{d["s4_n"]})',
                     "**qua**" if all(g.values()) else "loại"])
    return table(["Runtime", "Nối CDP", "0 phiên mất ở 3 song song", "Giữ phiên 15'", "s4_guarded ≥ 80%",
                  "Kết quả"], rows)


def blk_time(D):
    rows = []
    for rt in RUNTIMES:
        d = D[rt]
        rows.append([f"`{rt}`", f'{d["b_ok"]}/{d["b_n"]}', f(d["t_p50"], 0, " s"), f(d["t_p95"], 0, " s"),
                     f(d["steps_p50"], 0), f(d["create_p50"] / 1000 if d["create_p50"] else None, 2, " s"),
                     f(d["create_p95"] / 1000 if d["create_p95"] else None, 2, " s"),
                     f(d["first_p50"] / 1000 if d["first_p50"] else None, 2, " s"),
                     f(d["first_p95"] / 1000 if d["first_p95"] else None, 2, " s")])
    return table(["Runtime", "Success (1 phiên)", "Lượt đặt p50", "Lượt đặt p95", "Bước p50",
                  "Tạo phiên p50", "Tạo phiên p95", "Cold start p50", "Cold start p95"], rows)


def blk_per_task(D):
    tids = sorted({k for rt in RUNTIMES for k in D[rt]["per_task_p50"]})
    rows = [[f"`{rt}`"] + [f(D[rt]["per_task_p50"].get(t), 0) for t in tids] for rt in RUNTIMES]
    return table(["Runtime (giây, p50)"] + tids, rows)


def blk_resources(D):
    rows = []
    for rt in RUNTIMES:
        d = D[rt]
        cells = []
        for c in ("c1", "c3", "c5"):
            cells.append(f'{f(d[f"{c}_ram_p50"], 0)} / {f(d[f"{c}_ram_p95"], 0)}')
        cells.append(f(d["c1_cpu_p50"], 1, " s"))
        rows.append([f"`{rt}`", *cells, d["c1_scope"].split(" (")[0].replace("cây tiến trình pid", "cây tiến trình Chrome pid")])
    return table(["Runtime", "RAM đỉnh MB, 1 phiên (p50 / p95)", "3 song song", "5 song song", "CPU p50 / lượt",
                  "Đo cái gì"], rows)


def blk_stability(D):
    rows = []
    for rt in RUNTIMES:
        d = D[rt]
        rows.append([f"`{rt}`", f'{d["c3_ok"]}/{d["c3_n"]}', d["c3_lost"], d["c3_timeout"], f'{d["c5_ok"]}/{d["c5_n"]}',
                     f(d["c3_t_p50"], 0, " s"), f(d["c5_t_p50"], 0, " s"),
                     f'{d["orphans"]} / {d["orphan_checked"]}'])
    return table(["Runtime", "3 song song: success", "phiên mất (crashed)", "timeout", "5 song song: success",
                  "Lượt p50 ở 3 song song", "ở 5 song song", "Mồ côi sau stop() / số lần kiểm"], rows)


def _ab(d, page):
    a = d["ab"].get(page)
    if not a:
        return "—"
    t = a.get("text", "")
    if page == "browserscan":
        m = re.search(r"Test Results:\s*\n\s*(\w+)", t)
        return m.group(1) if m else "?"
    if page == "creepjs":
        g = {k: re.search(rf"(\d+)% {k}:", t) for k in ("like headless", "headless", "stealth")}
        return " · ".join(f"{k} {m.group(1)}%" for k, m in g.items() if m) or "?"
    return "ô Turnstile chờ bấm" if "NOWSECURE" in t.upper() else "?"


def blk_antibot(D):
    rows = []
    for rt in RUNTIMES:
        d = D[rt]
        ua = (d["ab"].get("browserscan") or {}).get("user_agent", "")
        m = re.search(r"\(([^;)]+)", ua)
        rows.append([f"`{rt}`", f'{d["s4_ok"]}/{d["s4_n"]}', _ab(d, "browserscan"), _ab(d, "creepjs"), _ab(d, "nowsecure"),
                     str((d["ab"].get("browserscan") or {}).get("webdriver", "—")).lower(), m.group(1) if m else "—"])
    return table(["Runtime", "s4_guarded success", "BrowserScan", "CreepJS", "nowsecure.nl", "navigator.webdriver",
                  "Hệ điều hành trong UA"], rows)


def blk_liveview(D):
    rows = []
    for rt in RUNTIMES:
        lv = D[rt]["lv"] or {}
        if not lv.get("has_url"):
            st = "không có URL Live View"
        elif lv.get("typed_ok"):
            st = "có, gõ được vào ô OTP"
        else:
            st = "có URL nhưng **không gõ được** (khung xem không nhận hình)"
        rows.append([f"`{rt}`", st, f(lv.get("input_latency_ms"), 0, " ms"), lv.get("viewer_ws_frames", "—")])
    return table(["Runtime", "Live View", "Trễ từ lúc gõ đến khi trang nhận", "Khung hình nhận được"], rows)


def blk_cost(D):
    rows = []
    for rt in RUNTIMES:
        d = D[rt]
        v = f'ước tính: {d["vps"][0]}' if d["vps"] else "giá dịch vụ (prices.toml)"
        rows.append([f"`{rt}`", f(d["session_s_p50"], 0, " s"), f(d["llm_per_ok"] and d["llm_per_ok"] * 1000, 2, " $"),
                     f(d["br_per_ok"] * 1000 + d["vps_per_ok"] * 1000 if d["b_ok"] else None, 2, " $"),
                     f(d["usd_1000"], 2, " $"), v, f(d["cache_ratio"] and d["cache_ratio"] * 100, 0, "%")])
    return table(["Runtime", "Phiên p50 (gồm chờ OTP)", "LLM / 1.000 lượt", "Trình duyệt / 1.000 lượt",
                  "Tổng / 1.000 lượt", "Nguồn giá trình duyệt", "Token đọc từ prompt cache"], rows)


def blk_scores(D):
    passed = [rt for rt in RUNTIMES if all(gates(D[rt]).values())]
    parts = []
    head = ["Runtime", "p95 lượt đặt (35)", "$/1.000 (30)", "RAM/phiên (15)", "p95 cold start (10)",
            "Live View (10)", "Tổng /100"]
    variants = [
        ("Chính thức (theo hợp đồng mục 10, chỉ runtime qua cổng loại)", D, passed, True),
        ("Tham khảo: cả 5 runtime, bỏ qua cổng loại", D, RUNTIMES, True),
        ("Tham khảo: cả 5 runtime, bỏ RAM (RAM cloud chỉ đo phía client nên không so được với local)", D, RUNTIMES, False),
    ]
    for title, data, cands, use_ram in variants:
        if not cands:
            parts.append(f"**{title}:** không runtime nào qua cổng loại.")
            continue
        S = scores(data, cands, use_ram)
        rows = [[f"`{rt}`"] + [f(S[rt].get(k), 0) if k in S[rt] else "—" for k in WEIGHTS] + [f"**{S[rt]['total']:.1f}**"]
                for rt in sorted(cands, key=lambda r: -S[r]["total"])]
        parts.append(f"**{title}**" + (" — tổng quy lại trên 85 điểm trọng số còn lại." if not use_ram else "")
                     + "\n\n" + table(head, rows))
    return "\n\n".join(parts)


def blk_latency(D):
    p = RES / "latency.json"
    if not p.exists():
        return "_Chưa đo: chạy `uv run python -m bench.runtime.latency`._"
    L = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for rt in RUNTIMES:
        x = L["runtimes"].get(rt)
        if not x or "error" in x:
            rows.append([f"`{rt}`", "lỗi: " + (x or {}).get("error", "chưa đo")[:80], "", "", ""])
            continue
        c, s = x["cdp_rtt"], x["site_ttfb_from_browser"]
        rows.append([f"`{rt}`", f'{c["p50_ms"]:.0f} / {c["p95_ms"]:.0f}', f'{s["p50_ms"]:.0f} / {s["p95_ms"]:.0f}',
                     "qua tunnel" if x["via_tunnel"] else "localhost", f(D[rt]["t_p50"], 0, " s")])
    out = table(["Runtime", "CDP máy đo ↔ trình duyệt, ms (p50 / p95)", "Trình duyệt → mock site, TTFB ms (p50 / p95)",
                 "Đường tới mock site", "Lượt đặt p50 (để đối chiếu)"], rows)
    h = L.get("harness_http")
    if h:
        out += (f'\n\nHTTP từ máy đo: localhost p50 {h["localhost"]["p50_ms"]:.0f} ms; qua tunnel p50 '
                f'{h["qua_tunnel"]["p50_ms"]:.0f} ms, p95 {h["qua_tunnel"]["p95_ms"]:.0f} ms. Đo lúc {L["checked_at"][:16]} UTC.')
    return out


BLOCKS = {"latency": blk_latency, "gates": blk_gates, "time": blk_time, "per_task": blk_per_task, "resources": blk_resources,
          "stability": blk_stability, "antibot": blk_antibot, "liveview": blk_liveview, "cost": blk_cost,
          "scores": blk_scores}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    D = collect()
    rendered = {k: fn(D) for k, fn in BLOCKS.items()}
    if a.print or not REPORT.exists():
        for k, v in rendered.items():
            print(f"\n## {k}\n\n{v}")
        return
    text = REPORT.read_text(encoding="utf-8")
    for k, v in rendered.items():
        text, n = re.subn(rf"(<!-- AUTO:{k} -->\r?\n).*?(<!-- /AUTO:{k} -->)",
                          lambda m: m.group(1) + v + "\n" + m.group(2), text, flags=re.S)
        if n == 0:
            print(f"(không thấy khối AUTO:{k} trong {REPORT.name})")
    REPORT.write_text(text, encoding="utf-8")
    print(f"đã cập nhật {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
