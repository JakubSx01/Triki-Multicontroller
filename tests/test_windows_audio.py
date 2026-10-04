"""Core Audio control seam, tested using scalar-only adapters."""
import pytest
from triki_controller.output.windows_audio import WindowsAudio, PlayerSession, Endpoint


class Adapter:
    def __init__(self):
        self.players = [PlayerSession('b', 'Paused', False, .4, False),
                        PlayerSession('a', 'Active', True, .7, False)]
        self.endpoint = Endpoint('speakers', .3)
        self.calls = []
    def sessions(self):
        self.calls.append(('scan',))
        return tuple(self.players)
    def set_player(self, key, level):
        self.calls.append(('player', key, level))
        self.players = [PlayerSession(p.key, p.name, p.active, level if p.key == key else p.volume,
                                      p.muted) for p in self.players]
    def set_mute(self, key, muted):
        self.calls.append(('mute', key, muted))
        self.players = [PlayerSession(p.key, p.name, p.active, p.volume,
                                     muted if p.key == key else p.muted) for p in self.players]
    def default_endpoint(self):
        return self.endpoint
    def set_endpoint(self, key, level):
        self.calls.append(('system', key, level))
        self.endpoint = Endpoint(key, level)
    def close(self):
        pass


def test_target_generation_cycle_rebases_same_frame_and_follows_delta():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.7) is None
    assert audio.apply_pulse('cycle_player') is None
    assert audio.apply_level(.7) is None
    assert adapter.players[0].volume == .4
    assert audio.apply_level(.8) is None
    assert adapter.players[0].volume == pytest.approx(.5)
    assert not any(c[0] == 'system' for c in adapter.calls)


def test_late_player_rebases_default_mapper_level_and_follows_delta():
    adapter = Adapter()
    adapter.players = []
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.5)
    adapter.players = [PlayerSession('new', 'New', True, .23, False)]
    assert audio.apply_level(.5) is None
    assert adapter.players[0].volume == .23
    assert audio.apply_level(.6) is None
    assert adapter.players[0].volume == pytest.approx(.33)


def test_player_volume_is_session_only_and_active_first():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.read_volume() == .7
    assert audio.apply_level(.7) is None  # First frame captures the mapped origin.
    assert audio.apply_level(.9) is None
    assert ('player', 'a', pytest.approx(.9)) in adapter.calls
    assert not any(call[0] == 'system' for call in adapter.calls)


@pytest.mark.parametrize('transition', ['active_change', 'restart', 'disappearance'])
def test_automatic_target_generation_rebases_actual_then_tracks_delta(transition):
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.7) is None
    assert audio.apply_level(.8) is None
    if transition == 'active_change':
        adapter.players = [PlayerSession('a', 'Active', False, .8, False),
                           PlayerSession('b', 'Paused', True, .23, False)]
    elif transition == 'restart':
        adapter.players = [PlayerSession('a:new-start-time', 'Active', True, .23, False)]
    else:
        adapter.players = []
        assert audio.apply_level(.9)
        adapter.players = [PlayerSession('a', 'Active', True, .23, False)]
    before = len([c for c in adapter.calls if c[0] == 'player'])
    assert audio.apply_level(.9) is None
    assert len([c for c in adapter.calls if c[0] == 'player']) == before
    assert audio.read_volume() == .23
    assert audio.apply_level(.8) is None
    assert audio.read_volume() == pytest.approx(.13)
    assert not any(c[0] == 'system' for c in adapter.calls)


@pytest.mark.parametrize('external', [False, True])
def test_unmute_discards_twists_during_mute_and_rebases_without_jump(external):
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.7) is None
    assert audio.apply_level(.8) is None
    if external:
        adapter.set_mute('a', True)
    else:
        assert audio.apply_pulse('mute') is None
    assert audio.apply_level(.2) is None
    assert audio.apply_level(.3) is None
    assert audio.read_volume() == pytest.approx(.8)
    if external:
        adapter.set_mute('a', False)
    else:
        assert audio.apply_pulse('mute') is None
    assert audio.apply_level(.3) is None
    assert audio.read_volume() == pytest.approx(.8)
    assert audio.apply_level(.2) is None
    assert audio.read_volume() == pytest.approx(.7)


def test_status_poll_and_read_do_not_discard_mapping_offset():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.7) is None
    assert audio.apply_pulse('cycle_player') is None
    assert audio.apply_level(.7) is None
    assert audio.apply_level(.8) is None
    assert audio.describe_status().volume == pytest.approx(.5)
    assert audio.read_volume() == pytest.approx(.5)
    assert audio.apply_level(.9) is None
    assert audio.read_volume() == pytest.approx(.6)


def test_first_frame_captures_fresh_actual_volume_not_cached_baseline_read():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, clock=lambda: 0, write_interval=0)
    assert audio.read_volume() == .7
    adapter.players = [PlayerSession('a', 'Active', True, .23, False)]
    assert audio.apply_level(.5) is None
    assert audio.apply_level(.6) is None
    assert adapter.players[0].volume == pytest.approx(.33)


def test_pre_muted_late_player_is_not_unmuted_or_overwritten():
    adapter = Adapter()
    adapter.players = []
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    assert audio.apply_level(.5)
    adapter.players = [PlayerSession('new', 'New', True, .23, True)]
    assert audio.apply_level(.5) is None
    assert audio.apply_level(.8) is None
    assert adapter.players[0].volume == .23
    assert adapter.players[0].muted
    assert not any(c[0] in {'player', 'mute', 'system'} for c in adapter.calls)
    assert audio.apply_pulse('mute') is None
    assert audio.apply_level(.8) is None
    assert adapter.players[0].volume == .23
    assert audio.apply_level(.9) is None
    assert adapter.players[0].volume == pytest.approx(.33)


def test_system_entry_offset_clip_leave_and_endpoint_switch():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.apply_offset(.5) is None
    assert adapter.calls == []
    assert audio.apply_offset(.7) is None
    assert adapter.calls[-1] == ('system', 'speakers', pytest.approx(.5))
    assert audio.apply_offset(5) is None
    assert adapter.endpoint.volume == 1
    adapter.endpoint = Endpoint('headphones', .2)
    assert audio.apply_offset(5) is None
    assert len(adapter.calls) == 2
    assert audio.apply_offset(5.1) is None
    assert adapter.calls[-1] == ('system', 'headphones', pytest.approx(.3))
    audio.leave()
    assert not audio.active
    assert adapter.endpoint.volume == pytest.approx(.3)
    assert audio.apply_offset(1) is None
    assert len(adapter.calls) == 3


def test_cycle_pin_is_predictable_and_disappearing_pin_reselects():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, write_interval=0, scan_interval=0)
    assert audio.read_volume() == .7
    assert audio.apply_pulse('cycle_player') is None
    assert audio.read_volume() == .4
    assert audio.apply_level(.6) is None
    assert adapter.players[0].volume == .4
    assert audio.apply_level(.8) is None
    assert ('player', 'b', pytest.approx(.6)) in adapter.calls
    adapter.players = [adapter.players[1]]
    assert audio.read_volume() == .7
    assert audio.apply_level(.8) is None
    assert adapter.players[0].volume == .7
    assert audio.apply_level(.9) is None
    assert adapter.calls[-1] == ('player', 'a', pytest.approx(.8))


def test_mute_toggles_selected_app_without_changing_volume_or_system():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.apply_pulse('mute') is None
    assert ('mute', 'a', True) in adapter.calls
    assert audio.apply_level(.9) is None
    assert not any(c[0] == 'player' for c in adapter.calls)
    assert audio.apply_pulse('mute') is None
    assert ('mute', 'a', False) in adapter.calls
    assert audio.read_volume() == .7
    audio.leave()
    assert not any(c[0] == 'system' for c in adapter.calls)


def test_throttle_coalesces_latest_repeated_sample_and_caches_scans():
    now = [0.0]
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, clock=lambda: now[0])
    assert audio.apply_level(.7) is None
    assert audio.apply_level(.61) is None
    assert audio.apply_level(.8) is None
    assert adapter.calls == [('scan',)]
    now[0] = .05
    assert audio.apply_level(.8) is None
    assert adapter.calls[-1] == ('player', 'a', pytest.approx(.8))
    assert audio.apply_level(.803) is None
    assert len(adapter.calls) == 2
    now[0] = .5
    assert audio.apply_level(.9) is None
    assert adapter.calls.count(('scan',)) == 2


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_volume_and_offsets_are_rejected_without_writes(bad):
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter)
    assert audio.apply_level(bad)
    assert audio.apply_offset(bad)
    assert adapter.calls == []


def test_clipping_nudges_are_app_only():
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.apply_level(.7) is None
    assert audio.apply_level(9) is None
    assert adapter.calls[-1] == ('player', 'a', 1)
    assert audio.apply_pulse('volume_down') is None
    assert adapter.calls[-1] == ('player', 'a', .95)
    assert audio.apply_level(.7) is None  # Nudge establishes a fresh origin.
    assert audio.apply_level(-3) is None
    assert adapter.calls[-1] == ('player', 'a', 0)
    assert not any(c[0] == 'system' for c in adapter.calls)


def test_player_disconnect_reports_error_never_falls_back_and_retries():
    class Failing(Adapter):
        def set_player(self, key, value):
            if len(self.players) > 1:
                raise RuntimeError('AUDCLNT_E_DEVICE_INVALIDATED')
            super().set_player(key, value)
    adapter = Failing()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.apply_level(.7) is None
    assert 'INVALIDATED' in audio.apply_level(.8)
    assert not any(c[0] == 'system' for c in adapter.calls)
    adapter.players = [adapter.players[0]]
    assert audio.apply_level(.8) is None
    assert adapter.players[0].volume == .4
    assert audio.apply_level(.9) is None
    assert adapter.calls[-1] == ('player', 'b', pytest.approx(.5))


def test_no_players_is_explicit_and_never_touches_endpoint():
    adapter = Adapter()
    adapter.players = []
    audio = WindowsAudio(adapter=adapter)
    assert audio.read_volume() is None
    assert 'no running' in audio.apply_level(.5)
    assert 'no running' in audio.apply_pulse('mute')
    assert not any(c[0] == 'system' for c in adapter.calls)


def test_endpoint_write_failure_rebases_next_entry_read_only():
    class Failing(Adapter):
        def set_endpoint(self, key, value):
            raise RuntimeError('endpoint disconnected')
    adapter = Failing()
    audio = WindowsAudio(adapter=adapter, write_interval=0)
    assert audio.apply_offset(0) is None
    assert 'disconnected' in audio.apply_offset(.2)
    assert not audio.active
    adapter.endpoint = Endpoint('new', .7)
    assert audio.apply_offset(.2) is None
    assert adapter.endpoint.volume == .7


def test_native_adapter_serializes_cross_thread_calls_and_balances_apartment():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from triki_controller.output.windows_audio import PycawAudioAdapter
    events = []
    class Runtime:
        def __enter__(self):
            events.append(('initialize', threading.get_ident()))
            return self
        def __exit__(self, *args):
            events.append(('uninitialize', threading.get_ident()))
        def sessions(self):
            events.append(('sessions', threading.get_ident()))
            return (PlayerSession('a', 'A', True, .5, False),)
        def set_player(self, key, value):
            events.append(('write', threading.get_ident()))
            raise RuntimeError('native failure')
    adapter = PycawAudioAdapter(runtime_factory=Runtime)
    with ThreadPoolExecutor(max_workers=2) as callers:
        results = list(callers.map(lambda _: adapter.sessions(), range(4)))
    assert all(result[0].volume == .5 for result in results)
    with pytest.raises(RuntimeError, match='native failure'):
        adapter.set_player('a', .6)
    adapter.close()
    assert len({thread for _, thread in events}) == 1
    assert events[0][1] != threading.get_ident()
    assert [name for name, _ in events].count('initialize') == 5
    assert [name for name, _ in events].count('uninitialize') == 5
    with pytest.raises(RuntimeError, match='closed'):
        adapter.sessions()


@pytest.fixture
def native_facade(monkeypatch):
    """Exercise native adapter API calls without claiming Windows execution."""
    import sys
    import threading
    import types
    from triki_controller.output.windows_audio import PycawAudioAdapter
    events = []
    class Process:
        def __init__(self, pid):
            self.pid = pid
        def create_time(self):
            return 123.0
        def name(self):
            return f'app-{self.pid}'
    class Volume:
        def __init__(self, level):
            self.level = level
            self.muted = False
        def GetMasterVolume(self):
            return self.level
        def SetMasterVolume(self, level, context):
            events.append(('session-volume', level, context))
            self.level = level
        def GetMute(self):
            return self.muted
        def SetMute(self, muted, context):
            events.append(('session-mute', muted, context))
            self.muted = bool(muted)
    class Session:
        def __init__(self, pid, active, level):
            self.ProcessId = pid
            self.State = active
            self.Process = Process(pid)
            self.SimpleAudioVolume = Volume(level)
        def QueryInterface(self, interface):
            return self
    class Enumerator:
        def __init__(self, sessions):
            self.sessions = sessions
        def GetCount(self):
            return len(self.sessions)
        def GetSession(self, index):
            return self.sessions[index]
    class Manager:
        def __init__(self, sessions):
            self.sessions = sessions
        def GetSessionEnumerator(self):
            return Enumerator(self.sessions)
    class EndpointVolume:
        level = .3
        def GetMasterVolumeLevelScalar(self):
            return self.level
        def SetMasterVolumeLevelScalar(self, level, context):
            events.append(('endpoint-volume', level, context))
            self.level = level
    class Device:
        def __init__(self, key, sessions):
            self.id = key
            self.AudioSessionManager = Manager(sessions)
            self.EndpointVolume = EndpointVolume()
    first = Session(11, 0, .4)
    second = Session(11, 1, .7)
    other = Session(22, 0, .2)
    system = Session(0, 1, .8)
    expired = Session(33, 2, .9)
    devices = [Device('speakers', [first, other, system, expired]),
               Device('headphones', [second])]
    default = [devices[0]]
    class Utilities:
        @staticmethod
        def GetAllDevices(*, data_flow, device_state):
            assert (data_flow, device_state) == (0, 1)
            return devices
        @staticmethod
        def GetSpeakers():
            return default[0]
    com = types.ModuleType('comtypes')
    com.CoInitializeEx = lambda flag: events.append(('init', flag, threading.get_ident()))
    com.CoUninitialize = lambda: events.append(('uninit', threading.get_ident()))
    pycaw = types.ModuleType('pycaw.pycaw')
    pycaw.AudioUtilities = Utilities
    pycaw.AudioSession = lambda control: control
    policy = types.ModuleType('pycaw.api.audiopolicy')
    policy.IAudioSessionControl2 = object()
    monkeypatch.setitem(sys.modules, 'comtypes', com)
    monkeypatch.setitem(sys.modules, 'pycaw', types.ModuleType('pycaw'))
    monkeypatch.setitem(sys.modules, 'pycaw.pycaw', pycaw)
    monkeypatch.setitem(sys.modules, 'pycaw.api', types.ModuleType('pycaw.api'))
    monkeypatch.setitem(sys.modules, 'pycaw.api.audiopolicy', policy)
    monkeypatch.setattr(sys, 'platform', 'win32')
    adapter = PycawAudioAdapter()
    yield adapter, events, first, second, other, default, devices
    adapter.close()


def test_native_session_enumeration_and_writes_cover_routed_audio_not_system(native_facade):
    adapter, events, first, second, other, _, _ = native_facade
    players = adapter.sessions()
    assert {p.key for p in players} == {'11:123.0', '22:123.0'}
    active = next(p for p in players if p.active)
    assert (active.key, active.volume) == ('11:123.0', .7)
    adapter.set_player(active.key, .9)
    assert first.SimpleAudioVolume.level == .9
    assert second.SimpleAudioVolume.level == .9
    assert other.SimpleAudioVolume.level == .2
    adapter.set_mute(active.key, True)
    assert first.SimpleAudioVolume.muted
    assert second.SimpleAudioVolume.muted
    assert not other.SimpleAudioVolume.muted
    assert not any(e[0] == 'endpoint-volume' for e in events)
    assert sum(e[0] == 'init' for e in events) == 3
    assert sum(e[0] == 'uninit' for e in events) == 3
    assert all(e[1] == 0 for e in events if e[0] == 'init')


def test_native_default_endpoint_switch_rejects_old_target(native_facade):
    adapter, events, _, _, _, default, devices = native_facade
    endpoint = adapter.default_endpoint()
    assert endpoint == Endpoint('speakers', .3)
    default[0] = devices[1]
    with pytest.raises(RuntimeError, match='endpoint changed'):
        adapter.set_endpoint(endpoint.key, .5)
    assert not any(e[0] == 'endpoint-volume' for e in events)
    adapter.set_endpoint('headphones', .6)
    assert devices[1].EndpointVolume.level == .6


def test_native_disconnected_player_does_not_fallback(native_facade):
    adapter, events, _, _, _, _, _ = native_facade
    with pytest.raises(RuntimeError, match='disconnected'):
        adapter.set_player('999:123.0', .5)
    assert not any(e[0] in {'session-volume', 'endpoint-volume'} for e in events)
