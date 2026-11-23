# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Command register: one entry per wire command, with handler and metadata.

A command is declared next to its implementation::

    @command("set_track_name", zone=REVERSIBLE,
             summary="Rename a track",
             params=[Int("track_index"), Text("name")])
    def set_track_name(live, track_index, name):
        ...

The register is the single source for dispatch, parameter checking and the
self description that ``list_commands`` returns. Nothing else in the bridge
knows command names.

Zones describe how much a command can break:

* ``read``        - looks, never changes the Live Set
* ``reversible``  - changes the Set, Live's own undo takes it back
* ``destructive`` - cannot be taken back by undo (saving, deleting files,
                    running code) or leaves the Set in a state the user
                    did not see coming
"""

import json

from .errors import BAD_PARAMS, UNKNOWN_COMMAND, CommandError

READ = "read"
REVERSIBLE = "reversible"
DESTRUCTIVE = "destructive"
ZONES = (READ, REVERSIBLE, DESTRUCTIVE)

_MISSING = object()
_TRUE_WORDS = ("true", "1", "yes", "on", "y")
_FALSE_WORDS = ("false", "0", "no", "off", "n", "", "none", "null")


class Param(object):
    """One named parameter of a command."""

    kind = "any"

    def __init__(self, name, default=_MISSING, doc="", nullable=False):
        self.name = name
        self.default = default
        self.doc = doc
        self.nullable = nullable

    @property
    def required(self):
        return self.default is _MISSING

    def convert(self, value):
        return value

    def read(self, given):
        """Pick this parameter out of the dict the client sent."""
        if self.name not in given:
            if self.required:
                raise CommandError(BAD_PARAMS, "missing parameter '%s'" % self.name)
            return self.default
        value = given[self.name]
        if value is None:
            if self.nullable or self.default is None:
                return None
            if not self.required:
                return self.default
            raise CommandError(BAD_PARAMS, "parameter '%s' must not be null" % self.name)
        try:
            return self.convert(value)
        except CommandError:
            raise
        except (TypeError, ValueError):
            raise CommandError(
                BAD_PARAMS,
                "parameter '%s' expects %s, got %r" % (self.name, self.kind, value),
            )

    def describe(self):
        info = {"name": self.name, "type": self.kind, "required": self.required}
        if not self.required:
            info["default"] = self.default
        if self.doc:
            info["doc"] = self.doc
        return info


class Int(Param):
    kind = "integer"

    def convert(self, value):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value != int(value):
                raise ValueError(value)
            return int(value)
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            number = float(text)
            if number != int(number):
                raise
            return int(number)


class Float(Param):
    kind = "number"

    def convert(self, value):
        if isinstance(value, bool):
            raise ValueError(value)
        if isinstance(value, str):
            text = value.strip().lower().replace(",", ".")
            if text in ("-inf", "-infinity"):
                return float("-inf")
            return float(text)
        return float(value)


class Bool(Param):
    kind = "boolean"

    def convert(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        word = str(value).strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise ValueError(value)


class Text(Param):
    kind = "string"

    def convert(self, value):
        if isinstance(value, (dict, list, tuple)):
            raise ValueError(value)
        return str(value)


class Items(Param):
    """A JSON array. A JSON-encoded string holding an array is accepted too."""

    kind = "array"

    def convert(self, value):
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, tuple):
            value = list(value)
        if not isinstance(value, list):
            raise ValueError(value)
        return value


class Raw(Param):
    """Passed through untouched (mixed-type legacy parameters)."""

    kind = "any"


class Later(object):
    """Returned by a handler whose change Live applies after the current tick.

    Live defers some setters (play position, loop switch, record button):
    reading the property back at once still gives the old value. Such a
    handler returns ``Later(read_back)``; the hub calls ``read_back()`` on a
    following display tick and sends its return value as the result.
    """

    def __init__(self, finish, ticks=1):
        self.finish = finish
        self.ticks = max(1, int(ticks))


class CommandSpec(object):
    """Everything the bridge knows about one command."""

    def __init__(self, name, handler, zone, params, summary, undo, timeout, group,
                 journal=True):
        if zone not in ZONES:
            raise ValueError("unknown zone %r for command %s" % (zone, name))
        self.name = name
        self.handler = handler
        self.zone = zone
        self.params = tuple(params)
        self.summary = summary
        self.undo = undo
        self.timeout = float(timeout)
        self.group = group
        self.journal = bool(journal)

    def bind(self, given):
        """Turn the client's params dict into keyword arguments."""
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise CommandError(BAD_PARAMS, "'params' must be an object")
        return dict((p.name, p.read(given)) for p in self.params)

    def describe(self):
        return {
            "name": self.name,
            "group": self.group,
            "zone": self.zone,
            "undo": self.undo,
            "summary": self.summary,
            "journal": self.journal,
            "timeout_s": self.timeout,
            "params": [p.describe() for p in self.params],
        }


class Registry(object):
    """Name -> CommandSpec. Built once at load and again on every hot reload."""

    def __init__(self):
        self._specs = {}

    def add(self, spec):
        if spec.name in self._specs:
            raise ValueError("command '%s' is registered twice" % spec.name)
        self._specs[spec.name] = spec

    def get(self, name):
        spec = self._specs.get(name)
        if spec is None:
            raise CommandError(UNKNOWN_COMMAND, "no such command: %s" % (name,))
        return spec

    def __contains__(self, name):
        return name in self._specs

    def __len__(self):
        return len(self._specs)

    def names(self):
        return sorted(self._specs)

    def describe(self):
        return [self._specs[name].describe() for name in self.names()]


# Handler modules register into whatever registry is being collected at the
# moment they are executed. `collect_into` switches the target; the loader in
# reloader.py uses it to build a fresh registry without touching the live one.
_target = [Registry()]


def collect_into(registry):
    previous = _target[0]
    _target[0] = registry
    return previous


def current_target():
    return _target[0]


def command(name, zone, summary, params=(), undo=None, timeout=10.0, aliases=(),
            journal=True):
    """Decorator that enters a handler into the register.

    ``undo`` says what takes the change back: ``"live"`` (Live's undo
    history), ``"none"`` or ``"n/a"`` for read commands. If left out it is
    derived from the zone. ``journal=False`` keeps a command out of the change
    journal (transport and view actions that leave the Set as it is).
    """
    if undo is None:
        undo = {READ: "n/a", REVERSIBLE: "live", DESTRUCTIVE: "none"}[zone]

    def register(handler):
        group = handler.__module__.rsplit(".", 1)[-1]
        for wire_name in (name,) + tuple(aliases):
            _target[0].add(
                CommandSpec(wire_name, handler, zone, params, summary, undo, timeout,
                            group, journal)
            )
        return handler

    return register
