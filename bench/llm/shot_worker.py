"""Giống direct_worker, nhưng chụp màn hình mỗi khi trang đổi trạng thái.

Chạy script cache quy trình (không LLM). Lớp chặn gửi đơn nằm ở tiến trình cha (bench.llm.shots),
cài trên cùng BrowserContext, giống đường chạy `direct` của combo.
Mỗi lần gọi helper (goto_url, js, click_at_xy, type_text, press_key...) mà làm đổi URL hoặc giá trị
các ô trên form thì chụp 1 ảnh, ghi lại helper nào đã gọi và ô nào đổi.
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from playwright.sync_api import sync_playwright

from bench.llm.direct_worker import make_env

STATE_JS = """() => ({
  url: location.href,
  vals: Object.fromEntries([...document.querySelectorAll('input,select,textarea')]
    .filter(e => e.type !== 'hidden' && e.type !== 'submit' && e.type !== 'button')
    .map((e, i) => [e.name || e.id || e.placeholder || (e.type + i),
                    e.tagName === 'SELECT' ? (e.options[e.selectedIndex] || {}).text || e.value : e.value]))
})"""
MAX_SHOTS = 40
FOCUS_JS = """(keys) => {
  document.querySelectorAll('[data-bench-hl]').forEach(e => { e.style.outline = e.dataset.benchHl; delete e.dataset.benchHl; });
  let first = null;
  for (const k of keys) {
    const e = document.querySelector(`[name="${CSS.escape(k)}"]`) || document.getElementById(k);
    if (!e) continue;
    const t = (e.offsetParent || e.type === 'hidden') ? e : (e.closest('.select2-container, .nice-select') || e.parentElement || e);
    t.dataset.benchHl = t.style.outline || '';
    t.style.outline = '3px solid red';
    first = first || t;
  }
  if (first) first.scrollIntoView({block: 'center'});
  return !!first;
}"""


def short(x, n=90) -> str:
    s = x if isinstance(x, str) else repr(x)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def wrap(env: dict, page, out_dir: Path, steps: list) -> None:
    last = {"state": None}

    def state():
        try:
            return page.evaluate(STATE_JS)
        except Exception:
            return None

    def snap(label: str, force: bool = False) -> None:
        if len(steps) >= MAX_SHOTS:
            return
        st = state()
        prev = last["state"]
        if st is None or (not force and st == prev):
            return
        changed = []
        if prev is None or st["url"] != prev["url"]:
            changed.append(f"URL → {st['url']}")
        old = (prev or {}).get("vals", {})
        keys = [k for k, v in st["vals"].items() if old.get(k) != v and v not in ("", None)]
        changed += [f"{k} = {st['vals'][k]}" for k in keys]
        last["state"] = st
        focus = keys if prev is not None else []
        if force and not focus:
            focus = [k for k, v in st["vals"].items() if v not in ("", None)]
        try:
            page.evaluate(FOCUS_JS, focus)
            page.wait_for_timeout(150)
        except Exception:
            pass
        n = len(steps) + 1
        f = out_dir / f"{n:02d}.png"
        try:
            page.screenshot(path=str(f), timeout=8000)
        except Exception as e:
            f = None
            changed.append(f"(không chụp được: {type(e).__name__})")
        steps.append({"n": n, "t": round(time.perf_counter() - T0, 2), "action": label, "changed": changed, "file": f.name if f else None})

    for name in ("goto_url", "new_tab", "js", "click_at_xy", "type_text", "press_key", "scroll", "wait_for_load"):
        fn = env[name]

        def make(fn=fn, name=name):
            def w(*a, **k):
                r = fn(*a, **k)
                if name == "js" and isinstance(a[0], str) and a[0].strip().startswith(("document.readyState", "(()=>!!document")):
                    return r
                snap(f"{name}({short(', '.join(map(str, a)), 120)})")
                return r

            return w

        env[name] = make()
    env["__snap__"] = snap


T0 = time.perf_counter()


def main() -> None:
    global T0
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(sys.argv[1])
        ctx = b.contexts[0]
        print(json.dumps({"ready": True}), flush=True)
        for line in sys.stdin:
            job = json.loads(line)
            out_dir = Path(job["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            page = ctx.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})
            steps: list = []
            out, err = io.StringIO(), None
            T0 = time.perf_counter()
            try:
                with redirect_stdout(out):
                    env = make_env(page)
                    wrap(env, page, out_dir, steps)
                    env["__name__"] = "job"
                    exec(compile(job["code"], "<replay>", "exec"), env)
            except BaseException as e:
                tb = traceback.extract_tb(e.__traceback__)
                line_no = next((f.lineno for f in reversed(tb) if f.filename == "<replay>"), None)
                err = f"{type(e).__name__}: {e} (line {line_no})"[:1200]
            try:
                env["__snap__"]("kết thúc script: form đã điền, dừng trước nút đặt", force=True)
                page.screenshot(path=str(out_dir / "final_full.png"), full_page=True, timeout=15000)
            except Exception:
                pass
            ms = (time.perf_counter() - T0) * 1000
            print(json.dumps({"ms": ms, "err": err, "out": out.getvalue()[-600:], "steps": steps}, ensure_ascii=False), flush=True)
            if sys.stdin.readline().strip() != "close":
                return
            try:
                page.close()
            except Exception:
                pass
            print(json.dumps({"closed": True}), flush=True)


if __name__ == "__main__":
    main()
