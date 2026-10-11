"""Low-level Windows keystroke injection (stdlib only).

Uses SendInput with KEYEVENTF_UNICODE so the characters land in whatever
window has focus - Google Docs in any browser, Word, a text box, anything.
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

ULONG_PTR = wintypes.WPARAM


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def _key_input(vk=0, scan=0, flags=0):
    return INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(vk, scan, flags, 0, 0))


def send_vk(vk):
    """Press and release a virtual key (Backspace, Enter, Tab...)."""
    _send(_key_input(vk=vk), _key_input(vk=vk, flags=KEYEVENTF_KEYUP))


def send_unicode(ch):
    """Type one character as a Unicode keystroke, whatever the layout is."""
    raw = ch.encode("utf-16-le")
    units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
    events = []
    for u in units:
        events.append(_key_input(scan=u, flags=KEYEVENTF_UNICODE))
        events.append(_key_input(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    _send(*events)


def type_char(ch):
    """Type a single character of source text."""
    if ch == "\n":
        send_vk(VK_RETURN)
    elif ch == "\t":
        send_vk(VK_TAB)
    else:
        send_unicode(ch)


def backspace():
    send_vk(VK_BACK)


def arrow_left():
    send_vk(VK_LEFT)


def arrow_right():
    send_vk(VK_RIGHT)


def is_escape_down():
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def foreground_title():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


class HighResClock:
    """Raise the Windows timer resolution to 1 ms for the duration of a run."""

    def __enter__(self):
        winmm.timeBeginPeriod(1)
        return self

    def __exit__(self, *exc):
        winmm.timeEndPeriod(1)
        return False


def sleep_until(deadline, stop_check=None, poll=0.02):
    """Sleep until perf_counter() >= deadline. Returns False if stopped early."""
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return True
        if stop_check is not None and stop_check():
            return False
        time.sleep(min(remaining, poll))
