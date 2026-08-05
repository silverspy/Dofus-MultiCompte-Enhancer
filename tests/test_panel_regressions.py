from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import ankama_launcher
import dofus_panel


def test_default_configuration_contains_current_controls() -> None:
    assert dofus_panel.DEFAULT_CONFIG["language"] == "fr"
    assert dofus_panel.DEFAULT_CONFIG["play_button_enabled"] is True
    assert dofus_panel.DEFAULT_CONFIG["orientation"] in {"vertical", "horizontal"}
    assert 0.70 <= dofus_panel.DEFAULT_CONFIG["ui_scale"] <= 1.50


def test_ui_translation_supports_french_and_english() -> None:
    assert dofus_panel.translate("fr", "settings") == "PARAMÈTRES"
    assert dofus_panel.translate("en", "settings") == "SETTINGS"
    assert (
        dofus_panel.translate("en", "replication_targets", count=3)
        == "REPLICATION ENABLED · 3 TARGETS"
    )
    assert dofus_panel.translate("unknown", "save") == "ENREGISTRER"


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


def test_player_cell_background_keeps_expected_dimensions() -> None:
    image = dofus_panel.rounded_cell_background("#4c5075", "#404455")

    assert isinstance(image, Image.Image)
    assert image.size == (36, 38)


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
