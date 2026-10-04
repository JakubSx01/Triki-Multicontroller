"""Public player picker tests using inert platform audio boundaries."""
import subprocess
import pytest
from triki_controller.output.windows_audio import WindowsAudio, PlayerSession
from triki_controller.output.macos_audio import MacOSPlayerVolume
from triki_controller.output.mpris_volume import MprisPlayerVolume

class WinAudio:
    def __init__(self):
        self.players = [PlayerSession('1:100', 'Music', True, .8, False), PlayerSession('2:200', 'Spotify', False, .2, False)]
        self.writes = []
    def sessions(self): return self.players
    def set_player(self, key, value): self.writes.append((key, value))
    def close(self): pass

class MacAudio:
    def __init__(self):
        self.players = ['Music', 'Spotify']
        self.writes = []
    def list_players(self): return tuple(self.players)
    def player_identity(self, name): return name, 123
    def read_player(self, name): return .8 if name == 'Music' else .2
    def write_player_target(self, name, identity, value): self.writes.append((name, value))

@pytest.fixture(params=['windows', 'macos'])
def player(request):
    if request.param == 'windows':
        adapter = WinAudio()
        obj = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
        ids = ['1:100', '2:200']
    else:
        adapter = MacAudio()
        obj = MacOSPlayerVolume(adapter=adapter)
        ids = ['Music', 'Spotify']
    return obj, adapter, ids

def test_list_is_observational_selection_rebases_first_frame(player):
    obj, adapter, ids = player
    obj.select_media_player(ids[0])
    assert obj.apply_level(.8) is None
    assert obj.take_media_baseline() == .8
    assert obj.list_media_players() == [(ids[0], 'Music'), (ids[1], 'Spotify')]
    assert obj.apply_level(.9) is None
    assert adapter.writes[-1][1] == pytest.approx(.9)
    obj.select_media_player(ids[1])
    count = len(adapter.writes)
    assert obj.apply_level(.9) is None
    assert len(adapter.writes) == count
    assert obj.take_media_baseline() == .2
    assert obj.apply_level(.3) is None
    assert adapter.writes[-1] == (ids[1], pytest.approx(.3))

def test_missing_explicit_selection_never_substitutes(player):
    obj, adapter, ids = player
    obj.select_media_player('missing:old-process')
    assert obj.read_volume() is None
    assert obj.apply_level(.6)
    assert 'unavailable' in obj.last_error
    assert adapter.writes == []
    obj.select_media_player(None)
    assert obj.read_volume() == .8

class Playerctl:
    def __init__(self): self.calls = []; self.players = ['vlc.instance1', 'spotify']
    def __call__(self, argv, timeout):
        self.calls.append(argv)
        command = argv[-1]
        output = '\n'.join(self.players) if command == '-l' else ('0.2' if command == 'volume' else 'Playing')
        return subprocess.CompletedProcess(argv, 0, output, '')

def test_linux_exact_identity_missing_target_is_not_replaced():
    run = Playerctl()
    obj = MprisPlayerVolume(run=run, playerctl_path='/inert/playerctl')
    obj.select_media_player('vlc.instance1')
    assert [entry[0] for entry in obj.list_media_players()] == run.players
    assert obj.read_volume() == .2
    run.players = ['spotify']
    assert obj.read_volume() is None
    assert obj.apply_level(.7)
    assert obj.apply_transport('play_pause')
    assert not any('-p' in c and c[c.index('-p') + 1] == 'spotify' and c[-1] in ['play-pause', '0.700'] for c in run.calls)
    obj.select_media_player(None)
    assert obj.read_volume() == .2


def test_linux_manual_target_first_frame_baseline_and_recenter_are_read_only():
    run = Playerctl()
    obj = MprisPlayerVolume(run=run, playerctl_path='/inert/playerctl')
    obj.select_media_player('spotify')
    assert obj.apply_level(.8) is None
    assert obj.take_media_baseline() == .2
    assert obj.apply_level(.3) is None
    assert ['/inert/playerctl', '-p', 'spotify', 'volume', '0.300'] in run.calls
    run.calls.clear()
    assert obj.read_volume() == .2  # Explicit recenter baseline read.
    assert obj.apply_level(.2) is None
    assert obj.take_media_baseline() == .2
    assert not any(c[-1] in {'0.200', '0.000', '1.000'} for c in run.calls)

@pytest.mark.parametrize('platform', ['windows', 'macos', 'linux'])
def test_backend_public_picker_pin_is_applied_before_initial_baseline(monkeypatch, platform):
    from triki_controller.output.windows_backend import WindowsOutputBackend
    from triki_controller.output.macos_backend import MacOSOutputBackend
    from triki_controller.output import uinput_backend
    from tests.test_output_bindings import Input, EvdevCodes, VirtualInput
    if platform == 'windows':
        adapter = WinAudio()
        obj = WindowsOutputBackend(audio=WindowsAudio(adapter=adapter), input_adapter=Input())
        pin = '2:200'
    elif platform == 'macos':
        obj = MacOSOutputBackend(audio=MacAudio(), input_adapter=Input())
        pin = 'Spotify'
    else:
        monkeypatch.setattr(uinput_backend, '_load_evdev', lambda: (EvdevCodes(), VirtualInput, lambda *a: a))
        obj = uinput_backend.UInputBackend(mpris=MprisPlayerVolume(run=Playerctl(), playerctl_path='/inert/playerctl'))
        pin = 'spotify'
    obj.select_media_player(pin)
    obj.open({'mode': 'media', 'media_player': pin, 'claim_native': True, 'claim_uinput': True})
    assert pin in dict(obj.list_media_players())
    assert obj.read_player_volume() == .2
    obj.select_media_player('unavailable-old-id')
    assert obj.read_player_volume() is None
    obj.close()
