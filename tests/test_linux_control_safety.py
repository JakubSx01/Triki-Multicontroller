"""Linux safety seams exercised with real mapper/backend and inert devices."""
from dataclasses import replace

import evdev
import pytest

from triki_controller.core.models import ConnectionState

from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.mpris_volume import MprisPlayerVolume
from triki_controller.output.trace import TraceOutput
from triki_controller.output.uinput_backend import UInputBackend
from triki_controller.runtime.synthetic import make_raw, pose_level
from tests.test_uinput_loopback import _mapped


class InertDevice:
    def __init__(self, **kwargs):
        self.events = []
        self.held = set()
        self.deny_release = False
        self.release_attempts = 0
        self.closed = False
        self.deny_close = False

    def write(self, kind, code, value):
        if kind == evdev.ecodes.EV_KEY:
            if value == 0:
                self.release_attempts += 1
                if self.deny_release:
                    raise OSError('inert key-up denied')
                self.held.discard(code)
            else:
                self.held.add(code)
        self.events.append((kind, code, value))

    def syn(self):
        pass

    def close(self):
        if self.deny_close:
            raise OSError('inert close denied')
        self.closed = True


@pytest.fixture(autouse=True)
def inert_uinput(monkeypatch):
    def deny_real(*args, **kwargs):
        raise AssertionError('REAL UInput FORBIDDEN')
    monkeypatch.setattr(evdev, 'UInput', deny_real)
    from evdev.device import AbsInfo
    monkeypatch.setattr('triki_controller.output.uinput_backend._load_evdev',
                        lambda: (evdev.ecodes, InertDevice, AbsInfo))


@pytest.mark.parametrize('pulse', ['play_pause', 'next_track', 'previous_track'])
def test_manual_target_without_playerctl_never_emits_global_transport(pulse):
    player = MprisPlayerVolume()
    player._resolve_playerctl = lambda: None
    backend = UInputBackend(mpris=player)
    backend.open({'claim_uinput': True, 'mode': 'media', 'activation_epoch': 1,
                  'media_player': 'missing'})
    receipt = backend.apply(_mapped(pulses=(pulse,)))
    assert not receipt.applied
    assert backend._ui.events == []
    assert player._manual_player == 'missing'
    backend.close()


def held_session():
    old = GuiSettings(profile='mouse', control_bindings={'mouse': {'button': 'key_a'}})
    backend = UInputBackend()
    session = ControllerSession(settings=old,
                                output_factory=lambda live: backend if live else TraceOutput())
    session._apply_connection(session._event(ConnectionState.STREAMING, 'inert'))
    assert session.start_output(live=True) is None
    for seq in range(1, 14):
        session._on_sample(session._conn_id, make_raw(accel=pose_level(), seq=seq,
                           t_ns=seq * 20_000_000, button=seq >= 12))
    assert session.snapshot().mapped.held_keys == ('key_a',)
    device = backend._ui
    assert device.held == {evdev.ecodes.KEY_A}
    device.deny_release = True
    return session, backend, device


@pytest.mark.parametrize('ending', ['stop', 'disconnect', 'profile', 'edit'])
def test_failed_linux_release_disarms_and_keeps_retryable_physical_owner(ending):
    session, backend, device = held_session()
    runtime = session._runtime
    previous = session.current_settings()
    if ending == 'edit':
        assert session.apply_settings(replace(previous, control_bindings={
            'mouse': {'button': 'key_b'}})) is not None
    elif ending == 'profile':
        assert session.set_profile('media') is not None
    elif ending == 'disconnect':
        session.disconnect()
    else:
        session.stop_output()
    assert not runtime.active and not runtime.live
    assert session.snapshot().output_mode == OutputMode.OFF
    assert 'key-up denied' in session.snapshot().error
    assert session.current_settings() == previous
    assert runtime.cleanup_pending and runtime.output is backend
    assert backend._ui is device and not backend.closed and not device.closed
    assert backend._held == {'key_a'} and device.held == {evdev.ecodes.KEY_A}
    events = list(device.events)
    runtime.feed(make_raw(accel=pose_level(), seq=14, t_ns=280_000_000, button=True))
    assert device.events == events
    with pytest.raises(RuntimeError):
        runtime.set_output(TraceOutput())
    with pytest.raises(RuntimeError):
        runtime.activate(live=True)
    attempts = device.release_attempts
    session.stop_output()
    assert device.release_attempts > attempts
    attempts = device.release_attempts
    session.disconnect()
    assert device.release_attempts > attempts
    assert runtime.cleanup_pending
    device.deny_release = False
    session.stop_output()
    assert not runtime.cleanup_pending and not runtime.active
    assert not device.held and device.closed and backend.closed
    assert backend._ui is None
    assert session.current_settings() == previous
    session.shutdown()


@pytest.mark.parametrize('manual', [True, False])
@pytest.mark.parametrize('failure', ['rejected', 'discovery', 'runtime', 'unsupported', 'absent'])
def test_transport_failures_respect_manual_identity_but_auto_keeps_fallback(monkeypatch, manual, failure):
    player = MprisPlayerVolume(playerctl_path='inert-playerctl')
    backend = UInputBackend(mpris=player)
    backend.open({'claim_uinput': True, 'mode': 'media', 'activation_epoch': 1,
                  'media_player': 'chosen' if manual else None})
    def denied(*args):
        raise OSError('arbitrary adapter failure')
    if failure == 'discovery':
        monkeypatch.setattr(player, '_resolve_playerctl', denied)
    elif failure == 'runtime':
        monkeypatch.setattr(player, 'apply_transport', denied)
    elif failure == 'unsupported':
        monkeypatch.setattr(player, 'handles_transport', lambda pulse: False)
    elif failure == 'absent':
        backend._mpris = None
    else:
        monkeypatch.setattr(player, 'apply_transport', lambda pulse: 'arbitrary rejection')
    receipt = backend.apply(_mapped(pulses=('play_pause',)))
    assert receipt.applied is not manual
    expected = [] if manual else [(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_PLAYPAUSE, 1),
                                 (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_PLAYPAUSE, 0)]
    assert backend._ui.events == expected
    assert backend._media_player == ('chosen' if manual else None)
    backend.close()


def test_close_failure_retains_device_and_session_owner_until_retry():
    session, backend, device = held_session()
    device.deny_release = False
    device.deny_close = True
    session.stop_output()
    assert not session._runtime.active and session._runtime.cleanup_pending
    assert backend._ui is device and not backend.closed
    assert not device.held and not backend._held
    assert session.start_output(live=True) is not None
    device.deny_close = False
    session.stop_output()
    assert not session._runtime.cleanup_pending
    assert backend.closed and device.closed and backend._ui is None
    session.shutdown()


def test_injected_manual_player_is_not_reset_by_open_without_selection():
    player = MprisPlayerVolume()
    player._resolve_playerctl = lambda: None
    player.select_media_player('chosen')
    backend = UInputBackend(mpris=player)
    backend.open({'claim_uinput': True, 'mode': 'media', 'activation_epoch': 1})
    assert player._manual_player == 'chosen'
    receipt = backend.apply(_mapped(pulses=('play_pause',)))
    assert not receipt.applied and backend._ui.events == []
    backend.close()


def test_linux_soft_volume_failure_remains_visible_in_status():
    player = MprisPlayerVolume()
    player._resolve_playerctl = lambda: None
    backend = UInputBackend(mpris=player)
    session = ControllerSession(settings=GuiSettings(profile='media'),
                                output_factory=lambda live: backend if live else TraceOutput())
    session._apply_connection(session._event(ConnectionState.STREAMING, 'inert'))
    assert session.start_output(live=True) is None
    session._output_note = 'prior status'
    receipt = backend.apply(_mapped(absolute_axes={'player_volume': .7}))
    assert receipt.applied  # Preserve Linux's existing soft-volume contract.
    session._note_mpris_errors(receipt)
    assert 'brak playerctl' in session.snapshot().output_note
    session.shutdown()
