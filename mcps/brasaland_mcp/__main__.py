"""Levanta el servidor MCP: `python -m mcps.brasaland_mcp [--port 8001]` (Streamable HTTP en /mcp)."""
from __future__ import annotations

import argparse
import logging

import uvicorn

from .server import create_app_from_env


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m mcps.brasaland_mcp", description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app_from_env(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
