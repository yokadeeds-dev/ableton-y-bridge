# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Start script of the MCP server.

Works both ways:

    python MCP_Server/server.py        (what MCP client configs usually point at)
    python -m MCP_Server.server        (or the console script from pyproject.toml)
"""

import os
import sys

if __package__ in (None, ""):
    # Started as a plain script: make the parent folder importable so the
    # package and its relative imports resolve.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from MCP_Server.app import main
else:
    from .app import main

if __name__ == "__main__":
    main()
