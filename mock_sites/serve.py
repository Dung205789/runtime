"""Chạy cả 5 mock site trong một tiến trình: `uv run python -m mock_sites.serve`."""

from __future__ import annotations

import asyncio
import importlib
import sys

import uvicorn

from bench.core.contract import SITE_PORTS


def load_app(site: str):
    return importlib.import_module(f"mock_sites.{site}").app


async def main(host: str = "127.0.0.1") -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(load_app(site), host=host, port=port, log_level="warning"))
        for site, port in SITE_PORTS.items()
    ]
    for site, port in SITE_PORTS.items():
        print(f"{site:12s} http://{host}:{port}", flush=True)
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 để trình duyệt trong Docker (steel_selfhost) truy cập được qua host.docker.internal")
    try:
        asyncio.run(main(ap.parse_args().host))
    except KeyboardInterrupt:
        sys.exit(0)
