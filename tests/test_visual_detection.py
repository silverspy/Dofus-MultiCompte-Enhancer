from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from chat_vision import detect_chat_bar
from dofus_character_login import (
    detect_invitation_accept_button,
    detect_start_play_button,
    read_selected_pseudo,
)


class FakeOcr:
    def __init__(self, texts: list[str], scores: list[float]) -> None:
        self.result = SimpleNamespace(txts=texts, scores=scores)

    def __call__(self, _image: np.ndarray) -> SimpleNamespace:
        return self.result


def test_chat_bar_detects_saturated_status_dot_over_dark_bar() -> None:
    image = np.full((600, 1000, 3), 28, dtype=np.uint8)
    cv2.circle(image, (250, 585), 4, (0, 255, 0), thickness=-1)

    detection = detect_chat_bar(image)

    assert detection is not None
    assert abs(detection.anchor_x - 250) <= 1
    assert abs(detection.anchor_y - 585) <= 1
    assert detection.click_x == 120
    assert detection.confidence >= 0.75


def test_chat_bar_rejects_dot_without_dark_input_background() -> None:
    image = np.full((600, 1000, 3), 190, dtype=np.uint8)
    cv2.circle(image, (250, 585), 4, (0, 255, 0), thickness=-1)

    assert detect_chat_bar(image) is None


def test_invitation_accept_button_is_detected_in_expected_panel() -> None:
    image = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(image, (15, 145), (165, 225), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (70, 184), (130, 197), (30, 180, 130), thickness=-1)

    button = detect_invitation_accept_button(image)

    assert button is not None
    assert 95 <= button.click_x <= 105
    assert 187 <= button.click_y <= 195


def test_start_play_requires_green_button_and_jouer_text() -> None:
    image = np.full((600, 1000, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (465, 180), (535, 215), (20, 190, 95), thickness=-1)

    button = detect_start_play_button(image, FakeOcr(["JOUER"], [0.99]))

    assert button is not None
    assert 495 <= button.click_x <= 505
    assert 194 <= button.click_y <= 202


def test_start_play_rejects_gray_loading_state() -> None:
    image = np.full((600, 1000, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (465, 180), (535, 215), (110, 110, 110), thickness=-1)

    assert detect_start_play_button(image, FakeOcr(["JOUER"], [0.99])) is None


def test_selected_pseudo_uses_highest_valid_ocr_candidate() -> None:
    image = np.zeros((600, 1000, 3), dtype=np.uint8)
    ocr = FakeOcr(["invalide!", "silvcra", "Silvawa"], [0.99, 0.91, 0.88])

    assert read_selected_pseudo(image, ocr) == ("Silvcra", 0.91)
