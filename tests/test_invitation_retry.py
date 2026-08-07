from __future__ import annotations

import json

import numpy as np

import dofus_character_login


def test_only_missing_character_is_reinvited(monkeypatch, tmp_path) -> None:
    players = {
        101: dofus_character_login.PlayerWindow("Leader", 0.99, 101, "one", True),
        202: dofus_character_login.PlayerWindow("Ready", 0.99, 202, "two", True),
        303: dofus_character_login.PlayerWindow("Late", 0.99, 303, "three", True),
    }
    commands: list[str] = []
    accept_attempts: dict[str, int] = {}
    activations: list[int] = []
    selection_actions: list[tuple[str, int]] = []
    invitation_actions: list[tuple[str, str]] = []
    sleeps: list[float] = []
    captures: list[int] = []
    capture_attempts: dict[int, int] = {}

    monkeypatch.setattr(
        dofus_character_login.cv2,
        "imread",
        lambda _path: np.zeros((10, 10, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(dofus_character_login, "RapidOCR", lambda: object())
    monkeypatch.setattr(
        dofus_character_login,
        "wait_for_dofus_windows",
        lambda **_kwargs: [(handle, player.window_title_before) for handle, player in players.items()],
    )
    monkeypatch.setattr(dofus_character_login, "try_click_start_play", lambda *_args, **_kwargs: None)
    def read_character(_image, handle, _title, _button, **_kwargs):
        selection_actions.append(("read", handle))
        return players[handle]

    def click_character(handle, _button):
        selection_actions.append(("click", handle))

    def capture(handle, **_kwargs):
        captures.append(handle)
        capture_attempts[handle] = capture_attempts.get(handle, 0) + 1
        return (handle, capture_attempts[handle]), 0, 0

    monkeypatch.setattr(dofus_character_login, "capture_window", capture)
    monkeypatch.setattr(
        dofus_character_login,
        "detect_character_play_button",
        lambda image, _template: (
            None
            if image == (101, 1)
            else dofus_character_login.CharacterButton(10, 10, 0.95)
        ),
    )
    monkeypatch.setattr(dofus_character_login, "read_character_identity", read_character)
    monkeypatch.setattr(dofus_character_login, "detect_start_play_button", lambda *_args: None)
    monkeypatch.setattr(dofus_character_login, "click_character_play", click_character)
    monkeypatch.setattr(dofus_character_login, "wait_for_game_interfaces", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        dofus_character_login,
        "execute_chat_commands_on_window",
        lambda _handle, batch, **_kwargs: (
            commands.extend(batch),
            invitation_actions.extend(("send", command) for command in batch),
        ),
    )

    def accept(player, **_kwargs):
        invitation_actions.append(("accept", player.pseudo))
        attempt = accept_attempts.get(player.pseudo, 0) + 1
        accept_attempts[player.pseudo] = attempt
        if player.pseudo == "Late" and attempt == 1:
            raise TimeoutError("invitation was not received")
        return dofus_character_login.InvitationButton(10, 10, 0.95)

    monkeypatch.setattr(dofus_character_login, "accept_group_invitation", accept)
    monkeypatch.setattr(dofus_character_login, "activate_window", activations.append)
    monkeypatch.setattr(dofus_character_login.time, "sleep", sleeps.append)

    output = tmp_path / "players.json"
    dofus_character_login.login_characters(
        output_path=output,
        assets_dir=tmp_path,
        leader="Leader",
        invitation_timeout=10.0,
    )

    assert commands == ["/invite Ready", "/invite Late", "/invite Late"]
    assert invitation_actions == [
        ("send", "/invite Ready"),
        ("send", "/invite Late"),
        ("accept", "Ready"),
        ("accept", "Late"),
        ("send", "/invite Late"),
        ("accept", "Late"),
    ]
    assert selection_actions == [
        ("click", 101),
        ("click", 202),
        ("click", 303),
        ("read", 101),
        ("read", 202),
        ("read", 303),
    ]
    assert captures[:4] == [101, 101, 202, 303]
    assert 0.35 in sleeps
    assert accept_attempts == {"Ready": 1, "Late": 2}
    assert activations[-1] == 101
    payload = json.loads(output.read_text(encoding="utf-8"))
    invitations = {item["target"]: item for item in payload["invitations"]}
    assert invitations["Ready"]["attempts"] == 1
    assert invitations["Late"]["attempts"] == 2
    assert all(item["accepted"] for item in invitations.values())


def test_missing_configured_leader_falls_back_to_first_player() -> None:
    players = [
        dofus_character_login.PlayerWindow("First", 0.99, 101, "one", True),
        dofus_character_login.PlayerWindow("Second", 0.99, 202, "two", True),
    ]

    leader, resolved_name = dofus_character_login.resolve_group_leader(
        players,
        "Unknown",
    )

    assert leader is players[0]
    assert resolved_name == "First"


def test_invitation_timeouts_keep_fast_probes_and_safe_final_wait() -> None:
    assert dofus_character_login.invitation_attempt_timeouts(60.0) == (3.0, 7.0, 60.0)
    assert dofus_character_login.invitation_attempt_timeouts(2.0) == (3.0, 7.0, 10.0)


def test_all_character_titles_must_be_loaded_before_invitations() -> None:
    players = [
        dofus_character_login.PlayerWindow("Leader", 0.99, 101, "Dofus", True),
        dofus_character_login.PlayerWindow("Second", 0.99, 202, "Dofus", True),
        dofus_character_login.PlayerWindow("Third", 0.99, 303, "Dofus", True),
    ]

    loaded = dofus_character_login.players_with_loaded_interfaces(
        players,
        [(101, "Leader - Cra"), (202, "Dofus"), (303, "Third - Feca")],
    )

    assert loaded == {101, 303}
