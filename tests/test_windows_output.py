"""Windows output contract tests; no Windows native validation implied."""
from triki_controller.core.models import MappedState, PipelineStageStatus
from triki_controller.output.windows_backend import WindowsOutputBackend


class Audio:
    def __init__(self):
        self.calls = []
    def apply_level(self, value):
        self.calls.append(('player', value))
    def apply_offset(self, value):
        self.calls.append(('system', value))
    def leave(self):
        self.calls.append(('leave',))
    def apply_pulse(self, pulse):
        self.calls.append(('pulse', pulse))
    def read_volume(self):
        return .7
    def close(self):
        pass


class Input:
    def __init__(self):
        self.calls = []
    def button(self, name, down):
        self.calls.append(('button', name, down))
    def transport(self, name):
        self.calls.append(('transport', name))
    def relative(self, x, y):
        self.calls.append(('relative', x, y))
    def absolute(self, x, y):
        self.calls.append(('absolute', x, y))
    def close(self):
        pass


def test_sendinput_native_mouse_and_transport_events():
    from triki_controller.output.windows_input import WindowsInput
    events = []
    def send(items):
        events.extend(items)
        return len(items)
    inputs = WindowsInput(send_input=send)
    inputs.relative(3, -4)
    inputs.absolute(-1, 1)
    inputs.button('mouse_left', True)
    inputs.button('mouse_left', False)
    inputs.transport('play_pause')
    assert (events[0].mi.dx, events[0].mi.dy) == (3, -4)
    assert (events[1].mi.dx, events[1].mi.dy, events[1].mi.dwFlags) == (0, 65535, 0xc001)
    assert [events[2].mi.dwFlags, events[3].mi.dwFlags] == [2, 4]
    assert [events[4].ki.wVk, events[5].ki.wVk, events[5].ki.dwFlags] == [0xb3, 0xb3, 2]


def state(**kw):
    values = dict(schema_version=1, raw_session_id='s', raw_connection_epoch=3,
                  raw_sample_seq=9, profile_id='media', profile_revision='1',
                  activation_epoch=4, held_buttons=(), held_keys=(),
                  absolute_axes={}, relative_deltas={},
                  stage_status=PipelineStageStatus.AVAILABLE)
    values.update(kw)
    return MappedState(**values)


def test_player_axis_does_not_touch_default_endpoint():
    audio, inputs = Audio(), Input()
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({'mode': 'media', 'activation_epoch': 4})
    receipt = output.apply(state(absolute_axes={'player_volume': .8, 'knob': .3}))
    assert receipt.applied
    assert ('player', .8) in audio.calls
    assert not any(call[0] == 'system' for call in audio.calls)
    assert receipt.backend == 'windows'
    assert (receipt.raw_session_id, receipt.raw_connection_epoch, receipt.raw_sample_seq) == ('s', 3, 9)


def test_backend_neutralize_releases_failed_transport_key_without_volume_restore():
    from triki_controller.output.windows_input import WindowsInput
    events = []
    fail_up = [True]
    def send(items):
        event = items[0]
        if event.type == 1 and event.ki.dwFlags == 2 and fail_up[0]:
            fail_up[0] = False
            return 0
        events.extend(items)
        return 1
    audio = Audio()
    inputs = WindowsInput(send_input=send)
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({'mode': 'media', 'activation_epoch': 4})
    receipt = output.apply(state(pulses=('play_pause',)))
    assert not receipt.applied
    assert output.neutralize('disconnect').applied
    assert [e.ki.dwFlags for e in events] == [0, 2]
    assert not any(c[0] in {'player', 'system'} for c in audio.calls)


def test_backend_epoch_guard_and_system_only_mapped_offset():
    audio, inputs = Audio(), Input()
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({'mode': 'media', 'activation_epoch': 4})
    assert not output.apply(state(activation_epoch=3, pulses=('mute',))).applied
    assert audio.calls == []
    assert output.apply(state(absolute_axes={'system_volume': .25})).applied
    assert audio.calls == [('system', .25)]
    assert output.apply(state(absolute_axes={'player_volume': .8})).applied
    assert audio.calls[-1] == ('leave',)
    receipt = output.neutralize('disconnect')
    assert receipt.activation_epoch == 5
    assert receipt.neutralization_reason == 'disconnect'
    assert not output.apply(state()).applied


def test_failed_player_level_does_not_emit_volume_keys_or_master_write():
    class Failing(Audio):
        def apply_level(self, value):
            return 'no app audio session'
    audio, inputs = Failing(), Input()
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({'mode': 'media', 'activation_epoch': 4})
    receipt = output.apply(state(absolute_axes={'player_volume': .8}, pulses=('next_track',)))
    assert not receipt.applied
    assert receipt.stage_status is PipelineStageStatus.ERROR
    assert 'no app audio session' in receipt.detail
    assert inputs.calls == [('transport', 'next_track')]
    assert not any(c[0] == 'system' for c in audio.calls)


def test_mouse_fractional_motion_and_neutralization_release():
    audio, inputs = Audio(), Input()
    output = WindowsOutputBackend(audio=audio, input_adapter=inputs)
    output.open({'mode': 'mouse', 'activation_epoch': 4})
    sample = state(relative_deltas={'pointer_x': .6, 'pointer_y': -.6}, held_buttons=('mouse_left',))
    assert output.apply(sample).applied
    assert output.apply(sample).applied
    assert inputs.calls == [('button', 'mouse_left', True), ('relative', 1, -1)]
    assert output.neutralize('lost connection').applied
    assert inputs.calls[-1] == ('button', 'mouse_left', False)
    assert not any(c[0] in {'player', 'system'} for c in audio.calls)


def test_release_failure_is_reported_and_retried():
    class Failing(Input):
        failed = False
        def button(self, name, down):
            if not down and not self.failed:
                self.failed = True
                raise RuntimeError('UIPI')
            super().button(name, down)
    inputs = Failing()
    output = WindowsOutputBackend(input_adapter=inputs)
    output.open({'mode': 'mouse', 'activation_epoch': 4})
    output.apply(state(held_buttons=('mouse_left',)))
    assert not output.neutralize('lost').applied
    assert output.neutralize('retry').applied
    assert inputs.calls[-1] == ('button', 'mouse_left', False)


def test_mouse_pulse_releases_on_next_neutralize_if_keyup_failed():
    class Failing(Input):
        failed = False
        def button(self, name, down):
            if not down and not self.failed:
                self.failed = True
                raise RuntimeError('blocked')
            super().button(name, down)
    inputs = Failing()
    output = WindowsOutputBackend(input_adapter=inputs)
    output.open({'mode': 'mouse', 'activation_epoch': 4})
    assert not output.apply(state(pulses=('mouse_right',))).applied
    assert output.neutralize('stop').applied
    assert inputs.calls[-1] == ('button', 'mouse_right', False)


def test_modes_requiring_driver_are_explicitly_unavailable():
    import pytest
    for mode in ('plane', 'steering'):
        with pytest.raises(RuntimeError, match='driver'):
            WindowsOutputBackend().open({'mode': mode})


def test_modules_import_without_linux_or_windows_dependencies():
    import subprocess
    import sys
    code = '''
import sys
from triki_controller.output.windows_backend import WindowsOutputBackend
import triki_controller.output.windows_audio
import triki_controller.output.windows_input
assert not {'evdev', 'pycaw', 'comtypes', 'pywayland'} & set(sys.modules)
assert 'triki_controller.output.uinput_backend' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sendinput_structures_have_windows_abi_sizes():
    import ctypes
    from triki_controller.output.windows_input import INPUT, MOUSEINPUT, KEYBDINPUT
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(INPUT) == 40
        assert ctypes.sizeof(MOUSEINPUT) == 32
        assert ctypes.sizeof(KEYBDINPUT) == 24
    else:
        assert ctypes.sizeof(INPUT) == 28
        assert ctypes.sizeof(MOUSEINPUT) == 24
        assert ctypes.sizeof(KEYBDINPUT) == 16


def test_native_input_rejects_volume_transport_and_nonfinite_pointer():
    import pytest
    from triki_controller.output.windows_input import WindowsInput
    events = []
    inputs = WindowsInput(send_input=lambda items: events.extend(items) or len(items))
    with pytest.raises(ValueError, match='transport'):
        inputs.transport('volume_up')
    with pytest.raises(ValueError, match='non-finite'):
        inputs.absolute(float('nan'), 0)
    assert events == []


def test_recenter_runtime_baseline_read_discards_old_target_mapping_offset():
    import pytest
    from tests.test_windows_audio import Adapter
    from triki_controller.output.windows_audio import WindowsAudio
    from triki_controller.profiles.builtin import profile_by_name
    from triki_controller.runtime.emulator import EmulatorRuntime
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    backend = WindowsOutputBackend(audio=audio, input_adapter=Input())
    runtime = EmulatorRuntime(profile_by_name('media'), backend)
    runtime.activate(live=True)
    runtime.recenter()
    epoch = runtime._epoch
    assert backend.apply(state(activation_epoch=epoch, absolute_axes={'player_volume': .7})).applied
    assert backend.apply(state(activation_epoch=epoch, pulses=('cycle_player',),
                               absolute_axes={'player_volume': .7})).applied
    assert backend.apply(state(activation_epoch=epoch, absolute_axes={'player_volume': .8})).applied
    assert adapter.players[0].volume == pytest.approx(.5)
    runtime.recenter()
    baseline = runtime.mapper._volume
    assert baseline == pytest.approx(.5)
    assert backend.apply(state(activation_epoch=epoch, absolute_axes={'player_volume': baseline})).applied
    assert adapter.players[0].volume == pytest.approx(.5)
    assert backend.apply(state(activation_epoch=epoch, absolute_axes={'player_volume': baseline + .1})).applied
    assert adapter.players[0].volume == pytest.approx(.6)
    runtime.deactivate('done')


def test_failed_open_closes_allocated_input_and_retains_failed_cleanup_for_retry(monkeypatch):
    import pytest
    from triki_controller.output import windows_input, windows_audio
    created = []
    class OwnedInput(Input):
        blocked = True
        def __init__(self):
            super().__init__()
            created.append(self)
        def close(self):
            self.calls.append(('close',))
            if self.blocked:
                raise RuntimeError('input close denied')
    def fail_audio():
        raise RuntimeError('audio construction denied')
    monkeypatch.setattr(windows_input, 'WindowsInput', OwnedInput)
    monkeypatch.setattr(windows_audio, 'WindowsAudio', fail_audio)
    output = WindowsOutputBackend()
    with pytest.raises(RuntimeError, match='audio construction denied.*input close denied'):
        output.open({'mode': 'media'})
    assert not output.opened
    assert output.input is created[0]
    assert created[0].calls == [('close',)]
    created[0].blocked = False
    output.close()
    output.close()
    assert output.input is None
    assert created[0].calls == [('close',), ('close',)]


def test_close_attempts_independent_owned_resources_when_audio_close_fails(monkeypatch):
    import pytest
    from triki_controller.output import windows_input, windows_audio
    class OwnedAudio(Audio):
        blocked = True
        def close(self):
            self.calls.append(('close',))
            if self.blocked:
                raise RuntimeError('audio close denied')
    class OwnedInput(Input):
        def close(self):
            self.calls.append(('close',))
    audio, inputs = OwnedAudio(), OwnedInput()
    monkeypatch.setattr(windows_input, 'WindowsInput', lambda: inputs)
    monkeypatch.setattr(windows_audio, 'WindowsAudio', lambda: audio)
    output = WindowsOutputBackend()
    output.open({'mode': 'media'})
    with pytest.raises(RuntimeError, match='audio close denied'):
        output.close()
    assert inputs.calls == [('close',)]
    assert output.input is None
    assert output.audio is audio
    audio.blocked = False
    output.close()
    output.close()
    assert output.audio is None


def test_reactivation_and_recenter_pulse_preserve_actual_volume():
    import pytest
    from tests.test_windows_audio import Adapter
    from triki_controller.output.windows_audio import WindowsAudio
    adapter = Adapter()
    audio = WindowsAudio(adapter=adapter, scan_interval=0, write_interval=0)
    output = WindowsOutputBackend(audio=audio, input_adapter=Input())
    output.open({'mode': 'media', 'activation_epoch': 4})
    output.apply(state(absolute_axes={'player_volume': .7}, pulses=('cycle_player',)))
    output.apply(state(absolute_axes={'player_volume': .8}))
    assert audio.read_volume() == pytest.approx(.5)
    output.close()
    output.open({'mode': 'media', 'activation_epoch': 4})
    assert output.apply(state(absolute_axes={'player_volume': .5})).applied
    assert audio.read_volume() == pytest.approx(.5)
    assert output.apply(state(absolute_axes={'player_volume': .6})).applied
    assert audio.read_volume() == pytest.approx(.6)
    assert output.apply(state(absolute_axes={'player_volume': .6}, pulses=('recenter',))).applied
    assert audio.read_volume() == pytest.approx(.6)
    assert output.apply(state(absolute_axes={'player_volume': .7})).applied
    assert audio.read_volume() == pytest.approx(.7)
    output.close()


def test_partial_allocation_cleanup_attempts_both_errors_and_retries_each(monkeypatch):
    import pytest
    from triki_controller.output import windows_input, windows_audio
    class OwnedAudio(Audio):
        blocked = True
        def close(self):
            self.calls.append(('close',))
            if self.blocked:
                raise RuntimeError('audio cleanup fault')
    class OwnedInput(Input):
        blocked = True
        def close(self):
            self.calls.append(('close',))
            if self.blocked:
                raise RuntimeError('input cleanup fault')
    audio, inputs = OwnedAudio(), OwnedInput()
    monkeypatch.setattr(windows_audio, 'WindowsAudio', lambda: audio)
    monkeypatch.setattr(windows_input, 'WindowsInput', lambda: inputs)
    output = WindowsOutputBackend()
    with pytest.raises(RuntimeError, match='audio cleanup fault.*input cleanup fault'):
        output.open({'mode': 'media', 'activation_epoch': 'invalid'})
    assert not output.opened
    assert output.audio is audio and output.input is inputs
    assert audio.calls == inputs.calls == [('close',)]
    audio.blocked = False
    inputs.blocked = False
    output.close()
    output.close()
    assert output.audio is None and output.input is None
    assert audio.calls == inputs.calls == [('close',), ('close',)]


def test_audio_leave_failure_does_not_block_independent_input_close(monkeypatch):
    import pytest
    from triki_controller.output import windows_input, windows_audio
    class OwnedAudio(Audio):
        def leave(self):
            raise RuntimeError('audio leave fault')
    class OwnedInput(Input):
        def close(self):
            self.calls.append(('close',))
    audio, inputs = OwnedAudio(), OwnedInput()
    monkeypatch.setattr(windows_audio, 'WindowsAudio', lambda: audio)
    monkeypatch.setattr(windows_input, 'WindowsInput', lambda: inputs)
    output = WindowsOutputBackend()
    output.open({'mode': 'media'})
    with pytest.raises(RuntimeError, match='audio leave fault'):
        output.close()
    assert inputs.calls == [('close',)]
    assert not output.opened and output.closed
    output.close()


def test_owned_pending_release_survives_failed_close_and_disables_dispatch(monkeypatch):
    import pytest
    from triki_controller.output import windows_input
    class OwnedInput(Input):
        blocked = True
        def button(self, name, down):
            if not down and self.blocked:
                raise RuntimeError('release denied')
            super().button(name, down)
        def close(self):
            self.calls.append(('close',))
    inputs = OwnedInput()
    monkeypatch.setattr(windows_input, 'WindowsInput', lambda: inputs)
    output = WindowsOutputBackend()
    output.open({'mode': 'mouse', 'activation_epoch': 4})
    assert output.apply(state(held_buttons=('mouse_left',))).applied
    with pytest.raises(RuntimeError, match='release denied'):
        output.close()
    assert output.input is inputs
    assert ('close',) not in inputs.calls
    with pytest.raises(RuntimeError, match='not open'):
        output.apply(state())
    inputs.blocked = False
    output.close()
    output.close()
    assert inputs.calls == [('button', 'mouse_left', True),
                            ('button', 'mouse_left', False), ('close',)]
    assert output.input is None
