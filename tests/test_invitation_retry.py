from __future__ import annotations

import json

import numpy as np

import dofus_character_login


def test_late_invitation_is_accepted_without_duplicate_command(monkeypatch) -> None:
    leader = dofus_character_login.PlayerWindow("Leader", 0.99, 101, "one", True)
    target = dofus_character_login.PlayerWindow("Late", 0.99, 202, "two", True)
    commands: list[str] = []
    accept_attempts = 0

    monkeypatch.setattr(
        dofus_character_login,
        "execute_chat_commands_on_window",
        lambda _handle, batch, **_kwargs: commands.extend(batch),
    )
    monkeypatch.setattr(
        dofus_character_login,
        "group_roster_is_complete",
        lambda *_args: False,
    )

    def accept(_player, **_kwargs):
        nonlocal accept_attempts
        accept_attempts += 1
        if accept_attempts == 1:
            raise TimeoutError("invitation arrived just after the first probe")
        return dofus_character_login.InvitationButton(10, 10, 0.95)

    monkeypatch.setattr(dofus_character_login, "accept_group_invitation", accept)
    monkeypatch.setattr(dofus_character_login.time, "sleep", lambda _seconds: None)

    invitations, _send_seconds, _accept_seconds = (
        dofus_character_login.invite_group_members(
            leader,
            [target],
            ocr=object(),
            chat_timeout=5.0,
            invitation_timeout=10.0,
        )
    )

    assert commands == ["/invite Late"]
    assert accept_attempts == 2
    assert invitations[0]["accepted"] is True
    assert invitations[0]["attempts"] == 1


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
        if player.pseudo == "Late" and attempt <= 2:
            raise TimeoutError("invitation was not received")
        return dofus_character_login.InvitationButton(10, 10, 0.95)

    monkeypatch.setattr(dofus_character_login, "accept_group_invitation", accept)
    monkeypatch.setattr(dofus_character_login, "activate_window", activations.append)
    monkeypatch.setattr(
        dofus_character_login,
        "group_roster_is_complete",
        lambda *_args: False,
    )
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
    assert accept_attempts == {"Ready": 1, "Late": 3}
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
    assert dofus_character_login.invitation_attempt_timeouts(60.0) == (3.0, 7.0)
    assert dofus_character_login.invitation_attempt_timeouts(2.0) == (3.0, 3.0)


def test_complete_existing_group_skips_all_invitation_commands(monkeypatch) -> None:
    leader = dofus_character_login.PlayerWindow("Leader", 0.99, 101, "one", True)
    targets = [
        dofus_character_login.PlayerWindow("Two", 0.99, 202, "two", True),
        dofus_character_login.PlayerWindow("Three", 0.99, 303, "three", True),
    ]
    commands: list[str] = []
    monkeypatch.setattr(
        dofus_character_login,
        "group_roster_is_complete",
        lambda _leader, expected_count: expected_count == 3,
    )
    monkeypatch.setattr(
        dofus_character_login,
        "execute_chat_commands_on_window",
        lambda _handle, batch, **_kwargs: commands.extend(batch),
    )

    invitations, _send_seconds, _accept_seconds = (
        dofus_character_login.invite_group_members(
            leader,
            targets,
            ocr=object(),
            chat_timeout=5.0,
            invitation_timeout=10.0,
        )
    )

    assert commands == []
    assert all(item["accepted"] for item in invitations)
    assert all(item["status"] == "already_grouped" for item in invitations)
    assert all(item["attempts"] == 0 for item in invitations)


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


def test_connected_players_require_a_complete_title_match() -> None:
    previous = {
        "players": [
            {"pseudo": "Leader", "ocr_confidence": 0.98},
            {"pseudo": "Second", "ocr_confidence": 0.97},
        ]
    }

    restored = dofus_character_login.restore_connected_players(
        previous,
        [(501, "Leader - Cra"), (502, "Second - Feca")],
    )

    assert restored is not None
    assert [(player.pseudo, player.window_handle) for player in restored] == [
        ("Leader", 501),
        ("Second", 502),
    ]
    assert dofus_character_login.restore_connected_players(
        previous,
        [(501, "Leader - Cra"), (502, "Dofus")],
    ) is None

    checked: list[int] = []
    restored_generic = dofus_character_login.restore_connected_players(
        previous,
        [(501, "Leader - Cra"), (502, "Dofus 3.6 - Release")],
        verify_in_game=lambda handle: checked.append(handle) or True,
    )
    assert restored_generic is not None
    assert [(player.pseudo, player.window_handle) for player in restored_generic] == [
        ("Leader", 501),
        ("Second", 502),
    ]
    assert checked == [502]


def test_already_connected_characters_skip_every_play_step(monkeypatch, tmp_path) -> None:
    output = tmp_path / "players.json"
    output.write_text(
        json.dumps(
            {
                "account_count": 2,
                "leader": "Leader",
                "players": [
                    {"pseudo": "Leader", "ocr_confidence": 0.98},
                    {"pseudo": "Second", "ocr_confidence": 0.97},
                ],
            }
        ),
        encoding="utf-8",
    )
    invitation_calls: list[tuple[list[str], str, float]] = []
    monkeypatch.setattr(
        dofus_character_login,
        "wait_for_dofus_windows",
        lambda **_kwargs: [(501, "Leader - Cra"), (502, "Second - Feca")],
    )
    monkeypatch.setattr(dofus_character_login, "RapidOCR", lambda: object())
    monkeypatch.setattr(
        dofus_character_login.cv2,
        "imread",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("selection template must not be loaded")
        ),
    )

    def invite(players, *, configured_leader, post_login_delay, **_kwargs):
        invitation_calls.append(
            ([player.pseudo for player in players], configured_leader, post_login_delay)
        )
        return "Leader", [{"target": "Second", "accepted": True}], {"invite": 0.1}

    monkeypatch.setattr(
        dofus_character_login,
        "run_group_invitation_phase",
        invite,
    )

    players = dofus_character_login.login_characters(
        output_path=output,
        assets_dir=tmp_path,
        leader="Leader",
    )

    assert [(player.pseudo, player.window_handle) for player in players] == [
        ("Leader", 501),
        ("Second", 502),
    ]
    assert invitation_calls == [(["Leader", "Second"], "Leader", 0.0)]
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["timings"]["already_connected"] is True
    assert payload["timings"]["startup_buttons_clicked"] == 0
    assert payload["players"][0]["window_handle"] == 501
