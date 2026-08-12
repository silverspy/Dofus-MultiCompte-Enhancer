from __future__ import annotations

import ctypes
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import ankama_launcher
import dofus_panel
import panel_settings


def test_default_configuration_contains_current_controls() -> None:
    assert dofus_panel.DEFAULT_CONFIG["language"] == "fr"
    assert dofus_panel.DEFAULT_CONFIG["play_button_enabled"] is True
    assert dofus_panel.DEFAULT_CONFIG["orientation"] in {"vertical", "horizontal"}
    assert 0.70 <= dofus_panel.DEFAULT_CONFIG["ui_scale"] <= 1.50
    assert dofus_panel.DEFAULT_CONFIG["leader"] == ""


def test_workflow_completion_marker_preserves_the_real_exit_code() -> None:
    assert dofus_panel.parse_workflow_done_marker(
        dofus_panel.workflow_done_marker(0)
    ) == 0
    assert dofus_panel.parse_workflow_done_marker(
        dofus_panel.workflow_done_marker(7)
    ) == 7
    assert dofus_panel.parse_workflow_done_marker("regular workflow output") is None


def test_emergency_stop_requires_ctrl_q() -> None:
    assert dofus_panel.is_emergency_stop_hotkey(0x51, {0xA2}) is True
    assert dofus_panel.is_emergency_stop_hotkey(0x51, set()) is False
    assert dofus_panel.is_emergency_stop_hotkey(0x50, {0xA2}) is False


def test_replication_settles_are_kept_below_one_frame() -> None:
    assert dofus_panel.BROADCAST_MOUSE_SOURCE_SETTLE < 0.010
    assert dofus_panel.BROADCAST_MOUSE_TARGET_SETTLE < 0.005
    assert dofus_panel.BROADCAST_KEYBOARD_SOURCE_SETTLE < 0.010
    assert dofus_panel.BROADCAST_KEYBOARD_TARGET_SETTLE < 0.005


def test_workflow_status_keeps_stop_hint_visible() -> None:
    panel = object.__new__(dofus_panel.DofusPanel)
    calls: list[tuple[str, str, bool]] = []
    panel.t = lambda key, **_kwargs: "CTRL+Q · STOP" if key == "stop_hint" else key
    panel.set_status = lambda text, color, persistent=False: calls.append(
        (text, color, persistent)
    )

    panel.set_workflow_status("RUNNING", dofus_panel.GOLD)

    assert calls == [("RUNNING\nCTRL+Q · STOP", dofus_panel.GOLD, True)]


def test_stop_workflow_terminates_only_an_active_process(monkeypatch) -> None:
    class Process:
        pid = 42

        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

    process = Process()
    panel = object.__new__(dofus_panel.DofusPanel)
    panel.workflow = process
    panel.workflow_cancel_requested = False
    panel.t = lambda key, **_kwargs: key
    statuses: list[tuple[str, str]] = []
    panel.set_workflow_status = lambda text, color: statuses.append((text, color))
    monkeypatch.setattr(dofus_panel, "append_panel_diagnostic", lambda *_args, **_kwargs: None)

    assert panel.stop_workflow() is True
    assert process.terminated is True
    assert panel.workflow_cancel_requested is True
    assert statuses == [("stopping", dofus_panel.GOLD)]


def test_ui_translation_supports_french_and_english() -> None:
    assert dofus_panel.translate("fr", "settings") == "PARAMÈTRES"
    assert dofus_panel.translate("en", "settings") == "SETTINGS"
    assert (
        dofus_panel.translate("en", "replication_targets", count=3)
        == "REPLICATION ENABLED · 3 TARGETS"
    )
    assert dofus_panel.translate("fr", "stop_hint") == "CTRL+Q · ARRÊTER"
    assert dofus_panel.translate("en", "cancelled") == "ACTION STOPPED"
    assert dofus_panel.translate("unknown", "save") == "ENREGISTRER"
    assert dofus_panel.translate("fr", "update_now") == "METTRE À JOUR"
    assert dofus_panel.translate("en", "update_now") == "UPDATE NOW"
    assert "prochain chargement" in dofus_panel.translate("fr", "group_leader_info")
    assert "next load" in dofus_panel.translate("en", "group_leader_info")
    assert dofus_panel.translate("fr", "minimize_app") == "RÉDUIRE L’APPLICATION"
    assert dofus_panel.translate("en", "quit_app") == "QUIT APPLICATION"


def test_english_mode_translates_input_names_without_changing_bindings() -> None:
    panel = object.__new__(dofus_panel.DofusPanel)
    panel.config_data = {"language": "en"}

    assert panel.display_input_name("SOURIS GAUCHE") == "LEFT MOUSE"
    assert panel.display_input_name("MÉDIA SUIVANT") == "NEXT TRACK"
    assert panel.display_input_name("TOUCHE 0xFE") == "KEY 0xFE"


def test_extended_keyboard_names_remain_stable() -> None:
    assert dofus_panel.keyboard_input_name(0x70) == "F1"
    assert dofus_panel.keyboard_input_name(0xDC) == "\\"
    assert dofus_panel.keyboard_input_name(0xB3) == "MÉDIA PLAY/PAUSE"
    assert dofus_panel.keyboard_input_name(0xFE) == "TOUCHE 0xFE"


def test_load_json_returns_copy_of_fallback_for_invalid_file(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{invalid", encoding="utf-8")
    fallback = {"orientation": "vertical"}

    loaded = dofus_panel.load_json(invalid, fallback)

    assert loaded == fallback
    assert loaded is not fallback


def test_save_json_preserves_unicode(tmp_path: Path) -> None:
    destination = tmp_path / "config.json"
    dofus_panel.save_json(destination, {"label": "Icônes"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"label": "Icônes"}
    assert "Icônes" in destination.read_text(encoding="utf-8")
    assert not (tmp_path / ".config.json.tmp").exists()


def test_panel_config_does_not_share_nested_default_state(tmp_path: Path) -> None:
    first = panel_settings.load_panel_config(tmp_path / "missing.json")
    second = panel_settings.load_panel_config(tmp_path / "missing.json")

    first["classes"]["Silvcra"] = "Cra"

    assert second["classes"] == {}
    assert panel_settings.DEFAULT_CONFIG["classes"] == {}


def test_panel_config_repairs_invalid_class_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"classes": null, "orientation": "horizontal"}', encoding="utf-8")

    loaded = panel_settings.load_panel_config(config_path)

    assert loaded["orientation"] == "horizontal"
    assert loaded["classes"] == {}


def test_player_cell_background_keeps_expected_dimensions() -> None:
    image = dofus_panel.rounded_cell_background("#4c5075", "#404455")

    assert isinstance(image, Image.Image)
    assert image.size == (36, 38)


def test_dialog_origin_is_clamped_to_the_monitor_work_area() -> None:
    work_area = (100, 50, 900, 650)

    assert dofus_panel.clamp_window_origin(-20, -10, 318, 480, work_area) == (100, 50)
    assert dofus_panel.clamp_window_origin(850, 600, 318, 480, work_area) == (582, 170)
    assert dofus_panel.clamp_window_origin(250, 100, 318, 480, work_area) == (250, 100)


def test_taskbar_refresh_preserves_exact_panel_geometry(monkeypatch) -> None:
    geometry_calls: list[str] = []

    class Root:
        def update_idletasks(self) -> None:
            pass

        def geometry(self, value: str | None = None) -> str:
            if value is not None:
                geometry_calls.append(value)
            return "42x196+1730+420"

        def attributes(self, name: str, value=None):
            if value is None:
                return 0.91
            return None

        def after_idle(self, _callback) -> None:
            pass

    monkeypatch.setattr(dofus_panel, "native_toplevel_handle", lambda _root: 101)
    monkeypatch.setattr(dofus_panel.user32, "GetWindowLongW", lambda *_args: 0)
    monkeypatch.setattr(dofus_panel.user32, "SetWindowLongW", lambda *_args: 0)
    monkeypatch.setattr(dofus_panel.user32, "ShowWindow", lambda *_args: 1)

    dofus_panel.expose_root_in_taskbar(Root())

    assert geometry_calls == ["42x196+1730+420"]


def test_panel_resizes_native_wrapper_to_all_player_cells() -> None:
    geometry_calls: list[str] = []

    class Root:
        def update_idletasks(self) -> None:
            pass

        def winfo_x(self) -> int:
            return 1700

        def winfo_y(self) -> int:
            return 300

        def geometry(self, value: str) -> None:
            geometry_calls.append(value)

    class Shell:
        def winfo_reqwidth(self) -> int:
            return 40

        def winfo_reqheight(self) -> int:
            return 172

    panel = object.__new__(dofus_panel.DofusPanel)
    panel.root = Root()
    panel.shell = Shell()

    panel.resize_to_content()

    assert geometry_calls == ["40x172+1700+300"]


def test_rounded_window_uses_antialiased_dwm_on_native_wrapper(monkeypatch) -> None:
    region_calls: list[tuple[int, object, bool]] = []
    dwm_calls: list[tuple[int, int, int]] = []

    class Window:
        def update_idletasks(self) -> None:
            pass

        def winfo_width(self) -> int:
            return 40

        def winfo_height(self) -> int:
            return 180

        def winfo_id(self) -> int:
            return 101

    monkeypatch.setattr(dofus_panel.user32, "GetParent", lambda hwnd: 202)
    monkeypatch.setattr(
        dofus_panel.user32,
        "SetWindowRgn",
        lambda hwnd, region, redraw: region_calls.append((hwnd, region, redraw)) or 1,
    )
    monkeypatch.setattr(
        dofus_panel.dwmapi,
        "DwmSetWindowAttribute",
        lambda hwnd, attribute, _value, size: (
            dwm_calls.append((hwnd, attribute, size)) or 0
        ),
    )

    dofus_panel.apply_rounded_window(Window())

    assert region_calls == [(202, None, True)]
    assert dwm_calls == [(
        202,
        dofus_panel.DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.sizeof(ctypes.c_int),
    )]


def test_compact_control_executes_only_on_mouse_release() -> None:
    calls: list[str] = []
    button = object.__new__(dofus_panel.RoundedControlButton)
    button.command = lambda: calls.append("pressed")
    button.press_origin = None
    button.press_cancelled = False
    event = SimpleNamespace(x_root=100, y_root=200)

    button._press(event)

    assert calls == []

    button._release(event)

    assert calls == ["pressed"]


def test_compact_control_release_is_cancelled_after_dragging() -> None:
    calls: list[str] = []
    button = object.__new__(dofus_panel.RoundedControlButton)
    button.command = lambda: calls.append("pressed")
    button.press_origin = None
    button.press_cancelled = False

    button._press(SimpleNamespace(x_root=100, y_root=200))
    button._motion(SimpleNamespace(x_root=105, y_root=200))
    button._release(SimpleNamespace(x_root=105, y_root=200))

    assert calls == []


def test_information_control_pins_on_mouse_press() -> None:
    calls: list[str] = []
    info = object.__new__(dofus_panel.DofusInfoTip)
    info.toggle_pin = lambda: calls.append("pressed")

    result = info._press()

    assert result == "break"
    assert calls == ["pressed"]


def test_settings_hitbox_accepts_only_points_inside_the_control() -> None:
    hitbox = (100, 200, 120, 220)

    assert dofus_panel.point_in_rectangle((100, 200), hitbox) is True
    assert dofus_panel.point_in_rectangle((119, 219), hitbox) is True
    assert dofus_panel.point_in_rectangle((120, 219), hitbox) is False
    assert dofus_panel.point_in_rectangle((119, 220), hitbox) is False
    assert dofus_panel.point_in_rectangle((110, 210), None) is False


def test_settings_dialog_is_placed_beside_its_owner_and_kept_on_screen() -> None:
    work_area = (0, 0, 1920, 1040)

    assert dofus_panel.position_dialog_near_rectangle(
        (20, 800, 60, 1000), (318, 493), work_area
    ) == (68, 547)
    assert dofus_panel.position_dialog_near_rectangle(
        (1880, 200, 1910, 400), (318, 493), work_area
    ) == (1554, 200)


def test_empty_player_list_displays_two_non_interactive_placeholders() -> None:
    visible_players = dofus_panel.players_with_placeholders([])

    assert len(visible_players) == 2
    assert all(player.placeholder for player in visible_players)
    assert all(player.handle is None for player in visible_players)


def test_empty_profile_slot_cannot_be_treated_as_group_leader() -> None:
    panel = object.__new__(dofus_panel.DofusPanel)
    panel.config_data = {"leader": ""}
    placeholder = dofus_panel.Player("", 0, placeholder=True)

    assert panel.is_leader(placeholder) is False


def test_real_players_are_preserved_when_placeholder_slots_are_added() -> None:
    player = dofus_panel.Player("Silvcra", 101, handle=101, class_name="Cra")

    visible_players = dofus_panel.players_with_placeholders([player])

    assert visible_players[0] is player
    assert len(visible_players) == 2
    assert visible_players[1].placeholder is True


def test_saved_icon_order_is_applied_below_the_group_leader() -> None:
    players = [
        dofus_panel.Player("Second", 202),
        dofus_panel.Player("Leader", 101),
        dofus_panel.Player("Third", 303),
    ]

    ordered = dofus_panel.sort_players_for_panel(
        players, ["Third", "Second", "Leader"], "Leader"
    )

    assert [player.pseudo for player in ordered] == ["Leader", "Third", "Second"]


def test_drag_reorders_icons_but_keeps_the_group_leader_first() -> None:
    leader = dofus_panel.Player("Leader", 101)
    second = dofus_panel.Player("Second", 202)
    third = dofus_panel.Player("Third", 303)
    players = [leader, second, third]

    assert dofus_panel.reorder_players(players, third, 1, "Leader") == [
        leader, third, second,
    ]
    assert dofus_panel.reorder_players(players, leader, 2, "Leader") == players
    assert dofus_panel.reorder_players(players, third, 0, "Leader") == [
        leader, third, second,
    ]


def test_drag_preview_uses_the_requested_cell_size() -> None:
    icon = Image.new("RGBA", (28, 28), (255, 255, 255, 255))

    preview = dofus_panel.drag_preview_image(icon, width=42, height=46)

    assert preview.mode == "RGBA"
    assert preview.size == (42, 46)


def test_placeholder_profile_uses_a_translucent_grayscale_dofus_icon() -> None:
    image = dofus_panel.placeholder_dofus_icon_image()

    assert image is not None
    assert image.size == (28, 28)
    assert image.mode == "RGBA"
    opaque_pixels = [
        image.getpixel((x, y))
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y))[3] > 0
    ]
    assert opaque_pixels
    assert all(red == green == blue for red, green, blue, _alpha in opaque_pixels)
    assert max(alpha for _red, _green, _blue, alpha in opaque_pixels) < 255


def test_leader_crown_keeps_transparent_background() -> None:
    symbol = Image.new("RGBA", (28, 28), (255, 255, 255, 255))

    decorated = dofus_panel.add_leader_crown(symbol)

    assert decorated.size == (28, 28)
    assert decorated.mode == "RGBA"
    assert decorated.getpixel((0, 0))[3] == 0


def test_launcher_path_is_not_hardcoded_to_developer_profile() -> None:
    path = str(ankama_launcher.DEFAULT_LAUNCHER).casefold()
    source = Path(ankama_launcher.__file__).read_text(encoding="utf-8").casefold()

    assert "ankama launcher" in path
    assert r"c:\users\silve" not in source
    assert "localappdata" in source


def test_required_assets_are_present() -> None:
    required = [
        dofus_panel.APP_ICON_PATH,
        dofus_panel.CLASS_SYMBOLS_DIR / "cra.png",
        dofus_panel.ASSETS_DIR / "ankama-play-people.png",
        dofus_panel.ASSETS_DIR / "ankama-play-text.png",
        dofus_panel.ASSETS_DIR / "dofus-character-play-button.png",
    ]

    assert all(path.is_file() for path in required)


def test_active_player_highlight_is_forced_after_cells_are_rebuilt() -> None:
    panel = object.__new__(dofus_panel.DofusPanel)
    panel.players = [
        dofus_panel.Player("Leader", 101, handle=101),
        dofus_panel.Player("Second", 202, handle=202),
    ]
    panel.active_handle = 101
    panel.selected_index = 0
    refreshes: list[bool] = []
    panel.refresh_cells = lambda: refreshes.append(True)

    synchronized = panel.synchronize_active_player(101, force_refresh=True)

    assert synchronized is True
    assert panel.active_handle == 101
    assert panel.selected_index == 0
    assert refreshes == [True]


def test_active_player_sync_ignores_unrelated_foreground_window() -> None:
    panel = object.__new__(dofus_panel.DofusPanel)
    panel.players = [dofus_panel.Player("Leader", 101, handle=101)]
    panel.active_handle = 101
    panel.selected_index = 0
    refreshes: list[bool] = []
    panel.refresh_cells = lambda: refreshes.append(True)

    assert panel.synchronize_active_player(999, force_refresh=True) is False
    assert panel.active_handle == 101
    assert refreshes == []
