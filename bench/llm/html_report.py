"""Sinh trang HTML kết quả trục LLM & cache (phần Agent 2), kèm ảnh từng bước.

Mọi số đọc từ results/llm/ (không nhập tay). Ảnh lấy từ results/llm/real/shots/, nén JPEG.

    uv run --with pillow python -m bench.llm.html_report
Ra: results/llm/real/html/index.html + img/*.jpg
"""
from __future__ import annotations

import html
import json
import math
import statistics as st
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from bench.llm.budget import family, records, spent_usd
from bench.llm.report import kind, real_rows, real_summary, wrong_fields

OUT = Path("results/llm/real/html")
SHOTS = Path("results/llm/real/shots")
SCRIPTS = Path("results/llm/real/scripts")
SITES = {"real_lauphan": "Lẩu Phan", "real_tong": "Tòng", "real_chaoxian": "Chao Xian", "real_lauwang": "Lẩu Wang", "real_kingbbq": "King BBQ"}
HAIKU, GEMINI = "claude-haiku-5-5", "gemini-3.5-flash-lite"
WAYS = [
    ("haiku", "Haiku chạy chay", "none", "cold", HAIKU),
    ("gemini", "Gemini flash-lite chạy chay", "none", "cold", GEMINI),
    ("replay", "Script cache qua browser-use", "actions", "replay", None),
    ("direct", "Script cache chạy thẳng", "actions", "direct", None),
]
E = html.escape


def pct(x, q):
    x = sorted(x)
    return x[max(0, math.ceil(q * len(x)) - 1)] if x else None


def f1(x):
    return "—" if x is None else f"{x:.1f}"


def money(x, d=4):
    return "—" if x is None else f"${x:.{d}f}"


def jpg(src: Path, name: str) -> str:
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    w, h = im.size
    im = im.resize((960, int(h * 960 / w)))
    im.save(OUT / "img" / name, "JPEG", quality=72, optimize=True)
    return f"img/{name}"


def runs_log() -> list[dict]:
    f = SHOTS / "runs.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def recheck_log() -> list[dict]:
    out = []
    for f in sorted(Path("results/llm/real").glob("recheck_*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def breakeven(R, site):
    p = SCRIPTS / f"{site}.json"
    cold = [r for r in kind(R, "cold", HAIKU) if r["site"] == site and r["outcome"] == "success"]
    di = [r for r in kind(R, "direct") if r["site"] == site and r["outcome"] == "success"]
    if not (p.exists() and cold and di):
        return None
    z = json.loads(p.read_text(encoding="utf-8"))
    learn = z["learn_cost_usd"] + z["cost_usd"]
    save = st.mean(r["llm_cost_usd"] for r in cold) - st.mean(r["llm_cost_usd"] for r in di)
    return {"learn": learn, "save": save, "n": math.ceil(learn / save)}


def pill(outcome: str) -> str:
    cls = {"success": "ok", "blocked": "warn", "wrong_data": "bad", "failed": "bad"}.get(outcome, "warn")
    label = {"success": "đúng", "blocked": "từ chối", "wrong_data": "điền sai", "failed": "hỏng"}.get(outcome, outcome)
    return f'<span class="pill {cls}">{label}</span>'


def bars(rows: list[tuple[str, float | None, float | None]]) -> str:
    vmax = max((b or 0) for _, _, b in rows) or 1
    scale = math.ceil(vmax / 20) * 20
    out = ['<div class="bars" role="img" aria-label="Thời gian p50 và p95 mỗi cách chạy, giây">']
    for label, p50, p95 in rows:
        out.append(
            f'<div class="bar-row"><span class="bar-label">{E(label)}</span><div class="bar-track">'
            f'<div class="bar p95" style="width:{(p95 or 0) / scale * 100:.1f}%"></div>'
            f'<div class="bar p50" style="width:{(p50 or 0) / scale * 100:.1f}%"></div></div>'
            f'<span class="bar-val num">{f1(p50)} / {f1(p95)} s</span></div>'
        )
    ticks = "".join(f'<span style="left:{t / scale * 100:.1f}%">{t:g}</span>' for t in range(0, int(scale) + 1, int(scale // 4) or 1))
    out.append(f'<div class="bar-row axis"><span class="bar-label"></span><div class="bar-ticks">{ticks}</div><span class="bar-val"></span></div>')
    out.append('<p class="legend"><span class="key p50"></span>p50 <span class="key p95"></span>p95 (giây, chỉ lượt đúng)</p></div>')
    return "".join(out)


def steps_html(site: str, d: dict, prefix: str) -> str:
    folder = SHOTS / site / prefix if prefix else SHOTS / site
    items = []
    for s in d["steps"]:
        if not s.get("file") or not (folder / s["file"]).exists():
            continue
        src = jpg(folder / s["file"], f"{site}_{prefix or 'main'}_{s['n']:02d}.jpg")
        ch = "".join(f"<li>{E(c)}</li>" for c in s["changed"][:8])
        items.append(
            f'<figure class="step"><a href="{src}" target="_blank" rel="noopener"><img src="{src}" loading="lazy" '
            f'alt="{E(SITES[site])} bước {s["n"]}"></a><figcaption><span class="step-n num">{s["n"]:02d}</span>'
            f'<span class="step-t num">{s["t"]:.1f} s</span><p class="step-a">{E(s["action"][:140])}</p><ul>{ch}</ul></figcaption></figure>'
        )
    return f'<div class="steps">{"".join(items)}</div>'


def build() -> str:
    R = real_rows()
    allrecs = records()
    S = {m: real_summary(kind(R, "cold", m)) for m in (HAIKU, GEMINI)}
    W = {}
    for key, label, mode, k, m in WAYS:
        rows = kind(R, k, m)
        sc = [r for r in rows if not r["versions"].get("unscored")]
        ok = [r for r in sc if r["outcome"] == "success"]
        t = [r["total_ms"] / 1000 for r in ok]
        cost = sum(r["llm_cost_usd"] for r in rows)
        W[key] = {"label": label, "mode": mode, "n": len(rows), "scored": len(sc), "ok": len(ok), "unscored": len(rows) - len(sc),
                  "wrong": sum(r["outcome"] == "wrong_data" for r in sc), "p50": pct(t, 0.5), "p95": pct(t, 0.95),
                  "cpr": cost / len(rows) if rows else None, "cps": cost / len(ok) if ok else None}
    spend = {f: spent_usd([r for r in allrecs if family(r.get("model") or "-") == f]) for f in ("claude", "gemini")}
    chk = kind(R, "check")
    runs = runs_log()
    rc = recheck_log()
    bev = {s: breakeven(R, s) for s in SITES}
    ns = [b["n"] for b in bev.values() if b]
    fo = kind(R, "failover")

    css = CSS
    h = []
    h.append(f"""<title>Agent 2 · LLM &amp; cache</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{css}</style>
<nav class="topnav"><div class="wrap nav-in"><span class="brand">Agent 2 · LLM &amp; cache</span>
<a href="#ket-luan">Kết luận</a><a href="#so-lieu">Số liệu</a><a href="#cache">Cache</a><a href="#script-v2">Script v2</a><a href="#tung-web">Từng web</a><a href="#chua-kiem-chung">Chưa kiểm chứng</a></div></nav>
<main class="wrap">
<header class="head" id="ket-luan">
<p class="eyebrow">Module chọn công nghệ · agent đặt bàn · trục LLM &amp; cache</p>
<h1>Haiku 5.5 làm agent, cache quy trình cho lượt lặp lại</h1>
<p class="lede">Đo trên 5 web nhà hàng thật, mỗi web 5 vòng, dừng trước nút đặt và chạy sau lớp chặn gửi đơn. Ca chính: 3 người, ngày mai, 18:00, khách giả <span class="mono">Khach Thu Nghiem · 0000000000</span>.</p>
<div class="verdict">
 <div class="v-card"><span class="v-k">Model thắng</span><span class="v-v mono">claude-haiku-5-5</span>
  <span class="v-d">{W['haiku']['ok']}/{W['haiku']['scored']} lượt chấm được đều đúng · p50 {f1(W['haiku']['p50'])} s · {money(W['haiku']['cps'])}/lượt đúng</span></div>
 <div class="v-card"><span class="v-k">Cache thắng</span><span class="v-v mono">actions · script chạy thẳng</span>
  <span class="v-d">{W['direct']['ok']}/{W['direct']['scored']} đúng · p50 {f1(W['direct']['p50'])} s · không gọi LLM · hòa vốn sau {min(ns)}–{max(ns)} lượt/web</span></div>
 <div class="v-card out"><span class="v-k">Bị loại</span><span class="v-v mono">gemini-3.5-flash-lite</span>
  <span class="v-d">{W['gemini']['wrong']} lượt điền sai giờ (cổng yêu cầu 0) · {W['gemini']['unscored']} lượt không chấm được</span></div>
</div>
<p class="note">Ngân sách đã dùng: Claude {money(spend['claude'], 2)} / $1,80 · Gemini {money(spend['gemini'], 2)} / $1,00. Sonnet và Grok chưa đo.</p>
</header>""")

    # ---------- số liệu ----------
    h.append('<section id="so-lieu"><h2>Số liệu theo cách chạy</h2><p class="sub">Đợt đo 24/11, 5 web × 5 vòng. Lượt không chấm được vẫn tính tiền vào $/lượt đúng.</p>')
    h.append(bars([(W[k]["label"], W[k]["p50"], W[k]["p95"]) for k, *_ in WAYS]))
    h.append('<div class="tbl"><table><thead><tr><th>Cách</th><th><span class="mono">cache_mode</span></th><th class="r">Đúng / chấm được</th><th class="r">Không chấm</th><th class="r">Điền sai</th><th class="r">p50 (s)</th><th class="r">p95 (s)</th><th class="r">$/lượt</th><th class="r">$/lượt đúng</th></tr></thead><tbody>')
    for key, *_ in WAYS:
        w = W[key]
        h.append(f'<tr><td>{E(w["label"])}</td><td class="mono">{w["mode"]}</td><td class="r num">{w["ok"]}/{w["scored"]}</td><td class="r num">{w["unscored"]}</td>'
                 f'<td class="r num {"bad-t" if w["wrong"] else ""}">{w["wrong"]}</td><td class="r num">{f1(w["p50"])}</td><td class="r num">{f1(w["p95"])}</td>'
                 f'<td class="r num">{money(w["cpr"])}</td><td class="r num">{money(w["cps"])}</td></tr>')
    h.append("</tbody></table></div>")
    h.append('<h3>Theo từng web (đúng / chấm được · p50 giây)</h3><div class="tbl"><table><thead><tr><th>Web</th>' +
             "".join(f'<th class="r">{E(w[1])}</th>' for w in WAYS) + "</tr></thead><tbody>")
    for site, name in SITES.items():
        cells = []
        for key, label, mode, k, m in WAYS:
            rows = [r for r in kind(R, k, m) if r["site"] == site]
            sc = [r for r in rows if not r["versions"].get("unscored")]
            ok = [r for r in sc if r["outcome"] == "success"]
            uns = len(rows) - len(sc)
            cls = "bad-t" if len(ok) < len(sc) else ""
            cells.append(f'<td class="r num {cls}">{len(ok)}/{len(sc)}{f" <small>+{uns} không chấm</small>" if uns else ""} · {f1(pct([r["total_ms"] / 1000 for r in ok], 0.5))}</td>')
        h.append(f"<tr><td>{E(name)}</td>{''.join(cells)}</tr>")
    h.append("</tbody></table></div>")
    wd = [r for r in R if r["outcome"] == "wrong_data"]
    h.append('<h3>Các lượt ghi <span class="mono">wrong_data</span></h3><div class="tbl"><table><thead><tr><th>Model</th><th>Web</th><th class="r">Vòng</th><th>Trường sai</th><th>Chấm?</th></tr></thead><tbody>')
    for r in wd:
        v = r["versions"]
        h.append(f'<tr><td class="mono">{E(r["model"])}</td><td>{E(SITES.get(r["site"], r["site"]))}</td><td class="r num">{r["rep"]}</td><td>{E(", ".join(wrong_fields(r)))}</td>'
                 f'<td>{"không: bộ đọc form không đọc được widget" if v.get("unscored") else "có"}</td></tr>')
    h.append('</tbody></table></div><p class="sub">Mọi lượt sai đều sai ở trường giờ.</p></section>')

    # ---------- cache ----------
    h.append(f"""<section id="cache"><h2>Cache quy trình và điểm hòa vốn</h2>
<p class="sub">Từ một lượt Haiku đúng, sinh một script có tham số (ngày, giờ, số người, tên, SĐT). Lượt sau chạy script, không gọi LLM. Script không khớp được dữ liệu thì tự từ chối và chuyển sang Haiku chạy chay.</p>
<div class="facts">
 <div><span class="f-v num">{sum(r['outcome'] == 'success' for r in chk)}/{len(chk)}</span><span class="f-k">ca đổi dữ liệu đúng (script v1)</span></div>
 <div><span class="f-v num">{sum(r['outcome'] == 'blocked' for r in chk)}</span><span class="f-k">ca script tự từ chối</span></div>
 <div><span class="f-v num">{sum(r['outcome'] == 'wrong_data' for r in chk)}</span><span class="f-k">ca điền sai mà không báo</span></div>
 <div><span class="f-v num">{sum(r['outcome'] == 'success' for r in fo)}/{len(fo)}</span><span class="f-k">lần Haiku cứu được khi cache hỏng</span></div>
</div>
<div class="tbl"><table><thead><tr><th>Web</th><th class="r">Chi phí học + sinh script</th><th class="r">Tiết kiệm mỗi lượt</th><th class="r">Hòa vốn sau</th></tr></thead><tbody>""")
    for site, name in SITES.items():
        b = bev[site]
        if b:
            h.append(f'<tr><td>{E(name)}</td><td class="r num">{money(b["learn"])}</td><td class="r num">{money(b["save"])}</td><td class="r num"><strong>{b["n"]} lượt</strong></td></tr>')
    h.append('</tbody></table></div><p class="sub">N* = chi phí học ÷ (chi phí lượt Haiku chạy chay − chi phí lượt script).</p></section>')

    # ---------- script v2 ----------
    h.append("""<section id="script-v2"><h2>Script cache v2</h2>
<p class="sub">Ảnh chụp từng bước (25/11) lộ 3 lỗi trong script v1 do Haiku sinh. Đã sửa tay thành v2; bản v1 vẫn giữ trong file script. Số đo 24/11 ở trên là của v1.</p>
<div class="fixes">""")
    FIX = {
        "real_lauphan": ("Giờ có lúc bị đặt lại về “Chọn” sau khi điền: script kết thúc khi ô Giờ còn đang tải.", "Chờ ô Giờ đứng yên 2 giây; bị đặt lại thì chọn lại."),
        "real_kingbbq": ("Chọn nhà hàng khi danh sách chưa tải xong, nên script tự từ chối.", "Chờ danh sách nhà hàng tải xong rồi mới chọn."),
        "real_lauwang": ("Gán thẳng vào ô <select> ẩn: giá trị đúng nhưng ô hiển thị vẫn ghi “Giờ” / “Chọn cơ sở”.", "Chọn qua widget của theme, kiểm tra cả chữ hiển thị."),
    }
    for site, (bug, fix) in FIX.items():
        def t(ver):
            rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == ver]
            c = Counter(r["outcome"] for r in rs)
            return f"{c['success']}/{len(rs)}" if rs else "—"
        rcs = [r for r in rc if r["site"] == site]
        rcc = Counter(r["outcome"] for r in rcs)
        h.append(f'<article class="fix"><h3>{E(SITES[site])}</h3><dl><dt>Lỗi ở v1</dt><dd>{E(bug)}</dd><dt>Sửa ở v2</dt><dd>{E(fix)}</dd></dl>'
                 f'<div class="fix-n"><span><b class="num">{t("v1")}</b> v1 đúng</span><span><b class="num">{t("v2")}</b> v2 đúng</span>'
                 f'<span><b class="num">{rcc["wrong_data"]}</b> điền sai / {len(rcs)} ca đổi dữ liệu (v2)</span></div></article>')
    h.append("</div><p class=\"sub\">Lần chạy lại: không gọi LLM, sau lớp chặn. Lẩu Phan có 1 lần sai với v1 trước khi bắt đầu ghi log, không nằm trong số đếm.</p></section>")

    # ---------- từng web ----------
    h.append('<section id="tung-web"><h2>Từng web, từng bước</h2><p class="sub">Ảnh chụp mỗi khi form đổi; ô viền đỏ là ô vừa đổi. Ảnh đầu là trang vừa tải xong; ảnh cuối chụp sau 3 giây chờ, đúng trạng thái được chấm. Bấm ảnh để xem cỡ lớn.</p>')
    h.append('<div class="site-tabs">' + "".join(f'<a href="#{s[5:]}">{E(n)}</a>' for s, n in SITES.items()) + "</div>")
    for site, name in SITES.items():
        d = json.loads((SHOTS / site / "steps.json").read_text(encoding="utf-8"))
        rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == d.get("script", "v1")]
        c = Counter(r["outcome"] for r in rs)
        h.append(f'<article class="site" id="{site[5:]}"><div class="site-head"><h3>{E(name)}</h3><a class="mono url" href="{E(d["url"])}" target="_blank" rel="noopener">{E(d["url"])}</a></div>'
                 f'<p class="site-meta">{pill(d["outcome"])} Script <b>{d.get("script", "v1")}</b> · {f1(d["ms"] / 1000)} s · lần chạy lại với script này: <b class="num">{c["success"]}/{len(rs)}</b> đúng'
                 f' · lớp chặn: {len(d["guard_blocked"])} request bị chặn, {d["guard_submit_attempts"]} lần dữ liệu khách định rời trang</p>')
        h.append(steps_html(site, d, ""))
        bad = SHOTS / site / "run_loi" / "steps.json"
        if bad.exists():
            b = json.loads(bad.read_text(encoding="utf-8"))
            h.append(f'<details class="bad-run"><summary>{pill(b["outcome"])} Một lần chạy không đúng (script {b.get("script", "v1")}): {E((b["err"] or "")[:120])}</summary>{steps_html(site, b, "run_loi")}</details>')
        h.append("</article>")
    h.append("</section>")

    # ---------- chưa kiểm chứng ----------
    lw = [r for r in kind(R, "cold", HAIKU) if r["versions"].get("unscored") and r["outcome"] == "wrong_data"]
    h.append(f"""<section id="chua-kiem-chung"><h2>Chưa kiểm chứng</h2><ul class="todo">
<li>{len(lw)} lượt Haiku chạy chay ở Lẩu Wang (vòng {", ".join(str(r["rep"]) for r in lw)}) ghi sai giờ nhưng xếp không chấm, vì bộ đọc form không đọc được widget. Chưa chứng minh Haiku đã chọn đúng.</li>
<li>Script v2 mới chạy lại ca chính và các ca đổi dữ liệu; thời gian và chi phí theo quy trình đo 24/11 vẫn là của v1.</li>
<li>Sonnet 5.5 chưa đo trên web thật; Grok chưa đo (không có credit xAI). Gemini có {W['gemini']['unscored']} lượt không chấm (lỗi API hoặc widget).</li>
<li>Mỗi web chỉ 5 vòng (hợp đồng gốc: 11), nên p95 gần bằng giá trị lớn nhất. Máy đo 24/11 chạy CPU rất cao, số giây chỉ dùng để so sánh tương đối.</li>
<li>Chưa bấm nút đặt và chưa đi tới OTP của nhà hàng thật (cố ý). Cổng OTP lấy từ mock site: Haiku dừng đúng 10/10.</li>
</ul>
<p class="foot">Sinh bởi <span class="mono">bench/llm/html_report.py</span> từ <span class="mono">results/llm/</span>. Báo cáo đầy đủ: <span class="mono">reports/llm.md</span>; bảng tính: <span class="mono">results/llm/real/llm_web.xlsx</span>.</p></section></main>""")
    return "\n".join(h)


CSS = """
/* Bố cục: một cột đọc, bảng số đặt trong khung cuộn ngang riêng, ảnh từng bước xếp lưới. */
:root{
 --bg:#f6f7f6;--surface:#ffffff;--ink:#16201d;--muted:#5d6b66;--line:#dde3e0;
 --accent:#b3261e;--accent-soft:#fbe9e7;--ok:#1d7a4f;--ok-soft:#e3f3ea;--warn:#9a6400;--warn-soft:#fbf0d9;--bad:#b3261e;--bad-soft:#fbe4e1;
 --bar1:#16201d;--bar2:#c9d3cf;
 --f-body:"Be Vietnam Pro",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--f-mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#111614;--surface:#18201d;--ink:#e7ece9;--muted:#9aa8a2;--line:#2b3531;
 --accent:#ff8a7a;--accent-soft:#3a1f1c;--ok:#6fd3a0;--ok-soft:#173326;--warn:#f0c060;--warn-soft:#3a2f14;--bad:#ff8a7a;--bad-soft:#3d1f1b;
 --bar1:#e7ece9;--bar2:#3c4843;color-scheme:dark}}
:root[data-theme="dark"]{
 --bg:#111614;--surface:#18201d;--ink:#e7ece9;--muted:#9aa8a2;--line:#2b3531;
 --accent:#ff8a7a;--accent-soft:#3a1f1c;--ok:#6fd3a0;--ok-soft:#173326;--warn:#f0c060;--warn-soft:#3a2f14;--bad:#ff8a7a;--bad-soft:#3d1f1b;
 --bar1:#e7ece9;--bar2:#3c4843;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:15px/1.6 var(--f-body)}
.wrap{max-width:1120px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--surface)}
.topnav{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--surface);border-bottom:1px solid var(--line)}
.nav-in{display:flex;gap:18px;align-items:center;overflow-x:auto;padding-block:10px;white-space:nowrap}
.brand{font-weight:700;margin-right:auto}
.topnav a,.site-tabs a{color:var(--muted);text-decoration:none;font-size:14px}
.topnav a:hover,.site-tabs a:hover{color:var(--accent)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
main{padding-block:28px 64px;display:flex;flex-direction:column;gap:48px}
section,header{display:flex;flex-direction:column;gap:14px;min-width:0;scroll-margin-top:64px}
h1{font-size:clamp(26px,4vw,38px);line-height:1.2;margin:0;text-wrap:balance;letter-spacing:-.01em}
h2{font-size:24px;margin:0;text-wrap:balance}
h3{font-size:17px;margin:6px 0 0}
.eyebrow{margin:0;text-transform:uppercase;letter-spacing:.08em;font-size:12px;color:var(--accent);font-weight:600}
.lede{margin:0;max-width:68ch;color:var(--muted);font-size:16px}
.sub,.note{margin:0;color:var(--muted);max-width:75ch}
.note{font-size:14px}
.mono{font-family:var(--f-mono);font-size:.92em;font-variant-ligatures:none}
.num{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.verdict{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.v-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:4px;min-width:0}
.v-card:first-child{border-color:var(--ink);border-width:2px}
.v-card.out{background:transparent;border-style:dashed}
.v-k{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.v-v{font-size:18px;font-weight:600;overflow-wrap:anywhere}
.v-card.out .v-v{text-decoration:line-through;text-decoration-color:var(--bad)}
.v-d{font-size:14px;color:var(--muted)}
.tbl{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-weight:600;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
.r{text-align:right}
td small{color:var(--muted);font-size:11px}
.bad-t{color:var(--bad);font-weight:600}
.bars{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:10px}
.bar-row{display:grid;grid-template-columns:minmax(120px,220px) 1fr 110px;gap:12px;align-items:center}
.bar-label{font-size:14px}
.bar-track{position:relative;height:22px;background:transparent;border-left:1px solid var(--line)}
.bar{position:absolute;left:0;height:100%;border-radius:0 3px 3px 0}
.bar.p95{background:var(--bar2)}
.bar.p50{background:var(--bar1);height:60%;top:20%}
.bar-val{font-size:13px;text-align:right}
.axis .bar-ticks{position:relative;height:16px;border-left:1px solid transparent}
.bar-ticks span{position:absolute;transform:translateX(-50%);font-size:11px;color:var(--muted);font-family:var(--f-mono)}
.legend{margin:0;font-size:12px;color:var(--muted);display:flex;gap:8px;align-items:center}
.key{display:inline-block;width:14px;height:10px;border-radius:2px}
.key.p50{background:var(--bar1)}.key.p95{background:var(--bar2);margin-left:10px}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.facts div{display:flex;flex-direction:column;border-top:2px solid var(--ink);padding-top:8px}
.f-v{font-size:26px;font-weight:600}
.f-k{font-size:13px;color:var(--muted)}
.fixes{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.fix{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0}
.fix h3{margin:0}
.fix dl{margin:0;display:grid;gap:4px}
.fix dt{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.fix dd{margin:0 0 6px}
.fix-n{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px}
.fix-n b{color:var(--ink);font-size:15px}
.site-tabs{display:flex;flex-wrap:wrap;gap:8px}
.site-tabs a{border:1px solid var(--line);border-radius:999px;padding:4px 12px;background:var(--surface)}
.site{display:flex;flex-direction:column;gap:10px;scroll-margin-top:64px;padding-top:10px;border-top:1px solid var(--line)}
.site-head{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:baseline}
.site-head h3{margin:0;font-size:20px}
.url{color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.site-meta{margin:0;font-size:14px;color:var(--muted)}
.site-meta b{color:var(--ink)}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:1px 9px;border-radius:999px;margin-right:6px}
.pill.ok{background:var(--ok-soft);color:var(--ok)}.pill.warn{background:var(--warn-soft);color:var(--warn)}.pill.bad{background:var(--bad-soft);color:var(--bad)}
.steps{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.step{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;min-width:0}
.step img{display:block;width:100%;aspect-ratio:1280/900;object-fit:cover;object-position:top;max-width:100%;background:var(--line)}
.step figcaption{padding:8px 10px 10px;display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px}
.step-n{font-weight:600;color:var(--accent)}
.step-t{color:var(--muted);text-align:right}
.step-a{grid-column:1/-1;margin:0;font-family:var(--f-mono);font-variant-ligatures:none;font-size:11px;color:var(--muted);overflow-wrap:anywhere}
.step ul{grid-column:1/-1;margin:2px 0 0;padding-left:16px;overflow-wrap:anywhere}
.bad-run{background:var(--bad-soft);border-radius:8px;padding:10px 12px}
.bad-run summary{cursor:pointer;font-size:14px}
.bad-run .steps{margin-top:10px}
.todo{margin:0;padding-left:20px;max-width:80ch;display:flex;flex-direction:column;gap:6px}
.foot{font-size:13px;color:var(--muted);margin:8px 0 0}
@media (max-width:600px){.bar-row{grid-template-columns:1fr 90px}.bar-label{grid-column:1/-1}.bar-track{grid-column:1}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (OUT / "img").glob("*.jpg"):
        f.unlink()
    (OUT / "index.html").write_text(build(), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"đã ghi {OUT}/index.html, {len(list((OUT / 'img').glob('*.jpg')))} ảnh, tổng {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
