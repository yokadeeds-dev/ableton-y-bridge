"""Lenient conversion of tool arguments.

MCP clients differ in what they send: some pass numbers and booleans as
strings, some pass lists as JSON text. Tools therefore declare the loose
types below and convert with these helpers.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Union

IntLike = Union[int, str]
FloatLike = Union[float, int, str]
BoolLike = Union[bool, str]
ListLike = Union[list, str]

_YES = {"true", "1", "yes", "on", "y", "ja"}
_NO = {"false", "0", "no", "off", "n", "nein", ""}


def to_int(value: Any, name: str = "value") -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        number = float(str(value).strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    if number != int(number):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    return int(number)


def to_float(value: Any, name: str = "value") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(",", ".")
    if text in ("-inf", "-infinity", "-∞"):
        return float("-inf")
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {value!r}")


def to_bool(value: Any, name: str = "value") -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    word = str(value).strip().lower()
    if word in _YES:
        return True
    if word in _NO:
        return False
    raise ValueError(f"{name} must be true or false, got {value!r}")


def to_list(value: Any, name: str = "value") -> List[Any]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError as problem:
            raise ValueError(f"{name} is not valid JSON: {problem}")
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def opt_int(value: Any, name: str = "value") -> Optional[int]:
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "null")):
        return None
    return to_int(value, name)


def opt_float(value: Any, name: str = "value") -> Optional[float]:
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "null")):
        return None
    return to_float(value, name)
