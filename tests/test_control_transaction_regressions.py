"""Settings transactions and pinned Linux recovery; never real OS output."""
from dataclasses import replace
import subprocess

import evdev
import pytest


def deny_uinput(*args, **kwargs):
    raise AssertionError('REAL UInput FORBIDDEN')


evdev.UInput = deny_uinput

from triki_controller.core.models import MotionSample, PipelineStageStatus, QualityFlags
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.trace import TraceOutput
from triki_controller.output.windows_backend import WindowsOutputBackend
from triki_controller.output.mpris_volume import MprisPlayerVolume
from triki_controller.output.uinput_backend import UInputBackend
from triki_controller.profiles.builtin import profile_by_name
from triki_controller.runtime.emulator import EmulatorRuntime


class Input:
    def open(self): pass
    def neutralize(self): pass
    def close(self): pass
    def key(self, *args): pass
    button = key


def test_rejected_binding_edit_preserves_entire_accepted_transaction():
    old = GuiSettings(profile='steering', control_bindings={'steering': {'left': 'key_a'}})
    backend = WindowsOutputBackend(input_adapter=Input())
    session = ControllerSession(settings=old, output_factory=lambda live: backend)
    runtime = session._runtime
    runtime.activate(live=True)
    session._output_mode = OutputMode.LIVE
    accepted = session.current_settings()
    candidate = replace(accepted, control_bindings={}, media_gestures_enabled=False,
                        media_player='b', invert_pitch=True,
                        axis_map={'steering': {'wheel': 'roll'}},
                        thresholds={'steering': {'deadzone_deg': 7}})
    assert session.apply_settings(candidate)
    assert session.current_settings() == accepted
    assert runtime.control_bindings == accepted.control_bindings
    assert not runtime.active
    assert session.snapshot().output_mode == OutputMode.OFF
    assert session.snapshot().error


class RejectingOutput(TraceOutput):
    BACKEND_NAME = 'windows'
    def __init__(self):
        super().__init__()
        self.selected = 'a'
        self.fail_close = False
        self.opens = 0
    def open(self, cap):
        self.opens += 1
        if cap['mode'] == 'plane':
            raise RuntimeError('candidate profile rejected')
        super().open({**cap, 'claim_uinput': False})
        self.select_media_player(cap.get('media_player'))
    def select_media_player(self, player):
        self.selected = player
        if player == 'b':
            raise RuntimeError('partial selection failure')
    def close(self):
        if self.fail_close:
            raise RuntimeError('release denied')
        super().close()


@pytest.mark.parametrize('failure', ['profile', 'selection', 'cleanup'])
def test_settings_failure_rolls_back_options_without_reactivating(failure):
    output = RejectingOutput()
    session = ControllerSession(settings=GuiSettings(profile='mouse', media_player='a'),
                                output_factory=lambda live: output)
    runtime = session._runtime
    runtime.activate(live=True)
    session._output_mode = OutputMode.LIVE
    accepted = session.current_settings()
    output.fail_close = failure == 'cleanup'
    candidate = replace(accepted, profile='plane' if failure == 'profile' else 'mouse',
                        control_bindings={'mouse': {'button': 'key_b'}},
                        media_gestures_enabled=False,
                        media_player='b' if failure == 'selection' else 'a',
                        invert_roll=True, thresholds={'mouse': {'deadzone_deg': 7}})
    assert session.apply_settings(candidate)
    assert session.current_settings() == accepted
    assert runtime.profile == session._build_profile()
    assert runtime.output is output
    assert not runtime.active
    assert session.snapshot().output_mode == OutputMode.OFF
    assert output.opens <= 2
    if failure == 'cleanup':
        assert runtime.cleanup_pending
    if failure == 'selection':
        assert output.selected == 'a'


def test_runtime_rejected_binding_edit_restores_old_mapping_without_reopen():
    old = {'steering': {'left': 'key_a'}}
    runtime = EmulatorRuntime(profile_by_name('steering'),
                              WindowsOutputBackend(input_adapter=Input()), control_bindings=old)
    runtime.activate(live=True)
    with pytest.raises(RuntimeError):
        runtime.set_control_bindings({})
    assert runtime.control_bindings == old
    assert not runtime.active


class Runner:
    def __init__(self):
        self.levels = {'a': .8, 'b': .2}
        self.writes = []
    def __call__(self, args, timeout):
        if args[-1] == '-l':
            text = '\n'.join(self.levels)
        elif '-p' not in args:
            text = ''
        else:
            player = args[args.index('-p') + 1]
            command = args[args.index('-p') + 2:]
            if player not in self.levels:
                return subprocess.CompletedProcess(args, 1, '', 'unavailable')
            if command == ['volume']:
                text = str(self.levels[player])
            elif command[0] == 'volume':
                self.levels[player] = float(command[1])
                self.writes.append((player, float(command[1])))
                text = ''
            elif command[0] == 'status': text = 'Playing'
            elif command[0] == 'position': text = '1'
            else: text = ''
        return subprocess.CompletedProcess(args, 0, text, '')


class NoSystem:
    active = False
    def leave(self): pass
    def apply_offset(self, value): raise AssertionError('system write forbidden')


class UI:
    def write(self, *args): pass
    def syn(self): pass
    def close(self): pass


class InertLinux(UInputBackend):
    def open(self, cap):
        self._mode = cap['mode']
        self._epoch = cap['activation_epoch']
        self.opened, self.closed = True, False
        self._ui, self._ecodes = UI(), evdev.ecodes
        if 'media_player' in cap:
            self.select_media_player(cap['media_player'])


def motion(yaw=0., seq=1):
    return MotionSample(1, 'test', 1, seq, .02, (0., 0., 9.8), (0., 0., 0.),
                        None, None, QualityFlags(), PipelineStageStatus.AVAILABLE,
                        False, seq * 20000000, 0., 0., yaw, 1.)


def test_linux_missing_pinned_target_recovers_read_only_and_full_range():
    runner = Runner()
    mpris = MprisPlayerVolume(run=runner, playerctl_path='inert-playerctl')
    runtime = EmulatorRuntime(profile_by_name('media'), InertLinux(mpris=mpris, system=NoSystem()),
                              media_player='missing')
    runtime.activate(live=True)
    runtime._armed = True
    runtime.mapper.set_media_baseline(.5)
    runtime.motion.process = lambda sample: sample
    runtime.feed(motion())
    runner.levels['missing'] = .2
    runtime.feed(motion(seq=2))
    assert runner.writes == []
    for seq in range(3, 24):
        runtime.feed(motion((seq - 2) * 10., seq))
    assert runner.levels['missing'] == pytest.approx(1.)
    for seq in range(24, 50):
        runtime.feed(motion(210. - (seq - 23) * 10., seq))
    assert runner.levels['missing'] == pytest.approx(0.)
    assert {player for player, value in runner.writes} == {'missing'}
    runtime.deactivate('done')


@pytest.mark.parametrize('axes,applied,expected', [
    ({'player_volume': .5}, True, 1),
    ({'player_volume': .5}, False, 0),
    ({'system_volume': .1}, True, 0),
    ({}, True, 0),
    ({'player_volume': .5, 'system_volume': .1}, True, 0),
])
def test_opt_in_handshake_only_follows_successful_player_apply(axes, applied, expected):
    class Handshake(TraceOutput):
        takes = 0
        def take_media_baseline(self):
            self.takes += 1
            return .2
        def apply(self, state):
            return replace(super().apply(state), applied=applied)
    output = Handshake()
    runtime = EmulatorRuntime(profile_by_name('media'), output)
    runtime.activate()
    runtime._armed = True
    runtime.motion.process = lambda sample: sample
    original = runtime.mapper.map
    runtime.mapper.map = lambda sample, profile: replace(original(sample, profile), absolute_axes=axes)
    runtime.feed(motion())
    assert output.takes == expected
    runtime.deactivate('done')


def test_default_runtime_matches_mapper_for_8000_samples_without_handshake():
    from triki_controller.profiles.devices import DeviceProfileMapper
    for name in ('mouse', 'steering', 'plane', 'media'):
        profile = profile_by_name(name)
        mapper = DeviceProfileMapper()
        output = TraceOutput()
        runtime = EmulatorRuntime(profile, output)
        runtime.activate()
        runtime._armed = True
        runtime.motion.process = lambda sample: sample
        for seq in range(1, 2001):
            sample = replace(motion(float((seq * 3) % 360), seq),
                             tilt_pitch_deg=float(seq % 31 - 15),
                             tilt_roll_deg=float(seq % 41 - 20))
            expected = replace(mapper.map(sample, profile), activation_epoch=1)
            step = runtime.feed(sample)
            assert step.mapped == expected
            assert step.receipt.applied
        runtime.deactivate('done')


def test_mpris_failed_write_keeps_baseline_pending_and_success_aligns_origin():
    runner = Runner()
    mpris = MprisPlayerVolume(run=runner, playerctl_path='inert-playerctl')
    mpris.select_media_player('b')
    assert mpris.apply_level(.5) is None
    assert runner.writes == []
    original = mpris._run
    def reject_write(args, timeout):
        if '-p' in args and args[args.index('-p') + 2] == 'volume' and len(args) > args.index('-p') + 3:
            return subprocess.CompletedProcess(args, 1, '', 'write denied')
        return original(args, timeout)
    mpris._run = reject_write
    assert mpris.apply_level(.6)
    assert mpris.take_media_baseline() is None
    mpris._run = original
    assert mpris.apply_level(.5) is None
    assert mpris.take_media_baseline() == .2
    assert mpris.apply_level(.3) is None
    assert runner.levels['b'] == pytest.approx(.3)


@pytest.mark.parametrize('transition', ['initial', 'resume', 'reappear'])
def test_linux_selected_target_baseline_frames_are_read_only(transition):
    runner = Runner()
    mpris = MprisPlayerVolume(run=runner, playerctl_path='inert-playerctl')
    runtime = EmulatorRuntime(profile_by_name('media'), InertLinux(mpris=mpris, system=NoSystem()),
                              media_player='b')
    runtime.recenter()
    runtime.activate(live=True)
    runtime.motion.process = lambda sample: sample
    runtime.feed(motion())
    if transition == 'resume':
        runtime.deactivate('pause', keep_origin=True)
        runner.levels['b'] = .35
        runtime.activate(live=True)
    elif transition == 'reappear':
        del runner.levels['b']
        runtime.feed(motion(seq=2))
        runner.levels['b'] = .35
    runner.writes.clear()
    runtime.feed(motion(10., 3))
    assert runner.writes == []
    runtime.feed(motion(10., 4))
    assert runner.writes == []
    runtime.deactivate('done')
