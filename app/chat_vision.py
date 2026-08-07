"""Visually detect the chat input and type a command into it.

For safety, Enter is pressed only when --send is provided. Moving the pointer
to a screen corner triggers the PyAutoGUI fail-safe.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes

import cv2
import mss
import numpy as np

__all__ = [
    "Detection",
    "CommandResult",
    "activate_window",
    "capture_window",
    "click_screen",
    "detect_chat_bar",
    "execute_chat_command",
    "execute_chat_command_on_window",
    "execute_chat_commands_on_window",
    "find_unique_window",
    "get_client_geometry",
    "list_matching_windows",
    "list_windows_by_executable",
]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
SW_RESTORE = 9
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


try:
    # Use physical coordinates on displays with scaling enabled.
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    user32.SetProcessDPIAware()


@dataclass(frozen=True)
class Detection:
    anchor_x: int
    anchor_y: int
    click_x: int
    click_y: int
    confidence: float


@dataclass(frozen=True)
class CommandResult:
    """Structured result returned by execute_chat_command."""

    window_title: str
    detection: Detection
    command: str
    submitted: bool
    dry_run: bool


def detect_chat_bar(image_bgr: np.ndarray) -> Detection | None:
    """Locate the status light and validate the dark input bar to its left."""
    height, width = image_bgr.shape[:2]
    x0, x1 = int(width * 0.08), int(width * 0.30)
    y0 = max(0, height - int(height * 0.06))
    roi = image_bgr[y0:height, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # The indicator may be green, orange, or red depending on chat state. Its
    # stable properties are its small size and high saturation; the dark bar to
    # the left then filters out unrelated colored UI pixels.
    mask = cv2.inRange(hsv, np.array([0, 90, 110]), np.array([179, 255, 255]))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=4)

    candidates: list[tuple[float, Detection]] = []
    for index in range(1, count):
        _, _, component_width, component_height, area = stats[index]
        if not (15 <= area <= 180):
            continue
        if not (4 <= component_width <= 18 and 4 <= component_height <= 18):
            continue

        center_x = int(round(x0 + centroids[index][0]))
        center_y = int(round(y0 + centroids[index][1]))
        if center_y < height - 35:
            continue

        bar_left = max(0, int(center_x * 0.05))
        bar_right = max(bar_left + 1, center_x - 12)
        bar_top = max(0, center_y - 7)
        bar_bottom = min(height, center_y + 8)
        bar = image_bgr[bar_top:bar_bottom:2, bar_left:bar_right:4]
        if bar.size == 0:
            continue

        brightness = bar.mean(axis=2)
        dark_ratio = float(np.mean(brightness < 85))
        if dark_ratio < 0.55:
            continue

        area_score = max(0.0, 1.0 - abs(int(area) - 52) / 100.0)
        confidence = min(1.0, dark_ratio * 0.8 + area_score * 0.2)
        click_x = max(20, int(center_x * 0.48))
        detection = Detection(center_x, center_y, click_x, center_y, confidence)
        candidates.append((confidence, detection))

    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def list_matching_windows(title_prefix: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if title.casefold().startswith(title_prefix.casefold()):
            matches.append((int(hwnd), title))
        return True

    callback_ref = callback_type(callback)
    if not user32.EnumWindows(callback_ref, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return matches


def find_unique_window(title_prefix: str) -> tuple[int, str]:
    matches = list_matching_windows(title_prefix)
    if not matches:
        raise RuntimeError(f"No window title starts with {title_prefix!r}.")
    if len(matches) != 1:
        titles = "\n  - ".join(title for _, title in matches)
        raise RuntimeError(
            f"Multiple window titles start with {title_prefix!r}:\n  - {titles}"
        )
    return matches[0]


def get_window_process_path(hwnd: int) -> Path | None:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return None
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
    if not process:
        return None
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(capacity)):
            return None
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(process)


def list_windows_by_executable(executable_name: str) -> list[tuple[int, str]]:
    """Return large visible windows owned by an executable."""
    matches: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        path = get_window_process_path(int(hwnd))
        if path is None or path.name.casefold() != executable_name.casefold():
            return True
        rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        if rect.right - rect.left < 400 or rect.bottom - rect.top < 300:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        if length:
            user32.GetWindowTextW(hwnd, buffer, length + 1)
        matches.append((int(hwnd), buffer.value))
        return True

    callback_ref = callback_type(callback)
    if not user32.EnumWindows(callback_ref, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return sorted(matches, key=lambda item: item[0])


def activate_window(hwnd: int) -> None:
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached_threads: list[int] = []
    for thread_id in {target_thread, foreground_thread}:
        if thread_id and thread_id != current_thread:
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)

    deadline = time.monotonic() + 3.0
    while user32.GetForegroundWindow() != hwnd and time.monotonic() < deadline:
        time.sleep(0.05)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("Windows refused to bring the Dofus window to the foreground.")


def escape_pressed() -> bool:
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def send_inputs(*events: INPUT) -> None:
    array_type = INPUT * len(events)
    event_array = array_type(*events)
    sent = user32.SendInput(len(events), event_array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


def keyboard_event(virtual_key: int, key_up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else 0
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(virtual_key, 0, flags, 0, 0))


def unicode_events(text: str) -> list[INPUT]:
    events: list[INPUT] = []
    encoded = text.encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[offset : offset + 2], "little")
        events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0)))
        events.append(
            INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0),
            )
        )
    return events


def click_and_type(screen_x: int, screen_y: int, text: str, send: bool) -> None:
    click_screen(screen_x, screen_y)
    time.sleep(0.15)
    if escape_pressed():
        raise RuntimeError("Action cancelled with Escape after the click.")
    send_inputs(
        keyboard_event(VK_CONTROL),
        keyboard_event(ord("A")),
        keyboard_event(ord("A"), key_up=True),
        keyboard_event(VK_CONTROL, key_up=True),
    )
    send_inputs(*unicode_events(text))
    if send:
        send_inputs(keyboard_event(VK_RETURN), keyboard_event(VK_RETURN, key_up=True))


def click_screen(screen_x: int, screen_y: int) -> None:
    """Click physical screen coordinates, with Escape as an emergency stop."""
    if escape_pressed():
        raise RuntimeError("Action cancelled: Escape is being held.")
    if not user32.SetCursorPos(screen_x, screen_y):
        raise ctypes.WinError(ctypes.get_last_error())
    send_inputs(
        INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)),
        INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)),
    )


def get_client_geometry(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    origin = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 400 or height < 300:
        raise RuntimeError(f"Dofus client area is too small: {width}×{height}.")
    return origin.x, origin.y, width, height


def capture_window(
    hwnd: int,
    *,
    settle_delay: float = 0.20,
) -> tuple[np.ndarray, int, int]:
    activate_window(hwnd)
    # Selection scans use a shorter delay for rapid window-to-window clicks;
    # ordinary visual detection retains the safer 200 ms default.
    time.sleep(max(0.0, settle_delay))
    left, top, width, height = get_client_geometry(hwnd)
    with mss.MSS() as screen:
        pixels = np.asarray(
            screen.grab({"left": left, "top": top, "width": width, "height": height})
        )
        return pixels[:, :, :3].copy(), left, top


def capture_primary_monitor() -> tuple[np.ndarray, int, int]:
    with mss.MSS() as screen:
        monitor = screen.monitors[1]
        pixels = np.asarray(screen.grab(monitor))
        return pixels[:, :, :3].copy(), monitor["left"], monitor["top"]


def save_diagnostic(image: np.ndarray, detection: Detection, destination: Path) -> None:
    diagnostic = image.copy()
    cv2.rectangle(
        diagnostic,
        (detection.anchor_x - 10, detection.anchor_y - 10),
        (detection.anchor_x + 10, detection.anchor_y + 10),
        (0, 255, 0),
        3,
    )
    cv2.circle(diagnostic, (detection.click_x, detection.click_y), 6, (0, 0, 255), -1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), diagnostic):
        raise RuntimeError(f"Impossible d'enregistrer {destination}")


def get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    if length:
        user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value or f"window {hwnd}"


def execute_chat_command_on_window(
    hwnd: int,
    command: str,
    *,
    submit: bool = False,
    dry_run: bool = False,
    delay: float = 0.0,
    wait_timeout: float = 0.0,
    poll_interval: float = 0.5,
    diagnostic_path: Path | None = None,
    after_path: Path | None = None,
) -> CommandResult:
    """Wait for chat in a known window, then execute a command in it."""
    return execute_chat_commands_on_window(
        hwnd,
        [command],
        submit=submit,
        dry_run=dry_run,
        delay=delay,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        diagnostic_path=diagnostic_path,
        after_path=after_path,
    )[0]


def execute_chat_commands_on_window(
    hwnd: int,
    commands: list[str],
    *,
    submit: bool = False,
    dry_run: bool = False,
    delay: float = 0.0,
    wait_timeout: float = 0.0,
    poll_interval: float = 0.5,
    command_interval: float = 0.12,
    diagnostic_path: Path | None = None,
    after_path: Path | None = None,
) -> list[CommandResult]:
    """Detect chat once, then submit several commands as a tight batch."""
    if not commands or any(not command for command in commands):
        raise ValueError("Commands cannot be empty.")

    deadline = time.monotonic() + max(0.0, wait_timeout)
    while True:
        image, _, _ = capture_window(hwnd)
        detection = detect_chat_bar(image)
        if detection is not None:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Chat input was not detected in {get_window_title(hwnd)!r}."
            )
        time.sleep(max(0.05, poll_interval))

    if diagnostic_path is not None:
        save_diagnostic(image, detection, diagnostic_path)

    if not dry_run:
        if delay > 0:
            time.sleep(delay)
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)
        for index, command in enumerate(commands):
            click_and_type(
                origin_x + detection.click_x,
                origin_y + detection.click_y,
                command,
                submit,
            )
            # Keep the interval short while still allowing the client to consume
            # Enter before the next command replaces the input contents.
            if submit and index < len(commands) - 1:
                time.sleep(max(0.04, command_interval))
        if submit:
            # Keep the leader focused long enough for the client to consume the
            # final Enter before another Dofus window is activated.
            time.sleep(0.20)
        if after_path is not None:
            time.sleep(0.25)
            after_image, _, _ = capture_window(hwnd)
            after_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(after_path), after_image):
                raise RuntimeError(f"Impossible d'enregistrer {after_path}")

    window_title = get_window_title(hwnd)
    return [
        CommandResult(
            window_title=window_title,
            detection=detection,
            command=command,
            submitted=submit and not dry_run,
            dry_run=dry_run,
        )
        for command in commands
    ]


def execute_chat_command(
    command: str,
    *,
    window_prefix: str = "Silvcra",
    submit: bool = False,
    dry_run: bool = False,
    delay: float = 0.5,
    diagnostic_path: Path | None = None,
    after_path: Path | None = None,
) -> CommandResult:
    """Detect a Dofus chat input and execute a command in it.

    Args:
        command: Text to type, for example ``/help``.
        window_prefix: Start of the target Dofus window title.
        submit: Press Enter after typing when true.
        dry_run: Perform detection only when true.
        delay: Safety delay between detection and action.
        diagnostic_path: Optional annotated screenshot before the action.
        after_path: Optional screenshot after the action.

    Returns:
        The exact window title, detection result, and submission state.

    Raises:
        RuntimeError: If the window is not unique or the chat input is missing.
    """
    if not command:
        raise ValueError("The command cannot be empty.")

    hwnd, window_title = find_unique_window(window_prefix)
    image, origin_x, origin_y = capture_window(hwnd)
    detection = detect_chat_bar(image)
    if detection is None:
        raise RuntimeError(f"Chat input was not detected in {window_title!r}.")

    if diagnostic_path is not None:
        save_diagnostic(image, detection, diagnostic_path)

    if not dry_run:
        if delay > 0:
            time.sleep(delay)
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)
        click_and_type(
            origin_x + detection.click_x,
            origin_y + detection.click_y,
            command,
            submit,
        )

        if after_path is not None:
            time.sleep(0.25)
            after_image, _, _ = capture_window(hwnd)
            after_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(after_path), after_image):
                raise RuntimeError(f"Impossible d'enregistrer {after_path}")

    return CommandResult(
        window_title=window_title,
        detection=detection,
        command=command,
        submitted=submit and not dry_run,
        dry_run=dry_run,
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="/help", help="text to type")
    parser.add_argument("--send", action="store_true", help="press Enter after typing")
    parser.add_argument("--dry-run", action="store_true", help="detect without clicking or typing")
    parser.add_argument("--delay", type=float, default=2.0, help="delay before the real click")
    parser.add_argument("--image", type=Path, help="analyze a screenshot instead of the desktop")
    parser.add_argument("--screen", action="store_true", help="analyze the primary display instead of a window")
    parser.add_argument(
        "--window-prefix",
        default="Silvcra",
        help="exact start of the target window title (default: Silvcra)",
    )
    parser.add_argument("--diagnostic", type=Path, help="save the annotated image")
    parser.add_argument("--after", type=Path, help="save a screenshot after typing")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    # The normal path uses the reusable public API. The --image and --screen
    # modes remain independent diagnostic tools.
    if not args.image and not args.screen:
        try:
            result = execute_chat_command(
                args.text,
                window_prefix=args.window_prefix,
                submit=args.send,
                dry_run=args.dry_run,
                delay=args.delay,
                diagnostic_path=args.diagnostic,
                after_path=args.after,
            )
        except (RuntimeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 3

        detection = result.detection
        print(f"Selected window: {result.window_title}")
        print(
            f"Chat detected: indicator=({detection.anchor_x},{detection.anchor_y}), "
            f"clic=({detection.click_x},{detection.click_y}), "
            f"confiance={detection.confidence:.0%}"
        )
        if args.diagnostic:
            print(f"Diagnostic saved: {args.diagnostic}")
        if result.dry_run:
            print("Diagnostic mode: no mouse or keyboard action was performed.")
        elif result.submitted:
            print("Text typed and submitted.")
        else:
            print("Text typed without pressing Enter.")
        if args.after and not result.dry_run:
            print(f"Post-action screenshot: {args.after}")
        return 0

    hwnd: int | None = None
    window_title: str | None = None
    if args.image:
        image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
        if image is None:
            print(f"Image illisible : {args.image}", file=sys.stderr)
            return 2
        origin_x = origin_y = 0
        args.dry_run = True
    elif args.screen:
        image, origin_x, origin_y = capture_primary_monitor()

    detection = detect_chat_bar(image)
    if detection is None:
        print("Chat input was not detected.", file=sys.stderr)
        return 1

    print(
        f"Chat detected: indicator=({detection.anchor_x},{detection.anchor_y}), "
        f"clic=({detection.click_x},{detection.click_y}), "
        f"confiance={detection.confidence:.0%}"
    )
    if args.diagnostic:
        save_diagnostic(image, detection, args.diagnostic)
        print(f"Diagnostic saved: {args.diagnostic}")

    if args.dry_run:
        print("Diagnostic mode: no mouse or keyboard action was performed.")
        return 0

    if args.delay > 0:
        print(f"Saisie dans {args.delay:g} seconde(s)...")
        time.sleep(args.delay)

    # Bring the same window forward immediately before the action and recompute
    # its origin in case it moved after capture.
    if hwnd is not None:
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)

    click_and_type(
        origin_x + detection.click_x,
        origin_y + detection.click_y,
        args.text,
        args.send,
    )
    if args.send:
        print("Text typed and submitted.")
    else:
        print("Text typed without pressing Enter.")

    if args.after:
        time.sleep(0.25)
        if hwnd is not None:
            after_image, _, _ = capture_window(hwnd)
        else:
            after_image, _, _ = capture_primary_monitor()
        args.after.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.after), after_image):
            raise RuntimeError(f"Impossible d'enregistrer {args.after}")
        print(f"Post-action screenshot: {args.after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
