"""config.py - persistent settings for QR Shot.

All tunables live in one JSON file under %APPDATA%/QRShot/config.json so both
the capture tool and the standalone settings program read the same values.
"""
from __future__ import annotations

import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "QRShot")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULTS = {
    # overlay look
    "border_color": "#d7f36b",     # selection rectangle color
    "mask_alpha": 110,             # 0-255 darkness outside the selection
    "handle_color": "#d7f36b",
    # behavior
    "default_tool": "pen",         # tool active when the overlay opens
    "drag_threshold": 6,           # px the right button must move to start
    "auto_copy": True,             # copy the raw selection on release
    # toolbar composition (order + which are shown)
    "tools": ["pen", "rect", "arrow", "highlight", "mosaic", "number", "text"],
    "hidden_tools": [],
    # pinned image
    "pin_shadow": True,
    "pin_opacity": 100,            # 30-100
    # drawing defaults
    "color": "#e23b3b",
    "alpha": 255,
    "pen_w": 3,
    "text_size": 16,
}

TOOL_LABELS = {
    "pen": "Pen", "rect": "Rect", "arrow": "Arrow", "highlight": "Highlight",
    "mosaic": "Mosaic", "number": "Number", "text": "Text",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    data = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reset() -> dict:
    save(DEFAULTS)
    return dict(DEFAULTS)
