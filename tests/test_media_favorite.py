"""Stable favorites through settings/session and inert native adapters."""
from dataclasses import replace

from triki_controller.gui.session import ControllerSession
from triki_controller.output.trace import TraceOutput
from triki_controller.gui.media_favorite import favorite_selector

import pytest

from triki_controller.gui.settings import GuiSettings, SettingsError, parse_settings, save_settings, load_settings

FAVORITE = {"platform": "mpris", "app_id": "org.example.Player", "label": "Player"}

class AudioAdapter:
    def __init__(self):
        from triki_controller.output.windows_audio import PlayerSession
        self.players = [PlayerSession("10:1", "Player", True, .2, False, r"C:\Player\player.exe")]
        self.writes = []

    def sessions(self):
        return tuple(self.players)

    def set_player(self, key, level):
        self.writes.append((key, level))


def test_windows_favorite_restart_absence_ambiguity_read_only_rebase():
    from triki_controller.output.windows_audio import WindowsAudio, PlayerSession
    adapter = AudioAdapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    descriptor = audio.favorite_media_descriptor("10:1")
    assert descriptor["app_id"] == r"C:\Player\player.exe"
    assert not adapter.writes
    audio.select_media_player(favorite_selector(descriptor))
    assert audio.apply_level(.8) is None
    assert not adapter.writes
    audio.take_media_baseline()
    assert audio.apply_level(.3) is None
    assert adapter.writes == [("10:1", pytest.approx(.3))]
    adapter.players = []
    assert "unavailable" in audio.apply_level(.9)
    assert "unavailable" in audio.check_transport_target()
    adapter.players = [PlayerSession("20:2", "Player", True, .7, False, descriptor["app_id"])]
    assert audio.apply_level(.9) is None
    assert len(adapter.writes) == 1
    adapter.players.append(PlayerSession("30:3", "Player", True, .1, False, descriptor["app_id"]))
    assert "ambiguous" in audio.apply_level(.9)
    assert "ambiguous" in audio.check_transport_target()
    with pytest.raises(ValueError, match="ambiguous"):
        audio.favorite_media_descriptor("20:2")


def test_windows_favorite_transport_never_emits_unpinned_global_keys():
    from triki_controller.output.windows_audio import WindowsAudio
    from triki_controller.output.windows_backend import WindowsOutputBackend
    from tests.test_windows_output import Input, state
    adapter = AudioAdapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0)
    favorite = favorite_selector(audio.favorite_media_descriptor("10:1"))
    inputs = Input()
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({"mode": "media", "media_player": favorite, "activation_epoch": 4})
    receipt = output.apply(state(pulses=("play_pause",)))
    assert not receipt.applied
    assert "targeted transport unavailable" in receipt.detail
    assert not inputs.calls


class MprisBus:
    def __init__(self):
        self.players = {"player.instance1": "org.example.Player"}
        self.calls = []
        self.generation = 1
        self.levels = {"player.instance1": .2, "player.instance2": .7}
        self.writes = []

    def _owners(self):
        return {player: f":1.{self.generation + index * 100}"
                for index, player in enumerate(self.players)}

    def _player_for_destination(self, destination):
        if destination.startswith(":"):
            return next(player for player, owner in self._owners().items()
                        if owner == destination)
        return destination.removeprefix("org.mpris.MediaPlayer2.")

    def __call__(self, argv, timeout):
        import subprocess
        self.calls.append(list(argv))
        if argv[-1] == "-l":
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.players), "")
        if "GetNameOwner" in argv:
            player = argv[-1].removeprefix("org.mpris.MediaPlayer2.")
            owner = self._owners().get(player)
            return subprocess.CompletedProcess(argv, 0 if owner else 1,
                                               f's "{owner}"' if owner else "", "")
        if "Set" in argv:
            player = self._player_for_destination(argv[3])
            self.writes.append((player, float(argv[-1])))
            self.levels[player] = float(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "get-property" in argv:
            player = self._player_for_destination(argv[3])
            if argv[-1] == "Volume":
                text = "d " + str(self.levels[player])
            else:
                text = 's "' + self.players.get(player, "") + '"'
            return subprocess.CompletedProcess(argv, 0, text, "")
        player = argv[2]
        if argv[3] == "volume":
            if len(argv) > 4:
                self.writes.append((player, float(argv[4])))
                self.levels[player] = float(argv[4])
            return subprocess.CompletedProcess(argv, 0, str(self.levels[player]), "")
        self.writes.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_mpris_desktop_entry_not_suffix_or_guessed_label(monkeypatch):
    from triki_controller.output.mpris_volume import MprisPlayerVolume
    monkeypatch.setattr("shutil.which", lambda name: name)
    bus = MprisBus()
    audio = MprisPlayerVolume(run=bus, playerctl_path="playerctl")
    descriptor = audio.favorite_media_descriptor("player.instance1")
    assert descriptor == {**FAVORITE, "label": "player.instance1"}
    assert not bus.writes
    audio.select_media_player(favorite_selector(descriptor))
    assert audio.apply_level(.8) is None and not bus.writes
    audio.take_media_baseline()
    assert audio.apply_level(.3) is None
    assert bus.writes == [("player.instance1", .3)]
    assert any("Set" in call and call[3] == ":1.1" for call in bus.calls)
    bus.generation = 2  # Same well-known bus name, restarted application.
    bus.levels["player.instance1"] = .6
    assert audio.apply_level(.9) is None
    assert len(bus.writes) == 1
    bus.players = {}
    assert "unavailable" in audio.apply_transport("play_pause")
    bus.players = {"player.instance2": "org.example.Player"}
    assert audio.apply_level(.9) is None
    assert len(bus.writes) == 1
    bus.players["other"] = "org.example.Player"
    assert "ambiguous" in audio.apply_level(.9)
    assert "ambiguous" in audio.apply_transport("play_pause")
    with pytest.raises(ValueError, match="ambiguous"):
        audio.favorite_media_descriptor("player.instance2")
    bus.players = {"player.instance1": ""}
    with pytest.raises(ValueError, match="DesktopEntry"):
        audio.favorite_media_descriptor("player.instance1")



def test_stream_discovery_addresses_captured_unique_owner():
    import subprocess
    from triki_controller.output.app_stream_volume import AppStreamVolume
    calls = []
    def run(argv, timeout):
        calls.append(argv)
        text = ('[{"index": 1, "properties": {"application.process.id": "123"}, '
                '"volume": {"front": {"value": 32768}}}]'
                if argv[-1] == "sink-inputs" else "u 123")
        return subprocess.CompletedProcess(argv, 0, text, "")
    stream = AppStreamVolume(run=run, busctl_path="busctl", pactl_path="pactl")
    assert stream.read_level(":1.22") == .5
    owner_calls = [call for call in calls if "GetConnectionUnixProcessID" in call]
    assert owner_calls[-1][-1] == ":1.22"


class MacAdapter:
    def __init__(self):
        self.running = True
        self.generation = 1
        self.writes = []

    def list_players(self):
        return ("Spotify",) if self.running else ()

    def player_identity(self, player):
        return "com.spotify.client", self.generation

    def read_player(self, player):
        return .6

    def write_player_target(self, player, identity, level):
        self.writes.append((player, identity, level))


def test_macos_bundle_identity_survives_restart_and_absence():
    from triki_controller.output.macos_audio import MacOSPlayerVolume
    adapter = MacAdapter()
    audio = MacOSPlayerVolume(adapter=adapter)
    descriptor = audio.favorite_media_descriptor("Spotify")
    assert descriptor == {"platform": "macos", "app_id": "com.spotify.client", "label": "Spotify"}
    audio.select_media_player(favorite_selector(descriptor))
    assert audio.apply_level(.2) is None and not adapter.writes
    adapter.running = False
    assert "unavailable" in audio.apply_level(.3)
    adapter.running = True
    adapter.generation = 2
    assert audio.apply_level(.9) is None and not adapter.writes
    with pytest.raises(ValueError, match="unavailable"):
        audio.favorite_media_descriptor("missing")


class Catalog(TraceOutput):
    def __init__(self):
        super().__init__()
        self.opens = []
        self.selections = []

    def open(self, capabilities):
        self.opens.append(dict(capabilities))
        super().open({**capabilities, "claim_uinput": False})

    def select_media_player(self, player):
        self.selections.append(player)

    def list_media_players(self):
        return [("player.instance1", "Player")]

    def favorite_media_descriptor(self, player):
        if player != "player.instance1":
            raise ValueError("selected player unavailable")
        return dict(FAVORITE)


@pytest.mark.parametrize("legacy", [None, "legacy"])
def test_session_startup_priority_and_manual_auto_override(legacy):
    catalog = Catalog()
    session = ControllerSession(settings=GuiSettings(media_player=legacy, media_favorite=FAVORITE), output_factory=lambda live: catalog)
    session._runtime.activate(live=True)
    assert catalog.opens[-1]["media_player"] == favorite_selector(FAVORITE)
    assert session.current_settings().media_player == legacy
    assert session.select_media_player(None) is None
    session._runtime.deactivate("test")
    session._runtime.activate(live=True)
    assert catalog.opens[-1]["media_player"] is None


def test_descriptor_discovery_failure_is_helpful_value_error():
    catalog = Catalog()
    def fail(player):
        raise RuntimeError("native discovery denied")
    catalog.favorite_media_descriptor = fail
    session = ControllerSession(output_factory=lambda live: catalog)
    with pytest.raises(ValueError, match="native discovery denied"):
        session.favorite_media_descriptor("player.instance1")
    assert not catalog.opens and not catalog.selections


def test_descriptor_observational_and_favorite_draft_detached():
    catalog = Catalog()
    session = ControllerSession(output_factory=lambda live: catalog)
    descriptor = session.favorite_media_descriptor("player.instance1")
    assert descriptor == FAVORITE
    assert not catalog.opens and not catalog.selections
    with pytest.raises(ValueError, match="unavailable"):
        session.favorite_media_descriptor("missing")
    session._runtime.activate(live=True)
    assert session.apply_settings(replace(session.current_settings(), media_favorite=descriptor)) is None
    assert len(catalog.opens) == 1 and not catalog.selections
    descriptor["label"] = "changed"
    detached = session.current_settings()
    assert detached.media_favorite == FAVORITE
    detached.media_favorite["label"] = "changed again"
    assert session.current_settings().media_favorite == FAVORITE


def test_favorite_schema_one_roundtrip_detached(tmp_path):
    source = dict(FAVORITE)
    settings = GuiSettings(media_player="old.instance12", media_favorite=source)
    parsed = parse_settings(settings.to_json())
    source["label"] = "mutated"
    assert parsed.media_favorite == FAVORITE
    path = tmp_path / "settings.json"
    save_settings(parsed, path)
    assert load_settings(path).media_favorite == FAVORITE
    assert parse_settings({"schema_version": 1}).media_favorite is None


@pytest.mark.parametrize("favorite", ["player", {}, {**FAVORITE, "app_id": ""}, {**FAVORITE, "platform": "guess"}, {**FAVORITE, "pid": "123"}])
def test_invalid_favorite_rejected(favorite):
    with pytest.raises(SettingsError, match="media_favorite"):
        parse_settings({"schema_version": 1, "media_favorite": favorite})
