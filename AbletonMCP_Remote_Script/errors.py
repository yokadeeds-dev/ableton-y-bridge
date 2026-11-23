# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Error type shared by the bridge core and all command handlers."""

# Stable error codes. They travel to the client next to the human message so
# that callers can react without parsing text.
UNKNOWN_COMMAND = "unknown_command"
BAD_PARAMS = "bad_params"
OUT_OF_RANGE = "out_of_range"
NOT_FOUND = "not_found"
WRONG_KIND = "wrong_kind"
UNSUPPORTED = "unsupported"
BUSY = "busy"
TIMEOUT = "timeout"
DISABLED = "disabled"
INTERNAL = "internal"


class CommandError(Exception):
    """A failure that is reported to the client as a normal error reply.

    Handlers raise it for everything the caller can fix (wrong index, wrong
    clip kind, feature missing in this Live version). Anything else that
    escapes a handler is treated as an internal error and logged with its
    traceback.
    """

    def __init__(self, code, message, **details):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.details = details

    def as_reply(self):
        reply = {"status": "error", "code": self.code, "message": self.message}
        if self.details:
            reply["details"] = self.details
        return reply


def out_of_range(what, index, count):
    """Build the usual 'index outside the list' error."""
    if count <= 0:
        span = "there are none"
    else:
        span = "valid: 0..%d" % (count - 1)
    return CommandError(
        OUT_OF_RANGE,
        "%s %s does not exist (%s)" % (what, index, span),
        index=index,
        count=count,
    )
