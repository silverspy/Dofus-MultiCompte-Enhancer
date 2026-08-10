from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

import ankama_launcher
import chat_vision
import dofus_character_login
from chat_vision import detect_chat_bar
from dofus_character_login import (
    PlayerWindow,
    accept_group_invitation,
    detect_group_member_count,
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


def test_chat_command_batch_detects_the_input_only_once(monkeypatch) -> None:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    detection = chat_vision.Detection(1, 2, 3, 4, 0.99)
    captures: list[int] = []
    typed: list[str] = []

    monkeypatch.setattr(
        chat_vision,
        "capture_window",
        lambda hwnd: (captures.append(hwnd) or image, 0, 0),
    )
    monkeypatch.setattr(chat_vision, "detect_chat_bar", lambda _image: detection)
    monkeypatch.setattr(chat_vision, "activate_window", lambda _hwnd: None)
    monkeypatch.setattr(chat_vision, "get_client_geometry", lambda _hwnd: (10, 20, 800, 600))
    monkeypatch.setattr(
        chat_vision,
        "click_and_type",
        lambda _x, _y, command, _submit: typed.append(command),
    )
    monkeypatch.setattr(chat_vision, "get_window_title", lambda _hwnd: "Leader")
    monkeypatch.setattr(chat_vision.time, "sleep", lambda _seconds: None)

    results = chat_vision.execute_chat_commands_on_window(
        101,
        ["/invite One", "/invite Two", "/invite Three"],
        submit=True,
    )

    assert captures == [101]
    assert typed == ["/invite One", "/invite Two", "/invite Three"]
    assert [result.command for result in results] == typed


def test_chat_bar_rejects_dot_without_dark_input_background() -> None:
    image = np.full((600, 1000, 3), 190, dtype=np.uint8)
    cv2.circle(image, (250, 585), 4, (0, 255, 0), thickness=-1)

    assert detect_chat_bar(image) is None


def test_invitation_accept_button_is_detected_in_expected_panel() -> None:
    image = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(image, (5, 145), (165, 225), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (8, 184), (68, 197), (70, 70, 75), thickness=-1)
    cv2.rectangle(image, (70, 184), (130, 197), (30, 180, 130), thickness=-1)

    button = detect_invitation_accept_button(image)

    assert button is not None
    assert 95 <= button.click_x <= 105
    assert 187 <= button.click_y <= 195


def test_invitation_accept_button_can_be_detected_anywhere() -> None:
    image = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(image, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (631, 320), (701, 335), (70, 70, 75), thickness=-1)
    cv2.rectangle(image, (705, 320), (775, 335), (30, 180, 130), thickness=-1)

    button = detect_invitation_accept_button(image)

    assert button is not None
    assert 735 <= button.click_x <= 745
    assert 325 <= button.click_y <= 332


def test_invitation_button_is_found_inside_bright_green_scenery() -> None:
    # Outdoor maps create one large green outer contour around the dark panel.
    image = np.full((600, 1000, 3), (45, 165, 105), dtype=np.uint8)
    cv2.rectangle(image, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (631, 320), (701, 335), (70, 70, 75), thickness=-1)
    cv2.rectangle(image, (705, 320), (775, 335), (30, 180, 130), thickness=-1)

    button = detect_invitation_accept_button(image)

    assert button is not None
    assert 735 <= button.click_x <= 745
    assert 325 <= button.click_y <= 332


def test_green_action_without_refuse_button_is_not_clicked() -> None:
    image = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(image, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (705, 320), (775, 335), (30, 180, 130), thickness=-1)

    assert detect_invitation_accept_button(image) is None


def test_complete_group_roster_counts_regular_portrait_cards() -> None:
    image = np.full((1000, 1600, 3), 25, dtype=np.uint8)
    y0, y1 = int(1000 * 0.875), int(1000 * 0.98) - 1
    first_boundary = int(1600 * 0.235)
    card_width = int(1600 * 0.029)
    for boundary_index in range(5):
        x = first_boundary + boundary_index * card_width
        cv2.line(image, (x, y0), (x, y1), (210, 210, 210), thickness=2)

    assert detect_group_member_count(image) == 4


def test_isolated_bottom_bar_edges_are_not_a_group_roster() -> None:
    image = np.full((1000, 1600, 3), 25, dtype=np.uint8)
    cv2.line(image, (400, 875), (400, 978), (210, 210, 210), thickness=2)
    cv2.line(image, (610, 875), (610, 978), (210, 210, 210), thickness=2)

    assert detect_group_member_count(image) == 0


def test_invitation_ocr_rejects_unrelated_green_action() -> None:
    image = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(image, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(image, (631, 320), (701, 335), (70, 70, 75), thickness=-1)
    cv2.rectangle(image, (705, 320), (775, 335), (30, 180, 130), thickness=-1)

    assert (
        detect_invitation_accept_button(image, FakeOcr(["ACHETER"], [0.99]))
        is None
    )


def test_live_invitation_acceptance_uses_fast_visual_detection(monkeypatch) -> None:
    invitation = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(invitation, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(invitation, (631, 320), (701, 335), (70, 70, 75), thickness=-1)
    cv2.rectangle(invitation, (705, 320), (775, 335), (30, 180, 130), thickness=-1)
    captures = iter([invitation, invitation])
    settle_delays: list[float] = []
    clicks: list[tuple[int, int]] = []

    class RejectOcrCalls:
        def __call__(self, _image: np.ndarray) -> SimpleNamespace:
            raise AssertionError("The polling path must not invoke OCR")

    player = PlayerWindow("Target", 0.9, 101, "Account", True)
    monkeypatch.setattr(
        dofus_character_login,
        "list_dofus_windows",
        lambda: [(101, "Target")],
    )
    monkeypatch.setattr(
        dofus_character_login,
        "capture_window",
        lambda _hwnd, *, settle_delay: (
            settle_delays.append(settle_delay) or next(captures),
            0,
            0,
        ),
    )
    monkeypatch.setattr(dofus_character_login, "activate_window", lambda _hwnd: None)
    monkeypatch.setattr(
        dofus_character_login,
        "get_client_geometry",
        lambda _hwnd: (10, 20, 1000, 600),
    )
    monkeypatch.setattr(
        dofus_character_login,
        "click_screen",
        lambda x, y: clicks.append((x, y)),
    )
    monkeypatch.setattr(dofus_character_login.time, "sleep", lambda _seconds: None)

    button = accept_group_invitation(player, ocr=RejectOcrCalls(), timeout=1.0)

    assert button.click_x in range(735, 746)
    assert clicks == [(10 + button.click_x, 20 + button.click_y)]
    assert settle_delays == [0.08, 0.02]


def test_confirmed_click_is_success_even_if_invitation_animation_would_linger(
    monkeypatch,
) -> None:
    invitation = np.full((600, 1000, 3), 170, dtype=np.uint8)
    cv2.rectangle(invitation, (620, 240), (830, 360), (35, 37, 48), thickness=-1)
    cv2.rectangle(invitation, (631, 320), (701, 335), (70, 70, 75), thickness=-1)
    cv2.rectangle(invitation, (705, 320), (775, 335), (30, 180, 130), thickness=-1)
    captures = iter([invitation, invitation])
    clicks: list[tuple[int, int]] = []
    sleeps: list[float] = []

    player = PlayerWindow("Target", 0.9, 101, "Account", True)
    monkeypatch.setattr(
        dofus_character_login,
        "list_dofus_windows",
        lambda: [(101, "Target")],
    )
    monkeypatch.setattr(
        dofus_character_login,
        "capture_window",
        lambda _hwnd, **_kwargs: (next(captures), 0, 0),
    )
    monkeypatch.setattr(dofus_character_login, "activate_window", lambda _hwnd: None)
    monkeypatch.setattr(
        dofus_character_login,
        "get_client_geometry",
        lambda _hwnd: (10, 20, 1000, 600),
    )
    monkeypatch.setattr(
        dofus_character_login,
        "click_screen",
        lambda x, y: clicks.append((x, y)),
    )
    monkeypatch.setattr(dofus_character_login.time, "sleep", sleeps.append)

    button = accept_group_invitation(player, timeout=1.0)

    assert clicks == [(10 + button.click_x, 20 + button.click_y)]
    assert sleeps == [0.08]


def test_account_count_is_inferred_after_window_set_stabilizes(monkeypatch) -> None:
    observations = iter(
        [
            [],
            [(101, "Account one")],
            [(101, "Account one"), (202, "Account two")],
        ]
    )
    latest = [(101, "Account one"), (202, "Account two")]
    launches: list[bool] = []
    clock = {"now": 0.0}

    def list_windows() -> list[tuple[int, str]]:
        return next(observations, latest)

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(dofus_character_login, "list_dofus_windows", list_windows)
    monkeypatch.setattr(
        dofus_character_login,
        "launch_dofus",
        lambda **_kwargs: launches.append(True),
    )
    monkeypatch.setattr(dofus_character_login.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(dofus_character_login.time, "sleep", sleep)

    windows = dofus_character_login.wait_for_dofus_windows(
        initial_wait=0.0,
        launch_wait=20.0,
        stability_wait=1.0,
    )

    assert windows == latest
    assert launches == [True]


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


def test_launcher_live_scans_cache_templates_and_use_short_settle(monkeypatch) -> None:
    image = np.zeros((600, 1000, 3), dtype=np.uint8)
    template = np.zeros((12, 24, 3), dtype=np.uint8)
    prepared = ((np.zeros((12, 24), dtype=np.uint8), 1.0),)
    captures: list[float] = []
    prepared_calls: list[np.ndarray] = []
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        ankama_launcher,
        "ensure_launcher_window",
        lambda _path: (101, "Ankama Launcher"),
    )
    monkeypatch.setattr(ankama_launcher, "load_template", lambda _path: template)
    monkeypatch.setattr(
        ankama_launcher,
        "prepare_multiscale_template",
        lambda value, _scales: prepared_calls.append(value) or prepared,
    )
    monkeypatch.setattr(
        ankama_launcher,
        "capture_window",
        lambda _hwnd, *, settle_delay: (
            captures.append(settle_delay) or image,
            0,
            0,
        ),
    )
    monkeypatch.setattr(
        ankama_launcher,
        "detect_play_button",
        lambda *_args, **_kwargs: ankama_launcher.PlayButton(
            10, 10, 0.9, 0.9, 1.0
        ),
    )
    monkeypatch.setattr(ankama_launcher.time, "sleep", sleep_calls.append)

    result = ankama_launcher.launch_dofus(dry_run=True, poll_interval=0.15)

    assert result.clicked is False
    assert captures == [ankama_launcher.LAUNCHER_CAPTURE_SETTLE]
    assert len(prepared_calls) == 2
    assert sleep_calls == []


def test_selected_pseudo_uses_highest_valid_ocr_candidate() -> None:
    image = np.zeros((600, 1000, 3), dtype=np.uint8)
    ocr = FakeOcr(["invalide!", "silvcra", "Silvawa"], [0.99, 0.91, 0.88])

    assert read_selected_pseudo(image, ocr) == ("Silvcra", 0.91)
