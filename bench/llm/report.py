from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from bench.llm.budget import is_valid, records, spent_usd

OUT = Path("reports/llm.md")
WEIGHTS = {"cost": 40, "p95": 35, "success": 25}
GATE_SUCCESS = 0.80
MODE_TOLERANCE_PP = 5.0


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, math.ceil(q * len(s)) - 1)
    return s[k]


def active_s(r: dict) -> float:
    return ((r.get("total_ms") or 0) - (r.get("human_wait_ms") or 0)) / 1000


def measured(recs: list[dict]) -> list[dict]:
    return [r for r in recs if is_valid(r) and not r.get("warmup") and r.get("outcome") != "skipped" and not r["site"].startswith(("dev", "real"))]


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["outcome"] == "success"]
    cost = sum(r.get("llm_cost_usd", 0) for r in rows)
    t = [active_s(r) for r in rows]
    tin = sum(r.get("tokens_in", 0) for r in rows)
    tcr = sum(r.get("tokens_cache_read", 0) for r in rows)
    return {
        "n": n,
        "success": len(ok),
        "rate": len(ok) / n if n else 0.0,
        "wrong": sum(r["outcome"] == "wrong_data" for r in rows),
        "outcomes": dict(sorted(_count(r["outcome"] for r in rows).items())),
        "cost": cost,
        "cost_per_run": cost / n if n else None,
        "cost_per_success": cost / len(ok) if ok else None,
        "p50": pct(t, 0.5),
        "p95": pct(t, 0.95),
        "steps_p50": pct([r["steps"] for r in rows if r.get("steps") is not None], 0.5),
        "steps_p95": pct([r["steps"] for r in rows if r.get("steps") is not None], 0.95),
        "tokens_in_mean": tin / n if n else 0,
        "tokens_out_mean": sum(r.get("tokens_out", 0) for r in rows) / n if n else 0,
        "cache_share": tcr / tin if tin else 0.0,
    }


def _count(it) -> dict:
    d: dict = defaultdict(int)
    for x in it:
        d[x] += 1
    return d


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:.4f}"


def sec(x: float | None) -> str:
    return "—" if x is None else f"{x:.1f} s"


def norm(values: dict[str, float], lower_is_better: bool) -> dict[str, float]:
    if len(values) == 1:
        return {k: 100.0 for k in values}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 100.0 for k in values}
    return {k: 100 * ((hi - v) if lower_is_better else (v - lo)) / (hi - lo) for k, v in values.items()}


def build() -> str:
    allrecs = records()
    recs = measured(allrecs)
    spent = spent_usd(allrecs)
    by_mm: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in recs:
        by_mm[(r["model"], r["cache_mode"])].append(r)
    models = sorted({m for m, _ in by_mm})
    L: list[str] = []
    L.append("# Báo cáo trục LLM & cache")
    L.append("")
    L.append(f"Sinh tự động bởi `uv run python -m bench.llm.report` ngày {date.today():%d/%m/%Y} từ `results/llm/*.jsonl`. Không có số nhập tay.")
    L.append("")
    L.append(f"- Runtime cố định: `chrome_local`. Tổng đã tiêu cho trục LLM (gồm warm-up, dev site): **${spent:.4f}**.")
    L.append("- Thời gian = thời gian chạy **không tính lúc chờ người** (OTP). p95 lấy theo nearest-rank; ô có ≤ 10 lượt thì p95 gần như là giá trị lớn nhất.")
    L.append("- Warm-up bị loại khỏi mọi bảng.")
    L.append("")

    L.append("## 1. Tổng hợp theo model × chế độ cache")
    L.append("")
    L.append("| Model | Cache | Lượt | Success | wrong_data | $/lượt | $/success | p50 | p95 | Bước p50/p95 | Token in TB | Token out TB | % input từ cache |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    S: dict[tuple[str, str], dict] = {}
    for (m, mode), rows in sorted(by_mm.items()):
        s = S[(m, mode)] = summarize(rows)
        L.append(
            f"| {m} | `{mode}` | {s['n']} | {s['success']}/{s['n']} ({s['rate']:.0%}) | {s['wrong']} | {money(s['cost_per_run'])} | "
            f"{money(s['cost_per_success'])} | {sec(s['p50'])} | {sec(s['p95'])} | {s['steps_p50']}/{s['steps_p95']} | "
            f"{s['tokens_in_mean']:.0f} | {s['tokens_out_mean']:.0f} | {s['cache_share']:.0%} |"
        )
    L.append("")

    L.append("## 2. Theo site (chế độ `none`)")
    L.append("")
    sites = sorted({r["site"] for r in recs})
    L.append("| Model | " + " | ".join(sites) + " |")
    L.append("|---|" + "---|" * len(sites))
    for m in models:
        cells = []
        for st in sites:
            rows = [r for r in by_mm.get((m, "none"), []) if r["site"] == st]
            if not rows:
                cells.append("—")
                continue
            s = summarize(rows)
            cells.append(f"{s['success']}/{s['n']} · {sec(s['p50'])} · {money(s['cost_per_run'])}")
        L.append(f"| {m} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("Mỗi ô: success/lượt · p50 thời gian · $/lượt.")
    L.append("")

    L.append("## 3. Cổng loại (chế độ `none`)")
    L.append("")
    L.append("| Model | Success ≥ 80% | 0 wrong_data | Dừng đúng ở OTP (s5) | Kết quả |")
    L.append("|---|---|---|---|---|")
    passed: list[str] = []
    for m in models:
        rows = by_mm.get((m, "none"), [])
        if not rows:
            continue
        s = summarize(rows)
        otp_rows = [r for r in rows if r.get("paused_for_otp") is not None]
        otp_ok = all(r["paused_for_otp"] for r in otp_rows) if otp_rows else None
        g1, g2 = s["rate"] >= GATE_SUCCESS, s["wrong"] == 0
        g3 = bool(otp_ok)
        ok = g1 and g2 and g3
        if ok:
            passed.append(m)
        otp_txt = "—" if otp_ok is None else f"{sum(r['paused_for_otp'] for r in otp_rows)}/{len(otp_rows)}"
        L.append(f"| {m} | {'✅' if g1 else '❌'} {s['rate']:.0%} | {'✅' if g2 else '❌'} {s['wrong']} | {'✅' if g3 else '❌'} {otp_txt} | {'**qua**' if ok else 'loại'} |")
    L.append("")

    L.append("## 4. Chấm điểm (các model qua cổng, chế độ `none`)")
    L.append("")
    if passed:
        cost = {m: S[(m, "none")]["cost_per_success"] or 0 for m in passed}
        p95 = {m: S[(m, "none")]["p95"] or 0 for m in passed}
        rate = {m: S[(m, "none")]["rate"] for m in passed}
        nc, np_, nr = norm(cost, True), norm(p95, True), norm(rate, False)
        total = {m: (nc[m] * WEIGHTS["cost"] + np_[m] * WEIGHTS["p95"] + nr[m] * WEIGHTS["success"]) / 100 for m in passed}
        L.append("| Model | $/success (40) | p95 (35) | Success (25) | Tổng |")
        L.append("|---|---|---|---|---|")
        for m in sorted(passed, key=lambda x: -total[x]):
            L.append(f"| {m} | {nc[m]:.0f} | {np_[m]:.0f} | {nr[m]:.0f} | **{total[m]:.1f}** |")
        winner = max(passed, key=lambda x: total[x])
        L.append("")
        L.append(f"**Model thắng: `{winner}`.**" + (" Chỉ có 1 model qua cổng nên điểm mặc định là 100." if len(passed) == 1 else ""))
    else:
        winner = None
        L.append("Không model nào qua cổng loại.")
    L.append("")

    L.append("## 5. Chế độ cache và điểm hòa vốn")
    L.append("")
    L.append("| Model | Cache | Success | $/lượt | So với `none` | Bước p50 |")
    L.append("|---|---|---|---|---|---|")
    mode_pick: dict[str, str] = {}
    for m in models:
        base = S.get((m, "none"))
        if not base:
            continue
        options = []
        for mode in ("none", "session", "actions"):
            s = S.get((m, mode))
            if not s:
                continue
            delta = "—" if mode == "none" else f"{(s['cost_per_run'] - base['cost_per_run']) / base['cost_per_run']:+.0%} chi phí, {(s['rate'] - base['rate']) * 100:+.0f} điểm % success"
            L.append(f"| {m} | `{mode}` | {s['rate']:.0%} | {money(s['cost_per_run'])} | {delta} | {s['steps_p50']} |")
            if (base["rate"] - s["rate"]) * 100 <= MODE_TOLERANCE_PP:
                options.append((s["cost_per_run"], mode))
        if options:
            mode_pick[m] = min(options)[1]
    L.append("")
    for m, mode in mode_pick.items():
        L.append(f"- `{m}`: chế độ cache được chọn **`{mode}`** (rẻ nhất mà success không thấp hơn `none` quá {MODE_TOLERANCE_PP:.0f} điểm %).")
    L.append("")
    caches = sorted(Path("results/llm/cache").glob("*/*.json"))
    learn: dict[str, list[float]] = defaultdict(list)
    for p in caches:
        if p.name.startswith("dev"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        learn[p.parent.name].append(d.get("learn_cost_usd") or 0)
    for m in models:
        base, act = S.get((m, "none")), S.get((m, "actions"))
        if not (base and act and learn.get(m)):
            continue
        lc = statistics.mean(learn[m])
        saving = base["cost_per_run"] - act["cost_per_run"]
        if saving > 0:
            L.append(f"- Điểm hòa vốn `{m}` · `actions`: chi phí học TB {money(lc)} ÷ tiết kiệm {money(saving)}/lượt ≈ **{lc / saving:.1f} lượt**.")
        else:
            L.append(f"- `{m}` · `actions` **không rẻ hơn** `none` về tiền ({money(act['cost_per_run'])} so với {money(base['cost_per_run'])}/lượt): không có điểm hòa vốn về chi phí; lợi ích nếu có nằm ở thời gian/số bước.")
    L.append("")

    L.append("## 6. Các lượt không thành công")
    L.append("")
    bad = [r for r in recs if r["outcome"] != "success"]
    if not bad:
        L.append("Không có.")
    else:
        L.append("| Model | Cache | Task | Kết quả | Lỗi / ghi chú |")
        L.append("|---|---|---|---|---|")
        for r in bad:
            note = (r.get("error") or "").replace("|", "/").replace("\n", " ")[:140]
            if r["outcome"] == "wrong_data":
                note = "đơn: " + json.dumps(r["versions"].get("bookings"), ensure_ascii=False)[:140]
            L.append(f"| {r['model']} | `{r['cache_mode']}` | {r['task_id']} | {r['outcome']} | {note} |")
    L.append("")

    L.append("## 7. Kết luận cho Agent 1 (bước M4)")
    L.append("")
    L.append(f"- Model thắng: **{winner or 'chưa có'}**")
    if winner:
        L.append(f"- Chế độ cache thắng: **`{mode_pick.get(winner, 'none')}`**")
    L.append("")

    L.append("## 8. Chưa kiểm chứng")
    L.append("")
    L.append("- Grok chưa đo (chưa có credit xAI). Kết luận chỉ là giữa các model Claude.")
    L.append("- Ngân sách chỉ $1,80, nên mỗi ô có ít lượt; p95 không ổn định, cần đo thêm khi có tiền.")
    L.append("- Sonnet chỉ có 1 lượt/task, không warm-up: số thời gian của Sonnet có thể bị lệch lên do lượt đầu.")
    L.append("- `actions` là gợi ý code đưa vào prompt (browser-use 1.0 bỏ chạy lại lịch sử); chưa đo phương án chạy lại code không qua LLM.")
    L.append("- Mock site chạy local; chưa đo trên site nhà hàng thật.")
    L.append("")
    return "\n".join(L)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"đã ghi {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
