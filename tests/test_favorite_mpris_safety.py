"""Favorite routing safety through production APIs, with no native I/O."""
import json
import subprocess

import pytest

from triki_controller.gui.media_favorite import favorite_selector
from triki_controller.output.app_stream_volume import AppStreamVolume
from triki_controller.output.mpris_volume import MprisPlayerVolume

FAVORITE = {"platform": "mpris", "app_id": "wanted.desktop", "label": "Wanted"}


class OwnerBus:
    """Keep immutable owner records separate from the mutable MPRIS alias."""

    def __init__(self):
        self.owner = ":1.10"
        self.records = {
            ":1.10": {"DesktopEntry": "wanted.desktop", "Identity": "Wanted", "Volume": .8},
            ":1.99": {"DesktopEntry": "unrelated.desktop", "Identity": "Other", "Volume": .9},
        }
        self.calls = []
        self.writes = []
        self.after_desktop = None
        self.players = ["alias"]
        self.after_volume = None
        self.absorb_volume = False
        self.sinks = {7: {"pid": 101, "volume": .8}, 9: {"pid": 991, "volume": .9}}

    def restart(self, volume=.2):
        self.owner = ":1.11"
        self.records[self.owner] = {"DesktopEntry": "wanted.desktop", "Identity": "Wanted", "Volume": volume}

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        out = ""
        if argv == ["/inert/playerctl", "-l"]:
            out = "\n".join(self.players) if self.owner else ""
        elif "GetConnectionUnixProcessID" in argv:
            assert argv[-1].startswith(":"), "PID lookup must pin a unique owner"
            out = "u " + str({":1.10": 100, ":1.11": 110, ":1.99": 990}[argv[-1]])
        elif argv[0] == "/inert/pactl":
            if "list" in argv:
                out = json.dumps([
                    {"index": index, "properties": {"application.process.id": str(sink["pid"])},
                     "volume": {"mono": {"value": round(sink["volume"] * 65536)}}}
                    for index, sink in self.sinks.items()
                ])
            else:
                assert argv[1] == "set-sink-input-volume"
                index, value = int(argv[2]), float(argv[3].rstrip("%")) / 100
                self.sinks[index]["volume"] = value
                self.writes.append((f"sink:{index}", value))
        elif "GetNameOwner" in argv:
            if not self.owner:
                return subprocess.CompletedProcess(argv, 1, "", "absent")
            out = "s " + json.dumps(self.owner)
        elif argv[0] == "/inert/busctl" and argv[2] == "get-property":
            destination = argv[3]
            owner = destination if destination.startswith(":") else self.owner
            record = self.records[owner]
            prop = argv[-1]
            value = record[prop]
            out = ("d " + str(value)) if prop == "Volume" else "s " + json.dumps(value)
            if prop == "DesktopEntry" and self.after_desktop:
                callback, self.after_desktop = self.after_desktop, None
                callback()
            if prop == "Volume" and self.after_volume:
                callback, self.after_volume = self.after_volume, None
                callback()
        elif argv[0] == "/inert/busctl" and argv[2] == "call" and argv[3].startswith(":"):
            owner = argv[3]
            value = float(argv[-1]) if "Set" in argv else argv[-1]
            if isinstance(value, float) and not self.absorb_volume:
                self.records[owner]["Volume"] = value
            self.writes.append((owner, value))
        elif argv[:3] == ["/inert/playerctl", "-p", "alias"]:
            if argv[3:] == ["volume"]:
                out = str(self.records[self.owner]["Volume"])
            elif argv[3:] == ["metadata", "xesam:url"]:
                out = "https://music.youtube.com/"  # Must not override favorite Identity.
            else:
                raise AssertionError(f"Unexpected alias operation: {argv}")
        else:
            raise AssertionError(f"Unexpected inert command: {argv}")
        return subprocess.CompletedProcess(argv, 0, out, "")


@pytest.fixture
def favorite_player(monkeypatch):
    monkeypatch.setattr("triki_controller.output.mpris_volume.shutil.which", lambda name: "/inert/" + name)
    bus = OwnerBus()
    stream = AppStreamVolume(run=bus, read_ppid=lambda pid: {101: 100, 111: 110, 991: 990}.get(pid),
                             pactl_path="/inert/pactl", busctl_path="/inert/busctl")
    player = MprisPlayerVolume(run=bus, playerctl_path="/inert/playerctl", stream=stream)
    player.select_media_player(favorite_selector(FAVORITE))
    return player, bus


def test_alias_replacement_after_metadata_never_controls_unrelated_owner(favorite_player):
    player, bus = favorite_player
    bus.after_desktop = lambda: setattr(bus, "owner", ":1.99")
    assert player.apply_transport("next_track")
    assert bus.writes == []


def test_restart_discards_mute_restore_but_same_owner_can_unmute(favorite_player):
    player, bus = favorite_player
    assert player.apply_pulse("mute") is None
    assert bus.records[":1.10"]["Volume"] == 0
    assert player.apply_pulse("mute") is None
    assert bus.records[":1.10"]["Volume"] == .8
    assert player.apply_pulse("mute") is None
    bus.restart()
    bus.writes.clear()
    assert player.apply_pulse("mute") is None
    assert bus.writes == [(":1.11", 0.0)]
    assert player.apply_pulse("mute") is None
    assert bus.records[":1.11"]["Volume"] == .2


def test_favorite_status_reads_metadata_and_volume_from_captured_owner(favorite_player):
    player, bus = favorite_player
    status = player.describe_status()
    assert status.identity == "Wanted"
    assert status.volume == .8
    property_calls = [c for c in bus.calls if "get-property" in c]
    assert property_calls
    assert all(c[3] == ":1.10" for c in property_calls)
    assert not any(c[:3] == ["/inert/playerctl", "-p", "alias"] for c in bus.calls)
    assert bus.writes == []


def test_descriptor_capture_rejects_alias_replacement(favorite_player):
    player, bus = favorite_player
    bus.after_desktop = lambda: setattr(bus, "owner", ":1.99")
    with pytest.raises(ValueError):
        player.favorite_media_descriptor("alias")
    assert bus.writes == []


def test_restart_rebases_read_only_then_accepts_motion_after_old_owner_mute(favorite_player):
    player, bus = favorite_player
    assert player.apply_level(.7) is None
    assert player.take_media_baseline() == .8
    assert player.apply_pulse("mute") is None
    bus.restart()
    bus.writes.clear()
    assert player.apply_level(.7) is None
    assert player.take_media_baseline() == .2
    assert bus.writes == []
    assert player.apply_level(.3) is None
    assert bus.writes == [(":1.11", .3)]


def test_same_owner_recenter_preserves_mute_restore(favorite_player):
    player, bus = favorite_player
    assert player.apply_level(.7) is None
    assert player.take_media_baseline() == .8
    assert player.apply_pulse("mute") is None
    assert player.read_volume() == 0
    assert player.apply_level(.7) is None
    assert player.take_media_baseline() == 0
    assert player.apply_pulse("mute") is None
    assert bus.records[":1.10"]["Volume"] == .8


@pytest.mark.parametrize("unavailable", ["absent", "wrong_identity", "no_busctl"])
def test_unavailable_favorite_forgets_old_restore_without_substitution(favorite_player, monkeypatch, unavailable):
    player, bus = favorite_player
    assert player.apply_pulse("mute") is None
    old_owner = bus.owner
    if unavailable == "absent":
        bus.owner = None
    elif unavailable == "wrong_identity":
        bus.records[old_owner]["DesktopEntry"] = "unrelated.desktop"
    else:
        monkeypatch.setattr("triki_controller.output.mpris_volume.shutil.which", lambda name: None)
    bus.writes.clear()
    assert player.apply_transport("next_track")
    assert bus.writes == []
    bus.owner = old_owner
    bus.records[old_owner]["DesktopEntry"] = "wanted.desktop"
    bus.records[old_owner]["Volume"] = .2
    monkeypatch.setattr("triki_controller.output.mpris_volume.shutil.which", lambda name: "/inert/" + name)
    assert player.apply_pulse("mute") is None
    assert bus.writes == [(old_owner, 0.0)]
    assert player.apply_pulse("mute") is None
    assert bus.records[old_owner]["Volume"] == .2


def test_stream_fallback_maps_only_captured_owner_process_tree(favorite_player):
    player, bus = favorite_player
    bus.absorb_volume = True
    assert player.apply_level(.7) is None
    player.take_media_baseline()
    # Replacement during verification must not retarget the PipeWire fallback.
    bus.after_volume = lambda: setattr(bus, "owner", ":1.99")
    assert player.apply_level(.4) is None
    assert bus.writes == [(":1.10", .4), ("sink:7", .4)]
    assert bus.sinks[9]["volume"] == .9
    assert player.apply_level(.5)
    assert bus.writes == [(":1.10", .4), ("sink:7", .4)]


def test_restart_discards_previous_owner_stream_and_writability_cache(favorite_player):
    player, bus = favorite_player
    bus.absorb_volume = True
    assert player.apply_level(.7) is None
    player.take_media_baseline()
    assert player.apply_level(.4) is None
    assert bus.writes == [(":1.10", .4), ("sink:7", .4)]
    assert player.apply_pulse("mute") is None
    bus.restart()
    bus.absorb_volume = False
    bus.sinks[8] = {"pid": 111, "volume": .6}
    bus.writes.clear()
    assert player.apply_level(.4) is None
    assert player.take_media_baseline() == .2  # New MPRIS owner, not stale stream .6.
    assert bus.writes == []
    assert player.apply_level(.3) is None
    assert bus.writes == [(":1.11", .3)]
    assert bus.sinks[8]["volume"] == .6


def test_ambiguity_forgets_instance_restore(favorite_player):
    player, bus = favorite_player
    assert player.apply_pulse("mute") is None
    bus.players.append("second")
    bus.writes.clear()
    assert player.apply_transport("next_track")
    assert bus.writes == []
    bus.players.remove("second")
    bus.records[bus.owner]["Volume"] = .2
    assert player.apply_pulse("mute") is None
    assert bus.writes == [(":1.10", 0.0)]
    assert player.apply_pulse("mute") is None
    assert bus.records[bus.owner]["Volume"] == .2


def test_stable_owner_transport_is_uniquely_addressed(favorite_player):
    player, bus = favorite_player
    assert player.apply_transport("next_track") is None
    assert bus.writes == [(":1.10", "Next")]
