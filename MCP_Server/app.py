"""Assembles the server: importing the tool modules registers all tools."""

from __future__ import annotations

import logging
import os
import sys

from .core import TOOLS, mcp
from . import tools  # noqa: F401  (registers the tools)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("ABLETON_MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,  # stdout carries the MCP protocol
    )
    logging.getLogger("ableton_mcp").info("starting with %d tools", len(TOOLS))
    mcp.run()
