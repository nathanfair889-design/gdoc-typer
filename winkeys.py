"""Low-level Windows keystroke injection (stdlib only).

Uses SendInput with KEYEVENTF_UNICODE so the characters land in whatever
window has focus - Google Docs in any browser, Word, a text box, anything.
"""

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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


# --------------------------------------------------------------------------
# watching for real input, and global hotkeys
#
# Windows tags every synthetic keystroke with LLKHF_INJECTED. Our own typing
# carries that flag; a human's does not. That is what lets the typist tell
# "the user just grabbed the keyboard" from "that was me", and bail out
# before the caret model desyncs and scrambles the document.
# --------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               ctypes.c_uint, ctypes.c_uint)
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM)


class InputWatcher:
    """Runs a message loop hosting low-level hooks and global hotkeys.

    `on_user_input` fires when a real (non-injected) keypress or mouse click
    happens while armed. Hotkeys are registered as {id: (mods, vk)} and
    reported through `on_hotkey`.
    """

    def __init__(self, on_user_input=None, on_hotkey=None, watch_mouse=True):
        self.on_user_input = on_user_input
        self.on_hotkey = on_hotkey
        self.watch_mouse = watch_mouse
        self._armed = threading.Event()
        self._thread = None
        self._thread_id = None
        self._hotkeys = {}
        self._ready = threading.Event()
        self.last_injected = None       # for diagnostics and tests
        self.hook_installed = False
        self.hook_error = 0

    # -- arming -----------------------------------------------------------
    def arm(self):
        """Start reacting to real input (call once typing actually begins)."""
        self._armed.set()

    def disarm(self):
        """Ignore real input - during breaks, countdowns and pauses."""
        self._armed.clear()

    @property
    def armed(self):
        return self._armed.is_set()

    # -- lifecycle --------------------------------------------------------
    def start(self, hotkeys=None):
        self._hotkeys = dict(hotkeys or {})
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return self

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)

    # -- the loop ---------------------------------------------------------
    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()

        def keyboard(code, wparam, lparam):
            if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                injected = bool(info.flags & LLKHF_INJECTED)
                self.last_injected = injected
                if not injected and self._armed.is_set() and self.on_user_input:
                    self.on_user_input("keyboard")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def mouse(code, wparam, lparam):
            if code == 0 and wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN,
                                        WM_MBUTTONDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if (not info.flags & LLMHF_INJECTED and self._armed.is_set()
                        and self.on_user_input):
                    self.on_user_input("mouse")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        # keep references alive or the callbacks get collected mid-flight
        self._kb_proc = HOOKPROC(keyboard)
        self._ms_proc = HOOKPROC(mouse)
        kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, None, 0)
        ms_hook = (user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, None, 0)
                   if self.watch_mouse else None)
        self.hook_installed = bool(kb_hook)
        if not kb_hook:
            self.hook_error = ctypes.get_last_error()

        for hotkey_id, (mods, vk) in self._hotkeys.items():
            user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk)

        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and self.on_hotkey:
                self.on_hotkey(int(msg.wParam))
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        for hotkey_id in self._hotkeys:
            user32.UnregisterHotKey(None, hotkey_id)
        if kb_hook:
            user32.UnhookWindowsHookEx(kb_hook)
        if ms_hook:
            user32.UnhookWindowsHookEx(ms_hook)
