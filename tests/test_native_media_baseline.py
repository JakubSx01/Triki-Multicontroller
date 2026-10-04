"""Runtime + real mapper/filter handshake; inert audio, NOT native validation."""
from dataclasses import replace

import pytest

from triki_controller.core.models import PipelineStageStatus
from triki_controller.output.macos_backend import MacOSOutputBackend
from triki_controller.output.windows_audio import Endpoint, PlayerSession, WindowsAudio
from triki_controller.output.windows_backend import WindowsOutputBackend
from triki_controller.profiles.builtin import profile_by_name
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.runtime.synthetic import make_raw, pose_level


class AudioAdapter:
    """Scalar native boundary supporting both backends without OS calls."""
    def __init__(self):
        self.players = {'a': .9, 'b': .23}
        self.generations = {'a': 1, 'b': 1}
        self.muted = set()
        self.endpoint = Endpoint('speakers', .4)
        self.writes = []
        self.fail_write = False

    def sessions(self):
        return tuple(PlayerSession(f'{key}:{self.generations[key]}', key, key == 'a',
                                   level, key in self.muted)
                     for key, level in self.players.items())

    def set_player(self, key, level):
        self.write_player_target(key.split(':')[0], None, level)

    def set_mute(self, key, muted):
        key = key.split(':')[0]
        if muted:
            self.muted.add(key)
        else:
            self.muted.discard(key)

    def default_endpoint(self):
        return self.endpoint

    def set_endpoint(self, key, level):
        self.writes.append(('system', key, level))
        self.endpoint = Endpoint(key, level)

    def list_players(self):
        return tuple(self.players)

    def player_identity(self, player):
        return player, self.generations[player]

    def read_player(self, player):
        return self.players[player]

    def write_player_target(self, player, identity, level):
        if self.fail_write:
            raise RuntimeError('player write denied')
        self.writes.append(('player', player, level))
        self.players[player] = level

    def read_system_endpoint(self):
        return self.endpoint.key, self.endpoint.volume

    def write_system_endpoint(self, key, level):
        self.set_endpoint(key, level)

    def transport(self, *args):
        pass

    def close(self):
        pass


class Input:
    def neutralize(self):
        pass

    def close(self):
        pass


class Harness:
    def __init__(self, platform):
        self.adapter = AudioAdapter()
        if platform == 'windows':
            self.audio = WindowsAudio(adapter=self.adapter, scan_interval=0, write_interval=0)
            self.backend = WindowsOutputBackend(audio=self.audio, input_adapter=Input())
        else:
            self.backend = MacOSOutputBackend(audio=self.adapter, input_adapter=Input())
            self.audio = self.backend.player
        self.runtime = EmulatorRuntime(profile_by_name('media'), self.backend)
        self.seq = 0
        self.runtime.activate(live=True)
        for _ in range(12):
            self.frame()

    def frame(self, rate=0, accel=None):
        self.seq += 1
        return self.runtime.feed(make_raw(accel=pose_level() if accel is None else accel,
                                         gyro=(0, 0, -int(rate * 131)), seq=self.seq,
                                         t_ns=self.seq * 20_000_000))

    def twist(self, direction, frames=400):
        for _ in range(frames):
            step = self.frame(25 * direction)
            assert step.receipt.applied, step.receipt.detail
        return step


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_baseline_hook_failure_is_visible_without_escaping_dispatch(platform):
    h = Harness(platform)
    def broken_hook():
        raise RuntimeError('baseline unavailable')
    setattr(h.runtime.output, 'take_media_baseline', broken_hook)
    step = h.frame()
    assert step.receipt is not None
    assert not step.receipt.applied
    assert 'baseline unavailable' in (step.receipt.detail or '')
    h.runtime.deactivate('done')


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_failed_apply_does_not_consume_native_baseline(platform):
    h = Harness(platform)
    calls = []
    setattr(h.runtime.output, 'take_media_baseline', lambda: calls.append('consumed'))
    h.adapter.players.clear()
    step = h.frame()
    assert step.receipt is not None
    assert not step.receipt.applied
    assert calls == []
    h.runtime.deactivate('done')


@pytest.mark.parametrize('platform', ['windows', 'macos'])
@pytest.mark.parametrize('transition', ['cycle', 'late', 'restart'])
def test_target_change_reseeds_endless_knob_full_range_without_jump(platform, transition):
    h = Harness(platform)
    h.twist(1)  # Old mapper is saturated at 100%.
    assert h.adapter.players['a'] == pytest.approx(1)
    if transition == 'cycle':
        assert h.audio.apply_pulse('cycle_player') is None
        target = 'b'
    else:
        h.adapter.players.clear()
        assert not h.frame().receipt.applied
        h.adapter.players = {'a': .23}
        if transition == 'restart':
            h.adapter.generations['a'] += 1
        target = 'a'
    before = len(h.adapter.writes)
    assert h.frame().receipt.applied  # New target's first safe frame is read-only.
    assert len(h.adapter.writes) == before
    assert h.adapter.players[target] == .23
    # set_media_baseline resets yaw: first subsequent moving sample is origin.
    first = h.frame(25)
    assert first.mapped.absolute_axes['player_volume'] == pytest.approx(.23)
    assert len(h.adapter.writes) == before
    h.twist(1)
    assert h.adapter.players[target] == pytest.approx(1)
    h.twist(-1)
    assert h.adapter.players[target] == pytest.approx(0)
    # Saturation discards unwind debt; slow reversal responds immediately.
    h.twist(1, frames=4)
    assert 0 < h.adapter.players[target] < .1
    assert not any(write[0] == 'system' for write in h.adapter.writes)
    h.runtime.deactivate('done')
