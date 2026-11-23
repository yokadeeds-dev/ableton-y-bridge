"""Keyboard shortcuts for the two things Live's API has no call for:
saving the Set and grouping tracks.

Windows only. The Python inside Live has no ``ctypes``, so the keys are
sent from here, the MCP server process: find Live's main window, bring it
to the front, type the shortcut. Nothing is typed unless Live really is
the foreground window afterwards.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Sequence

VK_SHIFT, VK_CONTROL = 0x10, 0x11
VK_UP, VK_RIGHT = 0x26, 0x27
_ARROWS = (0x25, 0x26, 0x27, 0x28)
VK_G, VK_S = 0x47, 0x53
_KEY_UP = 0x0002
_EXTENDED = 0x0001
_QUERY_LIMITED = 0x1000
LIVE_EXE_PREFIX = "ableton live"


class KeysUnavailable(Exception):
    """Shortcuts cannot be sent (wrong platform, Live not found or not in front)."""


def _api():
    if not sys.platform.startswith("win"):
        raise KeysUnavailable("keyboard shortcuts are implemented for Windows only")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    return ctypes, wintypes, user32, kernel32


def _exe_name(kernel32, ctypes, wintypes, pid: int) -> str:
    handle = kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def live_window() -> int:
    """Handle of the largest visible top-level window of a Live process, or 0."""
    ctypes, wintypes, user32, kernel32 = _api()
    best = {"handle": 0, "area": -1}
    known = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _unused):
        if not user32.IsWindowVisible(handle) or user32.GetWindow(handle, 4):
            return True  # hidden, or owned by another window (a dialog)
        if user32.GetWindowTextLengthW(handle) == 0:
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value not in known:
            known[pid.value] = _exe_name(kernel32, ctypes, wintypes, pid.value)
        if not known[pid.value].startswith(LIVE_EXE_PREFIX):
            return True
        box = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.byref(box))
        area = max(0, box.right - box.left) * max(0, box.bottom - box.top)
        if area > best["area"]:
            best["handle"], best["area"] = handle, area
        return True

    user32.EnumWindows(visit, 0)
    return best["handle"] or 0


def _in_front(user32, handle: int) -> bool:
    return bool(handle) and user32.GetForegroundWindow() == handle


def foreground_is_live() -> bool:
    """True if the foreground window (main window or a dialog) belongs to Live."""
    ctypes, wintypes, user32, kernel32 = _api()
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return _exe_name(kernel32, ctypes, wintypes, pid.value).startswith(LIVE_EXE_PREFIX)


def _dialog_open(user32, handle: int) -> bool:
    """Live disables its main window while one of its dialogs is open."""
    return not user32.IsWindowEnabled(handle)


def bring_live_forward() -> int:
    """Make Live the foreground window and return its handle."""
    _ctypes, _wintypes, user32, kernel32 = _api()
    handle = live_window()
    if not handle:
        raise KeysUnavailable("no Ableton Live window found")
    if _dialog_open(user32, handle):
        raise KeysUnavailable("Live is showing a dialog; answer it in Live first")
    for _attempt in range(3):
        if _in_front(user32, handle):
            return handle
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)  # SW_RESTORE
        # Windows refuses SetForegroundWindow from a background process. It
        # allows it while our input queue is attached to the one of the
        # thread that owns the foreground window.
        ours = kernel32.GetCurrentThreadId()
        theirs = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        attached = bool(theirs) and theirs != ours and bool(
            user32.AttachThreadInput(ours, theirs, True))
        try:
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
        finally:
            if attached:
                user32.AttachThreadInput(ours, theirs, False)
        time.sleep(0.2)
    if not _in_front(user32, handle):
        raise KeysUnavailable("Live's window could not be brought to the front; "
                              "click into Live once and try again")
    return handle


def chord(*virtual_keys: int) -> None:
    """Press the keys in order, release them in reverse order."""
    _ctypes, _wintypes, user32, _kernel32 = _api()
    for key in virtual_keys:
        user32.keybd_event(key, 0, _EXTENDED if key in _ARROWS else 0, 0)
    for key in reversed(virtual_keys):
        user32.keybd_event(key, 0, _KEY_UP | (_EXTENDED if key in _ARROWS else 0), 0)


def type_into_live(chords: Sequence[Sequence[int]], pause: float = 0.06) -> None:
    """Bring Live forward and type the given chords one after another."""
    handle = bring_live_forward()
    _ctypes, _wintypes, user32, _kernel32 = _api()
    for keys in chords:
        if not _in_front(user32, handle):
            raise KeysUnavailable("Live lost the keyboard focus while typing")
        chord(*keys)
        time.sleep(pause)


def dialog_appeared() -> bool:
    """True if Live opened a dialog (for example after a shortcut)."""
    _ctypes, _wintypes, user32, _kernel32 = _api()
    handle = live_window()
    return bool(handle) and _dialog_open(user32, handle)


def live_is_running() -> Optional[bool]:
    try:
        return bool(live_window())
    except KeysUnavailable:
        return None
