from __future__ import annotations

import subprocess

import triki_controller.output.mpris_volume as mpris_module
from triki_controller.gui.media_preferences import load_default_player, save_default_player
from triki_controller.output.mpris_volume import MprisPlayerVolume


class FakePlayerctl:
    def __init__(self, players: tuple[str, ...]) -> None:
        self.players = players

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        if argv[-1] == "-l":
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.players) + "\n", "")
        if argv[0].endswith("busctl"):
            return subprocess.CompletedProcess(argv, 1, "", "not available")
        if "metadata" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "metadata unavailable")
        if argv[-1] == "volume":
            return subprocess.CompletedProcess(argv, 0, "0.50\n", "")
        if argv[-1] == "status":
            return subprocess.CompletedProcess(argv, 0, "Paused\n", "")
        if argv[-1] == "position":
            return subprocess.CompletedProcess(argv, 0, "1.0\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_media_preference_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_default_player() is None
    save_default_player("spotify")
    assert load_default_player() == "spotify"
    save_default_player(None)
    assert load_default_player() is None


def test_explicit_player_selection_is_shared_process_wide(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    mpris_module._SELECTED_PLAYER = None
    fake = FakePlayerctl(("spotify", "vlc"))
    first = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
    second = MprisPlayerVolume(run=fake, playerctl_path="playerctl")

    assert first.select_player("vlc") is None
    assert second.describe_status().active_player == "vlc"
    mpris_module._SELECTED_PLAYER = None


def test_saved_default_player_wins_before_auto_selection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    mpris_module._SELECTED_PLAYER = None
    save_default_player("vlc")
    fake = FakePlayerctl(("spotify", "vlc"))
    controller = MprisPlayerVolume(run=fake, playerctl_path="playerctl")

    assert controller.describe_status().active_player == "vlc"
    mpris_module._SELECTED_PLAYER = None
