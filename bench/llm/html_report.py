"""Sinh trang HTML kết quả trục LLM & cache (phần Agent 2, chỉ Claude), kèm ảnh từng bước.

Mọi số đọc từ results/llm/ (không nhập tay). Ảnh lấy từ results/llm/real/shots/, nén JPEG.

    uv run --with pillow python -m bench.llm.html_report
Ra: results/llm/real/html/index.html + img/*.jpg
"""
from __future__ import annotations

import html
import json
import math
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from bench.llm.budget import family, records, spent_usd
from bench.llm.report import kind, real_rows, wrong_fields

OUT = Path("results/llm/real/html")
SHOTS = Path("results/llm/real/shots")
SCRIPTS = Path("results/llm/real/scripts")
SITES = {"real_lauphan": "Lẩu Phan", "real_tong": "Tòng", "real_chaoxian": "Chao Xian", "real_lauwang": "Lẩu Wang", "real_kingbbq": "King BBQ"}
HAIKU = "claude-haiku-5-5"
WAYS = [
    ("haiku", "Haiku tự làm từ đầu", "none", "cold", HAIKU),
    ("replay", "Script qua browser-use", "actions", "replay", None),
    ("direct", "Script chạy thẳng", "actions", "direct", None),
]
FIELD = {
    "selectCoso": "Cơ sở", "address": "Cơ sở", "inputRestaurant": "Nhà hàng",
    "selectSoNguoi": "Số người", "adult": "Số người lớn", "inputNumber": "Số người", "child": "Trẻ em",
    "selectDay": "Ngày", "date": "Ngày", "inputDate": "Ngày",
    "selectHour": "Giờ", "time": "Giờ", "inputHour": "Giờ", "inputMinute": "Phút",
    "nameOrder": "Tên khách", "your-name": "Tên khách", "inputName": "Tên khách",
    "sdtOrder": "Số điện thoại", "phone": "Số điện thoại", "inputPhone": "Số điện thoại", "inputEmail": "Email",
}
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


def plain(entry: str) -> tuple[str, str]:
    """'selectHour = 18:00' / 'mặc định: time = Giờ' / 'cuối: ...' → ('Giờ', '18:00')."""
    e = re.sub(r"^(mặc định|cuối): ", "", entry)
    if e.startswith("URL"):
        return "Địa chỉ", e.split(":", 1)[1].strip() if ":" in e else e
    k, _, v = e.partition(" = ")
    return FIELD.get(k.strip(), k.strip()), v.strip()


def step_text(s: dict) -> tuple[str, list[tuple[str, str]]]:
    a = s["action"]
    pairs = [plain(c) for c in s["changed"] if not c.startswith("(")]
    if a.startswith("Trang tải xong"):
        return "Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.", [p for p in pairs if p[0] != "Địa chỉ"]
    if a.startswith("Kết thúc"):
        return "Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.", pairs
    if a.startswith(("type_text", "press_key")):
        verb = "Gõ"
    elif a.startswith("click"):
        verb = "Bấm chọn"
    else:
        verb = "Chọn / điền"
    what = ", ".join(f"{k.lower()} {v}" for k, v in pairs[:2]) or "trang"
    return f"{verb} {what}.", []


def steps_html(site: str, d: dict, prefix: str) -> str:
    folder = SHOTS / site / prefix if prefix else SHOTS / site
    items = []
    for s in d["steps"]:
        if not s.get("file") or not (folder / s["file"]).exists():
            continue
        src = jpg(folder / s["file"], f"{site}_{prefix or 'main'}_{s['n']:02d}.jpg")
        text, pairs = step_text(s)
        kv = "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in pairs[:9])
        items.append(
            f'<figure class="step"><a href="{src}" target="_blank" rel="noopener"><img src="{src}" loading="lazy" '
            f'alt="{E(SITES[site])}, bước {s["n"]}: {E(text)}"></a><figcaption>'
            f'<div class="step-top"><span class="step-n num">Bước {s["n"]}</span><span class="step-t num">giây thứ {s["t"]:.1f}</span></div>'
            f'<p class="step-a">{E(text)}</p>{f"<dl class=kv>{kv}</dl>" if kv else ""}'
            f'<details class="code"><summary>Lệnh script</summary><code>{E(s["action"][:300])}</code></details></figcaption></figure>'
        )
    return f'<div class="steps">{"".join(items)}</div>'


def stat(rows):
    sc = [r for r in rows if not r["versions"].get("unscored")]
    ok = [r for r in sc if r["outcome"] == "success"]
    t = [r["total_ms"] / 1000 for r in ok]
    cost = sum(r["llm_cost_usd"] for r in rows)
    return {"n": len(rows), "scored": len(sc), "ok": len(ok), "unscored": len(rows) - len(sc),
            "wrong": sum(r["outcome"] == "wrong_data" for r in sc), "p50": pct(t, 0.5), "p95": pct(t, 0.95),
            "cpr": cost / len(rows) if rows else None, "cps": cost / len(ok) if ok else None,
            "calls": pct([r["versions"].get("llm_calls") or 0 for r in ok], 0.5),
            "llm_s": pct([(r["versions"].get("llm_ms") or 0) / 1000 for r in ok], 0.5)}


def build() -> str:
    R = real_rows()
    allrecs = records()
    W = {key: stat(kind(R, k, m)) | {"label": label, "mode": mode} for key, label, mode, k, m in WAYS}
    H = W["haiku"]
    spend = spent_usd([r for r in allrecs if family(r.get("model") or "-") == "claude"])
    chk = kind(R, "check")
    runs = runs_log()
    rc = recheck_log()
    bev = {s: breakeven(R, s) for s in SITES}
    ns = [b["n"] for b in bev.values() if b]
    fo = kind(R, "failover")
    ex_site = min((s for s in SITES if bev[s]), key=lambda s: bev[s]["n"])
    ex = bev[ex_site]
    speed = H["p50"] / W["direct"]["p50"] if W["direct"]["p50"] else None
    lw = [r for r in kind(R, "cold", HAIKU) if r["versions"].get("unscored")]
    otp = [r for r in allrecs if r.get("site") == "s5_otp" and r.get("cache_mode") == "none" and not r.get("warmup") and r.get("model") == HAIKU]

    h = []
    h.append(f"""<title>Agent 2 · Claude đặt bàn</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style>
<nav class="topnav"><div class="wrap nav-in"><span class="brand">Agent 2 · Claude đặt bàn</span>
<a href="#ket-luan">Kết luận</a><a href="#cach-do">Cách đo</a><a href="#haiku">Haiku</a><a href="#cache">Script ghi nhớ</a><a href="#script-v2">Sửa script</a><a href="#tung-web">Từng web</a><a href="#luu-y">Lưu ý</a></div></nav>
<main class="wrap">
<header class="head" id="ket-luan">
<p class="eyebrow">Module chọn công nghệ · agent đặt bàn · trục LLM &amp; cache</p>
<h1>Claude Haiku 5.5 tự đặt bàn được, và một script ghi nhớ giúp lần sau nhanh hơn {f1(speed)} lần</h1>
<p class="lede">Agent dùng Claude Haiku 5.5 đọc trang đặt bàn và tự điền form trên 5 web nhà hàng thật. Lần đầu ở mỗi web, Haiku làm từ đầu. Sau một lần làm đúng, cách làm được ghi lại thành script. Những lần sau chỉ cần chạy script, không phải hỏi lại Haiku.</p>
<div class="verdict">
 <div class="v-card"><span class="v-k">Model chọn</span><span class="v-v">Claude Haiku 5.5</span>
  <p class="v-d">Điền đúng <b class="num">{H['ok']}/{H['scored']}</b> lượt chấm được. Một lượt thường mất khoảng <b class="num">{f1(H['p50'])} giây</b> và tốn khoảng <b class="num">{money(H['cps'])}</b>.</p></div>
 <div class="v-card"><span class="v-k">Cách lưu cho lần sau</span><span class="v-v">Script ghi nhớ, chạy thẳng</span>
  <p class="v-d">Đúng <b class="num">{W['direct']['ok']}/{W['direct']['scored']}</b> lượt, thường mất <b class="num">{f1(W['direct']['p50'])} giây</b>, không tốn tiền gọi Claude. Có lời sau <b class="num">{min(ns)}–{max(ns)}</b> lần đặt ở cùng một web.</p></div>
</div>
<p class="note">Đã dùng <b class="num">{money(spend, 2)}</b> trong ngân sách $1,80 cho Claude. Claude Sonnet 5.5 chưa được đo.</p>
</header>""")

    # ---------- cách đo ----------
    h.append(f"""<section id="cach-do"><h2>Đã đo như thế nào</h2>
<div class="explain">
 <div><h3>Ở đâu</h3><p>5 web đặt bàn thật: Lẩu Phan, Tòng, Chao Xian, Lẩu Wang, King BBQ. Mỗi web đo 5 vòng, ngày 24/11.</p></div>
 <div><h3>Yêu cầu</h3><p>Đặt bàn cho <b>3 người, ngày mai, 18:00</b>, tên <span class="mono">Khach Thu Nghiem</span>, số điện thoại <span class="mono">0000000000</span> (khách giả).</p></div>
 <div><h3>An toàn</h3><p>Agent điền form rồi <b>dừng trước nút Đặt bàn</b>. Một lớp chặn trong trình duyệt chặn mọi yêu cầu chứa thông tin khách gửi ra ngoài. Không có đơn nào được gửi tới nhà hàng.</p></div>
 <div><h3>Chấm điểm</h3><p>Sau mỗi lượt, chương trình đọc lại các ô trên form và so với yêu cầu. Không tin lời agent tự báo.</p></div>
</div>
<h3>Hai cách điền form</h3>
<ol class="flow">
 <li><span class="flow-k">Lần đầu ở một web</span><b>Haiku tự làm từ đầu.</b> Haiku xem trang, quyết định bấm và gõ gì, từng bước một. Thường gọi Claude {H['calls']} lần mỗi lượt.</li>
 <li><span class="flow-k">Khi Haiku làm đúng</span><b>Ghi lại thành script.</b> Các thao tác được viết thành một script, trong đó ngày, giờ, số người, tên và số điện thoại là chỗ trống để điền dữ liệu mới.</li>
 <li><span class="flow-k">Những lần sau</span><b>Chạy script, không gọi Claude.</b> Script tự kiểm tra lại form trước khi kết thúc. Gặp trường hợp không làm được (ví dụ web không có giờ khách muốn), script <b>từ chối</b> và giao lại cho Haiku.</li>
</ol>
<dl class="glossary">
 <dt>Đúng</dt><dd>Mọi ô trên form khớp yêu cầu.</dd>
 <dt>Điền sai</dt><dd>Form có ô không khớp, ví dụ sai giờ. Đây là lỗi nặng nhất, vì khách sẽ nhận một đơn sai.</dd>
 <dt>Từ chối</dt><dd>Script biết mình không làm được nên dừng và giao lại cho Haiku. Không phải lỗi.</dd>
 <dt>Không chấm được</dt><dd>Chương trình chấm không đọc được ô trên form, nên không biết đúng hay sai. Không tính vào tỷ lệ đúng.</dd>
 <dt>Thời gian thường gặp (p50)</dt><dd>Một nửa số lượt xong nhanh hơn mức này.</dd>
 <dt>Lượt chậm (p95)</dt><dd>Gần như mọi lượt xong trước mức này. Với 25 lượt, con số này gần bằng lượt chậm nhất.</dd>
</dl></section>""")

    # ---------- haiku ----------
    h.append(f"""<section id="haiku"><h2>Haiku tự làm từ đầu</h2>
<div class="facts">
 <div><span class="f-v num">{H['ok']}/{H['scored']}</span><span class="f-k">lượt đúng trên số lượt chấm được ({H['unscored']} lượt không chấm được, xem Lưu ý)</span></div>
 <div><span class="f-v num">{f1(H['p50'])} s</span><span class="f-k">thời gian thường gặp; lượt chậm {f1(H['p95'])} s</span></div>
 <div><span class="f-v num">{money(H['cps'])}</span><span class="f-k">chi phí Claude cho một lượt đúng</span></div>
 <div><span class="f-v num">{H['calls']}</span><span class="f-k">lần gọi Claude trong một lượt (thường gặp), mất khoảng {f1(H['llm_s'])} s chờ Claude trả lời</span></div>
</div>
<p class="sub">Phần thời gian còn lại là khởi động agent và chờ trang web tải. Haiku cũng qua bài kiểm tra mã OTP trên trang thử: dừng lại hỏi người đúng lúc <b class="num">{sum(bool(r.get('paused_for_otp')) for r in otp)}/{len(otp)}</b> lần, không tự đoán mã.</p>
<div class="tbl"><table><thead><tr><th>Web</th><th class="r">Lượt đúng</th><th class="r">Thời gian thường gặp</th><th class="r">Lượt chậm nhất</th><th class="r">Chi phí / lượt</th></tr></thead><tbody>""")
    for site, name in SITES.items():
        rows = [r for r in kind(R, "cold", HAIKU) if r["site"] == site]
        x = stat(rows)
        extra = f' <small>+{x["unscored"]} không chấm được</small>' if x["unscored"] else ""
        h.append(f'<tr><td>{E(name)}</td><td class="r num">{x["ok"]}/{x["scored"]}{extra}</td><td class="r num">{f1(x["p50"])} s</td>'
                 f'<td class="r num">{f1(max([r["total_ms"] / 1000 for r in rows if r["outcome"] == "success"] or [0]))} s</td><td class="r num">{money(x["cpr"])}</td></tr>')
    h.append("</tbody></table></div></section>")

    # ---------- cache ----------
    h.append(f"""<section id="cache"><h2>Script ghi nhớ cho lần sau</h2>
<p class="sub">So sánh cùng yêu cầu đặt bàn: Haiku tự làm từ đầu, và chạy script đã ghi nhớ. Script có thể chạy qua browser-use (cùng bộ khung với agent) hoặc chạy thẳng trên trình duyệt; chạy thẳng nhanh hơn vì bỏ được bước khởi động agent.</p>""")
    h.append(bars([(W[k]["label"], W[k]["p50"], W[k]["p95"]) for k, *_ in WAYS]))
    h.append('<div class="tbl"><table><thead><tr><th>Cách</th><th class="r">Lượt đúng</th><th class="r">Thời gian thường gặp</th><th class="r">Lượt chậm</th><th class="r">Chi phí / lượt</th></tr></thead><tbody>')
    for key, *_ in WAYS:
        w = W[key]
        h.append(f'<tr><td>{E(w["label"])}</td><td class="r num">{w["ok"]}/{w["scored"]}</td><td class="r num">{f1(w["p50"])} s</td><td class="r num">{f1(w["p95"])} s</td><td class="r num">{money(w["cpr"])}</td></tr>')
    h.append(f"""</tbody></table></div>
<h3>Khi dữ liệu khách thay đổi</h3>
<p class="sub">Script được thử với {len(chk)} yêu cầu khác nhau (số người, giờ, ngày, tên, chi nhánh khác), mỗi web 10–12 yêu cầu, gồm cả yêu cầu cố ý không hợp lệ như 03:00 sáng.</p>
<div class="facts">
 <div><span class="f-v num">{sum(r['outcome'] == 'success' for r in chk)}</span><span class="f-k">yêu cầu điền đúng</span></div>
 <div><span class="f-v num">{sum(r['outcome'] == 'blocked' for r in chk)}</span><span class="f-k">yêu cầu script từ chối và giao lại cho Haiku (giờ web không có)</span></div>
 <div class="zero"><span class="f-v num">{sum(r['outcome'] == 'wrong_data' for r in chk)}</span><span class="f-k">yêu cầu điền sai mà không báo</span></div>
 <div><span class="f-v num">{sum(r['outcome'] == 'success' for r in fo)}/{len(fo)}</span><span class="f-k">lần Haiku cứu được khi script hỏng (thử bằng cách làm hỏng trang)</span></div>
</div>
<h3>Bao lâu thì có lời</h3>
<p class="sub">Ghi nhớ có giá: phải cho Haiku làm một lần rồi sinh script. Sau đó mỗi lần dùng script tiết kiệm được tiền gọi Claude. Ví dụ {E(SITES[ex_site])}: ghi nhớ tốn <b class="num">{money(ex['learn'])}</b>, mỗi lần dùng script tiết kiệm <b class="num">{money(ex['save'])}</b>, nên từ lần đặt thứ <b class="num">{ex['n']}</b> là có lời.</p>
<div class="tbl"><table><thead><tr><th>Web</th><th class="r">Chi phí ghi nhớ</th><th class="r">Tiết kiệm mỗi lần</th><th class="r">Có lời từ lần thứ</th></tr></thead><tbody>""")
    for site, name in SITES.items():
        b = bev[site]
        if b:
            h.append(f'<tr><td>{E(name)}</td><td class="r num">{money(b["learn"])}</td><td class="r num">{money(b["save"])}</td><td class="r num"><strong>{b["n"]}</strong></td></tr>')
    h.append("</tbody></table></div></section>")

    # ---------- script v2 ----------
    h.append("""<section id="script-v2"><h2>Sửa script sau khi xem ảnh</h2>
<p class="sub">Ngày 25/11, chạy lại script và chụp ảnh từng bước. Ảnh cho thấy 3 script do Haiku viết còn lỗi. Đã sửa tay thành bản v2; bản gốc (v1) vẫn được giữ. Các số ở trên là của bản v1.</p>
<div class="fixes">""")
    FIX = {
        "real_lauphan": ("Có lần giờ bị xóa về “Chọn” sau khi đã chọn 18:00. Web tải lại danh sách giờ chậm, script đã kết thúc trước đó.",
                         "Sau khi điền xong, script chờ ô Giờ đứng yên 2 giây. Nếu giờ bị xóa thì chọn lại."),
        "real_kingbbq": ("Script chọn nhà hàng khi danh sách nhà hàng chưa tải xong, không tìm thấy nên từ chối.",
                         "Chờ danh sách nhà hàng tải xong rồi mới chọn."),
        "real_lauwang": ("Giá trị trong form đúng, nhưng trên màn hình ô Giờ và ô Cơ sở vẫn hiện “Giờ”, “Chọn cơ sở”, như chưa chọn.",
                         "Chọn bằng cách bấm vào ô hiển thị như người dùng, và kiểm tra cả chữ hiện trên màn hình."),
    }
    for site, (bug, fix) in FIX.items():
        def t(ver):
            rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == ver]
            return f"{sum(r['outcome'] == 'success' for r in rs)}/{len(rs)}" if rs else "—"
        rcs = [r for r in rc if r["site"] == site]
        h.append(f'<article class="fix"><h3>{E(SITES[site])}</h3><dl><dt>Lỗi ở bản v1</dt><dd>{E(bug)}</dd><dt>Bản v2 sửa</dt><dd>{E(fix)}</dd></dl>'
                 f'<div class="fix-n"><span>v1 đúng <b class="num">{t("v1")}</b></span><span>v2 đúng <b class="num">{t("v2")}</b></span>'
                 f'<span>v2 điền sai <b class="num">{sum(r["outcome"] == "wrong_data" for r in rcs)}/{len(rcs)}</b> yêu cầu khác</span></div></article>')
    h.append("</div></section>")

    # ---------- từng web ----------
    h.append('<section id="tung-web"><h2>Từng web, từng bước</h2><p class="sub">Ảnh chụp mỗi khi form thay đổi. Ô viền đỏ là ô vừa được điền. Ảnh cuối chụp sau 3 giây chờ trang ổn định, đúng trạng thái được chấm. Bấm vào ảnh để xem cỡ lớn.</p>')
    h.append('<div class="site-tabs">' + "".join(f'<a href="#{s[5:]}">{E(n)}</a>' for s, n in SITES.items()) + "</div>")
    for site, name in SITES.items():
        d = json.loads((SHOTS / site / "steps.json").read_text(encoding="utf-8"))
        rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == d.get("script", "v1")]
        h.append(f'<article class="site" id="{site[5:]}"><div class="site-head"><h3>{E(name)}</h3><a class="mono url" href="{E(d["url"])}" target="_blank" rel="noopener">{E(d["url"])}</a></div>'
                 f'<p class="site-meta">{pill(d["outcome"])} Script bản <b>{d.get("script", "v1")}</b> điền xong trong <b class="num">{f1(d["ms"] / 1000)} giây</b>. '
                 f'Chạy lại bản này <b class="num">{len(rs)}</b> lần, đúng <b class="num">{sum(r["outcome"] == "success" for r in rs)}</b> lần. '
                 f'Không có thông tin khách nào bị gửi ra ngoài.</p>')
        h.append(steps_html(site, d, ""))
        bad = SHOTS / site / "run_loi" / "steps.json"
        if bad.exists():
            b = json.loads(bad.read_text(encoding="utf-8"))
            h.append(f'<details class="bad-run"><summary>{pill(b["outcome"])} Xem một lần script bản {b.get("script", "v1")} từ chối: danh sách nhà hàng chưa tải xong nên không tìm thấy chi nhánh</summary>{steps_html(site, b, "run_loi")}</details>')
        h.append("</article>")
    h.append("</section>")

    # ---------- lưu ý ----------
    h.append(f"""<section id="luu-y"><h2>Lưu ý</h2><ul class="todo">
<li><b>{len(lw)} lượt Haiku ở Lẩu Wang chưa chấm được.</b> Chương trình chấm không đọc được ô giờ của web này nên không biết Haiku chọn đúng giờ hay không. Lỗi hiển thị ở Lẩu Wang (mục Sửa script) có thể là nguyên nhân, nhưng chưa kiểm chứng.</li>
<li><b>Script bản v2 chưa được đo lại thời gian và chi phí</b> theo đúng quy trình ngày 24/11; mới chạy lại để kiểm tra đúng/sai.</li>
<li><b>Claude Sonnet 5.5 chưa được đo</b> trên web thật vì không đủ ngân sách.</li>
<li><b>Mỗi web chỉ đo 5 vòng</b>, ít hơn 11 vòng theo kế hoạch ban đầu. Máy đo ngày 24/11 rất bận, nên số giây chỉ nên dùng để so sánh giữa các cách.</li>
<li><b>Chưa bấm nút Đặt bàn và chưa nhận mã OTP thật</b> của nhà hàng, vì cố ý không tạo đơn thật.</li>
</ul>
<p class="foot">Sinh bởi <span class="mono">bench/llm/html_report.py</span> từ dữ liệu trong <span class="mono">results/llm/</span>. Báo cáo kỹ thuật: <span class="mono">reports/llm.md</span>.</p></section></main>""")
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
.explain{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.explain>div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}
.explain h3{margin:0 0 4px;font-size:15px}
.explain p{margin:0;font-size:14px;color:var(--muted)}
.explain p b{color:var(--ink)}
.flow{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;counter-reset:f}
.flow li{counter-increment:f;position:relative;padding:14px 16px 14px 52px;border:1px solid var(--line);border-radius:10px;background:var(--surface);font-size:14px;color:var(--muted);min-width:0}
.flow li::before{content:counter(f);position:absolute;left:14px;top:14px;width:26px;height:26px;border-radius:50%;background:var(--ink);color:var(--surface);display:grid;place-items:center;font-weight:700;font-size:13px}
.flow li>b:first-of-type{color:var(--ink);display:block;margin-bottom:2px}
.flow li b{color:var(--ink)}
.flow-k{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);font-weight:600}
.glossary{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:6px 16px;margin:0;font-size:14px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.glossary dt{font-weight:600}
.glossary dd{margin:0;color:var(--muted)}
.facts .zero .f-v{color:var(--ok)}
.v-d{margin:0}
.v-d b{color:var(--ink)}
.step-top{grid-column:1/-1;display:flex;justify-content:space-between}
.step figcaption{display:flex;flex-direction:column;gap:6px}
.step-a{font-family:var(--f-body)!important;font-size:13px!important;color:var(--ink)!important}
.kv{display:grid;grid-template-columns:auto 1fr;gap:1px 10px;margin:0;font-size:12px}
.kv dt{color:var(--muted)}
.kv dd{margin:0;overflow-wrap:anywhere}
.code summary{cursor:pointer;font-size:11px;color:var(--muted)}
.code code{display:block;margin-top:4px;font-family:var(--f-mono);font-variant-ligatures:none;font-size:10.5px;color:var(--muted);overflow-wrap:anywhere;white-space:pre-wrap}
@media (max-width:600px){.glossary{grid-template-columns:1fr}.glossary dd{margin-bottom:6px}}
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
