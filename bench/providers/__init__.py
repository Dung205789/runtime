"""Chọn runtime trình duyệt cho các module sau trong pipeline.

    from bench.providers import get_provider, site_url_for
    provider = get_provider()              # đọc BENCH_RUNTIME, mặc định chrome_local
    handle = await provider.start()        # handle.cdp_url -> browser_use.Browser(cdp_url=handle.cdp_url)
    url = site_url_for(provider.name, "s1_simple")   # URL mock site mà trình duyệt của runtime này truy cập được
    ...
    await provider.stop(handle)

Thiếu điều kiện (khóa API, Docker, tunnel) thì ném ProviderSkipped -> ghi outcome = "skipped".
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from bench.core.contract import SITE_PORTS, BrowserProvider, site_url
from bench.providers._util import ProviderSkipped, lib_versions

PUBLIC_URLS_FILE = Path(__file__).resolve().parents[2] / "tmp" / "public_urls.json"

__all__ = ["DEFAULT_RUNTIME", "RUNTIMES", "ProviderSkipped", "get_provider", "lib_versions", "site_url_for"]

DEFAULT_RUNTIME = "chrome_local"

RUNTIMES: dict[str, str] = {
    "chrome_local": "bench.providers.chrome_local:ChromeLocal",
    "steel_selfhost": "bench.providers.steel_selfhost:SteelSelfHost",
    "steel_cloud": "bench.providers.steel_cloud:SteelCloud",
    "browser_use_cloud": "bench.providers.browser_use_cloud:BrowserUseCloud",
    "kernel": "bench.providers.kernel:Kernel",
}

CLOUD = {"steel_cloud", "browser_use_cloud", "kernel"}


def get_provider(name: str | None = None, **kwargs) -> BrowserProvider:
    """Trả provider theo `name`, hoặc theo biến BENCH_RUNTIME nếu không truyền."""
    name = (name or os.environ.get("BENCH_RUNTIME") or DEFAULT_RUNTIME).strip()
    if name not in RUNTIMES:
        raise ValueError(f"BENCH_RUNTIME={name!r} không hợp lệ. Chọn một trong: {', '.join(RUNTIMES)}")
    mod, cls = RUNTIMES[name].split(":")
    return getattr(importlib.import_module(mod), cls)(**kwargs)


def site_url_for(runtime: str, site: str) -> str:
    """URL của mock site, nhìn từ trình duyệt của runtime đó.

    - chrome_local: http://127.0.0.1:<cổng> (như site_url()).
    - steel_selfhost: trình duyệt nằm trong container, nên dùng BENCH_DOCKER_HOST (mặc định host.docker.internal).
      Docker Desktop chuyển tiếp về 127.0.0.1 của máy (đã kiểm chứng). Docker trên Linux thì cần
      `uv run python -m mock_sites.serve --host 0.0.0.0` và `--add-host=host.docker.internal:host-gateway`.
    - cloud: trình duyệt ở máy chủ khác, không thấy 127.0.0.1 của máy đo. Cần tunnel công khai cho từng site:
      `uv run python -m mock_sites.tunnel` (ghi tmp/public_urls.json), hoặc tự đặt BENCH_PUBLIC_URL_<SITE>.
    """
    if site not in SITE_PORTS:
        raise KeyError(site)
    if runtime == "steel_selfhost":
        return f"http://{os.environ.get('BENCH_DOCKER_HOST', 'host.docker.internal')}:{SITE_PORTS[site]}"
    if runtime in CLOUD:
        key = f"BENCH_PUBLIC_URL_{site.upper()}"
        url = os.environ.get(key, "").strip().rstrip("/")
        if not url and PUBLIC_URLS_FILE.exists():  # do `uv run python -m mock_sites.tunnel` ghi
            url = json.loads(PUBLIC_URLS_FILE.read_text(encoding="utf-8")).get(site, "").rstrip("/")
        if not url:
            raise ProviderSkipped(f"{runtime}: trình duyệt cloud không truy cập được 127.0.0.1; chạy "
                                  f"`uv run python -m mock_sites.tunnel` hoặc đặt {key}")
        return url
    return site_url(site)
