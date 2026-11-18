"""
Where the always-on-top overlays (the voice pill and the task panel) sit on screen.

Jarvis draws them as XWayland override-redirect windows, which KWin stacks above everything,
fullscreen windows included. The catch: X11 clients on Plasma Wayland aren't told about the
Plasma panel (the work area equals the whole screen), so the overlays read the panel's size and
edge from Plasma's own config and keep clear of it.
"""

import configparser
import re
from pathlib import Path
from typing import Dict, Tuple

PLASMASHELLRC = Path.home() / ".config" / "plasmashellrc"
APPLETSRC = Path.home() / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
FLOATING_GAP = 8  # px a floating Plasma panel keeps from the screen edge (and from windows)
EDGES = {3: "top", 4: "bottom", 5: "left", 6: "right"}


def _read(path: Path) -> configparser.RawConfigParser:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
    except (configparser.Error, OSError):
        pass
    return cp


def plasma_panel_insets(screen_index: int = 0) -> Dict[str, int]:
    """Space Plasma panels take on each edge of one screen (0 = primary), in logical px."""
    insets = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    applets, shell = _read(APPLETSRC), _read(PLASMASHELLRC)
    for section in applets.sections():
        m = re.fullmatch(r"Containments\]\[(\d+)", section)
        if not m or applets.get(section, "plugin", fallback="") != "org.kde.panel":
            continue
        try:
            edge = EDGES.get(int(applets.get(section, "location", fallback="0")))
            screen = int(applets.get(section, "lastScreen", fallback="0"))
        except ValueError:
            continue
        if not edge or screen != screen_index:
            continue
        panel_id = m.group(1)
        try:
            thickness = int(shell.get(f"PlasmaViews][Panel {panel_id}][Defaults", "thickness", fallback="44"))
        except ValueError:
            thickness = 44
        floating = shell.get(f"PlasmaViews][Panel {panel_id}", "floating", fallback="0") == "1"
        insets[edge] = max(insets[edge], thickness + (2 * FLOATING_GAP if floating else 0))
    return insets


def pill_position(screen: Tuple[int, int, int, int], insets: Dict[str, int], w: int, h: int, gap: int = 6) -> Tuple[int, int]:
    """Bottom centre, just above the bottom panel. screen = (x, y, width, height)."""
    x, y, sw, sh = screen
    usable_x, usable_w = x + insets["left"], sw - insets["left"] - insets["right"]
    return int(usable_x + (usable_w - w) / 2), int(y + sh - insets["bottom"] - h - gap)


def edge_panel_position(screen: Tuple[int, int, int, int], insets: Dict[str, int], w: int, h: int,
                        margin: int = 12) -> Tuple[int, int]:
    """Right edge, vertically centred in the space between top and bottom panels."""
    x, y, sw, sh = screen
    top, bottom = y + insets["top"] + margin, y + sh - insets["bottom"] - margin
    h = min(h, bottom - top)
    return int(x + sw - insets["right"] - w - margin), int(top + max(0, (bottom - top - h) / 2))
