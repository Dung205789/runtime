"""Xuất kết quả trục LLM ra Excel: 1 sheet tổng hợp + mỗi web 1 sheet, kèm ảnh từng bước.

Số liệu đọc từ results/llm/real/combo.jsonl (đợt đo 24/11). Ảnh đọc từ results/llm/real/shots/
(chạy lại script cache bằng `python -m bench.llm.shots`). Không có số nhập tay.

    uv run --with openpyxl --with pillow python -m bench.llm.excel
"""
from __future__ import annotations

import io
import json
import math
import statistics as st
import sys
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image

from bench.llm.report import kind, real_rows, wrong_fields

OUT = Path("results/llm/real/llm_web.xlsx")
SHOTS = Path("results/llm/real/shots")
SCRIPTS = Path("results/llm/real/scripts")
SITES = {
    "real_lauphan": "Lẩu Phan", "real_tong": "Tòng", "real_chaoxian": "Chao Xian", "real_lauwang": "Lẩu Wang", "real_kingbbq": "King BBQ",
}
WAYS = [
    ("Haiku chạy chay (none)", "cold", "claude-haiku-5-5"),
    ("Gemini flash-lite chạy chay (none)", "cold", "gemini-3.5-flash-lite"),
    ("Script cache qua browser-use (actions)", "replay", None),
    ("Script cache chạy thẳng (actions)", "direct", None),
]
H = Font(bold=True, color="FFFFFF")
HFILL = PatternFill("solid", fgColor="2F5597")
TITLE = Font(bold=True, size=14)
SUB = Font(bold=True, size=12, color="2F5597")
OK = PatternFill("solid", fgColor="E2EFDA")
BAD = PatternFill("solid", fgColor="F8CBAD")
WARN = PatternFill("solid", fgColor="FFF2CC")
WRAP = Alignment(wrap_text=True, vertical="top", horizontal="left")
IMG_W = 600


def pct(x, q):
    x = sorted(x)
    return x[max(0, math.ceil(q * len(x)) - 1)] if x else None


def r1(x):
    return None if x is None else round(x, 1)


class Sheet:
    def __init__(self, ws):
        self.ws, self.row = ws, 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0

    def title(self, text, font=TITLE):
        self.ws.cell(self.row, 1, text).font = font
        self.row += 1

    def text(self, text, fill=None):
        c = self.ws.cell(self.row, 1, text)
        c.alignment = Alignment(wrap_text=False, vertical="top")
        if fill:
            c.fill = fill
        self.row += 1

    def table(self, header, rows, fills=None):
        for j, h in enumerate(header, 1):
            c = self.ws.cell(self.row, j, h)
            c.font, c.fill, c.alignment = H, HFILL, WRAP
        self.fit(self.row)
        self.row += 1
        for i, r in enumerate(rows):
            for j, v in enumerate(r, 1):
                c = self.ws.cell(self.row, j, v)
                c.alignment = WRAP
                if fills and fills[i]:
                    c.fill = fills[i]
            self.fit(self.row)
            self.row += 1
        self.row += 1

    def fit(self, row, min_h=15.0):
        """Đặt chiều cao hàng theo số dòng chữ, để ảnh neo theo hàng không bị lệch khi mở file."""
        lines = 1
        for c in self.ws[row]:
            if c.value is None:
                continue
            w = self.ws.column_dimensions[c.column_letter].width or 10
            per = max(1, int(w * 1.15))
            n = sum(max(1, math.ceil(len(part) / per)) for part in str(c.value).split("\n"))
            lines = max(lines, n)
        self.ws.row_dimensions[row].height = max(min_h, 15 * lines + 2)

    def gap(self, n=1):
        self.row += n


def way_stats(R, k, model, site=None):
    rows = [r for r in kind(R, k, model) if site is None or r["site"] == site]
    scored = [r for r in rows if not r["versions"].get("unscored")]
    ok = [r for r in scored if r["outcome"] == "success"]
    t = [r["total_ms"] / 1000 for r in ok]
    cost = sum(r["llm_cost_usd"] for r in rows)
    bad = Counter(r["outcome"] for r in scored if r["outcome"] != "success")
    return [
        len(rows), f"{len(ok)}/{len(scored)}", len(rows) - len(scored), bad.get("wrong_data", 0), bad.get("failed", 0),
        r1(pct(t, 0.5)), r1(pct(t, 0.95)), round(cost / len(rows), 4) if rows else None, round(cost / len(ok), 4) if ok else None,
    ], (len(ok) == len(scored) and scored != [])


def breakeven(R, site):
    p = SCRIPTS / f"{site}.json"
    cold = [r for r in kind(R, "cold", "claude-haiku-5-5") if r["site"] == site and r["outcome"] == "success"]
    di = [r for r in kind(R, "direct") if r["site"] == site and r["outcome"] == "success"]
    if not (p.exists() and cold and di):
        return None, None
    z = json.loads(p.read_text(encoding="utf-8"))
    learn = z["learn_cost_usd"] + z["cost_usd"]
    save = st.mean(r["llm_cost_usd"] for r in cold) - st.mean(r["llm_cost_usd"] for r in di)
    return round(learn, 4), math.ceil(learn / save)


def tally(site) -> str:
    f = SHOTS / "runs.jsonl"
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
    rows = [r for r in rows if r["site"] == site]
    if not rows:
        return "chưa chạy"
    parts = []
    for ver in ("v1", "v2"):
        rs = [r for r in rows if r.get("script", "v1") == ver]
        if not rs:
            continue
        c = Counter(r["outcome"] for r in rs)
        extra = ", ".join(f"{k} {v}" for k, v in c.items() if k != "success")
        parts.append(f"script {ver}: {c['success']}/{len(rs)} đúng" + (f" ({extra})" if extra else ""))
    return "; ".join(parts)


def recheck_rows(site):
    out = []
    for f in sorted(Path("results/llm/real").glob("recheck_*.jsonl")):
        out += [r for r in (json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()) if r["site"] == site]
    return out


def shot_data(site, sub=""):
    f = SHOTS / site / sub / "steps.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def add_img(ws, path: Path, anchor: str) -> float:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    nh = int(h * IMG_W / w)
    im = im.resize((IMG_W, nh))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    buf.seek(0)
    x = XLImage(buf)
    x.width, x.height = IMG_W, nh
    ws.add_image(x, anchor)
    return nh * 0.75


def steps_block(S: Sheet, site: str, d: dict, folder: Path):
    S.table(["Bước", "Giây", "Thao tác của script", "Ô thay đổi sau thao tác", "Ảnh (viền đỏ = ô vừa đổi)"], [])
    S.row -= 1
    for s in d["steps"]:
        row = S.row
        S.ws.cell(row, 1, s["n"]).alignment = WRAP
        S.ws.cell(row, 2, s["t"]).alignment = WRAP
        S.ws.cell(row, 3, s["action"]).alignment = WRAP
        S.ws.cell(row, 4, "\n".join(s["changed"]) or "—").alignment = WRAP
        S.fit(row)
        if s.get("file") and (folder / s["file"]).exists():
            h = add_img(S.ws, folder / s["file"], f"E{row}") + 6
            S.ws.row_dimensions[row].height = max(h, S.ws.row_dimensions[row].height)
        S.row += 1
    S.gap()


def site_sheet(wb, R, site, name):
    S = Sheet(wb.create_sheet(name))
    ws = S.ws
    for col, w in zip("ABCDEFGHIJ", (22, 22, 40, 44, 86, 10, 10, 10, 16, 12)):
        ws.column_dimensions[col].width = w
    from bench.llm.real import SITES as URLS

    S.title(f"{name} — {URLS[site]}")
    S.text("Ca đo chính (B): 3 người, ngày mai, 18:00, tên Khach Thu Nghiem, SĐT 0000000000. Mọi lượt dừng trước nút đặt, chạy sau lớp chặn gửi đơn.")
    S.gap()

    S.title("1. Số liệu theo cách chạy (đợt đo 24/11, 5 vòng)", SUB)
    rows, fills = [], []
    for label, k, m in WAYS:
        v, ok = way_stats(R, k, m, site)
        rows.append([label, *v])
        fills.append(OK if ok else BAD)
    S.table(["Cách", "Lượt", "Đúng/chấm được", "Không chấm", "wrong_data", "failed", "p50 (s)", "p95 (s)", "$/lượt", "$/đúng"], rows, fills)
    learn, n = breakeven(R, site)
    S.text(f"Chi phí học + sinh script: ${learn}. Hòa vốn sau N* = {n} lượt đặt (so với Haiku chạy chay)." if learn is not None else "Chưa có script cache.")
    S.gap()

    S.title("2. Từng lượt đo", SUB)
    rows, fills = [], []
    for r in sorted((r for r in R if r["site"] == site and r["versions"]["kind"] in ("cold", "replay", "direct", "warm", "failover", "detect")),
                    key=lambda r: (r["rep"], r["started_at"])):
        v = r["versions"]
        note = v.get("unscored") or (r.get("error") or v.get("err") or "")[:160]
        rows.append([v["kind"], r["model"], f"vòng {r['rep']}: {r['outcome']}", note,
                     "; ".join(f"{a}={b}" for a, b in (v.get("form") or [])[:8]), r1(r["total_ms"] / 1000), round(r["llm_cost_usd"], 4),
                     v.get("llm_calls"), ", ".join(wrong_fields(r)) if r["outcome"] != "success" else ""])
        fills.append(OK if r["outcome"] == "success" and not v.get("unscored") else WARN if v.get("unscored") else BAD)
    S.table(["Cách (kind)", "Model", "Kết quả", "Ghi chú / lỗi", "Giá trị form đọc được cuối lượt", "Giây", "$", "Gọi LLM", "Trường sai"], rows, fills)

    S.title("3. Script cache khi đổi dữ liệu khách", SUB)
    rows, fills = [], []
    for r in kind(R, "check"):
        if r["site"] != site:
            continue
        v = r["versions"]
        rows.append([v["case"], r["outcome"], "; ".join(f"{a}={b}" for a, b in (v.get("form") or [])[:8]), (v.get("err") or "")[:160],
                     None, r1(r["total_ms"] / 1000), None, None, ", ".join(wrong_fields(r)) if r["outcome"] != "success" else ""])
        fills.append(OK if r["outcome"] == "success" else WARN if r["outcome"] == "blocked" else BAD)
    S.table(["Ca", "Kết quả", "Giá trị form", "Lý do script từ chối", "", "Giây", "", "", "Trường không khớp"], rows, fills)

    rc = recheck_rows(site)
    if rc:
        ver = rc[-1]["versions"].get("script", "v1")
        c = Counter(r["outcome"] for r in rc)
        S.title(f"3b. Chạy lại các ca đổi dữ liệu với script {ver} (25/11): {c['success']}/{len(rc)} đúng, {c['blocked']} từ chối, {c['wrong_data']} điền sai", SUB)
        rows, fills = [], []
        for r in rc:
            v = r["versions"]
            rows.append([v["case"], r["outcome"], "; ".join(f"{a}={b}" for a, b in (v.get("form") or [])[:8]), (v.get("err") or "")[:160],
                         None, r1(r["total_ms"] / 1000), None, None, ", ".join(wrong_fields(r)) if r["outcome"] != "success" else ""])
            fills.append(OK if r["outcome"] == "success" else WARN if r["outcome"] == "blocked" else BAD)
        S.table(["Ca", "Kết quả", "Giá trị form", "Lý do script từ chối", "", "Giây", "", "", "Trường không khớp"], rows, fills)

    d = shot_data(site)
    S.title(f"4. Từng bước kèm ảnh, script {d.get('script', 'v1') if d else ''} (chạy lại 25/11, không gọi LLM). Các lần chạy lại: {tally(site)}", SUB)
    if not d:
        S.text("Chưa có ảnh. Chạy: uv run python -m bench.llm.shots " + site)
        return
    S.text("Ảnh chỉ chụp khi trang đổi. Bước đầu: trang vừa tải xong (giá trị mặc định, không viền). Bước cuối: chờ 3 giây rồi chụp, đúng trạng thái được chấm.")
    S.text(f"Kết quả lần chạy này: {d['outcome']} — {round(d['ms'] / 1000, 1)} s. Lỗi: {d['err'] or 'không'}. "
           f"Lớp chặn: {len(d['guard_blocked'])} request bị chặn, {d['guard_submit_attempts']} lần dữ liệu khách định rời trang.",
           OK if d["outcome"] == "success" else BAD)
    S.text("Form cuối: " + "; ".join(f"{a}={b}" for a, b in d["form"]))
    for note in NOTES.get(site, []):
        S.text("⚠ " + note, WARN)
    S.gap()
    steps_block(S, site, d, SHOTS / site)
    bad = shot_data(site, "run_loi")
    if bad:
        wrong = ", ".join(k for k, x in bad["check"].items() if not x)
        S.title(f"5. Một lần chạy lại không đúng (script {bad.get('script', 'v1')}): {bad['outcome']}" + (f", lỗi: {bad['err']}" if bad["err"] else f", trường sai: {wrong}"), SUB)
        S.text("Form cuối: " + "; ".join(f"{a}={b}" for a, b in bad["form"]), BAD)
        steps_block(S, site, bad, SHOTS / site / "run_loi")
    sc = SCRIPTS / f"{site}.json"
    if sc.exists():
        S.title("Script cache (sinh từ lượt Haiku thành công)", SUB)
        c = ws.cell(S.row, 1, json.loads(sc.read_text(encoding="utf-8"))["script"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=S.row, start_column=1, end_row=S.row, end_column=5)
        ws.row_dimensions[S.row].height = 400


# Quan sát từ ảnh chụp ngày 25/11 (không phải số đo).
NOTES = {
    "real_lauwang": [
        "Script v1 (do Haiku sinh) chỉ gán <select> gốc: giá trị đúng nhưng ô hiển thị vẫn ghi 'Giờ' / 'Chọn cơ sở'. "
        "Script v2 chọn qua widget của theme nên ô hiển thị đổi theo (ảnh bước cuối), và kiểm tra cả chữ hiển thị.",
    ],
    "real_lauphan": [
        "Script v1: một lần chạy lại (ngoài số đếm) bị sai giờ: script kết thúc khi ô Giờ còn đang tải, tải xong thì giờ bị đặt về 'Chọn'. "
        "Script v2 chờ ô Giờ đứng yên 2 giây sau khi điền, bị đặt lại thì chọn lại.",
    ],
    "real_kingbbq": [
        "Script v1 có lúc từ chối 'không có chi nhánh khớp chính xác' vì chọn nhà hàng khi danh sách chưa tải xong (ảnh mục 5). "
        "Script v2 chờ danh sách nhà hàng tải xong rồi mới chọn.",
    ],
}


def summary_sheet(wb, R):
    S = Sheet(wb.active)
    S.ws.title = "Tổng hợp"
    for col, w in zip("ABCDEFGHIJK", (16, 22, 22, 22, 22, 16, 12, 22, 60, 12, 12)):
        S.ws.column_dimensions[col].width = w
    S.title("Trục LLM & cache — 5 web nhà hàng thật")
    S.text("Kết luận (reports/llm.md): model thắng claude-haiku-5-5; cache thắng actions = script cache chạy thẳng, LLM chạy chay khi script từ chối.")
    S.text("Số liệu: đợt đo 24/11 (5 vòng/web, máy Windows). Ảnh: chạy lại script cache 25/11 trên Linux, không gọi LLM.")
    S.gap()
    rows, fills = [], []
    for site, name in SITES.items():
        cells = []
        for _, k, m in WAYS:
            v, _ok = way_stats(R, k, m, site)
            cells.append(f"{v[1]} đúng" + (f" (+{v[2]} không chấm)" if v[2] else "") + f" · p50 {v[5]}s")
        learn, n = breakeven(R, site)
        chk = [r for r in kind(R, "check") if r["site"] == site]
        d = shot_data(site)
        ok_chk = sum(r["outcome"] == "success" for r in chk)
        rows.append([name, *cells, f"{ok_chk}/{len(chk)} đúng, {sum(r['outcome'] == 'wrong_data' for r in chk)} sai", n,
                     tally(site), " ".join(NOTES.get(site, []))[:300]])
        fills.append(WARN if NOTES.get(site) else None)
    S.table(["Web", *(w[0] for w in WAYS), "Script khi đổi dữ liệu", "Hòa vốn N*", "Chạy lại 25/11", "Lưu ý"], rows, fills)
    S.text("Màu: xanh = đúng hết; đỏ = có lượt sai/hỏng; vàng = không chấm được hoặc cần lưu ý. Chi tiết và ảnh: mỗi web 1 sheet.")


def main() -> int:
    R = real_rows()
    wb = Workbook()
    summary_sheet(wb, R)
    for site, name in SITES.items():
        site_sheet(wb, R, site, name)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"đã ghi {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
