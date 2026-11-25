"""Pick the monitor where Silva was launched (shortcut, Desktop folder, or cursor)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Monitor:
    left: int
    top: int
    right: int
    bottom: int
    is_primary: bool = False

    @property
    def width(self) -> int:
        return max(1, self.right - self.left)

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


_cached: Monitor | None = None


def install_root() -> Path:
    return Path(__file__).resolve().parents[2]


def geometry_on_monitor(
    width: int,
    height: int,
    *,
    anchor: str = "ne",
    margin: int = 24,
    monitor: Monitor | None = None,
) -> str:
    """Tk geometry string on the launch monitor. Supports negative virtual-screen coords."""
    mon = monitor or preferred_monitor()
    if anchor == "ne":
        x = mon.right - width - margin
        y = mon.top + margin
    elif anchor == "nw":
        x = mon.left + margin
        y = mon.top + margin
    elif anchor == "se":
        x = mon.right - width - margin
        y = mon.bottom - height - margin
    elif anchor == "sw":
        x = mon.left + margin
        y = mon.bottom - height - margin
    else:
        x = mon.left + max(0, (mon.width - width) // 2)
        y = mon.top + max(0, (mon.height - height) // 2)
    return f"{width}x{height}+{x}+{y}"


def preferred_monitor() -> Monitor:
    global _cached
    if _cached is not None:
        return _cached
    _cached = _detect_monitor()
    return _cached


def reset_preferred_monitor() -> None:
    global _cached
    _cached = None


def list_monitors() -> list[Monitor]:
    if sys.platform != "win32":
        return [Monitor(0, 0, 1920, 1080, True)]
    try:
        return _win_monitors()
    except Exception:
        return [Monitor(0, 0, 1920, 1080, True)]


def monitor_from_point(x: int, y: int, monitors: list[Monitor] | None = None) -> Monitor | None:
    mons = monitors or list_monitors()
    for mon in mons:
        if mon.contains(x, y):
            return mon
    return None


def _primary(monitors: list[Monitor]) -> Monitor:
    for mon in monitors:
        if mon.is_primary:
            return mon
    return monitors[0] if monitors else Monitor(0, 0, 1920, 1080, True)


def _detect_monitor() -> Monitor:
    monitors = list_monitors()
    chosen = _primary(monitors)
    try:
        from silva.logger import log_info

        log_info(
            f"Silva GUI on primary monitor {chosen.left},{chosen.top}-{chosen.right},{chosen.bottom}."
        )
    except Exception:
        pass
    return chosen


def _desktop_dirs() -> list[Path]:
    dirs: list[Path] = []
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    for key in ("ONEDRIVE", "ONEDRIVECONSUMER", "USERPROFILE"):
        raw = os.environ.get(key)
        if raw:
            candidates.append(Path(raw) / "Desktop")
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in dirs:
            dirs.append(resolved)
    return dirs


def _desktop_item_names() -> list[str]:
    names: list[str] = []
    root = install_root()
    names.append(root.name)
    for desktop in _desktop_dirs():
        rel = _safe_relative(root, desktop)
        if rel is not None:
            names.append(rel.parts[0])
        try:
            links = list(desktop.glob("*.lnk"))
        except OSError:
            links = []
        for link in links:
            if _lnk_points_at_silva(link, root):
                names.append(link.stem)
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


def _safe_relative(path: Path, parent: Path) -> Path | None:
    try:
        path = path.resolve()
        parent = parent.resolve()
        if parent in path.parents or path == parent:
            return path.relative_to(parent)
    except (OSError, ValueError):
        return None
    return None


def _lnk_points_at_silva(link: Path, root: Path) -> bool:
    try:
        data = link.read_bytes()
    except OSError:
        return False
    hay = data.decode("latin-1", errors="ignore").lower() + data.decode("utf-16le", errors="ignore").lower()
    markers = (str(root).lower(), root.name.lower(), "run.bat", "main.py")
    return any(marker in hay for marker in markers)


def _desktop_item_point() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    for name in _desktop_item_names():
        point = _dispatch_desktop_icon_point(name)
        if point is not None:
            return point
    return None


def _cursor_point() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    except Exception:
        return None
    return None


def _console_point() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    except Exception:
        return None


def _win_monitors() -> list[Monitor]:
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    monitors: list[Monitor] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(hmon, _hdc, _lprect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            work = info.rcWork
            monitors.append(
                Monitor(
                    int(work.left),
                    int(work.top),
                    int(work.right),
                    int(work.bottom),
                    bool(info.dwFlags & 1),
                )
            )
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_callback), 0)
    return monitors


def _dispatch_desktop_icon_point(name: str) -> tuple[int, int] | None:
    """Read desktop icon coordinates from Explorer when win32com is available."""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None

    target = name.casefold()
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        for window in shell.Windows():
            try:
                path = str(window.Document.Folder.Self.Path)
                doc = window.Document
                count = doc.Count
            except Exception:
                continue
            if "desktop" not in path.casefold():
                continue
            for index in range(count):
                try:
                    item = doc.Item(index)
                    item_name = str(item.Name)
                except Exception:
                    continue
                if item_name.casefold() != target and not item_name.casefold().startswith(target + " "):
                    continue
                try:
                    left, top, _right, _bottom = doc.GetItemPosition(item)
                    return int(left), int(top)
                except Exception:
                    continue
    except Exception:
        return None
    return None
