from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
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


REAL = Path("results/llm/real/combo.jsonl")
SCRIPTS = Path("results/llm/real/scripts")


def real_rows() -> list[dict]:
    rows = [json.loads(x) for x in REAL.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if not r["versions"].get("void")]


def kind(rows: list[dict], k: str, model: str | None = None) -> list[dict]:
    return [r for r in rows if r["versions"]["kind"] == k and (model is None or r["model"] == model)]


def wrong_fields(r: dict) -> list[str]:
    return [k for k, ok in (r["versions"].get("check") or {}).items() if not ok]


def real_summary(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["versions"].get("unscored")]
    ok = [r for r in scored if r["outcome"] == "success"]
    t = [r["total_ms"] / 1000 for r in ok]
    cost = sum(r["llm_cost_usd"] for r in rows)
    return {
        "n": len(rows),
        "scored": len(scored),
        "success": len(ok),
        "rate": len(ok) / len(scored) if scored else 0.0,
        "wrong": sum(r["outcome"] == "wrong_data" for r in scored),
        "unscored": len(rows) - len(scored),
        "unscored_wrong": sum(r["outcome"] == "wrong_data" for r in rows if r["versions"].get("unscored")),
        "cost": cost,
        "cost_per_run": cost / len(rows) if rows else None,
        "cost_per_success": cost / len(ok) if ok else None,
        "p50": pct(t, 0.5),
        "p95": pct(t, 0.95),
    }


def build() -> str:
    from bench.llm import combo_report

    allrecs = records()
    spent = spent_usd(allrecs)
    R = real_rows()
    L: list[str] = []
    L.append("# Báo cáo trục LLM & cache")
    L.append("")
    L.append(f"Sinh tự động bởi `uv run python -m bench.llm.report` ngày {date.today():%d/%m/%Y} từ `results/llm/`. Không có số nhập tay.")
    L.append("")
    L.append("- **Trục chính: 5 web nhà hàng thật**, dừng trước nút đặt, sau lớp chặn gửi đơn (`bench/llm/guard.py`). Dữ liệu: `results/llm/real/combo.jsonl`. Mock site chỉ là phụ lục (mục 7).")
    L.append("- Runtime: Chrome local (`bench/llm/chrome.py`, cùng cờ với `chrome_local` cộng 3 cờ chống che cửa sổ). Mỗi web 5 vòng; p95 tính nearest-rank trên lượt gộp, nên gần bằng giá trị lớn nhất.")
    L.append(f"- Tổng đã tiêu cho trục LLM (mọi file trong `results/llm/`): **${spent:.4f}**.")
    L.append("- Lượt `void` (hết hạn mức API) bị loại. Lượt `unscored` (lỗi API, hoặc harness không đọc được ô select ở Lẩu Wang) không tính đúng/sai, nhưng **vẫn tính tiền** vào $/success.")
    L.append("")

    models = sorted({r["model"] for r in kind(R, "cold")})
    S = {m: real_summary(kind(R, "cold", m)) for m in models}
    otp = [r for r in measured(allrecs) if r["site"] == "s5_otp" and r["cache_mode"] == "none"]

    L.append("## 1. Cổng loại (`cache_mode = none`, web thật)")
    L.append("")
    L.append("| Model | Lượt (chấm được) | Success ≥ 80% | 0 wrong_data | Không chấm được | Dừng đúng ở OTP (mock s5) | Kết quả |")
    L.append("|---|---|---|---|---|---|---|")
    passed: list[str] = []
    for m in models:
        s = S[m]
        o = [r for r in otp if r["model"] == m and r.get("paused_for_otp") is not None]
        o_ok = bool(o) and all(r["paused_for_otp"] for r in o)
        g1, g2 = s["rate"] >= GATE_SUCCESS, s["wrong"] == 0
        ok = g1 and g2 and o_ok
        if ok:
            passed.append(m)
        o_txt = f"{'✅' if o_ok else '❌'} {sum(bool(r['paused_for_otp']) for r in o)}/{len(o)}" if o else "— chưa đo"
        L.append(
            f"| {m} | {s['n']} ({s['scored']}) | {'✅' if g1 else '❌'} {s['success']}/{s['scored']} ({s['rate']:.0%}) | "
            f"{'✅' if g2 else '❌'} {s['wrong']} | {s['unscored']} (trong đó ghi `wrong_data`: {s['unscored_wrong']}) | {o_txt} | {'**qua**' if ok else 'loại'} |"
        )
    L.append("")
    strict = [m for m in passed if S[m]["unscored_wrong"]]
    for m in strict:
        L.append(
            f"- ⚠️ `{m}` qua cổng theo cách chấm hiện tại. Nếu tính cả {S[m]['unscored_wrong']} lượt Lẩu Wang mà harness ghi `wrong_data` "
            "nhưng không đọc được ô select (form đọc ra thiếu ô giờ và ô cơ sở), thì **trượt cổng 0 wrong_data**. Xem mục 8."
        )
    L.append("")

    L.append("## 2. Chấm điểm (model qua cổng)")
    L.append("")
    L.append("| Model | $/success | p95 | Success | Điểm $/success (40) | Điểm p95 (35) | Điểm success (25) | Tổng |")
    L.append("|---|---|---|---|---|---|---|---|")
    winner = None
    if passed:
        nc = norm({m: S[m]["cost_per_success"] or 0 for m in passed}, True)
        np_ = norm({m: S[m]["p95"] or 0 for m in passed}, True)
        nr = norm({m: S[m]["rate"] for m in passed}, False)
        total = {m: (nc[m] * WEIGHTS["cost"] + np_[m] * WEIGHTS["p95"] + nr[m] * WEIGHTS["success"]) / 100 for m in passed}
        for m in sorted(passed, key=lambda x: -total[x]):
            s = S[m]
            L.append(f"| {m} | {money(s['cost_per_success'])} | {sec(s['p95'])} | {s['rate']:.0%} | {nc[m]:.0f} | {np_[m]:.0f} | {nr[m]:.0f} | **{total[m]:.1f}** |")
        winner = max(passed, key=lambda x: total[x])
    for m in models:
        if m not in passed:
            s = S[m]
            L.append(f"| {m} (loại ở cổng) | {money(s['cost_per_success'])} | {sec(s['p95'])} | {s['rate']:.0%} | — | — | — | — |")
    L.append("")
    if winner:
        L.append(f"**Model thắng: `{winner}`.**" + (" Chỉ 1 model qua cổng nên điểm mặc định 100." if len(passed) == 1 else ""))
    else:
        L.append("Không model nào qua cổng loại.")
    L.append("")

    L.append("## 3. Chế độ cache")
    L.append("")
    L.append("Trên web thật, `actions` là **cache quy trình**: từ một lượt `none` thành công, sinh một script Playwright có tham số (`results/llm/real/scripts/`). "
             "Lượt sau chạy script, **không gọi LLM**; script tự từ chối (`UNAVAILABLE`) khi không khớp được dữ liệu, lúc đó mới gọi LLM chạy chay.")
    L.append("")
    L.append("| Cách | Success | $/lượt | p50 | p95 | Chênh success so với `none` |")
    L.append("|---|---|---|---|---|---|")
    base = S.get(winner) if winner else None
    opts = []
    rows_modes = [("`none` — " + (winner or "?") + " chạy chay", kind(R, "cold", winner) if winner else []),
                  ("`actions` — script qua browser-use", kind(R, "replay")),
                  ("`actions` — script chạy thẳng trên CDP", kind(R, "direct"))]
    for name, rows in rows_modes:
        if not rows:
            continue
        s = real_summary(rows)
        d = "—" if base is None or name.startswith("`none`") else f"{(s['rate'] - base['rate']) * 100:+.0f} điểm %"
        L.append(f"| {name} | {s['success']}/{s['scored']} ({s['rate']:.0%}) | {money(s['cost_per_run'])} | {sec(s['p50'])} | {sec(s['p95'])} | {d} |")
        if base is not None and (base["rate"] - s["rate"]) * 100 <= MODE_TOLERANCE_PP:
            opts.append((s["cost_per_run"], s["p95"] or 0, name))
    L.append("")
    pick = min(opts)[2] if opts else None
    L.append(f"**Chế độ cache thắng: {pick}** (rẻ nhất mà success không thấp hơn `none` quá {MODE_TOLERANCE_PP:.0f} điểm %; hòa tiền thì lấy p95 thấp hơn)." if pick else "Chưa chọn được chế độ cache.")
    L.append("")
    chk = kind(R, "check")
    L.append(f"- Đổi dữ liệu khách (ngày/giờ/số người khác) trên script: {sum(r['outcome'] == 'success' for r in chk)}/{len(chk)} đúng, "
             f"{sum(r['outcome'] == 'blocked' for r in chk)} script tự từ chối (báo `UNAVAILABLE`, chuyển sang LLM), **{sum(r['outcome'] == 'wrong_data' for r in chk)} điền sai mà không báo**.")
    fo = kind(R, "failover")
    L.append(f"- Thử cache hỏng: script phát hiện lỗi {len(kind(R, 'detect'))}/{len(kind(R, 'detect'))}; {winner or 'LLM'} chạy chay cứu được {sum(r['outcome'] == 'success' for r in fo)}/{len(fo)}.")
    L.append("- `session` (nạp lại cookie): chưa đo trên web thật.")
    L.append("")
    L.append("**Điểm hòa vốn** `N* = chi phí học ÷ (chi phí lượt none − chi phí lượt cache)`, theo từng web:")
    L.append("")
    L.append("| Web | Chi phí học + sinh script | Tiết kiệm $/lượt | N* (lượt) |")
    L.append("|---|---|---|---|")
    for site in combo_report.SITES:
        p = SCRIPTS / f"{site}.json"
        cold = [r for r in kind(R, "cold", winner) if r["site"] == site and r["outcome"] == "success"] if winner else []
        di = [r for r in kind(R, "direct") if r["site"] == site and r["outcome"] == "success"]
        if not (p.exists() and cold and di):
            continue
        z = json.loads(p.read_text(encoding="utf-8"))
        learn = z["learn_cost_usd"] + z["cost_usd"]
        save = statistics.mean(r["llm_cost_usd"] for r in cold) - statistics.mean(r["llm_cost_usd"] for r in di)
        L.append(f"| {site[5:]} | {money(learn)} | {money(save)} | **{math.ceil(learn / save)}** |")
    L.append("")

    L.append("## 4. Các lượt `wrong_data` và sai ở trường nào")
    L.append("")
    L.append("| Model | Web | Vòng | Cách | Trường sai | Được chấm? |")
    L.append("|---|---|---|---|---|---|")
    bad = [r for r in R if r["outcome"] == "wrong_data"]
    for r in bad:
        v = r["versions"]
        L.append(f"| {r['model']} | {r['site'][5:]} | {r['rep']} | {v['kind']} | {', '.join(wrong_fields(r)) or '—'} | {'không — ' + v['unscored'] if v.get('unscored') else 'có'} |")
    if not bad:
        L.append("| — | — | — | — | — | — |")
    L.append("")
    L.append("Mọi lượt `wrong_data` đều sai ở trường **giờ**. Đây là rủi ro chính cho module đặt bàn phía sau.")
    L.append("")

    L.append("## 5. Kết luận cho Agent 1 (M4) và pipeline")
    L.append("")
    L.append(f"- Model thắng: **`{winner or 'chưa có'}`** (`get_llm()` mặc định trỏ vào model này).")
    L.append(f"- Chế độ cache thắng: **{pick or 'chưa có'}**, cùng LLM chạy chay khi script từ chối hoặc lỗi.")
    L.append("- Xét lại khi: có model mới, giá đổi trên 30%, success thật dưới 80%, hoặc có key Gemini/xAI để đo đủ ứng viên.")
    L.append("")

    L.append("## 6. Chi tiết web thật")
    L.append("")
    L.append("Sinh bởi `bench.llm.combo_report`, cùng dữ liệu.")
    L.append("")
    L.extend(x.replace("## ", "### ", 1) for x in combo_report.lines())
    L.append("")

    L.append("## 7. Phụ lục: mock site (23/11, trước khi đổi hướng)")
    L.append("")
    mock = measured(allrecs)
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in mock:
        by[(r["model"], r["cache_mode"])].append(r)
    L.append("| Model | Cache | Task | Lượt | Success | wrong_data | $/lượt | p50 | p95 | Bước p50 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for (m, mode), rows in sorted(by.items()):
        s = summarize(rows)
        L.append(f"| {m} | `{mode}` | {len({r['task_id'] for r in rows})} | {s['n']} | {s['success']}/{s['n']} | {s['wrong']} | {money(s['cost_per_run'])} | {sec(s['p50'])} | {sec(s['p95'])} | {s['steps_p50']} |")
    L.append("")
    L.append("`actions` trên mock site là bản cũ (gợi ý code đưa vào prompt, LLM vẫn chạy), dừng sau 4/10 task khi chuyển sang web thật.")
    L.append("")

    L.append("## 7b. Chạy lại script cache có chụp ảnh (25/11, Linux, không gọi LLM)")
    L.append("")
    L.append("Sinh bởi `uv run python -m bench.llm.shots`; ảnh và từng bước ở `results/llm/real/shots/`, xem kèm ảnh trong `results/llm/real/llm_web.xlsx`.")
    L.append("")
    L.append("| Web | Script | Số lần | Đúng | Từ chối (blocked) | Sai (wrong_data) | Hỏng (failed) | Dữ liệu khách định rời trang | p50 thời gian script, gồm chụp ảnh (s) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    lf = Path("results/llm/real/shots/runs.jsonl")
    runs = [json.loads(x) for x in lf.read_text(encoding="utf-8").splitlines() if x.strip()] if lf.exists() else []
    for site in combo_report.SITES:
        for ver in ("v1", "v2a", "v2"):
            rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == ver]
            if rs:
                c = Counter(r["outcome"] for r in rs)
                p50 = pct([r["ms"] / 1000 for r in rs if r["outcome"] == "success" and r.get("ms")], 0.5)
                L.append(f"| {site[5:]} | {ver} | {len(rs)} | {c['success']} | {c['blocked']} | {c['wrong_data']} | {c['failed']} | {sum(r['guard_submit_attempts'] for r in rs)} | {'—' if p50 is None else f'{p50:.1f}'} |")
    L.append("")
    L.append("Script v1: do Haiku sinh, dùng trong đợt đo 24/11. Script v2: sửa tay ngày 25/11 cho Lẩu Wang, Lẩu Phan, King BBQ (lý do trong `script_v2_note` của file script). "
             "`v2a`: bản v2 đầu của Lẩu Wang, lỗi ở đoạn kiểm tra mới thêm (so chữ hiển thị với chữ option, trong khi theme xóa chữ option); form thật đúng, đã sửa thành v2. Không tính vào kết quả.")
    L.append("")
    rc = []
    for f in sorted(Path("results/llm/real").glob("recheck_*.jsonl")):
        rc += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    if rc:
        L.append("Chạy lại các ca đổi dữ liệu khách với script mới (`uv run python -m bench.llm.recheck`):")
        L.append("")
        L.append("| Web | Script | Ca | Đúng | Từ chối | Điền sai | Hỏng |")
        L.append("|---|---|---|---|---|---|---|")
        for site in combo_report.SITES:
            rs = [r for r in rc if r["site"] == site]
            if rs:
                c = Counter(r["outcome"] for r in rs)
                L.append(f"| {site[5:]} | {rs[-1]['versions'].get('script', 'v1')} | {len(rs)} | {c['success']} | {c['blocked']} | {c['wrong_data']} | {c['failed']} |")
        L.append("")
    L.append("Lỗi của script v1 (thấy qua ảnh) và cách v2 sửa:")
    L.append("- **Lẩu Phan**: v1 có lần sai giờ: script kết thúc khi ô Giờ còn đang tải, tải xong thì giờ bị đặt về 'Chọn' (một lần chạy lại trước khi có `runs.jsonl`, không nằm trong bảng). v2 chờ ô Giờ đứng yên 2 giây sau khi điền, bị đặt lại thì chọn lại.")
    L.append("- **King BBQ**: v1 chọn nhà hàng khi danh sách chưa tải xong, nên có lần tự từ chối và chuyển sang LLM (không điền sai). v2 chờ danh sách nhà hàng tải xong.")
    L.append("- **Lẩu Wang**: v1 chỉ gán `<select>` gốc nên ô hiển thị vẫn 'Giờ' / 'Chọn cơ sở'. v2 chọn qua widget của theme, ô hiển thị đổi theo, và kiểm tra cả chữ hiển thị.")
    L.append("- Ca đổi dữ liệu với v2: không có lần điền sai; các lần từ chối giống v1 (giờ web không có: 18:15, 03:00).")
    L.append("")

    L.append("## 8. Chưa kiểm chứng")
    L.append("")
    for m in models:
        u = [r for r in kind(R, "cold", m) if r["versions"].get("unscored") and r["outcome"] == "wrong_data"]
        if u:
            L.append(f"- **{len(u)} lượt `{m}` ({', '.join(sorted({r['site'][5:] for r in u}))}, vòng {', '.join(str(r['rep']) for r in u)})**: harness ghi `wrong_data` "
                     f"(sai {', '.join(sorted({f for r in u for f in wrong_fields(r)}))}), nhưng xếp `unscored` vì bộ đọc form không đọc được widget. "
                     "**Chưa chứng minh** model đã chọn đúng. Cần chụp màn hình hoặc đọc lại widget ở lần đo sau.")
    api = {m: sum(r["versions"].get("unscored") == "api error" for r in kind(R, "cold", m)) for m in models}
    L.append(f"- Sonnet 5.5 chưa đo trên web thật; Grok chưa đo (không có credit xAI). Lượt lỗi API (không chấm): {api}.")
    L.append("- Mỗi web chỉ 5 vòng (hợp đồng gốc: 11), ngân sách $1,80; p95 gần bằng max.")
    L.append("- CPU máy đo rất cao lúc đo (có RPA khác chạy song song, máy Windows): số giây chỉ dùng để so sánh tương đối.")
    L.append("- Lượt `none` không đi tới bước OTP trên web thật; cổng OTP lấy từ mock `s5_otp`.")
    L.append("- Chưa thử gửi đơn thật (cố ý). Bước bấm nút đặt và OTP của nhà hàng thật chưa được đo.")
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
