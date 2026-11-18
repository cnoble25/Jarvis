"""Overlays keep clear of Plasma panels, which X11 apps on Plasma Wayland aren't told about."""

import daemon.overlay_layout as ol


def write_configs(tmp_path, monkeypatch, location="4", floating="1", thickness="46", screen="0"):
    applets = tmp_path / "appletsrc"
    applets.write_text(f"[Containments][2]\nlastScreen={screen}\nlocation={location}\nplugin=org.kde.panel\n\n"
                       "[Containments][1]\nplugin=org.kde.plasma.folder\nlastScreen=0\n")
    shell = tmp_path / "plasmashellrc"
    shell.write_text(f"[PlasmaViews][Panel 2]\nfloating={floating}\n\n[PlasmaViews][Panel 2][Defaults]\nthickness={thickness}\n")
    monkeypatch.setattr(ol, "APPLETSRC", applets)
    monkeypatch.setattr(ol, "PLASMASHELLRC", shell)


def test_floating_bottom_panel(tmp_path, monkeypatch):
    write_configs(tmp_path, monkeypatch)
    assert ol.plasma_panel_insets(0) == {"top": 0, "bottom": 62, "left": 0, "right": 0}
    assert ol.plasma_panel_insets(1)["bottom"] == 0  # panel lives on another screen


def test_right_panel_pushes_the_task_panel_left(tmp_path, monkeypatch):
    write_configs(tmp_path, monkeypatch, location="6", floating="0", thickness="44")
    insets = ol.plasma_panel_insets(0)
    x, _ = ol.edge_panel_position((0, 0, 1920, 1080), insets, 360, 300)
    assert x == 1920 - 44 - 360 - 12


def test_pill_sits_above_the_panel(tmp_path, monkeypatch):
    write_configs(tmp_path, monkeypatch)
    x, y = ol.pill_position((100, 0, 1920, 1080), ol.plasma_panel_insets(0), 520, 68)
    assert x == 100 + (1920 - 520) // 2
    assert y + 68 <= 1080 - 62


def test_missing_config_means_no_insets(tmp_path, monkeypatch):
    monkeypatch.setattr(ol, "APPLETSRC", tmp_path / "nope")
    monkeypatch.setattr(ol, "PLASMASHELLRC", tmp_path / "nope2")
    assert ol.plasma_panel_insets(0) == {"top": 0, "bottom": 0, "left": 0, "right": 0}
