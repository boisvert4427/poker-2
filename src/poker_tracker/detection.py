from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .history import find_history_file_for_table, find_latest_history_file


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(slots=True)
class WinamaxProcess:
    pid: int
    name: str
    window_title: str
    executable: str


@dataclass(slots=True)
class WinamaxWindow:
    hwnd: int
    pid: int
    title: str
    visible: bool
    rect: tuple[int, int, int, int]


@dataclass(slots=True)
class HistoryLocation:
    path: str
    exists: bool
    source: str
    accessible: bool
    details: str


def list_winamax_processes() -> list[WinamaxProcess]:
    windows = list_winamax_windows()
    processes: list[WinamaxProcess] = []
    seen: set[int] = set()
    for window in windows:
        if window.pid in seen:
            continue
        seen.add(window.pid)
        processes.append(
            WinamaxProcess(
                pid=window.pid,
                name="Winamax",
                window_title=window.title,
                executable=_process_executable_for_pid(window.pid),
            )
        )
    return processes


def list_winamax_windows() -> list[WinamaxWindow]:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows: list[WinamaxWindow] = []

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    psapi = ctypes.windll.psapi
    psapi.GetModuleBaseNameW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    psapi.GetModuleBaseNameW.restype = wintypes.DWORD

    def process_name_for_pid(pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(handle, None, buffer, len(buffer)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip()
        if not title:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = process_name_for_pid(pid.value).lower()
        title_lower = title.lower()
        if "poker tracker prototype" in title_lower:
            return True
        if "winamax" not in process_name and "winamax" not in title_lower:
            return True

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        windows.append(
            WinamaxWindow(
                hwnd=int(hwnd),
                pid=int(pid.value),
                title=title,
                visible=bool(user32.IsWindowVisible(hwnd)),
                rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    return windows


def guess_history_locations() -> list[HistoryLocation]:
    candidates = []
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    one_drive = Path(os.environ.get("OneDrive", user_profile / "OneDrive"))
    appdata_roaming = Path(os.environ.get("APPDATA", user_profile / "AppData" / "Roaming"))

    raw_candidates = [
        appdata_roaming / "winamax" / "documents",
        appdata_roaming / "winamax" / "documents" / "accounts",
        user_profile / "Documents" / "Winamax Poker",
        user_profile / "Documents" / "Winamax Poker" / "accounts",
        one_drive / "Documents" / "Winamax Poker",
        one_drive / "Documents" / "Winamax Poker" / "accounts",
    ]

    seen: set[str] = set()
    for candidate in raw_candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    results: list[HistoryLocation] = []
    for candidate in candidates:
        if candidate.name.lower() == "accounts":
            results.extend(_scan_accounts_directory(candidate))
        else:
            exists = candidate.exists()
            accessible = _is_accessible_dir(candidate) if exists else False
            details = "ok" if accessible else "inaccessible or missing"
            results.append(
                HistoryLocation(
                    path=str(candidate),
                    exists=exists,
                    source="known-default",
                    accessible=accessible,
                    details=details,
                )
            )
    return results


def summarize_detection() -> dict[str, object]:
    processes = list_winamax_processes()
    windows = list_winamax_windows()
    histories = guess_history_locations()
    active_table_window = select_preferred_table_window(windows)
    history_dirs = [item.path for item in histories if item.exists and item.accessible and item.path.lower().endswith("history")]
    latest_history_file = None
    if active_table_window is not None:
        latest_history_file = find_history_file_for_table(history_dirs, active_table_window.title)
    if latest_history_file is None:
        latest_history_file = find_latest_history_file(history_dirs)
    return {
        "processes": processes,
        "windows": windows,
        "history_locations": histories,
        "latest_history_file": latest_history_file,
        "active_table_window": active_table_window,
    }


def select_preferred_table_window(windows: Iterable[WinamaxWindow]) -> WinamaxWindow | None:
    window_list = list(windows)
    if not window_list:
        return None

    titled_tables = [window for window in window_list if window.visible and window.title.lower().startswith("winamax ")]
    titled_tables = [window for window in titled_tables if window.title.strip().lower() != "winamax"]
    if titled_tables:
        return max(titled_tables, key=lambda item: _window_area(item.rect))

    visible_windows = [window for window in window_list if window.visible]
    if visible_windows:
        return max(visible_windows, key=lambda item: _window_area(item.rect))
    return window_list[0]


def _scan_accounts_directory(accounts_dir: Path) -> Iterable[HistoryLocation]:
    if not accounts_dir.exists():
        yield HistoryLocation(
            path=str(accounts_dir),
            exists=False,
            source="accounts-root",
            accessible=False,
            details="missing",
        )
        return

    if not _is_accessible_dir(accounts_dir):
        yield HistoryLocation(
            path=str(accounts_dir),
            exists=True,
            source="accounts-root",
            accessible=False,
            details="root inaccessible",
        )
        return

    yield HistoryLocation(
        path=str(accounts_dir),
        exists=True,
        source="accounts-root",
        accessible=True,
        details="ok",
    )

    for account_dir in sorted([child for child in accounts_dir.iterdir() if child.is_dir()]):
        history_dir = account_dir / "history"
        exists = history_dir.exists()
        accessible = _is_accessible_dir(history_dir) if exists else False
        if not exists:
            details = "missing history folder"
        elif accessible:
            details = _history_details(history_dir)
        else:
            details = "exists but not accessible"

        yield HistoryLocation(
            path=str(history_dir),
            exists=exists,
            source=f"account:{account_dir.name}",
            accessible=accessible,
            details=details,
        )


def _is_accessible_dir(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_dir():
            return False
        next(path.iterdir(), None)
        return True
    except OSError:
        return False


def _history_details(path: Path) -> str:
    try:
        file_count = sum(1 for child in path.iterdir() if child.is_file())
        return f"{file_count} files visible"
    except OSError as exc:
        return f"error: {exc}"


def _window_area(rect: tuple[int, int, int, int]) -> int:
    left, top, right, bottom = rect
    return max(0, right - left) * max(0, bottom - top)


def _process_executable_for_pid(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
    QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    QueryFullProcessImageNameW.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)
