"""Xuất các bảng kết quả và ảnh từng bước của trang HTML (phần Claude) ra một file Markdown.

Dùng chung cách tính với bench.llm.html_report; ảnh dùng lại results/llm/real/html/img/
(chạy html_report trước để có ảnh).

    uv run --with pillow python -m bench.llm.md_report
Ra: results/llm/real/html/ket_qua.md
"""
from __future__ import annotations

import json
import sys

from bench.llm.html_report import (HAIKU, OUT, SHOTS, SITES, WAY_DESC, WAYS, breakeven, f1, kind, money, real_rows,
                                   runs_log, stat, step_text)

MD = OUT / "ket_qua.md"


def cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def table(head: list[str], rows: list[list]) -> list[str]:
    def numeric(i):
        return i > 0 and rows and all(str(r[i])[:1].isdigit() or str(r[i]).startswith("$") for r in rows)
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---:" if numeric(i) else "---" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(cell(x) for x in r) + " |" for r in rows]
    return out + [""]


def steps(site: str, d: dict, prefix: str) -> list[str]:
    out = []
    for s in d["steps"]:
        img = OUT / "img" / f"{site}_{prefix or 'main'}_{s['n']:02d}.jpg"
        if not img.exists():
            continue
        text, pairs = step_text(s)
        out.append(f"**Bước {s['n']}** (giây thứ {s['t']:.1f}): {text}")
        out.append("")
        if pairs:
            out += table(["Ô trên form", "Giá trị"], [[k, v] for k, v in pairs])
        out.append(f"![{SITES[site]}, bước {s['n']}](img/{img.name})")
        out.append("")
    return out


def build() -> str:
    R = real_rows()
    W = {key: stat(kind(R, k, m)) | {"label": label} for key, label, mode, k, m in WAYS}
    runs = runs_log()
    L = ["# Kết quả: Claude đặt bàn trên 5 web nhà hàng", ""]

    L += ["## Haiku tự điền, theo từng web", ""]
    rows = []
    for site, name in SITES.items():
        rs = [r for r in kind(R, "cold", HAIKU) if r["site"] == site]
        x = stat(rs)
        ok = f"{x['ok']}/{x['scored']}" + (f" (+{x['unscored']} không chấm được)" if x["unscored"] else "")
        slow = max([r["total_ms"] / 1000 for r in rs if r["outcome"] == "success"] or [0])
        rows.append([name, ok, f"{f1(x['p50'])} s", f"{f1(slow)} s", money(x["cpr"])])
    L += table(["Web", "Điền đúng (đúng / chấm được)", "Thời gian điển hình", "Lần chậm nhất (trong các lần đúng)", "Chi phí Claude (TB mỗi lần)"], rows)

    L += ["## Ba cách điền form", ""]
    L += table(["Cách điền form", "Làm gì", "Điền đúng", "Thời gian điển hình", "Lần chậm (p95)", "Chi phí Claude (TB mỗi lần)"],
               [[W[k]["label"], WAY_DESC[k], f"{W[k]['ok']}/{W[k]['scored']}", f"{f1(W[k]['p50'])} s", f"{f1(W[k]['p95'])} s", money(W[k]["cpr"])]
                for k, *_ in WAYS])

    L += ["## Bao lâu thì có lời khi dùng script", ""]
    rows = []
    for site, name in SITES.items():
        b = breakeven(R, site)
        if b:
            rows.append([name, money(b["learn"]), money(b["save"]), b["n"]])
    L += table(["Web", "Chi phí ghi nhớ (Haiku làm 1 lần + viết script)", "Tiết kiệm mỗi lần (so với Haiku tự điền)", "Có lời từ lần đặt thứ"], rows)

    L += ["## Ảnh từng bước", ""]
    for site, name in SITES.items():
        d = json.loads((SHOTS / site / "steps.json").read_text(encoding="utf-8"))
        rs = [r for r in runs if r["site"] == site and r.get("script", "v1") == d.get("script", "v1")]
        L += [f"### {name}", "", f"{d['url']} · script bản {d.get('script', 'v1')} · điền xong trong {f1(d['ms'] / 1000)} s · "
              f"chạy lại bản này {len(rs)} lần, đúng {sum(r['outcome'] == 'success' for r in rs)} lần", ""]
        L += steps(site, d, "")
        bad = SHOTS / site / "run_loi" / "steps.json"
        if bad.exists():
            b = json.loads(bad.read_text(encoding="utf-8"))
            L += [f"#### {name}: một lần script bản {b.get('script', 'v1')} từ chối", "", f"Lỗi: `{b['err']}`", ""]
            L += steps(site, b, "run_loi")
    return "\n".join(L)


def main() -> int:
    MD.write_text(build(), encoding="utf-8")
    n = MD.read_text(encoding="utf-8").count("](img/")
    print(f"đã ghi {MD}, {n} ảnh")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
