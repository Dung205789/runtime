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
SETTLE_MS = 3000
FOCUS_JS = """([keys, outline]) => {
  document.querySelectorAll('[data-bench-hl]').forEach(e => { e.style.removeProperty('outline'); e.style.removeProperty('outline-offset'); delete e.dataset.benchHl; });
  let first = null;
  for (const k of keys) {
    const e = document.querySelector(`[name="${CSS.escape(k)}"]`) || document.getElementById(k);
    if (!e) continue;
    const t = (e.offsetParent || e.type === 'hidden') ? e : (e.closest('.select2-container, .nice-select') || e.parentElement || e);
    if (outline) {
      t.dataset.benchHl = '1';
      t.style.setProperty('outline', '3px solid red', 'important');
      t.style.setProperty('outline-offset', '1px', 'important');
    }
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

    def snap(label: str, mode: str = "step") -> None:
        """mode: "base" = trang vừa tải xong (giá trị mặc định, không viền);
        "step" = sau một thao tác, chỉ chụp khi có thay đổi, viền ô vừa đổi;
        "final" = trạng thái cuối, viền mọi ô đã có giá trị."""
        if len(steps) >= MAX_SHOTS:
            return
        st = state()
        prev = last["state"]
        if st is None or (mode == "step" and st == prev):
            return
        last["state"] = st
        filled = [k for k, v in st["vals"].items() if v not in ("", None)]
        if mode == "base":
            changed = [f"URL: {st['url']}"] + [f"mặc định: {k} = {st['vals'][k]}" for k in filled]
            focus = []
        elif mode == "final":
            changed = [f"cuối: {k} = {st['vals'][k]}" for k in filled]
            focus = filled
        else:
            old = (prev or {}).get("vals", {})
            focus = [k for k in filled if old.get(k) != st["vals"][k]]
            changed = [f"{k} = {st['vals'][k]}" for k in focus]
            if prev is not None and st["url"] != prev["url"]:
                changed.insert(0, f"URL → {st['url']}")
        try:
            page.evaluate(FOCUS_JS, [focus or (filled if mode == "base" else []), mode != "base"])
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

    def settle_base():
        if not last["nav"]:
            return
        last["nav"] = False
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        snap("Trang tải xong, script chưa điền gì (giá trị mặc định)", "base")

    last["nav"] = False
    for name in ("goto_url", "new_tab", "js", "click_at_xy", "type_text", "press_key", "scroll", "wait_for_load"):
        fn = env[name]

        def make(fn=fn, name=name):
            def w(*a, **k):
                if name in ("goto_url", "new_tab"):
                    r = fn(*a, **k)
                    last["nav"] = True
                    return r
                if name == "wait_for_load":
                    r = fn(*a, **k)
                    settle_base()
                    return r
                settle_base()
                r = fn(*a, **k)
                if name == "js" and isinstance(a[0], str) and a[0].strip().startswith(("document.readyState", "(()=>!!document")):
                    return r
                snap(f"{name}({short(', '.join(map(str, a)), 120)})")
                return r

            return w

        env[name] = make()
    env["__settle__"] = settle_base
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
            ms = (time.perf_counter() - T0) * 1000
            try:
                env["__settle__"]()
                page.wait_for_timeout(SETTLE_MS)
                env["__snap__"](f"Kết thúc script, chờ {SETTLE_MS // 1000} giây cho trang ổn định: trạng thái được chấm. Dừng trước nút đặt", "final")
                page.screenshot(path=str(out_dir / "final_full.png"), full_page=True, timeout=15000)
            except Exception:
                pass
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
