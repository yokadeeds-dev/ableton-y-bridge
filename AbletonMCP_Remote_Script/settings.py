# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Fixed settings of the bridge. Environment variables override the defaults.

Live is usually started from the Start menu, so the environment route mostly
matters for tests and for a second Live instance on another port.
"""

import os

BRIDGE_VERSION = "2.2.0"


def _env_int(name, fallback):
    try:
        return int(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


# Loopback only: the bridge executes whatever a connected client asks for.
HOST = os.environ.get("ABLETON_MCP_HOST", "127.0.0.1")
PORT = _env_int("ABLETON_MCP_PORT", 9877)

# Largest request the bridge buffers before it gives up on a connection.
MAX_REQUEST_BYTES = _env_int("ABLETON_MCP_MAX_REQUEST", 16 * 1024 * 1024)

# `eval_code` runs arbitrary Python inside Live. It stays off unless this
# variable is set to 1 in Live's environment or a file named `allow_eval.flag`
# sits next to this module.
EVAL_ENV_SWITCH = "ABLETON_MCP_ALLOW_EVAL"
EVAL_FLAG_FILE = "allow_eval.flag"


# Destructive commands need "confirm": true in the request. Setting this
# variable to 0 in Live's environment switches the check off.
CONFIRM_ENV_SWITCH = "ABLETON_MCP_CONFIRM"

# Where the change journal is written; "off" disables the file.
JOURNAL_ENV = "ABLETON_MCP_JOURNAL_DIR"

# How many journal files are kept per Set: the newest ones, the file of the
# running session included; older ones are deleted at the first command
# through the bridge in a Live session (D22). 0 or less keeps all.
JOURNAL_KEEP_ENV = "ABLETON_MCP_JOURNAL_KEEP"
JOURNAL_KEEP_DEFAULT = 20


def journal_keep():
    return _env_int(JOURNAL_KEEP_ENV, JOURNAL_KEEP_DEFAULT)


def confirm_required():
    return os.environ.get(CONFIRM_ENV_SWITCH, "1").strip() != "0"


def journal_dir():
    """Folder for journal files, or None if journalling to disk is off."""
    chosen = os.environ.get(JOURNAL_ENV, "").strip()
    if chosen.lower() == "off":
        return None
    if chosen:
        return chosen
    return os.path.join(os.path.expanduser("~"), ".ableton-y-bridge", "journals")


def eval_allowed():
    if os.environ.get(EVAL_ENV_SWITCH, "").strip() == "1":
        return True
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.isfile(os.path.join(here, EVAL_FLAG_FILE))
