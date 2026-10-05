"""Connected settings transactions with an inert, resource-owning backend."""
from dataclasses import replace

import pytest

from triki_controller.core.models import ConnectionState
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.trace import TraceOutput
from triki_controller.profiles.builtin import profile_by_name
from triki_controller.profiles.devices import MOUSE_ORIENTATION, STEERING_ORIENTATION
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.runtime.synthetic import make_raw, pose_level


class OwnedOutput(TraceOutput):
    BACKEND_NAME = "uinput"

    def __init__(self):
        super().__init__()
        self.session = None
        self.opens = []
        self.events = []
        self.fail_open = False
        self.fail_release = False
        self.held = {"old_key"}

    def open(self, capabilities):
        self.events.append("open")
        self.opens.append((dict(capabilities), self.session._runtime.orientation if self.session else None))
        if self.fail_open:
            raise RuntimeError("open denied")
        super().open({**capabilities, "claim_uinput": False})

    def neutralize(self, reason):
        self.events.append("release")
        if self.fail_release:
            raise RuntimeError("release denied")
        self.held.clear()
        return super().neutralize(reason)

    def close(self):
        self.events.append("close")
        if self.fail_release:
            raise RuntimeError("owned release pending")
        super().close()


class TransportSentinel:
    def __init__(self):
        self.connects = self.disconnects = 0

    def disconnect(self):
        self.disconnects += 1
        raise AssertionError("profile switch touched transport")


def connected_session():
    output = OwnedOutput()
    session = ControllerSession(output_factory=lambda live: output)
    output.session = session
    session._state = ConnectionState.STREAMING
    session._transport = "ble"
    session._conn_id = 7
    session._task = object()
    session._loop = object()
    session._ble = TransportSentinel()
    assert session.start_output(live=True) is None
    return session, output


def test_profile_change_reopens_once_after_mount_without_transport_change():
    session, output = connected_session()
    transport = (session._task, session._loop, session._ble, session._conn_id)
    session._on_sample(7, make_raw(accel=pose_level(), seq=1, t_ns=20_000_000))
    assert session.set_profile("mouse") is None
    assert len(output.opens) == 2
    assert output.opens[-1][1] == MOUSE_ORIENTATION
    assert output.events[-3:] == ["release", "close", "open"]
    assert not output.held
    assert (session._task, session._loop, session._ble, session._conn_id) == transport
    assert session._ble.connects == session._ble.disconnects == 0
    session._on_sample(7, make_raw(accel=pose_level(), seq=2, t_ns=40_000_000))
    assert session.snapshot().samples == 2
    assert session.snapshot().profile_name == "mouse"
    assert session.snapshot().output_mode == OutputMode.LIVE


@pytest.mark.parametrize("failure", ["fail_open", "fail_release"])
def test_rejected_profile_preserves_settings_off_cleanup_retryable(failure):
    session, output = connected_session()
    before = session.current_settings()
    setattr(output, failure, True)
    assert session.set_profile("mouse") is not None
    assert session.current_settings() == before
    assert session.snapshot().profile_name == "steering"
    assert session.snapshot().orientation == STEERING_ORIENTATION
    assert session.snapshot().output_mode == OutputMode.OFF
    assert not session._runtime.active
    opens = len(output.opens)
    error = session.apply_settings(replace(before, media_gestures_enabled=False))
    if failure == "fail_open":
        assert error is None
    else:
        assert error is not None and session._runtime.cleanup_pending
        assert session.current_settings() == before
    assert len(output.opens) == opens  # No implicit reactivation after rejection.
    setattr(output, failure, False)
    session.stop_output()
    assert not session._runtime.cleanup_pending
    assert session.start_output(live=True) is None


def test_runtime_inactive_switch_never_activates_output():
    output = OwnedOutput()
    runtime = EmulatorRuntime(profile=profile_by_name("steering"), output=output)
    runtime.switch_profile(profile_by_name("mouse"))
    assert not runtime.active and not output.opens


def test_settings_profile_and_bindings_open_only_final_configuration():
    session, output = connected_session()
    candidate = replace(session.current_settings(), profile="mouse", control_bindings={"mouse": {"button": "key_space"}})
    assert session.apply_settings(candidate) is None
    assert len(output.opens) == 2
    assert output.opens[-1][1] == MOUSE_ORIENTATION
    assert output.opens[-1][0]["control_bindings"] == {"button": "key_space"}
