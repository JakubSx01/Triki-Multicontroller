"""Native controller contract regressions; all adapters are inert."""
from dataclasses import replace
import threading

import pytest

from triki_controller.core.models import MappedState, PipelineStageStatus
from triki_controller.output.windows_audio import PlayerSession, WindowsAudio
from triki_controller.output.windows_backend import WindowsOutputBackend


class InertInput:
    def __init__(self):
        self.calls = []

    def open(self):
        pass

    def key(self, name, down):
        self.calls.append((name, down))

    button = key

    def transport(self, pulse):
        self.calls.append(('global', pulse))

    def neutralize(self):
        pass

    def close(self):
        pass


class InertAudio:
    def __init__(self):
        self.players = [PlayerSession('42:123.5', 'Player', True, .7, False)]
        self.writes = []

    def sessions(self):
        return tuple(self.players)

    def set_player(self, *args):
        self.writes.append(args)
        raise AssertionError('unexpected player write')

    set_mute = set_player
    set_endpoint = set_player

    def close(self):
        pass


def state(**changes):
    baseline = MappedState(schema_version=1, raw_session_id='native-regression',
                           raw_connection_epoch=1, raw_sample_seq=1, profile_id='media',
                           profile_revision='1', activation_epoch=1, held_buttons=(),
                           held_keys=(), absolute_axes={}, relative_deltas={}, pulses=(),
                           stage_status=PipelineStageStatus.AVAILABLE)
    return replace(baseline, **changes)


@pytest.mark.parametrize('pulse', ['play_pause', 'next_track', 'previous_track'])
def test_missing_windows_manual_target_blocks_transport_without_writes(pulse):
    adapter = InertAudio()
    audio = WindowsAudio(adapter=adapter, scan_interval=0)
    input_adapter = InertInput()
    backend = WindowsOutputBackend(audio=audio, input_adapter=input_adapter)
    backend.open({'mode': 'media', 'activation_epoch': 1, 'media_player': 'missing'})
    try:
        receipt = backend.apply(state(pulses=(pulse,)))
        assert input_adapter.calls == []
        assert not receipt.applied
        assert 'missing' in (receipt.detail or '')
        assert adapter.writes == []
    finally:
        backend.close()


def test_windows_present_pin_uses_worker_identity_not_unreadable_volume():
    from triki_controller.output.windows_audio import PycawAudioAdapter, _CoreAudioRuntime

    threads = []

    class UnreadableSession:
        @property
        def SimpleAudioVolume(self):
            raise AssertionError('transport must not read volume')

    class InertRuntime(_CoreAudioRuntime):
        def __enter__(self):
            threads.append(threading.get_ident())
            return self

        def __exit__(self, *args):
            pass

        def _sessions(self):
            yield '42:123.5', 'Player', UnreadableSession()

    adapter = PycawAudioAdapter(runtime_factory=InertRuntime)
    audio = WindowsAudio(adapter=adapter)
    input_adapter = InertInput()
    backend = WindowsOutputBackend(audio=audio, input_adapter=input_adapter)
    backend.open({'mode': 'media', 'media_player': '42:123.5'})
    try:
        receipt = backend.apply(state(pulses=('play_pause',)))
        assert receipt.applied, receipt.detail
        assert input_adapter.calls == [('global', 'play_pause')]
        assert threads and all(t != threading.get_ident() for t in threads)
    finally:
        backend.close()
        audio.close()


class InertVolume:
    def leave(self):
        pass


def native_backend(platform, input_adapter):
    if platform == 'windows':
        return WindowsOutputBackend(input_adapter=input_adapter)
    from triki_controller.output.macos_backend import MacOSOutputBackend
    return MacOSOutputBackend(audio=object(), input_adapter=input_adapter,
                              player=InertVolume(), system=InertVolume())


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_native_direction_only_plane_default_button_is_inactive(platform):
    from triki_controller.core.models import MotionSample, QualityFlags
    from triki_controller.profiles.builtin import profile_by_name
    from triki_controller.profiles.devices import DeviceProfileMapper

    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({'plane': {'left': 'key_a'}})
    input_adapter = InertInput()
    backend = native_backend(platform, input_adapter)
    backend.open({'mode': 'plane', 'binding_only': True, 'claim_native': True,
                  'control_bindings': {'left': 'key_a'}, 'activation_epoch': 1})
    try:
        sample = MotionSample(1, 'native-regression', 1, 1, .02,
                              (0., 0., 9.8), (0., 0., 0.), None, None,
                              QualityFlags(), PipelineStageStatus.AVAILABLE,
                              True, 20000000, -45., 0., 0., 1.)
        pressed = replace(mapper.map(sample, profile_by_name('plane')), activation_epoch=1)
        assert 'trigger' in pressed.held_buttons
        assert 'key_a' in pressed.held_keys
        receipt = backend.apply(pressed)
        assert receipt.applied, receipt.detail
        released = replace(mapper.map(replace(sample, button=False, tilt_pitch_deg=0.,
                                               raw_sample_seq=2), profile_by_name('plane')),
                           activation_epoch=1)
        assert backend.apply(released).applied
        assert input_adapter.calls == [('key_a', True), ('key_a', False)]
    finally:
        backend.close()


@pytest.mark.parametrize('platform', ['windows', 'macos'])
@pytest.mark.parametrize('mode', ['plane', 'steering'])
@pytest.mark.parametrize('action', ['key_b', 'mouse_left'])
def test_native_configured_button_actions_are_pressed_and_released(platform, mode, action):
    from triki_controller.core.models import MotionSample, QualityFlags
    from triki_controller.profiles.builtin import profile_by_name
    from triki_controller.profiles.devices import DeviceProfileMapper

    mapper = DeviceProfileMapper()
    bindings = {'left': 'key_a', 'button': action}
    mapper.set_control_bindings({mode: bindings})
    input_adapter = InertInput()
    backend = native_backend(platform, input_adapter)
    backend.open({'mode': mode, 'binding_only': True, 'claim_native': True,
                  'control_bindings': bindings, 'activation_epoch': 1})
    try:
        sample = MotionSample(1, 'native-regression', 1, 1, .02,
                              (0., 0., 9.8), (0., 0., 0.), None, None,
                              QualityFlags(), PipelineStageStatus.AVAILABLE,
                              True, 20000000, 0., 0., 0., 1.)
        pressed = replace(mapper.map(sample, profile_by_name(mode)), activation_epoch=1)
        receipt = backend.apply(pressed)
        assert receipt.applied, receipt.detail
        released = replace(mapper.map(replace(sample, button=False, raw_sample_seq=2),
                                      profile_by_name(mode)), activation_epoch=1)
        assert backend.apply(released).applied
        assert input_adapter.calls == [(action, True), (action, False)]
    finally:
        backend.close()


@pytest.mark.parametrize('platform', ['windows', 'macos'])
@pytest.mark.parametrize('changes', [
    {'held_buttons': ('unknown_button',)},
    {'held_keys': ('trigger',)},
    {'pulses': ('trigger',)},
])
def test_native_binding_only_still_rejects_unknown_inputs(platform, changes):
    input_adapter = InertInput()
    backend = native_backend(platform, input_adapter)
    backend.open({'mode': 'plane', 'binding_only': True, 'claim_native': True,
                  'control_bindings': {'left': 'key_a'}})
    try:
        receipt = backend.apply(state(**changes))
        assert not receipt.applied
        assert 'unsupported' in (receipt.detail or '')
        assert input_adapter.calls == []
    finally:
        backend.close()


@pytest.mark.parametrize('platform', ['windows', 'macos'])
@pytest.mark.parametrize('mode', ['plane', 'steering'])
def test_native_unbound_analog_modes_still_require_virtual_hid(platform, mode):
    backend = native_backend(platform, InertInput())
    with pytest.raises(RuntimeError, match='virtual'):
        backend.open({'mode': mode, 'claim_native': True, 'binding_only': True})


def test_windows_auto_transport_does_not_require_sessions_or_volume():
    class NoDiscovery(InertAudio):
        def sessions(self):
            raise AssertionError('Auto global transport must not require audio sessions')

    adapter = NoDiscovery()
    audio = WindowsAudio(adapter=adapter)
    input_adapter = InertInput()
    backend = WindowsOutputBackend(audio=audio, input_adapter=input_adapter)
    backend.open({'mode': 'media', 'media_player': None})
    try:
        assert backend.apply(state(pulses=('play_pause',))).applied
        assert input_adapter.calls == [('global', 'play_pause')]
        assert adapter.writes == []
    finally:
        backend.close()


def test_windows_pin_disappearance_reappearance_and_auto_keep_exact_identity():
    adapter = InertAudio()
    audio = WindowsAudio(adapter=adapter, scan_interval=0)
    input_adapter = InertInput()
    backend = WindowsOutputBackend(audio=audio, input_adapter=input_adapter)
    backend.open({'mode': 'media', 'media_player': '42:123.5'})
    try:
        assert audio.apply_level(.4) is None
        assert backend.apply(state(pulses=('play_pause',))).applied
        # Observational transport discovery must not consume/reset the baseline.
        assert backend.take_media_baseline() == .7
        original = adapter.players.pop()
        adapter.players.append(replace(original, key='42:999.0'))
        receipt = backend.apply(state(pulses=('next_track',)))
        assert not receipt.applied
        assert '42:123.5' in (receipt.detail or '')
        assert input_adapter.calls == [('global', 'play_pause')]
        adapter.players.append(original)
        assert backend.apply(state(pulses=('previous_track',))).applied
        backend.select_media_player(None)
        adapter.players.clear()
        assert backend.apply(state(pulses=('next_track',))).applied
        assert input_adapter.calls == [('global', 'play_pause'),
                                       ('global', 'previous_track'), ('global', 'next_track')]
        assert adapter.writes == []
    finally:
        backend.close()


def test_windows_discovery_failure_is_not_reported_as_missing_or_emitted():
    class FailedDiscovery(InertAudio):
        def player_available(self, key):
            raise RuntimeError('enumeration denied')

    adapter = FailedDiscovery()
    input_adapter = InertInput()
    backend = WindowsOutputBackend(audio=WindowsAudio(adapter=adapter), input_adapter=input_adapter)
    backend.open({'mode': 'media', 'media_player': '42:123.5'})
    try:
        receipt = backend.apply(state(pulses=('play_pause',)))
        assert not receipt.applied
        assert 'discovery failed' in (receipt.detail or '')
        assert 'enumeration denied' in (receipt.detail or '')
        assert 'unavailable' not in (receipt.detail or '')
        assert input_adapter.calls == []
        assert adapter.writes == []
    finally:
        backend.close()
