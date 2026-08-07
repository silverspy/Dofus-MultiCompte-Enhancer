"""Persistent configuration helpers for the floating panel."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "language": "fr",
    "orientation": "vertical",
    "opacity": 0.94,
    "position_locked": False,
    "drag_cells_locked": False,
    "player_order": [],
    "play_button_enabled": True,
    "ui_scale": 1.0,
    "previous_key": "F7",
    "next_key": "F8",
    "broadcast_key": "F9",
    "leader": "",
    "classes": {},
    "x": 24,
    "y": 220,
}


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    """Read an object from JSON or return an independent fallback copy."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return deepcopy(fallback)
    return payload if isinstance(payload, dict) else deepcopy(fallback)


def load_panel_config(path: Path) -> dict[str, Any]:
    """Merge saved values onto fresh defaults without sharing nested state."""
    config = deepcopy(DEFAULT_CONFIG)
    config.update(load_json(path, {}))
    if not isinstance(config.get("classes"), dict):
        config["classes"] = {}
    return config


def save_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON atomically so an interrupted write cannot corrupt settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
