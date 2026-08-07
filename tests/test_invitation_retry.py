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
    sleeps: list[float] = []

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
    def read_character(handle, _title, **_kwargs):
        selection_actions.append(("read", handle))
        return (
            players[handle],
            dofus_character_login.CharacterButton(10, 10, 0.95),
        )

    def click_character(handle, _button):
        selection_actions.append(("click", handle))

    monkeypatch.setattr(dofus_character_login, "try_read_character_window", read_character)
    monkeypatch.setattr(dofus_character_login, "click_character_play", click_character)
    monkeypatch.setattr(
        dofus_character_login,
        "execute_chat_command_on_window",
        lambda _handle, command, **_kwargs: commands.append(command),
    )

    def accept(player, **_kwargs):
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
    assert selection_actions == [
        ("read", 101),
        ("read", 202),
        ("read", 303),
        ("click", 101),
        ("click", 202),
        ("click", 303),
    ]
    assert sleeps[0] == 2.5
    assert accept_attempts == {"Ready": 1, "Late": 2}
    assert activations[-1] == 101
    payload = json.loads(output.read_text(encoding="utf-8"))
    invitations = {item["target"]: item for item in payload["invitations"]}
    assert invitations["Ready"]["attempts"] == 1
    assert invitations["Late"]["attempts"] == 2
    assert all(item["accepted"] for item in invitations.values())
