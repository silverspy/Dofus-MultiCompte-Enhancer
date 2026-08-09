"""Floating panel for controlling a team of Dofus windows.

Native Tkinter interface: borderless, semi-transparent, and always visible.
It reads players.json, tracks the foreground window, and launches the workflow
without blocking the interface.
"""

from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageOps, ImageTk
import pystray

from build_version import APP_VERSION
from chat_vision import activate_window, list_windows_by_executable
from localization import INPUT_NAME_EN, LANGUAGE_LABELS, TRANSLATIONS, translate
from panel_settings import DEFAULT_CONFIG, load_json, load_panel_config, save_json
from updater import ReleaseInfo, fetch_latest_release, is_newer_release, launch_update


SOURCE_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))
if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Dofus MultiCompte Enhancer"
else:
    DATA_DIR = SOURCE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_DIR = DATA_DIR
ASSETS_DIR = BUNDLE_DIR / "assets"
PLAYERS_PATH = DATA_DIR / "players.json"
CONFIG_PATH = DATA_DIR / "panel_config.json"
WORKFLOW_PATH = BUNDLE_DIR / "dofus_character_login.py"
CLASS_SYMBOLS_DIR = ASSETS_DIR / "class-symbols"
APP_ICON_PATH = ASSETS_DIR / "dofus-multicompteenhancer.ico"
PANEL_DIAGNOSTICS_PATH = DATA_DIR / "panel-diagnostics.log"
MINIMUM_VISIBLE_PROFILES = 2
WORKFLOW_DONE_PREFIX = "__WORKFLOW_DONE__:"
CLICK_DRAG_THRESHOLD = 4


def workflow_done_marker(exit_code: int) -> str:
    """Encode the completed child-process result for the Tk polling queue."""
    return f"{WORKFLOW_DONE_PREFIX}{exit_code}"


def parse_workflow_done_marker(message: str) -> int | None:
    """Return a queued workflow exit code, or None for regular output."""
    if not message.startswith(WORKFLOW_DONE_PREFIX):
        return None
    try:
        return int(message.removeprefix(WORKFLOW_DONE_PREFIX))
    except ValueError:
        return None


def is_emergency_stop_hotkey(vk_code: int, held_keys: set[int]) -> bool:
    """Return whether the current key press is Ctrl+Q."""
    return vk_code == EMERGENCY_STOP_KEY and bool(CONTROL_KEYS & held_keys)

# Uniform blue-black background inspired by small Dofus panels.
DOFUS_NAVY = "#313445"
BG = DOFUS_NAVY
BG_DEEP = DOFUS_NAVY
PANEL = DOFUS_NAVY
PANEL_HOVER = "#3b4056"
PANEL_ACTIVE = "#414860"
CONTROL = DOFUS_NAVY
BORDER = DOFUS_NAVY
CELL_FILL = "#4c5075"
CELL_HOVER = "#555a7d"
CELL_ACTIVE = "#505976"
CELL_BORDER = "#404455"
CELL_HIGHLIGHT = "#555a7a"
CELL_SHADOW = "#22242c"
CONTROL_BORDER = CELL_HIGHLIGHT
TEXT = "#f0f1ea"
MUTED = "#adb2c3"
LIME = "#bed64a"
LIME_DARK = "#748a1c"
GOLD = "#f4c247"
RED = "#d05b59"

CLASS_NAMES = {
    "feca": "Feca",
    "osamodas": "Osamodas",
    "cra": "Cra",
    "pandawa": "Pandawa",
}

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012
MONITOR_DEFAULTTONEAREST = 2
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010
MK_XBUTTON1 = 0x0020
MK_XBUTTON2 = 0x0040
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MODIFIER_KEYS = (
    0xA0, 0xA1,  # left/right Shift
    0xA2, 0xA3,  # left/right Ctrl
    0xA4, 0xA5,  # left/right Alt
    0x5B, 0x5C,  # left/right Windows
    0x10, 0x11, 0x12,  # generic variants
)
CONTROL_KEYS = frozenset((0x11, 0xA2, 0xA3))
EMERGENCY_STOP_KEY = 0x51  # Q
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE = 0
SW_SHOW = 5
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUNDSMALL = 3

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

user32.SendMessageW.restype = wintypes.LPARAM
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.DrawIconEx.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
    ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
gdi32.CreateRoundRectRgn.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
]
dwmapi.DwmSetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
if hasattr(user32, "GetClassLongPtrW"):
    user32.GetClassLongPtrW.restype = ctypes.c_void_p

WM_GETICON = 0x007F
ICON_SMALL = 0
ICON_BIG = 1
ICON_SMALL2 = 2
GCLP_HICON = -14
GCLP_HICONSM = -34
DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HANDLE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.mouse_event.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t,
]
user32.keybd_event.argtypes = [
    wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t,
]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ScreenToClient.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL


KEY_NAMES = {
    0x08: "RETOUR ARRIÈRE", 0x09: "TAB", 0x0D: "ENTRÉE",
    0x10: "MAJ", 0x11: "CTRL", 0x12: "ALT", 0x13: "PAUSE",
    0x14: "VERR MAJ", 0x1B: "ESCAPE", 0x20: "ESPACE",
    0x21: "PAGEUP", 0x22: "PAGEDOWN", 0x23: "FIN", 0x24: "DÉBUT",
    0x25: "GAUCHE", 0x26: "HAUT", 0x27: "DROITE", 0x28: "BAS",
    0x2C: "IMPR ÉCRAN", 0x2D: "INSERT", 0x2E: "SUPPR",
    0x5B: "WINDOWS GAUCHE", 0x5C: "WINDOWS DROITE", 0x5D: "MENU",
    0x6A: "NUM *", 0x6B: "NUM +", 0x6D: "NUM -", 0x6E: "NUM .", 0x6F: "NUM /",
    0x90: "VERR NUM", 0x91: "ARRÊT DÉFIL",
    0xA0: "MAJ GAUCHE", 0xA1: "MAJ DROITE", 0xA2: "CTRL GAUCHE",
    0xA3: "CTRL DROITE", 0xA4: "ALT GAUCHE", 0xA5: "ALT DROITE",
    0xA6: "NAV PRÉCÉDENT", 0xA7: "NAV SUIVANT", 0xA8: "NAV ACTUALISER",
    0xAD: "MUET", 0xAE: "VOLUME -", 0xAF: "VOLUME +",
    0xB0: "MÉDIA SUIVANT", 0xB1: "MÉDIA PRÉCÉDENT", 0xB2: "MÉDIA STOP",
    0xB3: "MÉDIA PLAY/PAUSE",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "²", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
KEY_NAMES.update({ord(letter): letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
KEY_NAMES.update({ord(digit): digit for digit in "0123456789"})
KEY_NAMES.update({0x60 + index: f"NUM {index}" for index in range(10)})
KEY_NAMES.update({0x70 + index: f"F{index + 1}" for index in range(24)})


def keyboard_input_name(vk_code: int) -> str:
    return KEY_NAMES.get(vk_code, f"TOUCHE 0x{vk_code:02X}")


@dataclass
class Player:
    pseudo: str
    saved_handle: int
    handle: int | None = None
    class_name: str = ""
    placeholder: bool = False


@dataclass
class SettingsVariables:
    orientation: tk.StringVar
    language: tk.StringVar
    previous: tk.StringVar
    following: tk.StringVar
    broadcast: tk.StringVar
    leader: tk.StringVar
    opacity: tk.DoubleVar
    position_locked: tk.BooleanVar
    drag_cells_locked: tk.BooleanVar
    play_button_enabled: tk.BooleanVar
    ui_scale: tk.DoubleVar

    @classmethod
    def from_panel(
        cls,
        master: tk.Misc,
        panel: "DofusPanel",
    ) -> "SettingsVariables":
        config = panel.config_data
        return cls(
            orientation=tk.StringVar(master, value=str(config["orientation"])),
            language=tk.StringVar(master, value=LANGUAGE_LABELS[panel.language()]),
            previous=tk.StringVar(master, value=str(config["previous_key"])),
            following=tk.StringVar(master, value=str(config["next_key"])),
            broadcast=tk.StringVar(master, value=str(config["broadcast_key"])),
            leader=tk.StringVar(master, value=str(config["leader"])),
            opacity=tk.DoubleVar(master, value=float(config["opacity"])),
            position_locked=tk.BooleanVar(
                master, value=bool(config.get("position_locked", False))
            ),
            drag_cells_locked=tk.BooleanVar(
                master, value=bool(config.get("drag_cells_locked", False))
            ),
            play_button_enabled=tk.BooleanVar(
                master, value=bool(config.get("play_button_enabled", True))
            ),
            ui_scale=tk.DoubleVar(master, value=panel.ui_scale()),
        )

    def config_updates(self) -> dict[str, object]:
        language = next(
            (
                code
                for code, label in LANGUAGE_LABELS.items()
                if label == self.language.get()
            ),
            "fr",
        )
        return {
            "orientation": self.orientation.get(),
            "previous_key": self.previous.get(),
            "next_key": self.following.get(),
            "broadcast_key": self.broadcast.get(),
            "leader": self.leader.get(),
            "opacity": self.opacity.get(),
            "language": language,
            "position_locked": bool(self.position_locked.get()),
            "drag_cells_locked": bool(self.drag_cells_locked.get()),
            "play_button_enabled": bool(self.play_button_enabled.get()),
            "ui_scale": float(self.ui_scale.get()),
        }


def players_with_placeholders(
    players: list[Player],
    minimum: int = MINIMUM_VISIBLE_PROFILES,
) -> list[Player]:
    """Return display-only placeholders without modifying the real player list."""
    visible_players = list(players)
    missing = max(0, minimum - len(visible_players))
    visible_players.extend(
        Player("", 0, placeholder=True)
        for _index in range(missing)
    )
    return visible_players


def sort_players_for_panel(
    players: list[Player],
    saved_order: object,
    leader_name: str,
) -> list[Player]:
    """Apply the saved icon order while keeping the configured leader first."""
    order = saved_order if isinstance(saved_order, list) else []
    rank = {
        str(name).casefold(): index
        for index, name in enumerate(order)
        if str(name).strip()
    }
    fallback = len(rank)
    leader_key = leader_name.strip().casefold()
    return sorted(
        players,
        key=lambda player: (
            0 if leader_key and player.pseudo.casefold() == leader_key else 1,
            rank.get(player.pseudo.casefold(), fallback),
        ),
    )


def reorder_players(
    players: list[Player],
    source: Player,
    target_index: int,
    leader_name: str,
) -> list[Player]:
    """Move one player to a display slot without moving the leader from first."""
    reordered = list(players)
    if source not in reordered or len(reordered) < 2:
        return reordered
    leader_key = leader_name.strip().casefold()
    source_is_leader = bool(
        leader_key and source.pseudo.casefold() == leader_key
    )
    leader_present = any(
        leader_key and player.pseudo.casefold() == leader_key
        for player in reordered
    )
    target_index = max(0, min(int(target_index), len(reordered) - 1))
    if source_is_leader:
        target_index = 0
    elif leader_present:
        target_index = max(1, target_index)
    reordered.remove(source)
    reordered.insert(target_index, source)
    return reordered


@dataclass(frozen=True)
class BroadcastMouseAction:
    source: int
    targets: tuple[int, ...]
    ratio_x: float
    ratio_y: float
    message_id: int
    mouse_data: int


@dataclass(frozen=True)
class BroadcastKeyboardAction:
    source: int
    targets: tuple[int, ...]
    vk_code: int
    scan_code: int
    extended: bool
    modifiers: tuple[int, ...]


def monitor_work_area(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return the usable area of the monitor containing the window."""
    # Tk exposes the inner client handle.  MonitorFromWindow must receive the
    # native top-level wrapper, otherwise multi-monitor/DPI setups may select a
    # different screen and place the settings dialog far from the panel.
    native_handle = int(user32.GetParent(hwnd) or hwnd)
    monitor = user32.MonitorFromWindow(native_handle, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    work = info.rcWork
    return int(work.left), int(work.top), int(work.right), int(work.bottom)


def native_toplevel_handle(window: tk.Misc) -> int:
    """Return Tk's native top-level wrapper instead of its client child."""
    inner_handle = int(window.winfo_id())
    return int(user32.GetParent(inner_handle) or inner_handle)


def apply_rounded_window(window: tk.Misc, diameter: int = 4) -> None:
    """Use native antialiased corners, with a subtle legacy fallback."""
    window.update_idletasks()
    native_handle = native_toplevel_handle(window)

    # A Win32 region is a one-bit mask and therefore creates a visible pixel
    # staircase at this panel's very small size. Windows 11's DWM corner is
    # antialiased and also keeps the correct result over bright backgrounds.
    user32.SetWindowRgn(native_handle, None, True)
    preference = ctypes.c_int(DWMWCP_ROUNDSMALL)
    result = dwmapi.DwmSetWindowAttribute(
        native_handle,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(preference),
        ctypes.sizeof(preference),
    )
    if result == 0:
        return

    # Older Windows versions do not support the DWM attribute. A four-pixel
    # diameter removes only the extreme corner pixel and avoids a long stair.
    width = max(1, window.winfo_width())
    height = max(1, window.winfo_height())
    region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, diameter, diameter)
    if not region:
        return
    # Windows owns the region after a successful call.
    if not user32.SetWindowRgn(native_handle, region, True):
        gdi32.DeleteObject(region)


def clamp_window_origin(
    x: int,
    y: int,
    width: int,
    height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Keep a window's full rectangle inside a monitor work area."""
    left, top, right, bottom = work_area
    return (
        min(max(x, left), max(left, right - width)),
        min(max(y, top), max(top, bottom - height)),
    )


def point_in_rectangle(
    point: tuple[int, int],
    rectangle: tuple[int, int, int, int] | None,
) -> bool:
    """Return whether a screen point is inside a left/top/right/bottom rectangle."""
    if rectangle is None:
        return False
    x, y = point
    left, top, right, bottom = rectangle
    return left <= x < right and top <= y < bottom


def position_dialog_near_rectangle(
    owner: tuple[int, int, int, int],
    dialog_size: tuple[int, int],
    work_area: tuple[int, int, int, int],
    gap: int = 8,
) -> tuple[int, int]:
    """Place a dialog beside its owner while keeping it inside one monitor."""
    owner_left, owner_top, owner_right, _owner_bottom = owner
    width, height = dialog_size
    left, top, right, bottom = work_area
    right_candidate = owner_right + gap
    left_candidate = owner_left - width - gap
    if right_candidate + width <= right:
        x = right_candidate
    elif left_candidate >= left:
        x = left_candidate
    else:
        x = min(max(owner_left, left), max(left, right - width))
    y = min(max(owner_top, top), max(top, bottom - height))
    return x, y


def append_panel_diagnostic(event: str, **details: object) -> None:
    """Record compact UI diagnostics for failures that only occur when frozen."""
    try:
        suffix = " ".join(f"{key}={value!r}" for key, value in details.items())
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {event} {suffix}".rstrip()
        with PANEL_DIAGNOSTICS_PATH.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def bind_dialog_drag(
    dialog: tk.Toplevel,
    handles: tuple[tk.Misc, ...],
    work_area: tuple[int, int, int, int],
) -> None:
    """Make a borderless dialog movable from each supplied drag handle."""
    drag_origin = [0, 0]

    def start_drag(event: tk.Event) -> None:
        drag_origin[0] = event.x_root - dialog.winfo_x()
        drag_origin[1] = event.y_root - dialog.winfo_y()

    def drag(event: tk.Event) -> None:
        x, y = clamp_window_origin(
            event.x_root - drag_origin[0],
            event.y_root - drag_origin[1],
            dialog.winfo_width(),
            dialog.winfo_height(),
            work_area,
        )
        dialog.geometry(f"+{x}+{y}")

    for handle in handles:
        handle.bind("<ButtonPress-1>", start_drag)
        handle.bind("<B1-Motion>", drag)


def fit_dialog_to_content(
    dialog: tk.Toplevel,
    width: int,
    work_area: tuple[int, int, int, int],
    origin: tuple[int, int] | None = None,
) -> None:
    """Shrink a dialog to its requested height and keep it on-screen."""
    dialog.update_idletasks()
    left, top, right, bottom = work_area
    height = max(360, min(dialog.winfo_reqheight(), max(1, bottom - top)))
    desired_x, desired_y = origin or (dialog.winfo_x(), dialog.winfo_y())
    x, y = clamp_window_origin(
        desired_x,
        desired_y,
        width,
        height,
        work_area,
    )
    dialog.geometry(f"{width}x{height}{x:+d}{y:+d}")
    dialog.after_idle(lambda: apply_rounded_window(dialog, 6))


def reveal_dialog(
    dialog: tk.Toplevel,
    width: int,
    work_area: tuple[int, int, int, int],
    owner: tk.Misc | None = None,
) -> None:
    """Finalize, clamp, and force a borderless dialog onto the visible desktop."""
    if not dialog.winfo_exists():
        return
    dialog.update_idletasks()
    height = max(
        360,
        min(dialog.winfo_reqheight(), max(1, work_area[3] - work_area[1])),
    )
    origin = None
    if owner is not None and owner.winfo_exists():
        origin = position_dialog_near_rectangle(
            (
                owner.winfo_rootx(),
                owner.winfo_rooty(),
                owner.winfo_rootx() + owner.winfo_width(),
                owner.winfo_rooty() + owner.winfo_height(),
            ),
            (width, height),
            work_area,
        )
    fit_dialog_to_content(dialog, width, work_area, origin)
    dialog.update_idletasks()
    dialog.deiconify()
    dialog.attributes("-topmost", True)
    dialog.lift()
    dialog.focus_force()
    append_panel_diagnostic(
        "settings_revealed",
        geometry=dialog.geometry(),
        requested=(dialog.winfo_reqwidth(), dialog.winfo_reqheight()),
        state=dialog.state(),
        viewable=bool(dialog.winfo_viewable()),
        work_area=work_area,
    )


def configure_settings_style(dialog: tk.Toplevel) -> None:
    """Apply the shared Dofus palette to native ttk controls."""
    style = ttk.Style(dialog)
    style.theme_use("clam")
    style.configure(
        "Dark.TCombobox", fieldbackground=CELL_FILL, background=CELL_FILL,
        foreground=TEXT, arrowcolor=MUTED, bordercolor=CELL_BORDER,
        lightcolor=CELL_FILL, darkcolor=CELL_FILL, padding=4,
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", CELL_FILL)],
        foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", CELL_FILL)],
        selectforeground=[("readonly", TEXT)],
    )


def expose_root_in_taskbar(root: tk.Tk) -> None:
    """Keep the window borderless while creating a taskbar button."""
    root.update_idletasks()
    alpha = float(root.attributes("-alpha"))
    native_handle = native_toplevel_handle(root)
    style = int(user32.GetWindowLongW(native_handle, GWL_EXSTYLE))
    style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    user32.SetWindowLongW(native_handle, GWL_EXSTYLE, style)

    # A very brief hide forces Explorer to rebuild the button with the new style
    # without restoring the Windows title bar.
    user32.ShowWindow(native_handle, SW_HIDE)
    user32.ShowWindow(native_handle, SW_SHOW)
    root.attributes("-topmost", True)
    root.attributes("-alpha", alpha)
    # Explorer's hide/show refresh can briefly redraw Tk's native wrapper.
    # Reapply the region afterwards so its square black corners never surface.
    root.after_idle(lambda: apply_rounded_window(root))


def get_window_icon(hwnd: int, size: int = 36) -> Image.Image | None:
    """Convert the window's real Win32 icon to a Pillow image."""
    # GetClassLongPtrW is local to the caller and cannot remain blocked on the
    # Dofus UI thread, unlike SendMessageW.
    getter = getattr(user32, "GetClassLongPtrW", user32.GetClassLongW)
    hicon = getter(hwnd, GCLP_HICONSM) or getter(hwnd, GCLP_HICON)
    if not hicon:
        return None

    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bits = ctypes.c_void_p()
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = size
    info.bmiHeader.biHeight = -size
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    bitmap = gdi32.CreateDIBSection(
        screen_dc, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
    )
    if not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
        return None
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        user32.DrawIconEx(memory_dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        raw = ctypes.string_at(bits.value, size * size * 4)
        image = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()
        if image.getchannel("A").getbbox() is None:
            rgb = image.convert("RGB")
            alpha = rgb.convert("L").point(lambda value: 255 if value > 8 else 0)
            image = rgb.convert("RGBA")
            image.putalpha(alpha)
        return image
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def class_icon_image(class_name: str, size: int = 28) -> Image.Image | None:
    normalized = "".join(
        character for character in unicodedata.normalize("NFD", class_name.casefold())
        if unicodedata.category(character) != "Mn"
    )
    symbol_files = {
        "feca": "feca.png",
        "osamodas": "osamodas.png",
        "cra": "cra.png",
        "pandawa": "pandawa.png",
    }
    path = CLASS_SYMBOLS_DIR / symbol_files.get(normalized, "")
    if not path.is_file():
        return None
    with Image.open(path) as source:
        symbol = source.convert("RGBA")
        symbol.thumbnail((size, size), Image.Resampling.LANCZOS)
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        image.alpha_composite(symbol, ((size - symbol.width) // 2, (size - symbol.height) // 2))
        return image


def placeholder_dofus_icon_image(size: int = 28) -> Image.Image | None:
    """Create the muted Dofus egg used by empty profile slots."""
    if not APP_ICON_PATH.is_file():
        return None
    with Image.open(APP_ICON_PATH) as source:
        source_rgba = source.convert("RGBA")
        symbol = ImageOps.contain(
            source_rgba,
            (max(1, size - 4), max(1, size - 4)),
            Image.Resampling.LANCZOS,
        )
        alpha = symbol.getchannel("A").point(lambda value: round(value * 0.62))
        symbol = ImageOps.grayscale(symbol.convert("RGB")).convert("RGBA")
        symbol.putalpha(alpha)
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        image.alpha_composite(
            symbol,
            ((size - symbol.width) // 2, (size - symbol.height) // 2),
        )
        return image


def add_leader_crown(image: Image.Image, size: int = 28) -> Image.Image:
    """Add a small outline crown without any opaque background."""
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))

    def unit(value: float) -> int:
        return round(value * size / 28.0 * scale)

    # Keep the character symbol centered and slightly reduced so the crown has
    # room without clipping the top of the icon.
    symbol = ImageOps.contain(
        image.convert("RGBA"),
        (size - 2, size - 3),
        Image.Resampling.LANCZOS,
    )
    symbol = symbol.resize(
        (symbol.width * scale, symbol.height * scale), Image.Resampling.LANCZOS
    )
    canvas.alpha_composite(
        symbol,
        ((canvas.width - symbol.width) // 2, unit(3)),
    )

    draw = ImageDraw.Draw(canvas)
    crown = [
        (unit(7), unit(7)),
        (unit(8), unit(2)),
        (unit(12), unit(5)),
        (unit(14), unit(1)),
        (unit(16), unit(5)),
        (unit(20), unit(2)),
        (unit(21), unit(7)),
    ]
    # A thin shadow preserves legibility while the gold outline stays hollow.
    line_width = max(2, unit(1))
    shadow = [(x, y + max(1, unit(1))) for x, y in crown]
    draw.line(shadow, fill=(35, 30, 20, 210), width=2 * line_width, joint="curve")
    draw.line(crown, fill=(244, 211, 69, 255), width=line_width, joint="curve")
    draw.line(
        (unit(7), unit(8), unit(21), unit(8)),
        fill=(244, 211, 69, 255),
        width=line_width,
    )
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def rounded_cell_background(
    fill: str,
    outline: str,
    *,
    width: int = 36,
    height: int = 38,
    outline_width: int = 1,
) -> Image.Image:
    """Create an antialiased rounded cell background without resizing it."""
    scale = 4
    canvas_size = (width * scale, height * scale)
    image = Image.new("RGB", canvas_size, DOFUS_NAVY)
    draw = ImageDraw.Draw(image)

    # Small downward shadow, matching cells in the Dofus toolbar.
    shadow_box = (2 * scale, 3 * scale, (width - 1) * scale, (height - 1) * scale)
    draw.rounded_rectangle(shadow_box, radius=4 * scale, fill=CELL_SHADOW)

    main_box = (scale, scale, (width - 2) * scale, (height - 3) * scale)
    mask = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(main_box, radius=4 * scale, fill=255)

    top_rgb = tuple(int(fill[index:index + 2], 16) for index in (1, 3, 5))
    bottom_rgb = tuple(max(0, value - 4) for value in top_rgb)
    gradient = Image.new("RGB", canvas_size)
    gradient_pixels = gradient.load()
    gradient_height = max(1, main_box[3] - main_box[1])
    for y in range(main_box[1], main_box[3] + 1):
        ratio = (y - main_box[1]) / gradient_height
        color = tuple(
            round(top * (1.0 - ratio) + bottom * ratio)
            for top, bottom in zip(top_rgb, bottom_rgb, strict=True)
        )
        for x in range(main_box[0], main_box[2] + 1):
            gradient_pixels[x, y] = color
    image.paste(gradient, mask=mask)

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        main_box,
        radius=4 * scale,
        outline=outline,
        width=outline_width * scale,
    )
    # Very subtle highlight along the top edge.
    draw.line(
        (5 * scale, 2 * scale, (width - 6) * scale, 2 * scale),
        fill=CELL_HIGHLIGHT,
        width=scale,
    )
    return image.resize((width, height), Image.Resampling.LANCZOS)


def drag_preview_image(
    icon: Image.Image | None,
    *,
    width: int = 36,
    height: int = 38,
) -> Image.Image:
    """Build the floating Dofus-style card shown during icon reordering."""
    preview = rounded_cell_background(
        CELL_HOVER,
        GOLD,
        width=width,
        height=height,
        outline_width=2,
    ).convert("RGBA")
    if icon is not None:
        symbol = ImageOps.contain(
            icon.convert("RGBA"),
            (max(1, width - 8), max(1, height - 10)),
            Image.Resampling.LANCZOS,
        )
        preview.alpha_composite(
            symbol,
            ((width - symbol.width) // 2, (height - symbol.height) // 2),
        )
    return preview


def rounded_control_background(
    fill: str,
    outline: str,
    *,
    width: int = 16,
    height: int = 16,
) -> Image.Image:
    """Small, slightly rounded button with a one-pixel shadow."""
    scale = 4
    image = Image.new("RGB", (width * scale, height * scale), DOFUS_NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (scale, 2 * scale, (width - 1) * scale, (height - 1) * scale),
        radius=2 * scale,
        fill=CELL_SHADOW,
    )
    draw.rounded_rectangle(
        (0, 0, (width - 1) * scale, (height - 2) * scale),
        radius=2 * scale,
        fill=fill,
        outline=outline,
        width=scale,
    )
    return image.resize((width, height), Image.Resampling.LANCZOS)


class RoundedControlButton(tk.Button):
    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        command: Callable[[], None],
        fill: str,
        hover_fill: str,
        outline: str,
        font: tuple[str, int] | tuple[str, int, str],
    ) -> None:
        super().__init__(
            master,
            text=text,
            compound="center",
            bg=DOFUS_NAVY,
            fg=TEXT,
            activebackground=DOFUS_NAVY,
            activeforeground=TEXT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            font=font,
            cursor="hand2",
            relief="flat",
            overrelief="flat",
            takefocus=False,
        )
        self.command = command
        self.fill = fill
        self.hover_fill = hover_fill
        self.outline = outline
        self.background_ref: ImageTk.PhotoImage | None = None
        self.render_signature: tuple[int, int, str] | None = None
        self.press_origin: tuple[int, int] | None = None
        self.press_cancelled = False
        self.bind("<Configure>", lambda _event: self.render(self.fill))
        self.bind("<Enter>", lambda _event: self.render(self.hover_fill))
        self.bind("<Leave>", lambda _event: self.render(self.fill))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    def _press(self, event: tk.Event) -> None:
        self.press_origin = (int(event.x_root), int(event.y_root))
        self.press_cancelled = False

    def _motion(self, event: tk.Event) -> None:
        if self.press_origin is None:
            return
        distance = max(
            abs(int(event.x_root) - self.press_origin[0]),
            abs(int(event.y_root) - self.press_origin[1]),
        )
        if distance >= CLICK_DRAG_THRESHOLD:
            self.press_cancelled = True

    def _release(self, event: tk.Event) -> None:
        if self.press_origin is None:
            return
        self._motion(event)
        should_execute = not self.press_cancelled
        self.press_origin = None
        self.press_cancelled = False
        if should_execute and self.command is not None:
            self.command()

    def render(self, fill: str) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 2 or height <= 2:
            return
        signature = (width, height, fill)
        if signature == self.render_signature:
            return
        self.render_signature = signature
        self.background_ref = ImageTk.PhotoImage(
            rounded_control_background(
                fill, self.outline, width=width, height=height
            )
        )
        self.configure(image=self.background_ref)


class RoundedSettingsButton(tk.Label):
    """Large antialiased button matching the relief of Dofus cells."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        command: Callable[[], None] | None = None,
        fill: str = CELL_FILL,
        hover_fill: str = CELL_HOVER,
        outline: str = CELL_BORDER,
        foreground: str = TEXT,
    ) -> None:
        super().__init__(
            master, text=text, compound="center", bg=BG, fg=foreground,
            bd=0, highlightthickness=0, padx=0, pady=0,
            font=("Segoe UI Semibold", 8), cursor="hand2",
        )
        self.command = command
        self.fill = fill
        self.hover_fill = hover_fill
        self.outline = outline
        self.current_fill = fill
        self.background_ref: ImageTk.PhotoImage | None = None
        self.render_signature: tuple[int, str, str] | None = None
        self.bind("<Configure>", self._resize)
        self.bind("<Enter>", lambda _event: self.render(self.hover_fill))
        self.bind("<Leave>", lambda _event: self.render(self.current_fill))
        self.bind("<ButtonRelease-1>", self._release)

    def _resize(self, _event: tk.Event | None = None) -> None:
        self.render(self.current_fill)

    def _release(self, _event: tk.Event) -> None:
        if self.command is not None:
            self.command()

    def render(self, fill: str) -> None:
        width = self.winfo_width()
        height = 26
        if width <= 2:
            return
        signature = (width, fill, self.outline)
        if signature == self.render_signature:
            return
        self.render_signature = signature
        self.background_ref = ImageTk.PhotoImage(
            rounded_cell_background(
                fill, self.outline, width=width, height=height,
                outline_width=1,
            )
        )
        self.configure(image=self.background_ref)

    def set_state(
        self, *, text: str, fill: str, foreground: str,
        hover_fill: str | None = None,
    ) -> None:
        self.current_fill = fill
        self.fill = fill
        self.hover_fill = hover_fill or fill
        self.configure(text=text, fg=foreground)
        self.render(fill)


class SettingsInputCapture:
    """Own the temporary input-capture state used by the settings dialog."""

    def __init__(self, panel: "DofusPanel", dialog: tk.Toplevel) -> None:
        self.panel = panel
        self.dialog = dialog
        self.variable: tk.StringVar | None = None
        self.button: RoundedSettingsButton | None = None

    @property
    def active(self) -> bool:
        return self.button is not None

    def finish(self, value: str | None = None) -> None:
        if value and self.variable is not None:
            self.variable.set(value)
        if self.button is not None and self.variable is not None:
            self.button.set_state(
                text=self.panel.display_input_name(self.variable.get()),
                fill=CELL_FILL,
                foreground=TEXT,
                hover_fill=CELL_HOVER,
            )
        self.variable = None
        self.button = None
        self.panel.capture_input_handler = None
        self.panel.capture_started_at = 0.0
        self.panel.input_suppressed_until = time.monotonic() + 0.30

    def begin(
        self,
        variable: tk.StringVar,
        button: RoundedSettingsButton,
    ) -> None:
        if self.active:
            self.finish()
        self.variable = variable
        self.button = button
        button.set_state(
            text=self.panel.t("press_input"),
            fill=GOLD,
            foreground=BG_DEEP,
            hover_fill=GOLD,
        )
        self.panel.capture_started_at = time.monotonic()
        self.panel.capture_input_handler = lambda name: self.finish(
            None if name == "ESCAPE" else name
        )
        self.dialog.focus_force()
        self.panel.set_status(self.panel.t("input_prompt"), GOLD)


class DofusCheckBox(tk.Frame):
    """Flat shadowless checkbox with subtle rounding."""

    def __init__(
        self, master: tk.Misc, *, text: str, variable: tk.BooleanVar
    ) -> None:
        super().__init__(master, bg=BG, cursor="hand2")
        self.variable = variable
        self.icon_ref: ImageTk.PhotoImage | None = None
        self.icon = tk.Label(self, bg=BG, bd=0, highlightthickness=0)
        self.icon.pack(side="left", padx=(0, 4))
        self.caption = tk.Label(
            self, text=text, bg=BG, fg=TEXT, font=("Segoe UI", 8),
            cursor="hand2",
        )
        self.caption.pack(side="left")
        for widget in (self, self.icon, self.caption):
            widget.bind("<ButtonRelease-1>", lambda _event: self.toggle())
        self.variable.trace_add("write", lambda *_args: self.refresh())
        self.refresh()

    def toggle(self) -> None:
        self.variable.set(not bool(self.variable.get()))

    def refresh(self) -> None:
        size = 14
        scale = 4
        image = Image.new("RGB", (size * scale, size * scale), BG)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (scale, scale, (size - 1) * scale, (size - 1) * scale),
            radius=3 * scale,
            fill=CELL_FILL,
            outline=CELL_HIGHLIGHT if self.variable.get() else CELL_BORDER,
            width=scale,
        )
        if self.variable.get():
            draw.line(
                (3 * scale, 7 * scale, 6 * scale, 10 * scale, 11 * scale, 4 * scale),
                fill=LIME,
                width=2 * scale,
                joint="curve",
            )
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        self.icon_ref = ImageTk.PhotoImage(image)
        self.icon.configure(image=self.icon_ref)


class DofusInfoTip(tk.Button):
    """Compact information icon with a Dofus-styled tooltip."""

    def __init__(self, master: tk.Misc, message: str) -> None:
        super().__init__(
            master,
            text="ⓘ",
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            font=("Segoe UI Symbol", 9, "bold"),
            cursor="hand2",
            bd=0,
            relief="flat",
            highlightthickness=0,
            takefocus=False,
            padx=2,
        )
        self.message = message
        self.popup: tk.Toplevel | None = None
        self.pinned = False
        self.host = self.winfo_toplevel()
        self.host_configure_binding = self.host.bind(
            "<Configure>",
            lambda _event: self.after_idle(self.reposition_tip),
            add="+",
        )
        self.bind("<Enter>", lambda _event: self.show_tip())
        self.bind("<Leave>", lambda _event: self.leave_tip())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<Destroy>", lambda _event: self.dispose_tip())

    def _press(self, _event: tk.Event | None = None) -> str:
        """Pin the tip on mouse-down so borderless windows cannot lose the click."""
        self.toggle_pin()
        return "break"

    def leave_tip(self) -> None:
        if not self.pinned:
            self.hide_tip()

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        if self.pinned:
            self.show_tip()
        else:
            self.hide_tip()

    def show_tip(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.reposition_tip()
            return
        popup = tk.Toplevel(self.host)
        self.popup = popup
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(
            bg=PANEL_HOVER,
            highlightbackground=CELL_BORDER,
            highlightthickness=1,
        )
        popup.attributes("-topmost", True)
        tk.Label(
            popup,
            text=self.message,
            justify="left",
            wraplength=250,
            bg=PANEL_HOVER,
            fg=TEXT,
            font=("Segoe UI", 8),
            padx=9,
            pady=7,
        ).pack()
        popup.update_idletasks()
        self.reposition_tip()
        popup.deiconify()
        popup.lift()

    def reposition_tip(self) -> None:
        popup = self.popup
        if popup is None or not popup.winfo_exists() or not self.winfo_exists():
            return
        popup.update_idletasks()
        width = popup.winfo_reqwidth()
        height = popup.winfo_reqheight()
        work_area = monitor_work_area(self.host.winfo_id()) or (
            0,
            0,
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
        )
        anchor = (
            self.winfo_rootx(),
            self.winfo_rooty(),
            self.winfo_rootx() + self.winfo_width(),
            self.winfo_rooty() + self.winfo_height(),
        )
        x, y = position_dialog_near_rectangle(
            anchor,
            (width, height),
            work_area,
            gap=4,
        )
        popup.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def hide_tip(self) -> None:
        popup = self.popup
        self.popup = None
        if popup is not None and popup.winfo_exists():
            popup.destroy()

    def dispose_tip(self) -> None:
        self.pinned = False
        self.hide_tip()
        if self.host_configure_binding and self.host.winfo_exists():
            self.host.unbind("<Configure>", self.host_configure_binding)
        self.host_configure_binding = ""


class DofusSlider(tk.Canvas):
    """Compact slider with a rounded track and circular thumb."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        variable: tk.DoubleVar,
        from_: float,
        to: float,
        resolution: float,
        command: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            master, height=28, bg=BG, bd=0, highlightthickness=0,
            cursor="hand2",
        )
        self.variable = variable
        self.minimum = from_
        self.maximum = to
        self.resolution = resolution
        self.command = command
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Button-1>", self.set_from_event)
        self.bind("<B1-Motion>", self.set_from_event)
        self.variable.trace_add("write", lambda *_args: self.redraw())

    def set_from_event(self, event: tk.Event) -> None:
        track_left = 7
        track_right = max(track_left + 1, self.winfo_width() - 42)
        ratio = min(1.0, max(0.0, (event.x - track_left) / (track_right - track_left)))
        raw = self.minimum + ratio * (self.maximum - self.minimum)
        steps = round((raw - self.minimum) / self.resolution)
        value = min(self.maximum, max(self.minimum, self.minimum + steps * self.resolution))
        self.variable.set(round(value, 4))
        if self.command is not None:
            self.command(str(value))

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 10:
            return
        value = float(self.variable.get())
        ratio = (value - self.minimum) / max(0.0001, self.maximum - self.minimum)
        ratio = min(1.0, max(0.0, ratio))
        left = 7
        right = max(left + 1, width - 42)
        center_y = 14
        knob_x = round(left + ratio * (right - left))
        self.create_line(
            left, center_y, right, center_y, fill=CELL_FILL,
            width=6, capstyle=tk.ROUND,
        )
        self.create_line(
            left, center_y, knob_x, center_y, fill=LIME_DARK,
            width=6, capstyle=tk.ROUND,
        )
        self.create_oval(
            knob_x - 6, center_y - 6, knob_x + 6, center_y + 6,
            fill=CELL_HIGHLIGHT, outline=CELL_BORDER, width=1,
        )
        self.create_text(
            width - 2, center_y, text=f"{value:.2f}", anchor="e",
            fill=TEXT, font=("Segoe UI Semibold", 8),
        )


class DofusComboBox(RoundedSettingsButton):
    """Compact list with a rounded control and custom dark menu."""

    def __init__(
        self, master: tk.Misc, *, variable: tk.StringVar, values: list[str]
    ) -> None:
        self.variable = variable
        self.values = values
        self.popup: tk.Toplevel | None = None
        super().__init__(
            master, text="", fill=CELL_FILL, hover_fill=CELL_HOVER,
            outline=CELL_BORDER,
        )
        self.command = self.open_popup
        self.variable.trace_add("write", lambda *_args: self.refresh_text())
        self.refresh_text()

    def refresh_text(self) -> None:
        self.configure(text=f"{self.variable.get()}   ▾")

    def open_popup(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
            return
        self.update_idletasks()
        popup = tk.Toplevel(self)
        self.popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=CELL_BORDER)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        row_height = 25
        popup.geometry(f"{self.winfo_width()}x{max(1, len(self.values)) * row_height}+{x}+{y}")
        for value in self.values:
            option = tk.Label(
                popup, text=value, anchor="w", padx=9,
                bg=PANEL_HOVER, fg=TEXT, font=("Segoe UI", 8),
                cursor="hand2",
            )
            option.pack(fill="both", expand=True, padx=1, pady=(1, 0))
            option.bind("<Enter>", lambda event: event.widget.configure(bg=CELL_HOVER))
            option.bind("<Leave>", lambda event: event.widget.configure(bg=PANEL_HOVER))
            option.bind("<ButtonRelease-1>", lambda _event, item=value: self.select(item))
        popup.focus_force()
        popup.bind("<Escape>", lambda _event: popup.destroy())
        popup.bind("<FocusOut>", lambda _event: popup.after(100, self.close_popup_if_unfocused))

    def close_popup_if_unfocused(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()

    def select(self, value: str) -> None:
        self.variable.set(value)
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()


class PlayerCell(tk.Frame):
    def __init__(self, master: tk.Misc, app: "DofusPanel", player: Player) -> None:
        super().__init__(
            master, bg=DOFUS_NAVY, highlightthickness=0,
            relief="flat",
        )
        self.app = app
        self.player = player
        self.scale = app.ui_scale()
        self.cell_width = app.px(36)
        self.cell_height = app.px(38)
        self.icon_size = app.px(28)
        self.active = False
        self.hovered = False
        self.drop_target = False
        self.icon_ref: ImageTk.PhotoImage | None = None
        self.card_ref: ImageTk.PhotoImage | None = None
        self.icon_signature: tuple[int | None, str, bool, bool] | None = None
        self.configure(cursor="" if player.placeholder else "hand2")
        self.card = tk.Label(self, bg=DOFUS_NAVY, bd=0, highlightthickness=0)
        self.icon = tk.Label(
            self, bg=PANEL, fg=TEXT,
            font=("Segoe UI", max(7, app.px(10)), "bold"),
        )
        self.arrow = tk.Label(
            self, text="", bg=LIME_DARK, fg=TEXT,
            font=("Segoe UI Symbol", max(5, app.px(6)), "bold"), relief="flat",
        )
        self.configure(width=self.cell_width, height=self.cell_height)
        self.pack_propagate(False)
        self.card.place(x=0, y=0, width=self.cell_width, height=self.cell_height)
        self.icon.place(
            x=(self.cell_width - self.icon_size) // 2,
            y=self.app.px(5),
            width=self.icon_size,
            height=self.icon_size,
        )
        self.card.lower()
        self.icon.lift()
        if not player.placeholder:
            for widget in (self, self.card, self.icon, self.arrow):
                widget.bind(
                    "<ButtonPress-1>",
                    lambda event: app.start_player_interaction(event, player),
                )
                widget.bind(
                    "<B1-Motion>",
                    lambda event: app.drag_player_interaction(event, player),
                )
                widget.bind(
                    "<ButtonRelease-1>",
                    lambda event: app.end_player_interaction(event, player),
                )
                widget.bind("<Enter>", lambda _event: self.set_hover(True))
                widget.bind("<Leave>", lambda _event: self.set_hover(False))
        self.refresh(False)

    def set_hover(self, hovered: bool) -> None:
        if self.player.placeholder:
            return
        self.hovered = hovered
        color = (
            CELL_ACTIVE
            if self.active
            else CELL_HOVER if self.hovered else CELL_FILL
        )
        self.set_background(color)

    def set_drop_target(self, targeted: bool) -> None:
        if self.drop_target == targeted:
            return
        self.drop_target = targeted
        color = (
            CELL_ACTIVE
            if self.active
            else CELL_HOVER if self.hovered else CELL_FILL
        )
        self.set_background(color)

    def set_background(self, color: str) -> None:
        self.icon.configure(bg=color)
        border = GOLD if self.drop_target else LIME if self.active else CELL_BORDER
        border_width = 2 if self.drop_target or self.active else 1
        self.card_ref = ImageTk.PhotoImage(
            rounded_cell_background(
                color, border, width=self.cell_width, height=self.cell_height,
                outline_width=border_width,
            )
        )
        self.card.configure(image=self.card_ref)

    def refresh(self, active: bool) -> None:
        self.active = active
        color = CELL_ACTIVE if active else CELL_FILL
        self.set_background(color)
        self.arrow.configure(text="▶" if active else "")
        if active:
            arrow_size = self.app.px(9)
            self.arrow.place(
                x=self.cell_width - arrow_size - self.app.px(2),
                y=self.cell_height - arrow_size - self.app.px(4),
                width=arrow_size,
                height=arrow_size,
            )
            self.arrow.lift()
        else:
            self.arrow.place_forget()
        is_leader = self.app.is_leader(self.player)
        signature = (
            self.player.handle,
            self.player.class_name,
            is_leader,
            self.player.placeholder,
        )
        if self.icon_signature != signature:
            self.icon_signature = signature
            image = (
                placeholder_dofus_icon_image(self.icon_size)
                if self.player.placeholder
                else class_icon_image(self.player.class_name, self.icon_size)
            )
            if image is None and self.player.handle and not self.player.placeholder:
                image = get_window_icon(self.player.handle, self.icon_size)
            if image is not None and not self.player.handle and not self.player.placeholder:
                alpha = image.getchannel("A")
                image = ImageOps.grayscale(image.convert("RGB")).convert("RGBA")
                image.putalpha(alpha)
            if image is not None:
                if is_leader and not self.player.placeholder:
                    image = add_leader_crown(image, self.icon_size)
                self.icon_ref = ImageTk.PhotoImage(image)
                self.icon.configure(image=self.icon_ref, text="")
            else:
                self.icon_ref = None
                self.icon.configure(image="", text=self.player.pseudo[:1].upper())


class DofusPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config_data = load_panel_config(CONFIG_PATH)
        self.players: list[Player] = []
        self.cells: list[PlayerCell] = []
        self.active_handle: int | None = None
        self.pending_activation_handle: int | None = None
        self.activation_generation = 0
        self.selected_index = 0
        self.players_mtime = 0.0
        self.next_window_resolve = 0.0
        self.hotkey_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.hotkey_thread: threading.Thread | None = None
        self.hotkey_thread_id = 0
        self.capture_input_handler: Callable[[str], None] | None = None
        self.capture_started_at = 0.0
        self.input_suppressed_until = 0.0
        self.broadcast_enabled = False
        self.broadcast_actions: queue.Queue[
            BroadcastMouseAction | BroadcastKeyboardAction | None
        ] = queue.Queue()
        self.broadcast_stop = threading.Event()
        self.broadcast_replay_active = threading.Event()
        self.broadcast_thread: threading.Thread | None = None
        self.workflow: subprocess.Popen[str] | None = None
        self.workflow_cancel_requested = False
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.update_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.drag_origin = (0, 0)
        self.drag_start = (0, 0)
        self.dragging = False
        self.drag_allowed = False
        self.player_drag_source: Player | None = None
        self.player_drag_start = (0, 0)
        self.player_drag_pointer = (0, 0)
        self.player_dragging = False
        self.player_drag_target_index: int | None = None
        self.player_drag_ghost: tk.Toplevel | None = None
        self.player_drag_ghost_image: ImageTk.PhotoImage | None = None
        self.status_popup: tk.Toplevel | None = None
        self.status_after_id: str | None = None
        self.settings_dialog: tk.Toplevel | None = None
        self.settings_button: RoundedControlButton | None = None
        self.settings_hitbox: tuple[int, int, int, int] | None = None
        self.update_dialog: tk.Toplevel | None = None
        self.tray_icon: pystray.Icon | None = None
        self.tray_thread: threading.Thread | None = None
        self.update_check_started = False
        self.closing = False

        if getattr(sys, "frozen", False):
            try:
                PANEL_DIAGNOSTICS_PATH.write_text("", encoding="utf-8")
            except OSError:
                pass
            append_panel_diagnostic("panel_started", pid=os.getpid())

        root.title("Dofus Multicompte Enhancer")
        if APP_ICON_PATH.is_file():
            try:
                root.iconbitmap(default=str(APP_ICON_PATH))
            except tk.TclError:
                pass
        root.overrideredirect(True)
        root.configure(bg=BG_DEEP)
        root.attributes("-topmost", True)
        root.attributes("-alpha", float(self.config_data["opacity"]))
        root.geometry(f"+{int(self.config_data['x'])}+{int(self.config_data['y'])}")

        self.shell = tk.Frame(root, bg=BG_DEEP, highlightbackground=BORDER, highlightthickness=1)
        self.shell.pack(fill="both", expand=True)
        # Side margins act as handles without adding a top bar.
        self.shell.configure(cursor="fleur")
        # Bind at window level so thin side borders and gaps between cells remain
        # usable drag handles.
        root.bind("<ButtonPress-1>", self.start_drag)
        root.bind("<B1-Motion>", self.drag)
        root.bind("<ButtonRelease-1>", self.end_drag)

        self.content = tk.Frame(self.shell, bg=BG_DEEP)
        self.content.pack(padx=2, pady=0)
        self.build()
        self.start_broadcast_worker()
        self.start_input_listener()
        self.start_tray_icon()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(120, lambda: expose_root_in_taskbar(root))
        root.after(1800, self.check_for_updates_async)
        self.poll()

    def ui_scale(self) -> float:
        return min(1.50, max(0.70, float(self.config_data.get("ui_scale", 1.0))))

    def language(self) -> str:
        language = str(self.config_data.get("language", "fr"))
        return language if language in TRANSLATIONS else "fr"

    def t(self, key: str, **values: object) -> str:
        return translate(self.language(), key, **values)

    def display_input_name(self, name: str) -> str:
        if self.language() == "en":
            if name.startswith("TOUCHE 0x"):
                return name.replace("TOUCHE", "KEY", 1)
            return INPUT_NAME_EN.get(name, name)
        return name

    def px(self, value: int) -> int:
        return max(1, round(value * self.ui_scale()))

    def is_leader(self, player: Player) -> bool:
        configured_leader = str(self.config_data.get("leader", "")).strip()
        return bool(
            configured_leader
            and player.pseudo
            and not player.placeholder
            and player.pseudo.casefold() == configured_leader.casefold()
        )

    def read_players(self) -> list[Player]:
        data = load_json(PLAYERS_PATH, {})
        if data.get("leader") and self.config_data.get("leader") == DEFAULT_CONFIG["leader"]:
            self.config_data["leader"] = data["leader"]
        saved_classes = self.config_data.get("classes", {})
        players = [
            Player(
                str(item["pseudo"]),
                int(item.get("window_handle", 0)),
                class_name=str(saved_classes.get(str(item["pseudo"]), "")),
            )
            for item in data.get("players", [])
            if item.get("pseudo")
        ]
        if not players and not data.get("leader"):
            self.config_data["leader"] = ""
        return sort_players_for_panel(
            players,
            self.config_data.get("player_order", []),
            str(self.config_data.get("leader", "")),
        )

    def apply_window_title(self, player: Player, title: str) -> None:
        detected_class = ""
        for part in (part.strip() for part in title.split(" - ")):
            normalized = "".join(
                character for character in unicodedata.normalize("NFD", part.casefold())
                if unicodedata.category(character) != "Mn"
            )
            if normalized in CLASS_NAMES:
                detected_class = CLASS_NAMES[normalized]
                break
        if not detected_class:
            return
        player.class_name = detected_class
        classes = self.config_data.setdefault("classes", {})
        if classes.get(player.pseudo) != player.class_name:
            classes[player.pseudo] = player.class_name
            save_json(CONFIG_PATH, self.config_data)

    def resolve_windows(self) -> None:
        windows = list_windows_by_executable("Dofus.exe")
        unused = dict(windows)
        for player in self.players:
            player.handle = player.saved_handle if player.saved_handle in unused else None
            if player.handle:
                self.apply_window_title(player, unused[player.handle])
                unused.pop(player.handle, None)
                continue
            matches = [
                hwnd for hwnd, title in unused.items()
                if title.split(" - ", 1)[0].strip().casefold() == player.pseudo.casefold()
            ]
            if len(matches) == 1:
                player.handle = matches[0]
                self.apply_window_title(player, unused[matches[0]])
                unused.pop(matches[0], None)

    def build(self) -> None:
        self.clear_player_drag_visual()
        self.settings_button = None
        self.settings_hitbox = None
        for child in self.content.winfo_children():
            child.destroy()
        self.cells.clear()
        self.players = self.read_players()
        self.resolve_windows()
        self.content.pack_configure(padx=self.px(2), pady=0)

        horizontal = self.config_data["orientation"] == "horizontal"
        cell_width = self.px(36)
        cell_height = self.px(38)
        control_button_size = self.px(16)
        control_width = self.px(18) if horizontal else cell_width
        control_height = cell_height if horizontal else self.px(18)
        play_button_enabled = bool(
            self.config_data.get("play_button_enabled", True)
        )
        control = tk.Frame(
            self.content, bg=CONTROL, highlightbackground=BORDER, highlightthickness=1,
            width=control_width, height=control_height,
        )
        control.pack_propagate(False)
        control.pack(side="left" if horizontal else "top", padx=0, pady=0)
        gear = RoundedControlButton(
            control,
            text="⚙",
            command=lambda: self.request_open_settings("button"),
            fill=CELL_FILL,
            hover_fill=CELL_HOVER,
            outline=CONTROL_BORDER,
            font=("Segoe UI Symbol", max(7, self.px(9))),
        )
        if play_button_enabled:
            gear_x = (control_width - control_button_size) // 2 if horizontal else self.px(1)
            gear_y = self.px(1)
        else:
            gear_x = (control_width - control_button_size) // 2
            gear_y = (control_height - control_button_size) // 2
        gear.place(
            x=gear_x, y=gear_y,
            width=control_button_size, height=control_button_size,
        )
        self.settings_button = gear
        if play_button_enabled:
            play = RoundedControlButton(
                control,
                text="▶",
                command=self.run_workflow,
                fill=LIME_DARK,
                hover_fill=LIME,
                outline=LIME_DARK,
                font=("Segoe UI Symbol", max(6, self.px(8)), "bold"),
            )
            play_x = (
                (control_width - control_button_size) // 2
                if horizontal else control_width - control_button_size - self.px(1)
            )
            play_y = (
                control_height - control_button_size - self.px(1)
                if horizontal else self.px(1)
            )
            play.place(
                x=play_x, y=play_y,
                width=control_button_size, height=control_button_size,
            )

        separator = tk.Frame(
            self.content,
            bg=DOFUS_NAVY,
            width=self.px(1) if horizontal else cell_width,
            height=cell_height if horizontal else self.px(1),
        )
        separator.pack(side="left" if horizontal else "top")

        for player in players_with_placeholders(self.players):
            cell = PlayerCell(self.content, self, player)
            cell.pack(side="left" if horizontal else "top", padx=0, pady=0)
            self.cells.append(cell)
        foreground = int(user32.GetForegroundWindow() or 0)
        if not self.synchronize_active_player(foreground, force_refresh=True):
            self.refresh_cells()
        self.root.update_idletasks()
        self.ensure_visible()
        self.refresh_settings_hitbox()
        self.root.after_idle(self.refresh_settings_hitbox)
        self.root.after(250, self.refresh_settings_hitbox)
        self.root.after_idle(lambda: apply_rounded_window(self.root))

    def refresh_settings_hitbox(self) -> None:
        """Cache the settings control bounds for the low-level mouse fallback."""
        button = self.settings_button
        if button is None:
            self.settings_hitbox = None
            return
        try:
            if not button.winfo_exists() or not button.winfo_ismapped():
                self.settings_hitbox = None
                return
            padding = self.px(2)
            left = button.winfo_rootx() - padding
            top = button.winfo_rooty() - padding
            self.settings_hitbox = (
                left,
                top,
                left + button.winfo_width() + 2 * padding,
                top + button.winfo_height() + 2 * padding,
            )
        except tk.TclError:
            self.settings_hitbox = None

    def ensure_visible(self) -> None:
        """Keep the entire panel on-screen after resizing."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = max(0, min(self.root.winfo_x(), self.root.winfo_screenwidth() - width))
        y = max(0, min(self.root.winfo_y(), self.root.winfo_screenheight() - height))
        if (x, y) != (self.root.winfo_x(), self.root.winfo_y()):
            self.root.geometry(f"+{x}+{y}")
            self.config_data["x"] = x
            self.config_data["y"] = y
            save_json(CONFIG_PATH, self.config_data)

    def start_drag(self, event: tk.Event) -> None:
        self.drag_allowed = False
        self.dragging = False
        if isinstance(
            event.widget,
            (tk.Button, ttk.Combobox, tk.Scale, RoundedSettingsButton,
             tk.Checkbutton),
        ):
            return
        widget: tk.Misc | None = event.widget
        while widget is not None:
            if isinstance(widget, PlayerCell):
                return
            widget = getattr(widget, "master", None)
        self.drag_start = (event.x_root, event.y_root)
        if bool(self.config_data.get("position_locked", False)):
            return
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.drag_allowed = True

    def drag(self, event: tk.Event) -> None:
        if not self.drag_allowed:
            return
        if bool(self.config_data.get("position_locked", False)):
            return
        if not self.dragging:
            distance = max(
                abs(event.x_root - self.drag_start[0]),
                abs(event.y_root - self.drag_start[1]),
            )
            if distance < CLICK_DRAG_THRESHOLD:
                return
            self.dragging = True
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, _event: tk.Event) -> None:
        if not self.dragging:
            self.drag_allowed = False
            return
        self.config_data["x"] = self.root.winfo_x()
        self.config_data["y"] = self.root.winfo_y()
        save_json(CONFIG_PATH, self.config_data)
        self.root.update_idletasks()
        self.refresh_settings_hitbox()
        self.dragging = False
        self.drag_allowed = False

    def start_player_interaction(self, event: tk.Event, player: Player) -> None:
        self.clear_player_drag_visual()
        self.drag_allowed = False
        self.dragging = False
        self.player_drag_source = (
            None
            if bool(self.config_data.get("drag_cells_locked", False))
            else player
        )
        self.player_drag_start = (event.x_root, event.y_root)
        self.player_drag_pointer = self.player_drag_start
        self.player_dragging = False

    def drag_player_interaction(self, event: tk.Event, player: Player) -> None:
        if self.player_drag_source is not player:
            return
        self.player_drag_pointer = (event.x_root, event.y_root)
        if self.player_dragging:
            self.move_player_drag_visual(event.x_root, event.y_root)
            return
        distance = max(
            abs(event.x_root - self.player_drag_start[0]),
            abs(event.y_root - self.player_drag_start[1]),
        )
        if distance >= self.px(4):
            self.player_dragging = True
            self.begin_player_drag_visual(player, event.x_root, event.y_root)

    def begin_player_drag_visual(
        self, player: Player, x_root: int, y_root: int
    ) -> None:
        source_cell = next(
            (cell for cell in self.cells if cell.player is player),
            None,
        )
        icon: Image.Image | None = None
        if source_cell is not None and source_cell.icon_ref is not None:
            try:
                icon = ImageTk.getimage(source_cell.icon_ref).convert("RGBA")
            except (tk.TclError, ValueError):
                icon = None
        width = self.px(36)
        height = self.px(38)
        self.player_drag_ghost_image = ImageTk.PhotoImage(
            drag_preview_image(icon, width=width, height=height)
        )
        ghost = tk.Toplevel(self.root)
        self.player_drag_ghost = ghost
        ghost.withdraw()
        ghost.overrideredirect(True)
        ghost.configure(bg=DOFUS_NAVY)
        ghost.attributes("-topmost", True)
        try:
            ghost.attributes("-alpha", 0.90)
        except tk.TclError:
            pass
        tk.Label(
            ghost,
            image=self.player_drag_ghost_image,
            bg=DOFUS_NAVY,
            bd=0,
            highlightthickness=0,
        ).pack()
        self.move_player_drag_visual(x_root, y_root)
        ghost.deiconify()
        ghost.lift()

    def move_player_drag_visual(self, x_root: int, y_root: int) -> None:
        ghost = self.player_drag_ghost
        if ghost is not None and ghost.winfo_exists():
            width = self.px(36)
            height = self.px(38)
            offset = self.px(12)
            x = min(x_root + offset, self.root.winfo_screenwidth() - width)
            y = min(y_root + offset, self.root.winfo_screenheight() - height)
            ghost.geometry(f"{width}x{height}{max(0, x):+d}{max(0, y):+d}")
        target_index = self.player_drop_index(x_root, y_root)
        source = self.player_drag_source
        if source is not None:
            preview_order = reorder_players(
                self.players,
                source,
                target_index,
                str(self.config_data.get("leader", "")),
            )
            target_index = preview_order.index(source)
        self.player_drag_target_index = target_index
        for index, cell in enumerate(
            cell for cell in self.cells if not cell.player.placeholder
        ):
            cell.set_drop_target(index == target_index)

    def clear_player_drag_visual(self) -> None:
        ghost = self.player_drag_ghost
        self.player_drag_ghost = None
        self.player_drag_ghost_image = None
        if ghost is not None:
            try:
                if ghost.winfo_exists():
                    ghost.destroy()
            except tk.TclError:
                pass
        for cell in self.cells:
            try:
                cell.set_drop_target(False)
            except tk.TclError:
                pass
        self.player_drag_target_index = None

    def player_drop_index(self, x_root: int, y_root: int) -> int:
        real_cells = [cell for cell in self.cells if not cell.player.placeholder]
        if not real_cells:
            return 0
        horizontal = self.config_data["orientation"] == "horizontal"
        pointer = x_root if horizontal else y_root
        centers = [
            (
                cell.winfo_rootx() + cell.winfo_width() // 2
                if horizontal
                else cell.winfo_rooty() + cell.winfo_height() // 2
            )
            for cell in real_cells
        ]
        return min(range(len(centers)), key=lambda index: abs(centers[index] - pointer))

    def persist_player_order(self) -> None:
        self.config_data["player_order"] = [
            player.pseudo for player in self.players
        ]
        save_json(CONFIG_PATH, self.config_data)

    def end_player_interaction(self, event: tk.Event, player: Player) -> None:
        was_dragging = self.player_dragging and self.player_drag_source is player
        pointer = self.player_drag_pointer
        target_index = self.player_drag_target_index
        self.player_drag_source = None
        self.player_dragging = False
        self.clear_player_drag_visual()
        if was_dragging:
            if target_index is None:
                target_index = self.player_drop_index(*pointer)
            reordered = reorder_players(
                self.players,
                player,
                target_index,
                str(self.config_data.get("leader", "")),
            )
            if reordered != self.players:
                self.players = reordered
                self.persist_player_order()
                self.build()
            return
        self.activate_player(player)

    def activate_player(self, player: Player) -> None:
        if player.handle is None:
            self.set_status(self.t("offline", player=player.pseudo), RED)
            return
        self.activation_generation += 1
        generation = self.activation_generation
        self.pending_activation_handle = player.handle
        self.active_handle = player.handle
        self.selected_index = self.players.index(player)
        self.refresh_cells()
        self.root.update_idletasks()
        # Give Tk one frame to paint the new selection before Windows activation
        # begins.
        self.root.after(
            16,
            lambda: self.finish_player_activation(player, generation),
        )

    def finish_player_activation(self, player: Player, generation: int) -> None:
        if generation != self.activation_generation:
            return
        if self.pending_activation_handle != player.handle:
            return
        try:
            activate_window(player.handle)
        except RuntimeError as error:
            self.set_status(str(error), RED)
            foreground = int(user32.GetForegroundWindow() or 0)
            matching_index = next(
                (
                    index for index, candidate in enumerate(self.players)
                    if candidate.handle == foreground
                ),
                None,
            )
            if matching_index is not None:
                self.active_handle = foreground
                self.selected_index = matching_index
                self.refresh_cells()
        finally:
            if generation == self.activation_generation:
                self.pending_activation_handle = None

    def navigate(self, delta: int) -> None:
        online = [index for index, player in enumerate(self.players) if player.handle]
        if not online:
            self.set_status(self.t("no_window"), RED)
            return
        if self.selected_index not in online:
            target_index = online[0]
        else:
            position = online.index(self.selected_index)
            target_index = online[(position + delta) % len(online)]
        self.activate_player(self.players[target_index])

    def is_control_input(self, name: str) -> bool:
        return name in {
            str(self.config_data["previous_key"]),
            str(self.config_data["next_key"]),
            str(self.config_data["broadcast_key"]),
        }

    def set_broadcast_enabled(self, enabled: bool) -> None:
        self.broadcast_enabled = enabled
        # Status text indicates the mode without a persistent yellow border that
        # would alter the panel's visual language.
        self.shell.configure(highlightbackground=BORDER)
        online_count = sum(player.handle is not None for player in self.players)
        if enabled and online_count < 2:
            message = self.t("replication_no_target")
            color = RED
        elif enabled:
            message = self.t("replication_targets", count=online_count - 1)
            color = LIME
        else:
            message = self.t("replication_disabled")
            color = MUTED
        self.set_status(message, color)

    def broadcast_targets(self) -> tuple[int, list[int]] | None:
        if not self.broadcast_enabled:
            return None
        source = int(user32.GetForegroundWindow() or 0)
        handles = [int(player.handle) for player in self.players if player.handle]
        if source not in handles:
            return None
        return source, [handle for handle in handles if handle != source]

    def start_broadcast_worker(self) -> None:
        """Execute replicated clicks outside the global Windows hook."""
        self.broadcast_stop.clear()

        def worker() -> None:
            while not self.broadcast_stop.is_set():
                action = self.broadcast_actions.get()
                if action is None:
                    break
                try:
                    if isinstance(action, BroadcastMouseAction):
                        self.replay_mouse_action(action)
                    else:
                        self.replay_keyboard_action(action)
                except Exception as error:
                    self.hotkey_events.put(("broadcast_error", str(error)))

        self.broadcast_thread = threading.Thread(
            target=worker, daemon=True, name="dofus-broadcast"
        )
        self.broadcast_thread.start()

    def replay_mouse_action(self, action: BroadcastMouseAction) -> None:
        """Replay a physical click on each client, then restore the source."""
        # Let Windows deliver the original click to the source window before
        # rapidly activating secondary windows.
        time.sleep(0.020)
        original_cursor = POINT()
        user32.GetCursorPos(ctypes.byref(original_cursor))
        self.broadcast_replay_active.set()
        try:
            for handle in action.targets:
                if not user32.IsWindow(handle):
                    continue
                activate_window(handle)
                target_rect = wintypes.RECT()
                if not user32.GetClientRect(handle, ctypes.byref(target_rect)):
                    continue
                width = max(1, target_rect.right - target_rect.left)
                height = max(1, target_rect.bottom - target_rect.top)
                point = POINT(
                    min(width - 1, round(action.ratio_x * width)),
                    min(height - 1, round(action.ratio_y * height)),
                )
                if not user32.ClientToScreen(handle, ctypes.byref(point)):
                    continue
                user32.SetCursorPos(point.x, point.y)
                time.sleep(0.012)

                if action.message_id == WM_LBUTTONUP:
                    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                elif action.message_id == WM_RBUTTONUP:
                    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                elif action.message_id == WM_MBUTTONUP:
                    user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
                    user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
                elif action.message_id == WM_XBUTTONUP:
                    button = (action.mouse_data >> 16) & 0xFFFF
                    user32.mouse_event(MOUSEEVENTF_XDOWN, 0, 0, button, 0)
                    user32.mouse_event(MOUSEEVENTF_XUP, 0, 0, button, 0)
                elif action.message_id in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                    delta = ctypes.c_short((action.mouse_data >> 16) & 0xFFFF).value
                    flag = (
                        MOUSEEVENTF_WHEEL
                        if action.message_id == WM_MOUSEWHEEL
                        else MOUSEEVENTF_HWHEEL
                    )
                    user32.mouse_event(flag, 0, 0, ctypes.c_uint32(delta).value, 0)

            if user32.IsWindow(action.source):
                activate_window(action.source)
        finally:
            user32.SetCursorPos(original_cursor.x, original_cursor.y)
            self.broadcast_replay_active.clear()

    def replay_keyboard_action(self, action: BroadcastKeyboardAction) -> None:
        """Replay a key or key combination on each secondary window."""
        time.sleep(0.015)
        self.broadcast_replay_active.set()

        def emit_key(
            vk_code: int, scan_code: int, key_up: bool, extended: bool = False
        ) -> None:
            flags = KEYEVENTF_KEYUP if key_up else 0
            if extended or vk_code in {
                0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
                0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5,
            }:
                flags |= KEYEVENTF_EXTENDEDKEY
            user32.keybd_event(vk_code, scan_code & 0xFF, flags, 0)

        try:
            for handle in action.targets:
                if not user32.IsWindow(handle):
                    continue
                activate_window(handle)
                time.sleep(0.008)
                for modifier in action.modifiers:
                    modifier_scan = int(user32.MapVirtualKeyW(modifier, 0))
                    emit_key(modifier, modifier_scan, False)
                emit_key(action.vk_code, action.scan_code, False, action.extended)
                emit_key(action.vk_code, action.scan_code, True, action.extended)
                for modifier in reversed(action.modifiers):
                    modifier_scan = int(user32.MapVirtualKeyW(modifier, 0))
                    emit_key(modifier, modifier_scan, True)

            if user32.IsWindow(action.source):
                activate_window(action.source)
        finally:
            self.broadcast_replay_active.clear()

    def mirror_keyboard_event(
        self, name: str, vk_code: int, scan_code: int, flags: int, message_id: int,
        modifiers: tuple[int, ...],
    ) -> None:
        targets = self.broadcast_targets()
        if targets is None or self.is_control_input(name):
            return
        if message_id not in (WM_KEYUP, WM_SYSKEYUP) or vk_code in MODIFIER_KEYS:
            return
        source, target_handles = targets
        self.broadcast_actions.put(
            BroadcastKeyboardAction(
                source=source,
                targets=tuple(target_handles),
                vk_code=vk_code,
                scan_code=scan_code,
                extended=bool(flags & LLKHF_EXTENDED),
                modifiers=modifiers,
            )
        )

    def mirror_mouse_event(
        self, input_name: str | None, message_id: int, screen_x: int, screen_y: int,
        mouse_data: int, button_state: int,
    ) -> None:
        targets = self.broadcast_targets()
        if targets is None or (input_name is not None and self.is_control_input(input_name)):
            return
        source, target_handles = targets
        source_point = POINT(screen_x, screen_y)
        source_rect = wintypes.RECT()
        if not user32.ScreenToClient(source, ctypes.byref(source_point)):
            return
        if not user32.GetClientRect(source, ctypes.byref(source_rect)):
            return
        source_width = max(1, source_rect.right - source_rect.left)
        source_height = max(1, source_rect.bottom - source_rect.top)
        ratio_x = min(1.0, max(0.0, source_point.x / source_width))
        ratio_y = min(1.0, max(0.0, source_point.y / source_height))
        # Unity often ignores mouse messages posted in the background. Wait for
        # the original click to finish, then let a worker replay a real click in
        # each window without blocking the global hook.
        if message_id in {
            WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP, WM_XBUTTONUP,
            WM_MOUSEWHEEL, WM_MOUSEHWHEEL,
        }:
            self.broadcast_actions.put(
                BroadcastMouseAction(
                    source=source,
                    targets=tuple(target_handles),
                    ratio_x=ratio_x,
                    ratio_y=ratio_y,
                    message_id=message_id,
                    mouse_data=mouse_data,
                )
            )

    def refresh_cells(self) -> None:
        for cell in self.cells:
            cell.refresh(cell.player.handle is not None and cell.player.handle == self.active_handle)

    def synchronize_active_player(
        self, foreground: int, *, force_refresh: bool = False
    ) -> bool:
        """Synchronize selection with the foreground Dofus window."""
        matching_index = next(
            (
                index
                for index, player in enumerate(self.players)
                if player.handle is not None and player.handle == foreground
            ),
            None,
        )
        if matching_index is None:
            return False
        changed = self.active_handle != foreground or self.selected_index != matching_index
        self.active_handle = foreground
        self.selected_index = matching_index
        if changed or force_refresh:
            self.refresh_cells()
        return True

    def check_for_updates_async(self) -> None:
        """Check GitHub in the background without delaying application startup."""
        if self.update_check_started or not getattr(sys, "frozen", False):
            return
        self.update_check_started = True

        def worker() -> None:
            try:
                release = fetch_latest_release()
                if is_newer_release(APP_VERSION, release):
                    self.update_events.put(("available", release))
            except Exception:
                # A failed network check must never prevent local use.
                return

        threading.Thread(target=worker, daemon=True, name="update-check").start()

    def show_update_dialog(self, release: ReleaseInfo) -> None:
        if self.update_dialog is not None and self.update_dialog.winfo_exists():
            return
        dialog = tk.Toplevel(self.root)
        self.update_dialog = dialog
        dialog.overrideredirect(True)
        dialog.configure(bg=BG)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        width, height = 320, 150
        work_area = monitor_work_area(self.root.winfo_id())
        if work_area is None:
            left, top, right, bottom = (
                0,
                0,
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )
        else:
            left, top, right, bottom = work_area
        x = min(max(self.root.winfo_x() + 35, left), max(left, right - width))
        y = min(max(self.root.winfo_y() + 35, top), max(top, bottom - height))
        dialog.geometry(f"{width}x{height}{x:+d}{y:+d}")

        tk.Label(
            dialog,
            text=self.t("update_available"),
            bg=PANEL_HOVER,
            fg=TEXT,
            font=("Segoe UI Semibold", 9),
            padx=12,
            pady=8,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            dialog,
            text=self.t("update_message", version=release.version),
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 8),
            wraplength=292,
            justify="left",
            padx=14,
            pady=12,
        ).pack(fill="x")

        actions = tk.Frame(dialog, bg=BG)
        actions.pack(fill="x", padx=12, pady=(0, 11))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        def dismiss() -> None:
            dialog.destroy()
            self.update_dialog = None

        def install() -> None:
            dismiss()
            self.set_status(self.t("update_downloading"), GOLD)

            def update_worker() -> None:
                try:
                    launch_update(release)
                    self.update_events.put(("launched", release.version))
                except Exception as error:
                    self.update_events.put(("error", str(error)))

            threading.Thread(
                target=update_worker, daemon=True, name="update-download"
            ).start()

        update_button = RoundedSettingsButton(
            actions,
            text=self.t("update_now"),
            command=install,
            fill=LIME_DARK,
            hover_fill="#8da329",
            outline="#5f7118",
        )
        update_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        later_button = RoundedSettingsButton(
            actions,
            text=self.t("update_later"),
            command=dismiss,
            fill=CELL_FILL,
            hover_fill=CELL_HOVER,
            outline=CELL_BORDER,
        )
        later_button.grid(row=0, column=1, padx=(4, 0), sticky="ew")
        dialog.after_idle(lambda: apply_rounded_window(dialog, 6))

    def poll_updates(self) -> None:
        try:
            while True:
                event, payload = self.update_events.get_nowait()
                if event == "available" and isinstance(payload, ReleaseInfo):
                    self.show_update_dialog(payload)
                elif event == "launched":
                    self.close()
                    return
                elif event == "error":
                    self.set_status(self.t("update_failed", error=payload), RED)
        except queue.Empty:
            pass

    def set_status(
        self,
        text: str,
        color: str = MUTED,
        *,
        persistent: bool = False,
    ) -> None:
        if self.status_popup is None or not self.status_popup.winfo_exists():
            self.status_popup = tk.Toplevel(self.root)
            self.status_popup.overrideredirect(True)
            self.status_popup.attributes("-topmost", True)
            self.status_popup.attributes("-alpha", 0.94)
            self.status_text = tk.Label(
                self.status_popup, bg=BG_DEEP, fg=color, padx=7, pady=4,
                font=("Segoe UI Semibold", 7), relief="solid", bd=1,
            )
            self.status_text.pack()
        self.status_text.configure(text=text[:72].upper(), fg=color)
        self.status_popup.update_idletasks()
        x = self.root.winfo_x() + self.root.winfo_width() + 5
        y = self.root.winfo_y() + 6
        self.status_popup.geometry(f"+{x}+{y}")
        self.status_popup.deiconify()
        if self.status_after_id:
            self.root.after_cancel(self.status_after_id)
            self.status_after_id = None
        if not persistent:
            self.status_after_id = self.root.after(2400, self.status_popup.withdraw)

    def set_workflow_status(self, text: str, color: str = MUTED) -> None:
        self.set_status(
            f"{text[:48]}\n{self.t('stop_hint')}",
            color,
            persistent=True,
        )

    def run_workflow(self) -> None:
        if self.workflow is not None and self.workflow.poll() is None:
            self.set_workflow_status(self.t("action_running"), GOLD)
            return
        self.workflow_cancel_requested = False
        self.set_workflow_status(self.t("starting"), GOLD)
        workflow_arguments = [
            "--output", str(PLAYERS_PATH),
            "--assets-dir", str(ASSETS_DIR),
            "--diagnostics-dir", str(DATA_DIR / "character-diagnostics"),
            "--leader", str(self.config_data.get("leader", DEFAULT_CONFIG["leader"])),
        ]
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--workflow", *workflow_arguments]
        else:
            command = [sys.executable, str(WORKFLOW_PATH), *workflow_arguments]
        self.workflow = subprocess.Popen(
            command,
            cwd=str(DATA_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        process = self.workflow

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                self.output_queue.put(line.strip())
            # Waiting here avoids the small EOF/poll race that could display an
            # error even though the workflow had actually exited successfully.
            self.output_queue.put(workflow_done_marker(process.wait()))

        threading.Thread(target=read_output, daemon=True).start()

    def stop_workflow(self) -> bool:
        """Stop the active automation child process without closing the panel."""
        process = self.workflow
        if process is None or process.poll() is not None:
            return False
        self.workflow_cancel_requested = True
        append_panel_diagnostic("workflow_cancel_requested", pid=process.pid)
        self.set_workflow_status(self.t("stopping"), GOLD)
        try:
            process.terminate()
        except OSError as error:
            append_panel_diagnostic(
                "workflow_cancel_error",
                error=f"{type(error).__name__}: {error}",
            )
            return False
        return True

    def open_settings(self) -> None:
        dialog_width = 318
        existing_dialog = self.settings_dialog
        if existing_dialog is not None:
            try:
                if existing_dialog.winfo_exists():
                    existing_area = monitor_work_area(existing_dialog.winfo_id())
                    if existing_area is None:
                        existing_area = (
                            0,
                            0,
                            self.root.winfo_screenwidth(),
                            self.root.winfo_screenheight(),
                        )
                    reveal_dialog(
                        existing_dialog, dialog_width, existing_area, self.root,
                    )
                    return
            except tk.TclError:
                pass
            self.settings_dialog = None
        dialog_height = 528
        original_opacity = float(self.root.attributes("-alpha"))
        original_ui_scale = self.ui_scale()
        desired_x = self.root.winfo_x() + 35
        desired_y = self.root.winfo_y() + 35
        work_area = monitor_work_area(self.root.winfo_id())
        if work_area is None:
            left, top = 0, 0
            right = self.root.winfo_screenwidth()
            bottom = self.root.winfo_screenheight()
        else:
            left, top, right, bottom = work_area
        dialog_work_area = (left, top, right, bottom)
        dialog_x, dialog_y = clamp_window_origin(
            desired_x,
            desired_y,
            dialog_width,
            dialog_height,
            dialog_work_area,
        )

        dialog = tk.Toplevel(self.root)
        self.settings_dialog = dialog
        dialog.overrideredirect(True)
        dialog.configure(bg=BG)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.geometry(
            f"{dialog_width}x{dialog_height}{dialog_x:+d}{dialog_y:+d}"
        )
        dialog.bind(
            "<Destroy>",
            lambda event: self.settings_dialog_destroyed(event, dialog),
        )
        dialog.grid_columnconfigure(0, minsize=126)
        dialog.grid_columnconfigure(1, weight=1)

        header = tk.Frame(
            dialog, bg=PANEL_HOVER, height=30, cursor="fleur",
            highlightbackground=CELL_BORDER, highlightthickness=1,
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        title_label = tk.Label(
            header,
            text=f"⚙  {self.t('settings')} · v{APP_VERSION}",
            bg=PANEL_HOVER,
            fg=TEXT,
            font=("Segoe UI Semibold", 8), padx=10,
            cursor="fleur",
        )
        title_label.pack(side="left", fill="y")
        close_settings = tk.Button(
            header, text="−", bg=PANEL_HOVER, fg=TEXT,
            activebackground=CELL_HOVER, activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI Semibold", 12), cursor="hand2",
        )
        close_settings.pack(side="right", fill="y", ipadx=7)
        bind_dialog_drag(dialog, (header, title_label), dialog_work_area)
        configure_settings_style(dialog)

        variables = SettingsVariables.from_panel(dialog, self)
        fields = [
            (1, self.t("layout"), variables.orientation, ["vertical", "horizontal"]),
            (2, self.t("language"), variables.language, list(LANGUAGE_LABELS.values())),
            (
                6,
                self.t("group_leader"),
                variables.leader,
                [player.pseudo for player in self.players],
            ),
        ]
        for row, label, variable, values in fields:
            label_container = tk.Frame(dialog, bg=BG)
            label_container.grid(
                row=row, column=0, padx=(12, 7), pady=7, sticky="w"
            )
            tk.Label(
                label_container, text=label.upper(), bg=BG, fg=MUTED,
                font=("Segoe UI Semibold", 8),
            ).pack(side="left")
            if row == 6:
                DofusInfoTip(
                    label_container,
                    self.t("group_leader_info"),
                ).pack(side="left", padx=(3, 0))
            DofusComboBox(
                dialog, variable=variable, values=list(values),
            ).grid(row=row, column=1, padx=(5, 12), pady=7, sticky="ew")

        capture = SettingsInputCapture(self, dialog)

        def cancel_settings() -> None:
            if capture.active:
                capture.finish()
            scale_changed = abs(self.ui_scale() - original_ui_scale) > 0.001
            self.root.attributes("-alpha", original_opacity)
            self.config_data["ui_scale"] = original_ui_scale
            if dialog.winfo_exists():
                dialog.destroy()
            if scale_changed:
                self.build()
            else:
                self.root.after(250, self.refresh_settings_hitbox)

        close_settings.configure(command=cancel_settings)

        def capture_key(event: tk.Event) -> str | None:
            if capture.active:
                return "break"
            if str(event.keysym).upper() == "ESCAPE":
                cancel_settings()
                return "break"
            return None

        dialog.bind("<KeyPress>", capture_key)

        for row, label, variable in (
            (3, self.t("previous_key"), variables.previous),
            (4, self.t("next_key"), variables.following),
            (5, self.t("replication_mode"), variables.broadcast),
        ):
            tk.Label(
                dialog, text=label.upper(), bg=BG, fg=MUTED,
                font=("Segoe UI Semibold", 8),
            ).grid(
                row=row, column=0, padx=(12, 7), pady=7, sticky="w"
            )
            button = RoundedSettingsButton(
                dialog, text=self.display_input_name(variable.get()), fill=CELL_FILL,
                hover_fill=CELL_HOVER, outline=CELL_BORDER,
            )
            button.command = lambda item=variable, target=button: capture.begin(item, target)
            button.grid(row=row, column=1, padx=(5, 12), pady=7, sticky="ew")

        tk.Label(
            dialog, text=self.t("lock"), bg=BG, fg=MUTED,
            font=("Segoe UI Semibold", 8),
        ).grid(row=7, column=0, padx=(12, 7), pady=7, sticky="w")

        lock_options = tk.Frame(dialog, bg=BG)
        lock_options.grid(row=7, column=1, padx=(5, 12), pady=7, sticky="ew")
        lock_options.grid_columnconfigure(0, weight=1)
        lock_options.grid_columnconfigure(1, weight=1)
        for column, text, variable in (
            (0, self.t("position"), variables.position_locked),
            (1, self.t("icons"), variables.drag_cells_locked),
        ):
            DofusCheckBox(
                lock_options, text=text, variable=variable,
            ).grid(row=0, column=column, sticky="w")

        tk.Label(
            dialog, text=self.t("play_button"), bg=BG, fg=MUTED,
            font=("Segoe UI Semibold", 8),
        ).grid(row=8, column=0, padx=(12, 7), pady=7, sticky="w")
        DofusCheckBox(
            dialog, text=self.t("enabled"), variable=variables.play_button_enabled,
        ).grid(row=8, column=1, padx=(5, 12), pady=7, sticky="w")

        tk.Label(
            dialog, text=self.t("scale"), bg=BG, fg=MUTED,
            font=("Segoe UI Semibold", 8),
        ).grid(row=9, column=0, padx=(12, 7), pady=7, sticky="w")

        def preview_scale(value: str) -> None:
            self.config_data["ui_scale"] = min(1.50, max(0.70, float(value)))
            self.build()

        DofusSlider(
            dialog, from_=0.70, to=1.50, resolution=0.05,
            variable=variables.ui_scale, command=preview_scale,
        ).grid(row=9, column=1, padx=(5, 12), pady=3, sticky="ew")

        tk.Label(
            dialog, text=self.t("opacity"), bg=BG, fg=MUTED,
            font=("Segoe UI Semibold", 8),
        ).grid(
            row=10, column=0, padx=(12, 7), pady=7, sticky="w"
        )
        def preview_opacity(value: str) -> None:
            alpha = min(1.0, max(0.40, float(value)))
            self.root.attributes("-alpha", alpha)
            dialog.attributes("-alpha", alpha)

        DofusSlider(
            dialog, from_=0.40, to=1.0, resolution=0.01,
            variable=variables.opacity, command=preview_opacity,
        ).grid(row=10, column=1, padx=(5, 12), pady=3, sticky="ew")

        def apply_settings() -> None:
            if capture.active:
                capture.finish()
            self.config_data.update(variables.config_updates())
            save_json(CONFIG_PATH, self.config_data)
            self.root.attributes("-alpha", float(variables.opacity.get()))
            dialog.destroy()
            self.build()
            self.restart_tray_icon()

        save_button = RoundedSettingsButton(
            dialog, text=self.t("save"), command=apply_settings,
            fill=LIME_DARK, hover_fill="#8da329", outline="#5f7118",
            foreground=TEXT,
        )
        save_button.grid(
            row=11, column=0, columnspan=2, padx=12, pady=(9, 5),
            ipady=3, sticky="ew",
        )

        action_row = tk.Frame(dialog, bg=BG)
        action_row.grid(row=12, column=0, columnspan=2, padx=12, pady=(2, 4), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)

        def minimize_from_settings() -> None:
            cancel_settings()
            self.minimize_app()

        minimize_button = RoundedSettingsButton(
            action_row, text=self.t("minimize_app"), command=minimize_from_settings,
            fill=PANEL_HOVER, hover_fill=CELL_HOVER, outline=CELL_BORDER,
        )
        minimize_button.grid(row=0, column=0, padx=(0, 3), ipady=3, sticky="ew")
        quit_button = RoundedSettingsButton(
            action_row, text=self.t("quit_app"), command=self.close,
            fill="#6d3d43", hover_fill=RED, outline="#8b4c52",
        )
        quit_button.grid(row=0, column=1, padx=(3, 0), ipady=3, sticky="ew")
        dialog.after_idle(
            lambda: reveal_dialog(
                dialog, dialog_width, dialog_work_area, self.root,
            )
        )
        dialog.after(
            100,
            lambda: reveal_dialog(
                dialog, dialog_width, dialog_work_area, self.root,
            ),
        )

    def request_open_settings(self, source: str) -> None:
        append_panel_diagnostic(
            "settings_requested",
            source=source,
            dialog=bool(self.settings_dialog),
            hitbox=self.settings_hitbox,
        )
        try:
            self.open_settings()
            append_panel_diagnostic("settings_opened", source=source)
        except Exception as error:
            append_panel_diagnostic(
                "settings_error",
                source=source,
                error=f"{type(error).__name__}: {error}",
            )
            self.set_status(f"PARAMÈTRES · {type(error).__name__}", RED)

    def settings_dialog_destroyed(self, event: tk.Event, dialog: tk.Toplevel) -> None:
        if event.widget is not dialog:
            return
        self.settings_dialog = None
        append_panel_diagnostic("settings_closed")

    def start_input_listener(self) -> None:
        self.stop_input_listener()
        ready = threading.Event()

        def worker() -> None:
            self.hotkey_thread_id = int(kernel32.GetCurrentThreadId())
            held_keys: set[int] = set()
            suppressed_keys: set[int] = set()
            mouse_button_state = 0
            last_mouse_move_at = 0.0
            settings_press_origin: tuple[int, int] | None = None
            settings_press_hitbox: tuple[int, int, int, int] | None = None
            settings_press_moved = False

            def emit_input(name: str) -> None:
                self.hotkey_events.put(("input", (name, time.monotonic())))

            @HOOKPROC
            def keyboard_hook_proc(
                code: int, message: wintypes.WPARAM, data_pointer: wintypes.LPARAM
            ) -> int:
                try:
                    if code == HC_ACTION:
                        data = ctypes.cast(
                            data_pointer, ctypes.POINTER(KBDLLHOOKSTRUCT)
                        ).contents
                        if int(data.flags) & LLKHF_INJECTED:
                            return int(
                                user32.CallNextHookEx(None, code, message, data_pointer)
                            )
                        vk_code = int(data.vkCode)
                        message_id = int(message)
                        name = keyboard_input_name(vk_code)
                        active_modifiers = tuple(
                            modifier for modifier in MODIFIER_KEYS
                            if modifier in held_keys and modifier != vk_code
                        )
                        emergency_stop = (
                            message_id in (WM_KEYDOWN, WM_SYSKEYDOWN)
                            and is_emergency_stop_hotkey(vk_code, held_keys)
                        )
                        if emergency_stop:
                            suppressed_keys.add(vk_code)
                            self.hotkey_events.put(("stop_workflow", None))
                        if vk_code not in suppressed_keys:
                            self.mirror_keyboard_event(
                                name, vk_code, int(data.scanCode), int(data.flags),
                                message_id, active_modifiers,
                            )
                        if message_id in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            if vk_code not in held_keys:
                                held_keys.add(vk_code)
                                if not emergency_stop:
                                    emit_input(name)
                        elif message_id in (WM_KEYUP, WM_SYSKEYUP):
                            held_keys.discard(vk_code)
                            suppressed_keys.discard(vk_code)
                except Exception:
                    pass
                return int(user32.CallNextHookEx(None, code, message, data_pointer))

            @HOOKPROC
            def mouse_hook_proc(
                code: int, message: wintypes.WPARAM, data_pointer: wintypes.LPARAM
            ) -> int:
                nonlocal mouse_button_state, last_mouse_move_at
                nonlocal settings_press_origin, settings_press_hitbox
                nonlocal settings_press_moved
                try:
                    if code == HC_ACTION:
                        message_id = int(message)
                        input_name: str | None = None
                        data = ctypes.cast(
                            data_pointer, ctypes.POINTER(MSLLHOOKSTRUCT)
                        ).contents
                        if int(data.flags) & LLMHF_INJECTED:
                            return int(
                                user32.CallNextHookEx(None, code, message, data_pointer)
                            )
                        point = (int(data.pt.x), int(data.pt.y))
                        if message_id == WM_LBUTTONDOWN:
                            mouse_button_state |= MK_LBUTTON
                            input_name = "SOURIS GAUCHE"
                            emit_input(input_name)
                            if point_in_rectangle(point, self.settings_hitbox):
                                settings_press_origin = point
                                settings_press_hitbox = self.settings_hitbox
                                settings_press_moved = False
                            else:
                                settings_press_origin = None
                                settings_press_hitbox = None
                                settings_press_moved = False
                        elif message_id == WM_LBUTTONUP:
                            if (
                                settings_press_origin is not None
                                and not settings_press_moved
                                and point_in_rectangle(point, settings_press_hitbox)
                            ):
                                self.hotkey_events.put(
                                    (
                                        "open_settings",
                                        (point, settings_press_hitbox),
                                    )
                                )
                            settings_press_origin = None
                            settings_press_hitbox = None
                            settings_press_moved = False
                            mouse_button_state &= ~MK_LBUTTON
                            input_name = "SOURIS GAUCHE"
                        elif message_id == WM_MOUSEMOVE:
                            if settings_press_origin is not None:
                                distance = max(
                                    abs(point[0] - settings_press_origin[0]),
                                    abs(point[1] - settings_press_origin[1]),
                                )
                                if distance >= CLICK_DRAG_THRESHOLD:
                                    settings_press_moved = True
                        elif message_id == WM_RBUTTONDOWN:
                            mouse_button_state |= MK_RBUTTON
                            input_name = "SOURIS DROITE"
                            emit_input(input_name)
                        elif message_id == WM_RBUTTONUP:
                            mouse_button_state &= ~MK_RBUTTON
                            input_name = "SOURIS DROITE"
                        elif message_id == WM_MBUTTONDOWN:
                            mouse_button_state |= MK_MBUTTON
                            input_name = "SOURIS MILIEU"
                            emit_input(input_name)
                        elif message_id == WM_MBUTTONUP:
                            mouse_button_state &= ~MK_MBUTTON
                            input_name = "SOURIS MILIEU"
                        elif message_id == WM_XBUTTONDOWN:
                            button = (int(data.mouseData) >> 16) & 0xFFFF
                            mouse_button_state |= MK_XBUTTON1 if button == 1 else MK_XBUTTON2
                            input_name = "SOURIS 4" if button == 1 else "SOURIS 5"
                            emit_input(input_name)
                        elif message_id == WM_XBUTTONUP:
                            button = (int(data.mouseData) >> 16) & 0xFFFF
                            mouse_button_state &= ~(MK_XBUTTON1 if button == 1 else MK_XBUTTON2)
                            input_name = "SOURIS 4" if button == 1 else "SOURIS 5"
                        elif message_id == WM_MOUSEWHEEL:
                            delta = ctypes.c_short((int(data.mouseData) >> 16) & 0xFFFF).value
                            input_name = "MOLETTE HAUT" if delta > 0 else "MOLETTE BAS"
                            emit_input(input_name)
                        elif message_id == WM_MOUSEHWHEEL:
                            delta = ctypes.c_short((int(data.mouseData) >> 16) & 0xFFFF).value
                            input_name = "MOLETTE DROITE" if delta > 0 else "MOLETTE GAUCHE"
                            emit_input(input_name)
                        supported_messages = {
                            WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP,
                            WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN,
                            WM_MBUTTONUP, WM_XBUTTONDOWN, WM_XBUTTONUP,
                            WM_MOUSEWHEEL, WM_MOUSEHWHEEL,
                        }
                        should_mirror = message_id in supported_messages and message_id != WM_MOUSEMOVE
                        if message_id == WM_MOUSEMOVE:
                            now = time.monotonic()
                            should_mirror = now - last_mouse_move_at >= 0.008
                            if should_mirror:
                                last_mouse_move_at = now
                        if should_mirror:
                            self.mirror_mouse_event(
                                input_name, message_id, int(data.pt.x), int(data.pt.y),
                                int(data.mouseData), mouse_button_state,
                            )
                except Exception:
                    pass
                return int(user32.CallNextHookEx(None, code, message, data_pointer))

            module_handle = kernel32.GetModuleHandleW(None)
            keyboard_hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, keyboard_hook_proc, module_handle, 0
            )
            mouse_hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL, mouse_hook_proc, module_handle, 0
            )
            if not keyboard_hook or not mouse_hook:
                missing = []
                if not keyboard_hook:
                    missing.append("CLAVIER")
                if not mouse_hook:
                    missing.append("SOURIS")
                self.hotkey_events.put(("error", missing))
            ready.set()
            message = MSG()
            try:
                while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                    pass
            finally:
                if keyboard_hook:
                    user32.UnhookWindowsHookEx(keyboard_hook)
                if mouse_hook:
                    user32.UnhookWindowsHookEx(mouse_hook)

        self.hotkey_thread = threading.Thread(target=worker, daemon=True, name="dofus-inputs")
        self.hotkey_thread.start()
        ready.wait(0.5)

    def stop_input_listener(self) -> None:
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, WM_QUIT, 0, 0)
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            self.hotkey_thread.join(0.4)
        self.hotkey_thread = None
        self.hotkey_thread_id = 0

    def poll_inputs(self) -> None:
        try:
            while True:
                event, payload = self.hotkey_events.get_nowait()
                if event == "stop_workflow":
                    self.stop_workflow()
                elif event == "open_settings":
                    point, hitbox = payload if payload else (None, None)
                    append_panel_diagnostic(
                        "settings_hook_hit", point=point, hitbox=hitbox,
                    )
                    self.request_open_settings("mouse_hook")
                elif event == "input":
                    name, occurred_at = payload
                    if self.capture_input_handler is not None:
                        if float(occurred_at) >= self.capture_started_at:
                            self.capture_input_handler(str(name))
                        continue
                    if float(occurred_at) < self.input_suppressed_until:
                        continue
                    if str(name) == str(self.config_data["broadcast_key"]):
                        self.set_broadcast_enabled(not self.broadcast_enabled)
                    elif str(name) == str(self.config_data["previous_key"]):
                        self.navigate(-1)
                    elif str(name) == str(self.config_data["next_key"]):
                        self.navigate(1)
                elif event == "error":
                    devices = ", ".join(
                        self.display_input_name(str(device)) for device in payload
                    )
                    self.set_status(
                        self.t("listener_unavailable", devices=devices), RED
                    )
                elif event == "broadcast_error":
                    self.set_status(self.t("replication_error", error=payload), RED)
        except queue.Empty:
            pass

    def poll(self) -> None:
        self.poll_inputs()
        self.poll_updates()
        foreground = int(user32.GetForegroundWindow() or 0)
        if (
            self.pending_activation_handle is None
            and not self.broadcast_replay_active.is_set()
            and foreground != self.active_handle
        ):
            self.synchronize_active_player(foreground)

        now = time.monotonic()
        if now >= self.next_window_resolve:
            previous_handles = [player.handle for player in self.players]
            self.resolve_windows()
            self.next_window_resolve = now + 1.0
            if previous_handles != [player.handle for player in self.players]:
                self.refresh_cells()

        try:
            mtime = PLAYERS_PATH.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime and mtime != self.players_mtime:
            self.players_mtime = mtime
            self.build()

        try:
            while True:
                line = self.output_queue.get_nowait()
                exit_code = parse_workflow_done_marker(line)
                if exit_code is not None:
                    cancelled = self.workflow_cancel_requested
                    self.workflow_cancel_requested = False
                    self.workflow = None
                    if cancelled:
                        self.set_status(self.t("cancelled"), GOLD)
                    else:
                        self.set_status(
                            self.t("done") if exit_code == 0 else self.t("error"),
                            LIME if exit_code == 0 else RED,
                        )
                    self.build()
                elif line:
                    self.set_workflow_status(line)
        except queue.Empty:
            pass

        self.root.after(80, self.poll)

    def start_tray_icon(self) -> None:
        """Expose show, minimize, and quit actions from the Windows tray."""
        if self.tray_icon is not None or not APP_ICON_PATH.is_file():
            return
        try:
            image = Image.open(APP_ICON_PATH).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem(
                    self.t("show_app"),
                    lambda _icon, _item: self.root.after(0, self.restore_app),
                    default=True,
                ),
                pystray.MenuItem(
                    self.t("minimize_app"),
                    lambda _icon, _item: self.root.after(0, self.minimize_app),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    self.t("quit_app"),
                    lambda _icon, _item: self.root.after(0, self.close),
                ),
            )
            self.tray_icon = pystray.Icon(
                "dofus-multicompte-enhancer",
                image,
                "Dofus MultiCompte Enhancer",
                menu,
            )
            self.tray_thread = threading.Thread(
                target=self.tray_icon.run,
                name="dofus-panel-tray",
                daemon=True,
            )
            self.tray_thread.start()
        except Exception:
            # The panel remains usable if Explorer temporarily refuses tray icons.
            self.tray_icon = None
            self.tray_thread = None

    def stop_tray_icon(self) -> None:
        icon = self.tray_icon
        self.tray_icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    def restart_tray_icon(self) -> None:
        self.stop_tray_icon()
        self.start_tray_icon()

    def minimize_app(self) -> None:
        """Hide the borderless panel while keeping its tray controls available."""
        if self.closing:
            return
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.withdraw()
        self.settings_hitbox = None
        self.root.withdraw()

    def restore_app(self) -> None:
        """Restore the panel and its taskbar presence from the tray menu."""
        if self.closing:
            return
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.refresh_settings_hitbox)
        self.root.after_idle(lambda: expose_root_in_taskbar(self.root))

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            self.stop_tray_icon()
            self.stop_input_listener()
            self.broadcast_stop.set()
            self.broadcast_actions.put(None)
            if self.broadcast_thread and self.broadcast_thread.is_alive():
                self.broadcast_thread.join(0.5)
            self.config_data["x"] = self.root.winfo_x()
            self.config_data["y"] = self.root.winfo_y()
            save_json(CONFIG_PATH, self.config_data)
        finally:
            # Destruction remains guaranteed even if a Windows hook or config
            # save fails during shutdown.
            try:
                self.root.destroy()
            except tk.TclError:
                pass


def main() -> int:
    if "--workflow" in sys.argv:
        sys.argv.remove("--workflow")
        from dofus_character_login import main as workflow_main

        return workflow_main()
    root = tk.Tk()
    panel = DofusPanel(root)
    if "--settings" in sys.argv:
        root.after(250, panel.open_settings)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
