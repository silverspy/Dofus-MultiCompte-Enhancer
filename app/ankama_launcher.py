"""Ouvre Ankama Launcher, attend le bouton JOUER puis lance Dofus.

La reconnaissance exige deux ancres visuelles simultanées : le mot JOUER et
le pictogramme des personnages placé à sa gauche. Un téléchargement peut donc
remplacer temporairement le bouton sans provoquer de clic erroné.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from chat_vision import (
    activate_window,
    capture_window,
    click_screen,
    get_client_geometry,
    list_matching_windows,
)


DEFAULT_LAUNCHER = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
) / Path(
    "Programs/Ankama Launcher/Ankama Launcher.exe"
)
DEFAULT_ASSETS = Path(__file__).with_name("assets")


@dataclass(frozen=True)
class TemplateMatch:
    x: int
    y: int
    width: int
    height: int
    score: float
    scale: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass(frozen=True)
class PlayButton:
    click_x: int
    click_y: int
    text_score: float
    people_score: float
    scale: float

    @property
    def confidence(self) -> float:
        return min(self.text_score, self.people_score)


@dataclass(frozen=True)
class LaunchResult:
    window_title: str
    button: PlayButton
    clicked: bool
    waited_seconds: float


def load_template(path: Path) -> np.ndarray:
    template = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"Modèle visuel introuvable ou illisible : {path}")
    return template


def best_multiscale_match(
    image: np.ndarray,
    template: np.ndarray,
    *,
    scales: tuple[float, ...],
) -> TemplateMatch | None:
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image_edges = cv2.Canny(image_gray, 60, 160)
    best: TemplateMatch | None = None

    for scale in scales:
        width = max(8, int(round(template.shape[1] * scale)))
        height = max(8, int(round(template.shape[0] * scale)))
        if width >= image.shape[1] or height >= image.shape[0]:
            continue
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        resized = cv2.resize(template, (width, height), interpolation=interpolation)
        edges = cv2.Canny(cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY), 60, 160)
        response = cv2.matchTemplate(image_edges, edges, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(response)
        match = TemplateMatch(location[0], location[1], width, height, float(score), scale)
        if best is None or match.score > best.score:
            best = match
    return best


def detect_play_button(
    image: np.ndarray,
    people_template: np.ndarray,
    text_template: np.ndarray,
    *,
    threshold: float = 0.68,
) -> PlayButton | None:
    height, width = image.shape[:2]
    # Le catalogue et son bouton sont dans la partie supérieure gauche.
    search = image[: int(height * 0.72), : int(width * 0.58)]
    scales = tuple(float(value) for value in np.linspace(0.65, 1.45, 17))
    text = best_multiscale_match(search, text_template, scales=scales)
    people = best_multiscale_match(search, people_template, scales=scales)
    if text is None or people is None:
        return None
    if text.score < threshold or people.score < threshold:
        return None

    text_x, text_y = text.center
    people_x, people_y = people.center
    average_scale = (text.scale + people.scale) / 2.0

    # Les personnages doivent se trouver à gauche, dans le même bouton.
    horizontal_gap = text_x - people_x
    vertical_gap = abs(text_y - people_y)
    if not (70 * average_scale <= horizontal_gap <= 220 * average_scale):
        return None
    if vertical_gap > 35 * average_scale:
        return None

    # Vérifie le fond blanc du bouton autour du texte.
    radius_x = max(12, int(32 * text.scale))
    radius_y = max(8, int(18 * text.scale))
    x0, x1 = max(0, text_x - radius_x), min(search.shape[1], text_x + radius_x)
    y0, y1 = max(0, text_y - radius_y), min(search.shape[0], text_y + radius_y)
    patch = search[y0:y1, x0:x1]
    if patch.size == 0 or float(np.mean(patch)) < 175:
        return None

    return PlayButton(
        click_x=text_x,
        click_y=text_y,
        text_score=text.score,
        people_score=people.score,
        scale=average_scale,
    )


def find_launcher_window() -> tuple[int, str] | None:
    matches = [
        item
        for item in list_matching_windows("Ankama Launcher")
        if item[1].casefold() == "ankama launcher"
    ]
    if not matches:
        return None
    if len(matches) != 1:
        titles = ", ".join(title for _, title in matches)
        raise RuntimeError(f"Plusieurs fenêtres Ankama Launcher visibles : {titles}")
    return matches[0]


def ensure_launcher_window(
    executable: Path = DEFAULT_LAUNCHER,
    *,
    launch_timeout: float = 120.0,
) -> tuple[int, str]:
    existing = find_launcher_window()
    if existing is not None:
        activate_window(existing[0])
        return existing

    if not executable.is_file():
        raise RuntimeError(f"Ankama Launcher introuvable : {executable}")
    subprocess.Popen(
        [str(executable)],
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + launch_timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        window = find_launcher_window()
        if window is not None:
            activate_window(window[0])
            return window
    raise TimeoutError("Ankama Launcher ne présente aucune fenêtre après le délai prévu.")


def save_button_diagnostic(image: np.ndarray, button: PlayButton, path: Path) -> None:
    diagnostic = image.copy()
    cv2.circle(diagnostic, (button.click_x, button.click_y), 14, (0, 0, 255), 4)
    cv2.putText(
        diagnostic,
        f"JOUER {button.confidence:.0%}",
        (max(0, button.click_x - 80), max(25, button.click_y - 25)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), diagnostic):
        raise RuntimeError(f"Impossible d'enregistrer {path}")


def launch_dofus(
    *,
    launcher_path: Path = DEFAULT_LAUNCHER,
    assets_dir: Path = DEFAULT_ASSETS,
    wait_timeout: float = 2700.0,
    poll_interval: float = 5.0,
    dry_run: bool = False,
    diagnostic_path: Path | None = None,
) -> LaunchResult:
    """Ouvre le launcher, attend JOUER et clique une seule fois."""
    start = time.monotonic()
    hwnd, title = ensure_launcher_window(launcher_path)
    people = load_template(assets_dir / "ankama-play-people.png")
    text = load_template(assets_dir / "ankama-play-text.png")
    deadline = time.monotonic() + wait_timeout
    last_message = 0.0

    while time.monotonic() < deadline:
        image, origin_x, origin_y = capture_window(hwnd)
        button = detect_play_button(image, people, text)
        if button is not None:
            if diagnostic_path is not None:
                save_button_diagnostic(image, button, diagnostic_path)
            if not dry_run:
                # Recalcule l'origine immédiatement avant l'unique clic.
                activate_window(hwnd)
                origin_x, origin_y, _, _ = get_client_geometry(hwnd)
                click_screen(origin_x + button.click_x, origin_y + button.click_y)
            return LaunchResult(
                window_title=title,
                button=button,
                clicked=not dry_run,
                waited_seconds=time.monotonic() - start,
            )

        now = time.monotonic()
        if now - last_message >= 30:
            elapsed = now - start
            print(f"JOUER indisponible après {elapsed:.0f}s ; mise à jour possible, attente...")
            last_message = now
        time.sleep(max(0.5, poll_interval))

    raise TimeoutError(f"Le bouton JOUER n'est pas apparu après {wait_timeout:.0f} secondes.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher-path", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--image", type=Path, help="tester une capture sans ouvrir le launcher")
    parser.add_argument("--timeout", type=float, default=2700.0, help="attente maximale en secondes")
    parser.add_argument("--poll", type=float, default=5.0, help="intervalle de vérification")
    parser.add_argument("--dry-run", action="store_true", help="détecter sans cliquer")
    parser.add_argument("--diagnostic", type=Path, help="enregistrer la détection annotée")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.image is not None:
        image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
        if image is None:
            print(f"Image illisible : {args.image}")
            return 2
        try:
            people = load_template(args.assets_dir / "ankama-play-people.png")
            text = load_template(args.assets_dir / "ankama-play-text.png")
            button = detect_play_button(image, people, text)
        except RuntimeError as error:
            print(str(error))
            return 2
        if button is None:
            print("Bouton JOUER non détecté dans la capture.")
            return 1
        if args.diagnostic is not None:
            save_button_diagnostic(image, button, args.diagnostic)
        print(
            f"Bouton JOUER détecté à ({button.click_x},{button.click_y}), "
            f"confiance {button.confidence:.0%}. Aucune action effectuée."
        )
        return 0

    try:
        result = launch_dofus(
            launcher_path=args.launcher_path,
            assets_dir=args.assets_dir,
            wait_timeout=args.timeout,
            poll_interval=args.poll,
            dry_run=args.dry_run,
            diagnostic_path=args.diagnostic,
        )
    except (RuntimeError, TimeoutError) as error:
        print(str(error))
        return 1

    action = "détecté sans clic" if not result.clicked else "cliqué"
    print(
        f"Bouton JOUER {action} dans {result.window_title!r} après "
        f"{result.waited_seconds:.1f}s (confiance {result.button.confidence:.0%})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
