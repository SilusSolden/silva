"""Keep Silva running while another app or game has focus — no cmd.exe clicking."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

from silva.config import load_config
from silva.logger import log_error, log_info

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_RESTORE = 9
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002
WM_APP = 0x8000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
IDI_APPLICATION = 32512
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_S = 0x53
VK_CONTROL = 0x11
VK_SHIFT = 0x10

LRESULT = ctypes.c_ssize_t
HWND = wintypes.HWND
HINSTANCE = wintypes.HINSTANCE
HMENU = wintypes.HMENU
HICON = wintypes.HANDLE

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32

_kernel32.GetConsoleWindow.restype = HWND
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = HINSTANCE
_kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
_kernel32.SetConsoleTitleW.restype = wintypes.BOOL

_user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = HWND
_user32.SetForegroundWindow.argtypes = [HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = wintypes.SHORT
_user32.RegisterHotKey.argtypes = [HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.DestroyWindow.argtypes = [HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.TranslateMessage.argtypes = [ctypes.c_void_p]
_user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
_user32.LoadIconW.argtypes = [HINSTANCE, ctypes.c_void_p]
_user32.LoadIconW.restype = HICON

if hasattr(_user32, "GetWindowLongPtrW"):
    _user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
else:
    _user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long

_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    HWND,
    HMENU,
    HINSTANCE,
    ctypes.c_void_p,
]
_user32.CreateWindowExW.restype = HWND
_user32.RegisterClassW.argtypes = [ctypes.c_void_p]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.GetMessageW.argtypes = [ctypes.c_void_p, HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL

_lock = threading.Lock()
_started = False
_hidden = False
_stop = threading.Event()
_hotkey_thread: threading.Thread | None = None
_hotkey_hwnd = 0
_on_type_hotkey: Callable[[], None] | None = None


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


def background_mode_enabled() -> bool:
    return bool(load_config().get("background_mode_enabled", True))


def _usable_hwnd(hwnd) -> int:
    try:
        value = int(hwnd or 0)
    except (TypeError, ValueError):
        return 0
    if value <= 0 or value in {0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF}:
        return 0
    return value


def console_hwnd() -> int:
    try:
        return _usable_hwnd(_kernel32.GetConsoleWindow())
    except Exception:
        return 0


def _clear_no_activate(hwnd: int) -> None:
    if not hwnd:
        return
    try:
        handle = HWND(hwnd)
        if hasattr(_user32, "GetWindowLongPtrW"):
            style = _user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
            _user32.SetWindowLongPtrW(handle, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
        else:
            style = _user32.GetWindowLongW(handle, GWL_EXSTYLE)
            _user32.SetWindowLongW(handle, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
    except Exception:
        pass


def _set_no_activate(hwnd: int) -> None:
    if not hwnd:
        return
    try:
        handle = HWND(hwnd)
        if hasattr(_user32, "GetWindowLongPtrW"):
            style = _user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
            _user32.SetWindowLongPtrW(handle, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_APPWINDOW)
        else:
            style = _user32.GetWindowLongW(handle, GWL_EXSTYLE)
            _user32.SetWindowLongW(handle, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_APPWINDOW)
    except Exception:
        pass


def minimize_console() -> None:
    hwnd = console_hwnd()
    if not hwnd:
        return
    _set_no_activate(hwnd)
    _user32.ShowWindow(HWND(hwnd), SW_SHOWMINNOACTIVE)
    global _hidden
    _hidden = True
    log_info("Silva console minimized to the taskbar (still listening).")


def hide_console() -> None:
    hwnd = console_hwnd()
    if not hwnd:
        return
    _set_no_activate(hwnd)
    _user32.ShowWindow(HWND(hwnd), SW_HIDE)
    global _hidden
    _hidden = True
    log_info("Silva console hidden. Voice still works in the background.")


def show_console() -> None:
    hwnd = console_hwnd()
    if not hwnd:
        return
    _clear_no_activate(hwnd)
    _user32.ShowWindow(HWND(hwnd), SW_SHOWNOACTIVATE)
    global _hidden
    _hidden = False
    log_info("Silva console shown without stealing focus.")


def show_console_front(hwnd: int | None = None) -> bool:
    """Restore the console on top so it can be read or closed."""
    target = _usable_hwnd(hwnd) or console_hwnd()
    if not target:
        return False
    handle = HWND(target)
    _clear_no_activate(target)
    _user32.ShowWindow(handle, SW_RESTORE)
    _user32.ShowWindow(handle, SW_SHOW)
    try:
        fg = _usable_hwnd(_user32.GetForegroundWindow())
        unused_pid = wintypes.DWORD(0)
        fg_tid = 0
        if fg:
            fg_tid = _user32.GetWindowThreadProcessId(HWND(fg), ctypes.byref(unused_pid))
        my_tid = _kernel32.GetCurrentThreadId()
        if fg_tid and my_tid and fg_tid != my_tid:
            _user32.AttachThreadInput(my_tid, fg_tid, True)
            _user32.SetForegroundWindow(handle)
            _user32.BringWindowToTop(handle)
            _user32.AttachThreadInput(my_tid, fg_tid, False)
        else:
            _user32.SetForegroundWindow(handle)
            _user32.BringWindowToTop(handle)
    except Exception:
        try:
            _user32.SetForegroundWindow(handle)
        except Exception:
            pass
    global _hidden
    _hidden = False
    log_info("Silva console brought to the front.")
    return True


def console_is_hidden() -> bool:
    return _hidden


def _fire_type_hotkey() -> None:
    callback = _on_type_hotkey
    if callback is None:
        return
    try:
        callback()
    except Exception as exc:
        log_error("Background type hotkey failed", exc=exc)


def _wnd_proc(hwnd, message, wparam, lparam):
    if message == WM_HOTKEY and int(wparam) == 1:
        _fire_type_hotkey()
        return 0
    if message == WM_APP:
        click = int(lparam) & 0xFFFF
        if click in {WM_LBUTTONUP, WM_LBUTTONDBLCLK}:
            if _hidden:
                show_console()
            else:
                minimize_console()
        return 0
    if message == WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return _user32.DefWindowProcW(hwnd, message, wparam, lparam)


_wnd_proc_ref = WNDPROC(_wnd_proc)


def _add_tray(hwnd) -> None:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = 1
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = WM_APP
    data.hIcon = _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
    data.szTip = "Silva is listening in the background"
    _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))


def _remove_tray(hwnd) -> None:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = 1
    _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))


def _key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _poll_hotkey_loop() -> None:
    """Fallback when a message window cannot be created (64-bit ctypes, games, etc.)."""
    was_down = False
    while not _stop.is_set():
        down = _key_down(VK_CONTROL) and _key_down(VK_SHIFT) and _key_down(VK_S)
        if down and not was_down:
            _fire_type_hotkey()
        was_down = bool(down)
        _stop.wait(0.08)


def _message_hotkey_loop() -> bool:
    global _hotkey_hwnd
    class_name = "SilvaBackgroundHost"
    instance = _kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(_wnd_proc_ref, ctypes.c_void_p)
    wc.hInstance = instance
    wc.lpszClassName = class_name
    _user32.RegisterClassW(ctypes.byref(wc))
    hwnd = _user32.CreateWindowExW(
        0,
        class_name,
        "SilvaBackground",
        0,
        0,
        0,
        0,
        0,
        None,
        None,
        instance,
        None,
    )
    if not hwnd:
        return False
    _hotkey_hwnd = int(hwnd) if not isinstance(hwnd, int) else hwnd
    handle = hwnd if not isinstance(hwnd, int) else HWND(hwnd)
    if not _user32.RegisterHotKey(handle, 1, MOD_CONTROL | MOD_SHIFT, VK_S):
        log_info("Ctrl+Shift+S was already in use; using key poll instead.")
        _poll_hotkey_loop()
        try:
            _user32.DestroyWindow(handle)
        except Exception:
            pass
        _hotkey_hwnd = 0
        return True
    try:
        _add_tray(handle)
    except Exception as exc:
        log_error("Silva tray icon failed", exc=exc)
    msg = MSG()
    while not _stop.is_set() and _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        _user32.TranslateMessage(ctypes.byref(msg))
        _user32.DispatchMessageW(ctypes.byref(msg))
    try:
        _user32.UnregisterHotKey(handle, 1)
        _remove_tray(handle)
        _user32.DestroyWindow(handle)
    except Exception:
        pass
    _hotkey_hwnd = 0
    return True


def _hotkey_loop() -> None:
    try:
        if not _message_hotkey_loop():
            log_info("Background hotkey window unavailable; polling Ctrl+Shift+S.")
            _poll_hotkey_loop()
    except Exception as exc:
        log_error("Background hotkey setup failed; voice still works", exc=exc)
        try:
            _poll_hotkey_loop()
        except Exception:
            pass


def start_background_mode(*, on_type_hotkey: Callable[[], None] | None = None) -> None:
    """Keep listening while games/apps stay in front. Window stays open until you hide it."""
    global _started, _on_type_hotkey, _hotkey_thread
    if not background_mode_enabled():
        return
    with _lock:
        _on_type_hotkey = on_type_hotkey
        if _started:
            return
        _started = True
        _stop.clear()
    try:
        from silva.instance import CONSOLE_TITLE

        _kernel32.SetConsoleTitleW(CONSOLE_TITLE)
    except Exception:
        try:
            _kernel32.SetConsoleTitleW("Silva Assistant")
        except Exception:
            pass
    # Keep the window visible on launch so a Stream Deck / shortcut press
    # can be read, closed, or checked for errors. Say hide the console later.
    try:
        _hotkey_thread = threading.Thread(target=_hotkey_loop, name="silva-background-hotkey", daemon=True)
        _hotkey_thread.start()
    except Exception as exc:
        log_error("Background hotkey thread failed; voice still works", exc=exc)
    log_info("Background mode on: voice works without focusing cmd.exe. Ctrl+Shift+S types a command.")


def stop_background_mode() -> None:
    _stop.set()
    hwnd = _hotkey_hwnd
    if hwnd:
        try:
            _user32.PostMessageW(HWND(hwnd), WM_DESTROY, 0, 0)
        except Exception:
            pass
    show_console()
