"""Process every Dofus window opened for the selected Ankama accounts.

The program first opens missing windows through Ankama Launcher, reads each
selected character name with local OCR, validates the PLAY button, and enters
the game. Character names and window handles are saved in players.json.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from rapidocr import RapidOCR

from ankama_launcher import DEFAULT_ASSETS, best_multiscale_match, launch_dofus
from chat_vision import (
    activate_window,
    capture_window,
    click_screen,
    execute_chat_commands_on_window,
    get_client_geometry,
    list_windows_by_executable,
)


PLAYER_NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]{1,24}$")


@dataclass(frozen=True)
class CharacterButton:
    click_x: int
    click_y: int
    confidence: float


@dataclass(frozen=True)
class InvitationButton:
    click_x: int
    click_y: int
    confidence: float


@dataclass(frozen=True)
class PlayerWindow:
    pseudo: str
    ocr_confidence: float
    window_handle: int
    window_title_before: str
    clicked_play: bool


def read_selected_pseudo(image: np.ndarray, ocr: RapidOCR) -> tuple[str, float] | None:
    """Read only the proportional name area above the character."""
    height, width = image.shape[:2]
    x0, x1 = int(width * 0.53), int(width * 0.68)
    y0, y1 = int(height * 0.25), int(height * 0.36)
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    result = ocr(enlarged)
    if not result.txts:
        return None

    candidates: list[tuple[float, str]] = []
    for raw_text, raw_score in zip(result.txts, result.scores, strict=True):
        text = str(raw_text).strip().replace(" ", "")
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        score = float(raw_score)
        if score >= 0.70 and PLAYER_NAME_PATTERN.fullmatch(text):
            candidates.append((score, text))
    if not candidates:
        return None
    score, pseudo = max(candidates, key=lambda item: item[0])
    return pseudo, score


def detect_character_play_button(
    image: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = 0.70,
) -> CharacterButton | None:
    """Validate the PLAY button in its fixed proportional region."""
    height, width = image.shape[:2]
    x0, x1 = int(width * 0.53), int(width * 0.67)
    y0, y1 = int(height * 0.65), int(height * 0.78)
    roi = image[y0:y1, x0:x1]
    scales = tuple(float(value) for value in np.linspace(0.70, 1.30, 13))
    match = best_multiscale_match(roi, template, scales=scales)
    if match is None or match.score < threshold:
        return None
    center_x, center_y = match.center
    return CharacterButton(x0 + center_x, y0 + center_y, match.score)


def detect_start_play_button(
    image: np.ndarray,
    ocr: RapidOCR | None,
) -> CharacterButton | None:
    """Locate the large central PLAY button on the Dofus landing screen."""
    height, width = image.shape[:2]
    x0, x1 = int(width * 0.42), int(width * 0.58)
    y0, y1 = int(height * 0.25), int(height * 0.42)
    roi = image[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    # Filter the yellow-green button shape first. The more expensive OCR pass
    # runs only when a plausible shape exists in the expected area.
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([25, 80, 70]), np.array([85, 255, 255]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[float, CharacterButton]] = []
    for contour in contours:
        x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
        relative_width = candidate_width / width
        relative_height = candidate_height / height
        aspect = candidate_width / max(1, candidate_height)
        center_x = x0 + x + candidate_width // 2
        center_y = y0 + y + candidate_height // 2
        center_x_ratio = center_x / width
        center_y_ratio = center_y / height

        if not (0.050 <= relative_width <= 0.110):
            continue
        if not (0.035 <= relative_height <= 0.090 and 1.5 <= aspect <= 3.5):
            continue
        if not (0.46 <= center_x_ratio <= 0.54 and 0.29 <= center_y_ratio <= 0.38):
            continue

        # The loading state keeps the PLAY label but turns the button grey.
        # Require a genuinely green, saturated fill instead of accepting a
        # small nearby green ornament.
        candidate_hsv = hsv[y:y + candidate_height, x:x + candidate_width]
        candidate_green = cv2.inRange(
            candidate_hsv,
            np.array([25, 80, 70]),
            np.array([85, 255, 255]),
        )
        green_ratio = float(np.mean(candidate_green > 0))
        gray_ratio = float(
            np.mean(
                (candidate_hsv[:, :, 1] < 55)
                & (candidate_hsv[:, :, 2] >= 55)
                & (candidate_hsv[:, :, 2] <= 220)
            )
        )
        if green_ratio < 0.40 or gray_ratio > 0.30:
            continue

        center_score = max(
            0.0,
            1.0 - abs(center_x_ratio - 0.50) / 0.04
            - abs(center_y_ratio - 0.333) / 0.06,
        )
        shape_score = max(0.0, 1.0 - abs(aspect - 2.05) / 1.5)
        color_score = min(1.0, green_ratio / 0.60)
        confidence = 0.45 * center_score + 0.25 * shape_score + 0.30 * color_score
        candidates.append(
            (confidence, CharacterButton(center_x, center_y, confidence))
        )

    if not candidates:
        return None

    _, button = max(candidates, key=lambda item: item[0])
    if ocr is None:
        return button

    enlarged = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    result = ocr(enlarged)
    text_confidence = max(
        (
            float(score)
            for text, score in zip(result.txts or [], result.scores or [], strict=True)
            if re.sub(r"[^A-Z]", "", str(text).upper()) == "JOUER"
        ),
        default=0.0,
    )
    if text_confidence < 0.85:
        return None

    return CharacterButton(
        button.click_x,
        button.click_y,
        min(1.0, 0.55 * button.confidence + 0.45 * text_confidence),
    )


def try_click_start_play(
    hwnd: int,
    *,
    ocr: RapidOCR,
    dry_run: bool,
) -> CharacterButton | None:
    """Click the central PLAY button once when that screen is visible."""
    image, _, _ = capture_window(hwnd)
    button = detect_start_play_button(image, ocr)
    if button is None:
        return None
    if not dry_run:
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)
        click_screen(origin_x + button.click_x, origin_y + button.click_y)
    return button


def detect_invitation_accept_button(
    image: np.ndarray,
    ocr: RapidOCR | None = None,
) -> InvitationButton | None:
    """Locate an invitation ACCEPT button anywhere in the client area."""
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # The button is saturated, yellow-green, and horizontal. A light closing
    # operation combines its bright letters and background variations.
    mask = cv2.inRange(hsv, np.array([28, 70, 90]), np.array([78, 255, 255]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    # Connected components are intentional here. On bright outdoor maps the
    # scenery can form one large outer contour surrounding the dark invitation
    # panel. RETR_EXTERNAL then hides the green button as an island inside that
    # contour, even though it is a separate foreground component.
    component_count, _labels, component_stats, _centroids = (
        cv2.connectedComponentsWithStats(mask)
    )

    candidates: list[tuple[float, InvitationButton]] = []
    for component_index in range(1, component_count):
        x, y, candidate_width, candidate_height, _area = map(
            int,
            component_stats[component_index],
        )
        relative_width = candidate_width / width
        relative_height = candidate_height / height
        aspect = candidate_width / max(1, candidate_height)
        center_x = x + candidate_width // 2
        center_y = y + candidate_height // 2

        if not (0.035 <= relative_width <= 0.080):
            continue
        if not (0.010 <= relative_height <= 0.040 and 2.5 <= aspect <= 9.0):
            continue
        # The button must belong to a dark invitation panel, regardless of where
        # that panel was moved by the user.
        panel_x0 = max(0, x - int(candidate_width * 1.15))
        panel_x1 = min(width, x + int(candidate_width * 1.10))
        panel_y0 = max(0, y - int(candidate_height * 3.40))
        panel_y1 = min(height, y + candidate_height + 2)
        panel = image[panel_y0:panel_y1, panel_x0:panel_x1]
        dark_ratio = float(np.mean(panel.mean(axis=2) < 105)) if panel.size else 0.0
        if dark_ratio < 0.55:
            continue

        # The ACCEPT button is the right-hand control of a two-button row. The
        # neutral REFUSE button immediately to its left is a much stronger cue
        # than green alone and prevents clicks on vegetation or action buttons.
        sibling_gap = max(2, int(candidate_width * 0.05))
        sibling_x1 = x - sibling_gap
        sibling_x0 = max(0, sibling_x1 - candidate_width)
        sibling = hsv[y:y + candidate_height, sibling_x0:sibling_x1]
        if sibling.shape[:2] != (candidate_height, candidate_width):
            continue
        sibling_neutral_ratio = float(
            np.mean(
                (sibling[:, :, 1] < 90)
                & (sibling[:, :, 2] > 55)
                & (sibling[:, :, 2] < 175)
            )
        )
        if sibling_neutral_ratio < 0.60:
            continue

        text_score = 0.0
        if ocr is not None:
            candidate = image[y:y + candidate_height, x:x + candidate_width]
            enlarged = cv2.resize(
                candidate, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC
            )
            result = ocr(enlarged)
            recognized = [
                (re.sub(r"[^A-Z]", "", str(text).upper()), float(score))
                for text, score in zip(
                    result.txts or [], result.scores or [], strict=True
                )
            ]
            text_score = max(
                (
                    score
                    for text, score in recognized
                    if text in {"ACCEPTER", "ACCEPT"}
                ),
                default=0.0,
            )
            # Reject a clearly readable unrelated action, but retain the visual
            # fallback when the small stylized label cannot be read at all.
            if text_score < 0.55 and any(score >= 0.70 for _text, score in recognized):
                continue

        shape_score = max(0.0, 1.0 - abs(aspect - 5.0) / 5.0)
        green_ratio = float(
            np.mean(mask[y:y + candidate_height, x:x + candidate_width] > 0)
        )
        confidence = float(
            min(
                1.0,
                0.35 * dark_ratio
                + 0.20 * sibling_neutral_ratio
                + 0.20 * shape_score
                + 0.15 * min(1.0, green_ratio / 0.55)
                + 0.10 * text_score,
            )
        )
        candidates.append(
            (confidence, InvitationButton(center_x, center_y, confidence))
        )

    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def accept_group_invitation(
    player: PlayerWindow,
    *,
    ocr: RapidOCR | None = None,
    timeout: float = 60.0,
    poll_interval: float = 0.35,
) -> InvitationButton:
    """Wait for and accept the invitation received by a character window.

    The full-screen visual detector is deliberately used without OCR here.
    Its panel, colour, size, and aspect-ratio checks are fast enough to run on
    every poll, while OCR remains available to callers that need additional
    diagnostics or validation.
    """
    windows = list_dofus_windows()
    if any(hwnd == player.window_handle for hwnd, _ in windows):
        hwnd = player.window_handle
    else:
        matches = [
            candidate_hwnd
            for candidate_hwnd, title in windows
            if title.casefold().startswith(player.pseudo.casefold())
        ]
        if len(matches) != 1:
            visible = ", ".join(title or str(candidate) for candidate, title in windows) or "none"
            raise RuntimeError(
                f"Current window for {player.pseudo} was not found "
                f"(visible Dofus windows: {visible})."
            )
        hwnd = matches[0]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image, _, _ = capture_window(hwnd, settle_delay=0.08)
        button = detect_invitation_accept_button(image)
        if button is not None:
            # Confirm the exact same control in a second frame before clicking.
            # Animated scenery can briefly resemble a green action button; a
            # real invitation stays at a stable client-relative position.
            time.sleep(0.08)
            stable_image, _, _ = capture_window(hwnd, settle_delay=0.02)
            stable_button = detect_invitation_accept_button(stable_image)
            stability_tolerance = max(6, int(stable_image.shape[1] * 0.006))
            if (
                stable_button is None
                or abs(stable_button.click_x - button.click_x) > stability_tolerance
                or abs(stable_button.click_y - button.click_y) > stability_tolerance
            ):
                time.sleep(max(0.05, poll_interval))
                continue

            detected_button = stable_button
            activate_window(hwnd)
            origin_x, origin_y, _, _ = get_client_geometry(hwnd)
            click_screen(
                origin_x + stable_button.click_x,
                origin_y + stable_button.click_y,
            )

            # Never treat one animation frame as confirmation. The panel must
            # be absent in two consecutive captures before acceptance succeeds.
            missing_confirmations = 0
            for confirmation_delay in (0.20, 0.20, 0.25):
                time.sleep(confirmation_delay)
                verification, _, _ = capture_window(hwnd, settle_delay=0.04)
                if detect_invitation_accept_button(verification) is None:
                    missing_confirmations += 1
                    if missing_confirmations == 2:
                        return detected_button
                else:
                    missing_confirmations = 0
            time.sleep(max(0.25, poll_interval))
            continue
        time.sleep(max(0.05, poll_interval))
    raise TimeoutError(
        f"ACCEPT button was not found for {player.pseudo} within {timeout:.0f}s."
    )


def list_dofus_windows() -> list[tuple[int, str]]:
    return list_windows_by_executable("Dofus.exe")


def wait_for_dofus_windows(
    *,
    initial_wait: float = 0.0,
    launch_wait: float = 180.0,
    stability_wait: float = 2.0,
    expected_count: int | None = None,
) -> list[tuple[int, str]]:
    """Detect the selected account count from the windows Ankama launches.

    Ankama Launcher already knows which accounts are selected. The application
    therefore clicks PLAY once and treats the window count as final after it has
    remained unchanged for ``stability_wait`` seconds.
    """
    poll_interval = 0.5
    last_count: int | None = None

    def observe() -> list[tuple[int, str]]:
        nonlocal last_count
        current = list_dofus_windows()
        if len(current) != last_count:
            print(f"Visible Dofus windows: {len(current)}", flush=True)
            last_count = len(current)
        return current

    initial_deadline = time.monotonic() + max(0.0, initial_wait)
    while time.monotonic() < initial_deadline:
        windows = observe()
        if windows:
            break
        time.sleep(poll_interval)
    else:
        windows = observe()

    expected_count = expected_count if expected_count and expected_count > 0 else None
    if windows and expected_count is not None and len(windows) >= expected_count:
        print(f"Detected {len(windows)} known account(s).", flush=True)
        return windows

    should_launch = not windows or (
        expected_count is not None and len(windows) < expected_count
    )
    if should_launch:
        print("Starting the selected Ankama accounts.", flush=True)
        launch_dofus(poll_interval=0.5)
        print("Launcher clicked; waiting for Dofus windows...", flush=True)

    deadline = time.monotonic() + launch_wait
    stable_since: float | None = None
    last_handles: tuple[int, ...] = ()
    while time.monotonic() < deadline:
        windows = observe()
        handles = tuple(sorted(hwnd for hwnd, _title in windows))
        now = time.monotonic()
        if handles and handles != last_handles:
            last_handles = handles
            stable_since = now
        elif handles and stable_since is not None:
            if now - stable_since >= max(0.5, stability_wait):
                print(f"Detected {len(windows)} selected account(s).", flush=True)
                return windows
        time.sleep(poll_interval)

    raise RuntimeError("No stable set of Dofus windows was detected before the timeout.")


def save_character_diagnostic(
    image: np.ndarray,
    pseudo: str,
    ocr_confidence: float,
    button: CharacterButton,
    path: Path,
) -> None:
    diagnostic = image.copy()
    height, width = image.shape[:2]
    cv2.rectangle(
        diagnostic,
        (int(width * 0.53), int(height * 0.25)),
        (int(width * 0.68), int(height * 0.36)),
        (255, 200, 0),
        3,
    )
    cv2.circle(diagnostic, (button.click_x, button.click_y), 16, (0, 0, 255), 4)
    cv2.putText(
        diagnostic,
        f"{pseudo} OCR={ocr_confidence:.0%} PLAY={button.confidence:.0%}",
        (max(10, button.click_x - 180), max(30, button.click_y - 45)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), diagnostic):
        raise RuntimeError(f"Impossible d'enregistrer {path}")


def try_read_character_window(
    hwnd: int,
    initial_title: str,
    *,
    ocr: RapidOCR,
    play_template: np.ndarray,
    diagnostics_dir: Path | None,
) -> tuple[PlayerWindow, CharacterButton] | None:
    """Read a ready selection screen without clicking its PLAY button."""
    image, _, _ = capture_window(hwnd)
    return try_read_character_image(
        image,
        hwnd,
        initial_title,
        ocr=ocr,
        play_template=play_template,
        diagnostics_dir=diagnostics_dir,
    )


def try_read_character_image(
    image: np.ndarray,
    hwnd: int,
    initial_title: str,
    *,
    ocr: RapidOCR,
    play_template: np.ndarray,
    diagnostics_dir: Path | None,
) -> tuple[PlayerWindow, CharacterButton] | None:
    """Read character data from an already captured selection screen."""
    button = detect_character_play_button(image, play_template)
    if button is None:
        return None

    player = read_character_identity(
        image,
        hwnd,
        initial_title,
        button,
        ocr=ocr,
        diagnostics_dir=diagnostics_dir,
    )
    if player is None:
        return None
    return player, button


def read_character_identity(
    image: np.ndarray,
    hwnd: int,
    initial_title: str,
    button: CharacterButton,
    *,
    ocr: RapidOCR,
    diagnostics_dir: Path | None,
) -> PlayerWindow | None:
    """Read a pseudo from a saved selection frame after PLAY was clicked."""
    pseudo_data = read_selected_pseudo(image, ocr)
    if pseudo_data is None:
        return None

    pseudo, ocr_confidence = pseudo_data
    if diagnostics_dir is not None:
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", pseudo)
        save_character_diagnostic(
            image,
            pseudo,
            ocr_confidence,
            button,
            diagnostics_dir / f"character-{safe_name}.png",
        )

    return PlayerWindow(
        pseudo=pseudo,
        ocr_confidence=ocr_confidence,
        window_handle=hwnd,
        window_title_before=initial_title,
        clicked_play=False,
    )


def click_character_play(hwnd: int, button: CharacterButton) -> None:
    """Activate a character window and click its already-detected PLAY button."""
    activate_window(hwnd)
    origin_x, origin_y, _, _ = get_client_geometry(hwnd)
    click_screen(origin_x + button.click_x, origin_y + button.click_y)


def try_process_character_window(
    hwnd: int,
    initial_title: str,
    *,
    ocr: RapidOCR,
    play_template: np.ndarray,
    dry_run: bool,
    diagnostics_dir: Path | None,
) -> PlayerWindow | None:
    """Process a window once without blocking while it is still loading."""
    ready = try_read_character_window(
        hwnd,
        initial_title,
        ocr=ocr,
        play_template=play_template,
        diagnostics_dir=diagnostics_dir,
    )
    if ready is None:
        return None
    player, button = ready
    if not dry_run:
        click_character_play(hwnd, button)
    return PlayerWindow(
        pseudo=player.pseudo,
        ocr_confidence=player.ocr_confidence,
        window_handle=player.window_handle,
        window_title_before=player.window_title_before,
        clicked_play=not dry_run,
    )


def process_character_window(
    hwnd: int,
    initial_title: str,
    *,
    ocr: RapidOCR,
    play_template: np.ndarray,
    selection_timeout: float,
    dry_run: bool,
    diagnostics_dir: Path | None,
) -> PlayerWindow:
    deadline = time.monotonic() + selection_timeout
    pseudo_data: tuple[str, float] | None = None
    button: CharacterButton | None = None
    image: np.ndarray | None = None
    origin_x = origin_y = 0

    while time.monotonic() < deadline:
        image, origin_x, origin_y = capture_window(hwnd)
        pseudo_data = read_selected_pseudo(image, ocr)
        button = detect_character_play_button(image, play_template)
        if pseudo_data is not None and button is not None:
            break
        time.sleep(0.5)

    if image is None or pseudo_data is None or button is None:
        raise RuntimeError(
            f"Incomplete selection screen for window {hwnd}: "
            f"name={'yes' if pseudo_data else 'no'}, button={'yes' if button else 'no'}."
        )

    pseudo, ocr_confidence = pseudo_data
    if diagnostics_dir is not None:
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", pseudo)
        save_character_diagnostic(
            image,
            pseudo,
            ocr_confidence,
            button,
            diagnostics_dir / f"character-{safe_name}.png",
        )

    if not dry_run:
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)
        click_screen(origin_x + button.click_x, origin_y + button.click_y)

    return PlayerWindow(
        pseudo=pseudo,
        ocr_confidence=ocr_confidence,
        window_handle=hwnd,
        window_title_before=initial_title,
        clicked_play=not dry_run,
    )


def resolve_group_leader(
    players: list[PlayerWindow],
    configured_leader: str,
) -> tuple[PlayerWindow, str]:
    """Resolve the configured leader, falling back to the first character."""
    leader = next(
        (
            player
            for player in players
            if player.pseudo.casefold() == configured_leader.casefold()
        ),
        None,
    )
    if leader is not None:
        return leader, leader.pseudo
    if not players:
        raise RuntimeError("No character was detected.")
    return players[0], players[0].pseudo


def players_with_loaded_interfaces(
    players: list[PlayerWindow],
    windows: list[tuple[int, str]],
) -> set[int]:
    """Return handles whose title confirms that the character entered the game."""
    titles = {handle: title.strip() for handle, title in windows}
    loaded: set[int] = set()
    for player in players:
        title = titles.get(player.window_handle, "")
        if title.casefold().startswith(player.pseudo.casefold()):
            loaded.add(player.window_handle)
    return loaded


def wait_for_game_interfaces(
    players: list[PlayerWindow],
    *,
    timeout: float,
    poll_interval: float = 0.20,
) -> None:
    """Wait without changing focus until every Dofus client is in the game UI."""
    expected = {player.window_handle for player in players}
    deadline = time.monotonic() + max(1.0, timeout)
    previous_loaded: set[int] = set()
    while time.monotonic() < deadline:
        loaded = players_with_loaded_interfaces(players, list_dofus_windows())
        if loaded != previous_loaded:
            print(
                f"Game interfaces ready: {len(loaded)}/{len(expected)}.",
                flush=True,
            )
            previous_loaded = loaded
        if loaded == expected:
            return
        time.sleep(max(0.05, poll_interval))
    missing = ", ".join(
        player.pseudo for player in players if player.window_handle not in previous_loaded
    )
    raise TimeoutError(f"Game interface did not become ready for: {missing}.")


def invitation_attempt_timeouts(final_timeout: float) -> tuple[float, ...]:
    """Return short probes followed by one final, user-configurable wait."""
    return 3.0, 7.0, max(10.0, float(final_timeout))


def invite_group_members(
    leader: PlayerWindow,
    targets: list[PlayerWindow],
    *,
    ocr: RapidOCR,
    chat_timeout: float,
    invitation_timeout: float,
) -> tuple[list[dict[str, object]], float, float]:
    """Invite every target and retry only characters still missing."""
    invitations = [
        {
            "target": target.pseudo,
            "command": f"/invite {target.pseudo}",
            "sent": False,
            "accepted": False,
            "attempts": 0,
        }
        for target in targets
    ]
    invitations_by_handle = {
        target.window_handle: invitation
        for target, invitation in zip(targets, invitations, strict=True)
    }
    send_seconds = 0.0
    accept_seconds = 0.0
    pending_targets = list(targets)
    timeouts = invitation_attempt_timeouts(invitation_timeout)

    for attempt, accept_timeout in enumerate(timeouts, start=1):
        if not pending_targets:
            break

        # Before resending a command, give a late-arriving invitation one last
        # short visual check. This avoids duplicate /invite commands when the
        # panel appeared just after the previous probe ended.
        if attempt > 1:
            still_missing: list[PlayerWindow] = []
            for target in pending_targets:
                invitation = invitations_by_handle[target.window_handle]
                accept_started = time.monotonic()
                try:
                    button = accept_group_invitation(
                        target,
                        ocr=ocr,
                        timeout=min(1.25, accept_timeout),
                        poll_interval=0.18,
                    )
                except TimeoutError:
                    accept_seconds += time.monotonic() - accept_started
                    still_missing.append(target)
                    continue

                accept_seconds += time.monotonic() - accept_started
                invitation["accepted"] = True
                invitation["accept_confidence"] = round(button.confidence, 5)
                print(
                    f"  Late invitation accepted for {target.pseudo}; "
                    "reinvitation skipped.",
                    flush=True,
                )
            pending_targets = still_missing
            if not pending_targets:
                break

        commands = [
            str(invitations_by_handle[target.window_handle]["command"])
            for target in pending_targets
        ]
        send_started = time.monotonic()
        execute_chat_commands_on_window(
            leader.window_handle,
            commands,
            submit=True,
            wait_timeout=(chat_timeout if attempt == 1 else 8.0),
            poll_interval=0.25,
            command_interval=0.14,
        )
        send_seconds += time.monotonic() - send_started
        for target in pending_targets:
            invitation = invitations_by_handle[target.window_handle]
            invitation["sent"] = True
            invitation["attempts"] = attempt
            print(
                f"  Invitation sent to {target.pseudo} "
                f"(attempt {attempt}/{len(timeouts)}).",
                flush=True,
            )

        # All invitations now exist before focus leaves the leader. Walk the
        # target windows only after the complete command batch was submitted.
        failed_this_pass: list[PlayerWindow] = []
        for target in pending_targets:
            invitation = invitations_by_handle[target.window_handle]
            accept_started = time.monotonic()
            try:
                button = accept_group_invitation(
                    target,
                    ocr=ocr,
                    timeout=accept_timeout,
                )
            except TimeoutError:
                accept_seconds += time.monotonic() - accept_started
                failed_this_pass.append(target)
                print(
                    f"  Invitation not confirmed for {target.pseudo}; "
                    "queued for reinvitation.",
                    flush=True,
                )
                continue

            accept_seconds += time.monotonic() - accept_started
            invitation["accepted"] = True
            invitation["accept_confidence"] = round(button.confidence, 5)
            print(
                f"  {target.pseudo} accepted ({button.confidence:.0%}).",
                flush=True,
            )

        pending_targets = failed_this_pass
        if pending_targets and attempt < len(timeouts):
            missing_names = ", ".join(target.pseudo for target in pending_targets)
            print(f"Reinviting missing character(s): {missing_names}.", flush=True)
            time.sleep(0.75)

    if pending_targets:
        missing_names = ", ".join(target.pseudo for target in pending_targets)
        raise TimeoutError(
            "Group invitation could not be confirmed after "
            f"{len(timeouts)} attempts for: {missing_names}."
        )

    return invitations, send_seconds, accept_seconds


def run_group_invitation_phase(
    players: list[PlayerWindow],
    *,
    configured_leader: str,
    ocr: RapidOCR,
    chat_timeout: float,
    invitation_timeout: float,
    post_login_delay: float,
) -> tuple[str, list[dict[str, object]], dict[str, object]]:
    """Settle the clients, form the group, and return focus to its leader."""
    leader, resolved_name = resolve_group_leader(players, configured_leader)
    if configured_leader and resolved_name.casefold() != configured_leader.casefold():
        print(
            f"Configured leader was not found; using {resolved_name}.",
            flush=True,
        )
    targets = [
        player for player in players if player.window_handle != leader.window_handle
    ]
    phase_started = time.monotonic()
    phase_timings: dict[str, object] = {}
    print("Waiting for all game interfaces before invitations...", flush=True)
    interfaces_started = time.monotonic()
    wait_for_game_interfaces(players, timeout=chat_timeout)
    phase_timings["game_interfaces_ready_seconds"] = round(
        time.monotonic() - interfaces_started,
        3,
    )
    settle_delay = max(0.0, float(post_login_delay))
    if settle_delay:
        print(
            f"Stabilizing loaded interfaces for {settle_delay:.2f}s...",
            flush=True,
        )
        settle_started = time.monotonic()
        time.sleep(settle_delay)
        phase_timings["post_login_settle_seconds"] = round(
            time.monotonic() - settle_started,
            3,
        )

    print(f"Waiting for {leader.pseudo} to enter the game...", flush=True)
    invitations, send_seconds, accept_seconds = invite_group_members(
        leader,
        targets,
        ocr=ocr,
        chat_timeout=chat_timeout,
        invitation_timeout=invitation_timeout,
    )
    phase_timings.update(
        {
            "invitations_sent_seconds": round(send_seconds, 3),
            "invitations_accepted_seconds": round(accept_seconds, 3),
            "invitation_phase_total_seconds": round(
                time.monotonic() - phase_started,
                3,
            ),
        }
    )

    activate_window(leader.window_handle)
    print(f"Returned to group leader {leader.pseudo}.", flush=True)
    return resolved_name, invitations, phase_timings


def login_characters(
    *,
    output_path: Path,
    assets_dir: Path = DEFAULT_ASSETS,
    dry_run: bool = False,
    diagnostics_dir: Path | None = None,
    initial_wait: float = 0.0,
    selection_timeout: float = 120.0,
    leader: str = "",
    invite_others: bool = True,
    chat_timeout: float = 180.0,
    invitation_timeout: float = 60.0,
    post_login_delay: float = 0.35,
) -> list[PlayerWindow]:
    workflow_started = time.monotonic()
    timings: dict[str, object] = {}
    template = cv2.imread(str(assets_dir / "dofus-character-play-button.png"))
    if template is None:
        raise RuntimeError("Character PLAY button template was not found.")
    # Load OCR models in parallel while Dofus/Ankama starts.
    previous_payload: dict[str, object] = {}
    if output_path.is_file():
        try:
            loaded_payload = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(loaded_payload, dict):
                previous_payload = loaded_payload
        except (OSError, ValueError):
            previous_payload = {}
    saved_count = previous_payload.get("account_count")
    expected_count = int(saved_count) if isinstance(saved_count, int) and saved_count > 0 else None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rapidocr") as executor:
        ocr_future = executor.submit(RapidOCR)
        windows_started = time.monotonic()
        windows = wait_for_dofus_windows(
            initial_wait=initial_wait,
            expected_count=expected_count,
        )
        timings["windows_ready_seconds"] = round(
            time.monotonic() - windows_started, 3
        )
        print(
            f"{len(windows)} window(s) ready in {timings['windows_ready_seconds']:.3f}s.",
            flush=True,
        )
        ocr = ocr_future.result()

    players: list[PlayerWindow] = []
    character_timings: list[dict[str, object]] = []
    character_phase_started = time.monotonic()
    pending = [(index, hwnd, title) for index, (hwnd, title) in enumerate(windows, start=1)]
    processing_seconds = {hwnd: 0.0 for _, hwnd, _ in pending}
    captured_selections: list[
        tuple[int, int, str, np.ndarray, CharacterButton, float]
    ] = []
    startup_clicked: set[int] = set()
    play_click_seconds = 0.0
    first_play_click_at: float | None = None
    last_play_click_at: float | None = None
    deadline = character_phase_started + selection_timeout
    print(f"Scanning {len(windows)} character-selection screen(s)...", flush=True)
    cursor = 0
    while pending and time.monotonic() < deadline:
        index, hwnd, title = pending[cursor]
        attempt_started = time.monotonic()
        image, _, _ = capture_window(hwnd, settle_delay=0.06)
        button = detect_character_play_button(image, template)
        processing_seconds[hwnd] += time.monotonic() - attempt_started

        if button is not None:
            clicked_at = time.monotonic()
            if first_play_click_at is None:
                first_play_click_at = clicked_at
            click_started = time.monotonic()
            if not dry_run:
                click_character_play(hwnd, button)
            play_click_seconds += time.monotonic() - click_started
            last_play_click_at = time.monotonic()
            ready_after = time.monotonic() - character_phase_started
            captured_selections.append(
                (index, hwnd, title, image, button, ready_after)
            )
            print(
                f"  Window {index}: character PLAY "
                f"{'clicked' if not dry_run else 'detected'} "
                f"at +{ready_after:.3f}s",
                flush=True,
            )
            pending.pop(cursor)
            if pending:
                cursor %= len(pending)
            continue

        if hwnd not in startup_clicked:
            # A grey central button means that this window is still loading.
            # Stay on it instead of visibly cycling through every account.
            startup_button = detect_start_play_button(image, None)
            if startup_button is not None:
                if not dry_run:
                    activate_window(hwnd)
                    origin_x, origin_y, _, _ = get_client_geometry(hwnd)
                    click_screen(
                        origin_x + startup_button.click_x,
                        origin_y + startup_button.click_y,
                    )
                startup_clicked.add(hwnd)
                print(
                    f"  Window {index}: central PLAY "
                    f"{'clicked' if not dry_run else 'detected'} "
                    f"({startup_button.confidence:.0%}).",
                    flush=True,
                )
                # Start every account rapidly before waiting for character
                # selection on the first one.
                cursor = (cursor + 1) % len(pending)
                continue

        not_started_elsewhere = any(
            candidate_hwnd not in startup_clicked
            for _, candidate_hwnd, _ in pending
            if candidate_hwnd != hwnd
        )
        if hwnd in startup_clicked and not_started_elsewhere:
            cursor = (cursor + 1) % len(pending)
            continue
        time.sleep(0.06)

    if pending:
        handles = ", ".join(str(hwnd) for _, hwnd, _ in pending)
        raise RuntimeError(f"Selection screens incomplete after {selection_timeout:.0f}s: {handles}")

    # OCR is intentionally deferred until every PLAY click has been issued. It
    # can take several seconds per image, but no longer spaces out the clicks.
    print("Reading character names from saved selection frames...", flush=True)
    for index, hwnd, title, image, button, ready_after in captured_selections:
        recognition_started = time.monotonic()
        player = read_character_identity(
            image,
            hwnd,
            title,
            button,
            ocr=ocr,
            diagnostics_dir=diagnostics_dir,
        )
        if player is None:
            raise RuntimeError(f"Character name could not be read for window {index}.")
        if any(
            existing.pseudo.casefold() == player.pseudo.casefold()
            for existing in players
        ):
            raise RuntimeError(f"Duplicate OCR character name: {player.pseudo}")
        players.append(
            PlayerWindow(
                pseudo=player.pseudo,
                ocr_confidence=player.ocr_confidence,
                window_handle=player.window_handle,
                window_title_before=player.window_title_before,
                clicked_play=not dry_run,
            )
        )
        character_timings.append(
            {
                "pseudo": player.pseudo,
                "ready_after_seconds": round(ready_after, 3),
                "processing_seconds": round(processing_seconds[hwnd], 3),
                "recognition_seconds": round(
                    time.monotonic() - recognition_started,
                    3,
                ),
            }
        )
        print(f"  Window {index}: {player.pseudo} ({player.ocr_confidence:.0%}).", flush=True)

    timings["character_play_clicks_seconds"] = round(play_click_seconds, 3)
    timings["character_play_sequence_seconds"] = round(
        (last_play_click_at - first_play_click_at)
        if first_play_click_at is not None and last_play_click_at is not None
        else 0.0,
        3,
    )
    print(
        f"Clicked {len(players)} character PLAY button(s) in "
        f"{timings['character_play_clicks_seconds']:.3f}s.",
        flush=True,
    )
    timings["characters_total_seconds"] = round(
        time.monotonic() - character_phase_started, 3
    )
    timings["startup_buttons_clicked"] = len(startup_clicked) if not dry_run else 0
    timings["characters"] = character_timings

    invitations: list[dict[str, object]] = []
    if invite_others and not dry_run:
        leader, invitations, invitation_timings = run_group_invitation_phase(
            players,
            configured_leader=leader,
            ocr=ocr,
            chat_timeout=chat_timeout,
            invitation_timeout=invitation_timeout,
            post_login_delay=post_login_delay,
        )
        timings.update(invitation_timings)

    timings["workflow_total_seconds"] = round(time.monotonic() - workflow_started, 3)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "account_count": len(players),
        "leader": leader,
        "players": [asdict(player) for player in players],
        "invitations": invitations,
        "timings": timings,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return players


def test_saved_image(
    image_path: Path,
    *,
    assets_dir: Path,
    diagnostic_path: Path | None,
) -> int:
    image = cv2.imread(str(image_path))
    template = cv2.imread(str(assets_dir / "dofus-character-play-button.png"))
    if image is None or template is None:
        print("Screenshot or template is unreadable.")
        return 2
    ocr = RapidOCR()
    pseudo_data = read_selected_pseudo(image, ocr)
    button = detect_character_play_button(image, template)
    if pseudo_data is None or button is None:
        print(f"Failure: character_name={pseudo_data}, button={button}")
        return 1
    pseudo, confidence = pseudo_data
    if diagnostic_path is not None:
        save_character_diagnostic(image, pseudo, confidence, button, diagnostic_path)
    print(
        f"Character={pseudo!r} ({confidence:.0%}), button=({button.click_x},{button.click_y}) "
        f"({button.confidence:.0%}). No action was performed."
    )
    return 0


def test_invitation_image(image_path: Path) -> int:
    """Test ACCEPT detection on a saved screenshot without clicking."""
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Capture illisible : {image_path}")
        return 2
    button = detect_invitation_accept_button(image)
    if button is None:
        print("ACCEPT button was not detected.")
        return 1
    print(
        f"ACCEPT button detected at ({button.click_x}, {button.click_y}), "
        f"confidence {button.confidence:.0%}. No click was performed."
    )
    return 0


def test_start_image(image_path: Path) -> int:
    """Test the large central PLAY button on a screenshot without clicking."""
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Capture illisible : {image_path}")
        return 2
    button = detect_start_play_button(image, RapidOCR())
    if button is None:
        print("Central PLAY button was not detected.")
        return 1
    print(
        f"Central PLAY button detected at ({button.click_x}, {button.click_y}), "
        f"confidence {button.confidence:.0%}. No click was performed."
    )
    return 0


def accept_saved_invitations(output_path: Path, timeout: float) -> int:
    """Accept pending invitations using window handles from players.json."""
    if not output_path.is_file():
        raise RuntimeError(f"Player file was not found: {output_path}")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    leader = str(payload.get("leader", ""))
    players = [PlayerWindow(**item) for item in payload.get("players", [])]
    targets = [player for player in players if player.pseudo.casefold() != leader.casefold()]
    if not targets:
        return 0

    invitations_by_target = {
        str(item.get("target", "")).casefold(): item
        for item in payload.get("invitations", [])
    }
    ocr = RapidOCR()
    for target in targets:
        button = accept_group_invitation(target, ocr=ocr, timeout=timeout)
        invitation = invitations_by_target.setdefault(
            target.pseudo.casefold(),
            {"target": target.pseudo, "command": f"/invite {target.pseudo}", "sent": True},
        )
        invitation["accepted"] = True
        invitation["accept_confidence"] = round(button.confidence, 5)
        print(f"{target.pseudo} accepted ({button.confidence:.0%}).", flush=True)

    payload["invitations"] = list(invitations_by_target.values())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("players.json"))
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--diagnostics-dir", type=Path, default=Path(__file__).with_name("character-diagnostics"))
    parser.add_argument("--dry-run", action="store_true", help="read and validate without clicking")
    parser.add_argument("--initial-wait", type=float, default=0.0)
    parser.add_argument("--selection-timeout", type=float, default=120.0)
    parser.add_argument(
        "--leader",
        default="",
        help="character that invites the group (first detected character by default)",
    )
    parser.add_argument("--skip-invites", action="store_true", help="do not send invitations")
    parser.add_argument("--chat-timeout", type=float, default=180.0)
    parser.add_argument("--invitation-timeout", type=float, default=60.0)
    parser.add_argument("--post-login-delay", type=float, default=0.35)
    parser.add_argument("--image", type=Path, help="test a screenshot without controlling Windows")
    parser.add_argument("--start-image", type=Path, help="test central PLAY on a screenshot")
    parser.add_argument("--invitation-image", type=Path, help="test ACCEPT on a screenshot")
    parser.add_argument("--accept-pending", action="store_true", help="accept invitations already received")
    parser.add_argument("--diagnostic", type=Path, help="diagnostic output for --image")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.start_image is not None:
        return test_start_image(args.start_image)
    if args.invitation_image is not None:
        return test_invitation_image(args.invitation_image)
    if args.accept_pending:
        try:
            return accept_saved_invitations(args.output, args.invitation_timeout)
        except (RuntimeError, TimeoutError) as error:
            print(str(error))
            return 1
    if args.image is not None:
        return test_saved_image(
            args.image,
            assets_dir=args.assets_dir,
            diagnostic_path=args.diagnostic,
        )
    try:
        players = login_characters(
            output_path=args.output,
            assets_dir=args.assets_dir,
            dry_run=args.dry_run,
            diagnostics_dir=args.diagnostics_dir,
            initial_wait=args.initial_wait,
            selection_timeout=args.selection_timeout,
            leader=args.leader,
            invite_others=not args.skip_invites,
            chat_timeout=args.chat_timeout,
            invitation_timeout=args.invitation_timeout,
            post_login_delay=args.post_login_delay,
        )
    except (RuntimeError, TimeoutError) as error:
        print(str(error))
        return 1
    print(f"Done: {len(players)} character names saved to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
