from __future__ import annotations

import io
import json
import sys
import time
import traceback
from contextlib import redirect_stdout

from playwright.sync_api import sync_playwright


def make_env(page) -> dict:
    s = page.context.new_cdp_session(page)

    def cdp(method, **params):
        params.pop("session_id", None)
        return s.send(method, params)

    def js(expression, target_id=None):
        def ev(e):
            return s.send("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})

        r = ev(expression)
        ex = r.get("exceptionDetails")
        if ex and "Illegal return" in json.dumps(ex):
            r = ev("(()=>{" + expression + "\n})()")
            ex = r.get("exceptionDetails")
        if ex:
            d = ex.get("exception", {}).get("description") or ex.get("text")
            raise RuntimeError(f"JS error: {d}; expression: {expression[:200]}")
        return r["result"].get("value")

    def goto_url(url):
        page.goto(url, wait_until="commit", timeout=40000)

    def wait_for_load(timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            if js("document.readyState") == "complete":
                return True
            time.sleep(0.1)
        return False

    def wait_for_element(selector, timeout=10.0, visible=False):
        end = time.time() + timeout
        q = json.dumps(selector)
        while time.time() < end:
            if js(f"(()=>{{const e=document.querySelector({q});return !!e && ({'!!e.offsetParent' if visible else 'true'})}})()"):
                return True
            time.sleep(0.1)
        return False

    def click_at_xy(x, y, button="left", clicks=1):
        for t in ("mousePressed", "mouseReleased"):
            cdp("Input.dispatchMouseEvent", type=t, x=x, y=y, button=button, clickCount=clicks)

    return {
        "cdp": cdp,
        "js": js,
        "goto_url": goto_url,
        "new_tab": goto_url,
        "wait_for_load": wait_for_load,
        "wait_for_element": wait_for_element,
        "wait_for_network_idle": lambda *a, **k: time.sleep(0.5),
        "click_at_xy": click_at_xy,
        "type_text": lambda t: cdp("Input.insertText", text=t),
        "press_key": lambda k, *a: page.keyboard.press(k),
        "scroll": lambda x=0, y=0, dy=600, dx=0: cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy),
        "screenshot": lambda *a, **k: None,
        "ensure_real_tab": lambda *a, **k: None,
        "page_info": lambda: js("({url:location.href,title:document.title})"),
    }


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(sys.argv[1])
        ctx = b.contexts[0]
        print(json.dumps({"ready": True}), flush=True)
        for line in sys.stdin:
            job = json.loads(line)
            page = ctx.new_page()
            out, err = io.StringIO(), None
            t0 = time.perf_counter()
            try:
                with redirect_stdout(out):
                    env = make_env(page)
                    env["__name__"] = "job"
                    exec(compile(job["code"], "<replay>", "exec"), env)
            except BaseException as e:
                tb = traceback.extract_tb(e.__traceback__)
                line_no = next((f.lineno for f in reversed(tb) if f.filename == "<replay>"), None)
                err = f"{type(e).__name__}: {e} (line {line_no})"[:1200]
            print(json.dumps({"ms": (time.perf_counter() - t0) * 1000, "err": err, "out": out.getvalue()[-600:]}), flush=True)
            if sys.stdin.readline().strip() != "close":
                return
            try:
                page.close()
            except Exception:
                pass
            print(json.dumps({"closed": True}), flush=True)


if __name__ == "__main__":
    main()
