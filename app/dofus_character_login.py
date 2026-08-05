"""Traite quatre fenêtres Dofus à l'écran de sélection des personnages.

Le programme complète d'abord les fenêtres manquantes via Ankama Launcher,
lit le pseudonyme sélectionné avec un OCR local, valide le bouton JOUER puis
entre en jeu. Les pseudonymes et fenêtres sont enregistrés dans players.json.
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
    execute_chat_command_on_window,
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
    """Lit uniquement la zone proportionnelle du nom au-dessus du personnage."""
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
    """Valide le bouton JOUER dans sa zone fixe proportionnelle."""
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
    ocr: RapidOCR,
) -> CharacterButton | None:
    """Repère le grand bouton JOUER central de l'écran d'accueil Dofus."""
    height, width = image.shape[:2]
    x0, x1 = int(width * 0.42), int(width * 0.58)
    y0, y1 = int(height * 0.25), int(height * 0.42)
    roi = image[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    # Filtre d'abord la forme vert-jaune du bouton. L'OCR, plus coûteux, n'est
    # exécuté que si une forme plausible existe au bon endroit.
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

        # L'état de chargement conserve le texte JOUER mais grise le bouton.
        # On exige donc que son remplissage soit réellement vert et saturé,
        # pas seulement qu'un petit ornement vert soit présent à proximité.
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

    _, button = max(candidates, key=lambda item: item[0])
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
    """Clique une seule fois sur le JOUER central si cet écran est visible."""
    image, _, _ = capture_window(hwnd)
    button = detect_start_play_button(image, ocr)
    if button is None:
        return None
    if not dry_run:
        activate_window(hwnd)
        origin_x, origin_y, _, _ = get_client_geometry(hwnd)
        click_screen(origin_x + button.click_x, origin_y + button.click_y)
    return button


def detect_invitation_accept_button(image: np.ndarray) -> InvitationButton | None:
    """Repère le bouton vert ACCEPTER du panneau d'invitation à gauche."""
    height, width = image.shape[:2]
    x0, x1 = 0, int(width * 0.20)
    y0, y1 = int(height * 0.20), int(height * 0.48)
    roi = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Le bouton est jaune-vert, saturé et horizontal. Une fermeture légère
    # réunit les lettres claires et les variations du fond en un seul bloc.
    mask = cv2.inRange(hsv, np.array([28, 70, 90]), np.array([78, 255, 255]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[float, InvitationButton]] = []
    for contour in contours:
        x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
        relative_width = candidate_width / width
        relative_height = candidate_height / height
        aspect = candidate_width / max(1, candidate_height)
        center_x = x0 + x + candidate_width // 2
        center_y = y0 + y + candidate_height // 2

        if not (0.035 <= relative_width <= 0.080):
            continue
        if not (0.010 <= relative_height <= 0.040 and 2.5 <= aspect <= 9.0):
            continue
        if not (0.07 <= center_x / width <= 0.15):
            continue
        if not (0.27 <= center_y / height <= 0.39):
            continue

        # Le bouton doit appartenir au panneau sombre d'invitation.
        panel_x0 = max(0, center_x - int(width * 0.09))
        panel_x1 = min(width, center_x + int(width * 0.04))
        panel_y0 = max(0, center_y - int(height * 0.07))
        panel_y1 = min(height, center_y + int(height * 0.02))
        panel = image[panel_y0:panel_y1, panel_x0:panel_x1]
        dark_ratio = float(np.mean(panel.mean(axis=2) < 105)) if panel.size else 0.0
        if dark_ratio < 0.35:
            continue

        center_score = max(0.0, 1.0 - abs(center_x / width - 0.109) / 0.05)
        shape_score = max(0.0, 1.0 - abs(aspect - 5.0) / 5.0)
        confidence = min(1.0, 0.45 * dark_ratio + 0.30 * center_score + 0.25 * shape_score)
        candidates.append(
            (confidence, InvitationButton(center_x, center_y, confidence))
        )

    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def accept_group_invitation(
    player: PlayerWindow,
    *,
    timeout: float = 60.0,
    poll_interval: float = 0.35,
) -> InvitationButton:
    """Attend et accepte l'invitation reçue dans la fenêtre d'un personnage."""
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
            visible = ", ".join(title or str(candidate) for candidate, title in windows) or "aucune"
            raise RuntimeError(
                f"Fenêtre actuelle de {player.pseudo} introuvable "
                f"(fenêtres Dofus visibles : {visible})."
            )
        hwnd = matches[0]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image, _, _ = capture_window(hwnd)
        button = detect_invitation_accept_button(image)
        if button is not None:
            detected_button = button
            # Confirme aussi le clic : un changement de focus au même instant
            # pouvait faire croire que l'invitation était acceptée alors que le
            # panneau restait affiché.
            for _click_attempt in range(3):
                activate_window(hwnd)
                origin_x, origin_y, _, _ = get_client_geometry(hwnd)
                click_screen(origin_x + button.click_x, origin_y + button.click_y)
                time.sleep(0.25)
                verification, _, _ = capture_window(hwnd)
                remaining = detect_invitation_accept_button(verification)
                if remaining is None:
                    return detected_button
                button = remaining
        time.sleep(max(0.05, poll_interval))
    raise TimeoutError(
        f"Bouton ACCEPTER introuvable pour {player.pseudo} après {timeout:.0f}s."
    )


def list_dofus_windows() -> list[tuple[int, str]]:
    return list_windows_by_executable("Dofus.exe")


def wait_for_exactly_four_windows(
    *,
    initial_wait: float = 0.0,
    launch_wait: float = 180.0,
    max_launch_attempts: int = 2,
) -> list[tuple[int, str]]:
    """Attend les fenêtres existantes puis relance le launcher si nécessaire."""
    poll_interval = 0.5
    last_count: int | None = None

    def observe() -> list[tuple[int, str]]:
        nonlocal last_count
        current = list_dofus_windows()
        if len(current) != last_count:
            print(f"Fenêtres Dofus visibles : {len(current)}/4", flush=True)
            last_count = len(current)
        return current

    initial_deadline = time.monotonic() + max(0.0, initial_wait)
    while time.monotonic() < initial_deadline:
        windows = observe()
        if len(windows) >= 4:
            break
        time.sleep(poll_interval)
    else:
        windows = observe()

    attempts = 0
    while len(windows) < 4 and attempts < max_launch_attempts:
        missing = 4 - len(windows)
        print(
            f"Seulement {len(windows)} fenêtre(s) Dofus ; relance via Ankama Launcher "
            f"({missing} manquante(s)).",
            flush=True,
        )
        launch_dofus(poll_interval=1.0)
        print("Clic du launcher effectué ; attente des fenêtres Dofus...", flush=True)
        attempts += 1
        deadline = time.monotonic() + launch_wait
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            windows = observe()
            if len(windows) >= 4:
                break

    if len(windows) != 4:
        raise RuntimeError(f"Quatre fenêtres Dofus requises, {len(windows)} détectée(s).")
    return windows


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


def try_process_character_window(
    hwnd: int,
    initial_title: str,
    *,
    ocr: RapidOCR,
    play_template: np.ndarray,
    dry_run: bool,
    diagnostics_dir: Path | None,
) -> PlayerWindow | None:
    """Traite une fenêtre une fois, sans bloquer si elle charge encore."""
    image, _, _ = capture_window(hwnd)
    pseudo_data = read_selected_pseudo(image, ocr)
    button = detect_character_play_button(image, play_template)
    if pseudo_data is None or button is None:
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
            f"Écran de sélection incomplet pour la fenêtre {hwnd} : "
            f"pseudo={'oui' if pseudo_data else 'non'}, bouton={'oui' if button else 'non'}."
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


def login_four_characters(
    *,
    output_path: Path,
    assets_dir: Path = DEFAULT_ASSETS,
    dry_run: bool = False,
    diagnostics_dir: Path | None = None,
    initial_wait: float = 0.0,
    selection_timeout: float = 120.0,
    leader: str = "Silvcra",
    invite_others: bool = True,
    chat_timeout: float = 180.0,
    invitation_timeout: float = 60.0,
) -> list[PlayerWindow]:
    workflow_started = time.monotonic()
    timings: dict[str, object] = {}
    template = cv2.imread(str(assets_dir / "dofus-character-play-button.png"))
    if template is None:
        raise RuntimeError("Modèle du bouton JOUER des personnages introuvable.")
    # Charge les modèles OCR en parallèle pendant que Dofus/Ankama démarre.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rapidocr") as executor:
        ocr_future = executor.submit(RapidOCR)
        windows_started = time.monotonic()
        windows = wait_for_exactly_four_windows(initial_wait=initial_wait)
        timings["four_windows_ready_seconds"] = round(
            time.monotonic() - windows_started, 3
        )
        print(
            f"Quatre fenêtres prêtes en {timings['four_windows_ready_seconds']:.3f}s.",
            flush=True,
        )
        ocr = ocr_future.result()

    players: list[PlayerWindow] = []
    character_timings: list[dict[str, object]] = []
    character_phase_started = time.monotonic()
    pending = [(index, hwnd, title) for index, (hwnd, title) in enumerate(windows, start=1)]
    processing_seconds = {hwnd: 0.0 for _, hwnd, _ in pending}
    startup_clicked: set[int] = set()
    deadline = character_phase_started + selection_timeout
    print("Balayage des quatre écrans de sélection...", flush=True)
    while pending and time.monotonic() < deadline:
        progress = False
        for index, hwnd, title in list(pending):
            attempt_started = time.monotonic()
            if hwnd not in startup_clicked:
                startup_button = try_click_start_play(
                    hwnd,
                    ocr=ocr,
                    dry_run=dry_run,
                )
                if startup_button is not None:
                    startup_clicked.add(hwnd)
                    processing_seconds[hwnd] += time.monotonic() - attempt_started
                    progress = True
                    print(
                        f"  Fenêtre {index} : JOUER central "
                        f"{'cliqué' if not dry_run else 'détecté'} "
                        f"({startup_button.confidence:.0%}).",
                        flush=True,
                    )
                    continue
            player = try_process_character_window(
                hwnd,
                title,
                ocr=ocr,
                play_template=template,
                dry_run=dry_run,
                diagnostics_dir=diagnostics_dir,
            )
            processing_seconds[hwnd] += time.monotonic() - attempt_started
            if player is None:
                continue
            if any(existing.pseudo.casefold() == player.pseudo.casefold() for existing in players):
                raise RuntimeError(f"Pseudonyme OCR dupliqué : {player.pseudo}")
            players.append(player)
            pending.remove((index, hwnd, title))
            progress = True
            ready_after = time.monotonic() - character_phase_started
            character_timings.append(
                {
                    "pseudo": player.pseudo,
                    "ready_after_seconds": round(ready_after, 3),
                    "processing_seconds": round(processing_seconds[hwnd], 3),
                }
            )
            print(
                f"  {player.pseudo} ({player.ocr_confidence:.0%}) : "
                f"{'JOUER cliqué' if player.clicked_play else 'validé sans clic'} "
                f"à +{ready_after:.3f}s",
                flush=True,
            )
        if pending and not progress:
            time.sleep(0.10)

    if pending:
        handles = ", ".join(str(hwnd) for _, hwnd, _ in pending)
        raise RuntimeError(f"Écrans de sélection incomplets après {selection_timeout:.0f}s : {handles}")
    timings["characters_total_seconds"] = round(
        time.monotonic() - character_phase_started, 3
    )
    timings["startup_buttons_clicked"] = len(startup_clicked) if not dry_run else 0
    timings["characters"] = character_timings

    invitations: list[dict[str, object]] = []
    if invite_others and not dry_run:
        leader_player = next(
            (player for player in players if player.pseudo.casefold() == leader.casefold()),
            None,
        )
        if leader_player is None:
            names = ", ".join(player.pseudo for player in players)
            raise RuntimeError(f"Personnage principal {leader!r} introuvable parmi : {names}")

        targets = [
            player for player in players
            if player.window_handle != leader_player.window_handle
        ]
        invite_phase_started = time.monotonic()
        invitation_send_seconds = 0.0
        invitation_accept_seconds = 0.0
        print(f"Attente de l'arrivée en jeu de {leader_player.pseudo}...", flush=True)
        for index, target in enumerate(targets):
            command = f"/invite {target.pseudo}"
            invitation: dict[str, object] = {
                "target": target.pseudo,
                "command": command,
                "sent": False,
                "accepted": False,
                "attempts": 0,
            }
            invitations.append(invitation)

            # On confirme chaque envoi par l'apparition du bouton ACCEPTER.
            # En cas de course de focus/chargement, seule l'invitation fautive
            # est renvoyée au lieu de recommencer tout le groupe.
            attempt_timeouts = (3.0, 6.0, max(8.0, invitation_timeout))
            for attempt, accept_timeout in enumerate(attempt_timeouts, start=1):
                send_started = time.monotonic()
                execute_chat_command_on_window(
                    leader_player.window_handle,
                    command,
                    submit=True,
                    wait_timeout=chat_timeout if index == 0 and attempt == 1 else 8.0,
                    poll_interval=0.35,
                )
                invitation_send_seconds += time.monotonic() - send_started
                invitation["sent"] = True
                invitation["attempts"] = attempt
                print(
                    f"  Invitation envoyée à {target.pseudo}"
                    f" (tentative {attempt}/3).",
                    flush=True,
                )

                accept_started = time.monotonic()
                try:
                    button = accept_group_invitation(target, timeout=accept_timeout)
                except TimeoutError:
                    invitation_accept_seconds += time.monotonic() - accept_started
                    if attempt == len(attempt_timeouts):
                        raise
                    print(
                        f"  Invitation non confirmée pour {target.pseudo}, nouvel essai...",
                        flush=True,
                    )
                    time.sleep(0.35)
                    continue

                invitation_accept_seconds += time.monotonic() - accept_started
                invitation["accepted"] = True
                invitation["accept_confidence"] = round(button.confidence, 5)
                print(
                    f"  {target.pseudo} a accepté ({button.confidence:.0%}).",
                    flush=True,
                )
                break

        timings["invitations_sent_seconds"] = round(invitation_send_seconds, 3)
        timings["invitations_accepted_seconds"] = round(invitation_accept_seconds, 3)
        timings["invitation_phase_total_seconds"] = round(
            time.monotonic() - invite_phase_started, 3
        )

        # Termine toujours sur le chef de groupe, une fois toutes les
        # invitations confirmées et acceptées.
        activate_window(leader_player.window_handle)
        print(
            f"Retour sur le chef de groupe {leader_player.pseudo}.",
            flush=True,
        )

    timings["workflow_total_seconds"] = round(time.monotonic() - workflow_started, 3)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        print("Capture ou modèle illisible.")
        return 2
    ocr = RapidOCR()
    pseudo_data = read_selected_pseudo(image, ocr)
    button = detect_character_play_button(image, template)
    if pseudo_data is None or button is None:
        print(f"Échec : pseudo={pseudo_data}, bouton={button}")
        return 1
    pseudo, confidence = pseudo_data
    if diagnostic_path is not None:
        save_character_diagnostic(image, pseudo, confidence, button, diagnostic_path)
    print(
        f"Pseudo={pseudo!r} ({confidence:.0%}), bouton=({button.click_x},{button.click_y}) "
        f"({button.confidence:.0%}). Aucune action effectuée."
    )
    return 0


def test_invitation_image(image_path: Path) -> int:
    """Teste sans clic le détecteur ACCEPTER sur une capture enregistrée."""
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Capture illisible : {image_path}")
        return 2
    button = detect_invitation_accept_button(image)
    if button is None:
        print("Bouton ACCEPTER non détecté.")
        return 1
    print(
        f"Bouton ACCEPTER détecté à ({button.click_x}, {button.click_y}), "
        f"confiance {button.confidence:.0%}. Aucun clic effectué."
    )
    return 0


def test_start_image(image_path: Path) -> int:
    """Teste sans clic le grand bouton JOUER central sur une capture."""
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Capture illisible : {image_path}")
        return 2
    button = detect_start_play_button(image, RapidOCR())
    if button is None:
        print("Bouton JOUER central non détecté.")
        return 1
    print(
        f"Bouton JOUER central détecté à ({button.click_x}, {button.click_y}), "
        f"confiance {button.confidence:.0%}. Aucun clic effectué."
    )
    return 0


def accept_saved_invitations(output_path: Path, timeout: float) -> int:
    """Accepte les invitations en attente à partir des handles de players.json."""
    if not output_path.is_file():
        raise RuntimeError(f"Fichier de personnages introuvable : {output_path}")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    leader = str(payload.get("leader", "Silvcra"))
    players = [PlayerWindow(**item) for item in payload.get("players", [])]
    targets = [player for player in players if player.pseudo.casefold() != leader.casefold()]
    if len(targets) != 3:
        raise RuntimeError(f"Trois personnages invités attendus, {len(targets)} trouvé(s).")

    invitations_by_target = {
        str(item.get("target", "")).casefold(): item
        for item in payload.get("invitations", [])
    }
    for target in targets:
        button = accept_group_invitation(target, timeout=timeout)
        invitation = invitations_by_target.setdefault(
            target.pseudo.casefold(),
            {"target": target.pseudo, "command": f"/invite {target.pseudo}", "sent": True},
        )
        invitation["accepted"] = True
        invitation["accept_confidence"] = round(button.confidence, 5)
        print(f"{target.pseudo} a accepté ({button.confidence:.0%}).", flush=True)

    payload["invitations"] = list(invitations_by_target.values())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("players.json"))
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--diagnostics-dir", type=Path, default=Path(__file__).with_name("character-diagnostics"))
    parser.add_argument("--dry-run", action="store_true", help="lire et valider sans cliquer")
    parser.add_argument("--initial-wait", type=float, default=0.0)
    parser.add_argument("--selection-timeout", type=float, default=120.0)
    parser.add_argument("--leader", default="Silvcra", help="personnage qui invite le groupe")
    parser.add_argument("--skip-invites", action="store_true", help="ne pas envoyer les invitations")
    parser.add_argument("--chat-timeout", type=float, default=180.0)
    parser.add_argument("--invitation-timeout", type=float, default=60.0)
    parser.add_argument("--image", type=Path, help="tester une capture sans contrôler Windows")
    parser.add_argument("--start-image", type=Path, help="tester le JOUER central sur une capture")
    parser.add_argument("--invitation-image", type=Path, help="tester ACCEPTER sur une capture")
    parser.add_argument("--accept-pending", action="store_true", help="accepter les invitations déjà reçues")
    parser.add_argument("--diagnostic", type=Path, help="diagnostic pour --image")
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
        players = login_four_characters(
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
        )
    except (RuntimeError, TimeoutError) as error:
        print(str(error))
        return 1
    print(f"Terminé : {len(players)} pseudonymes enregistrés dans {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
