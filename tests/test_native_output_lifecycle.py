"""Native lifecycle safety at runtime and session seams; no native API calls."""
from unittest.mock import Mock

import pytest

from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.trace import TraceOutput
from triki_controller.profiles.builtin import profile_by_name
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.runtime.synthetic import make_raw, pose_level
from tests.test_gui_session import _stream


class Native(TraceOutput):
    BACKEND_NAME = "windows"

    def __init__(self):
        super().__init__()
        self.faults = {}
        self.calls = []
        self.held = {"mouse_left"}

    def fail(self, operation):
        self.calls.append(operation)
        if operation in self.faults:
            raise RuntimeError(self.faults[operation])

    def open(self, capabilities):
        self.fail("open")
        player = self._mpris
        super().open({**capabilities, "claim_uinput": False})
        self._mpris = player

    def apply(self, state):
        self.fail("apply")
        return super().apply(state)

    def neutralize(self, reason):
        self.fail("neutralize")
        self.held.clear()
        return super().neutralize(reason)

    def close(self):
        self.fail("close")
        super().close()


def session_for(backend):
    session = ControllerSession(settings=GuiSettings(profile="mouse"),
                                output_factory=lambda live: backend if live else TraceOutput())
    _stream(session)
    assert session.start_output(live=True) is None
    return session


@pytest.mark.parametrize("backend_name", ["windows", "macos"])
@pytest.mark.parametrize("operation", ["neutralize", "close"])
def test_stop_disables_dispatch_retains_backend_and_retries(operation, backend_name):
    backend = Native()
    backend.BACKEND_NAME = backend_name
    session = session_for(backend)
    backend.faults[operation] = "release denied UIPI"
    session.stop_output()
    assert not session._runtime.active
    assert session.snapshot().output_mode == OutputMode.OFF
    assert "release denied UIPI" in session.snapshot().error
    assert session._runtime.output is backend
    assert "close" in backend.calls
    count = backend.calls.count("apply")
    session._on_sample(session._conn_id, make_raw(accel=pose_level(), seq=1, t_ns=20_000_000))
    assert backend.calls.count("apply") == count
    assert session.start_output(live=True) is not None
    backend.faults.clear()
    session.stop_output()
    assert not backend.held
    assert session.start_output(live=True) is None
    session.shutdown()


@pytest.mark.parametrize("command", ["disconnect", "shutdown"])
def test_disconnect_and_shutdown_drain_worker_despite_release_failure(command):
    backend = Native()
    session = session_for(backend)
    loop = session._ensure_loop()
    thread = session._thread
    backend.faults["neutralize"] = "still held"
    backend.faults["close"] = "close denied"
    getattr(session, command)()
    assert session.snapshot().output_mode == OutputMode.OFF
    assert not session._runtime.active
    assert session._runtime.output is backend
    assert backend.held == {"mouse_left"}
    assert "still held" in (session.snapshot().error or "")
    assert "close denied" in (session.snapshot().error or "")
    if command == "shutdown":
        assert not thread.is_alive()
        assert loop.is_closed()
    backend.faults.clear()
    session.shutdown()


@pytest.mark.parametrize("failure", ["open", "baseline"])
def test_failed_activation_cleans_partial_owner_and_keeps_original_error(failure):
    backend = Native()
    runtime = EmulatorRuntime(profile_by_name("media"), backend)
    if failure == "open":
        backend.faults["open"] = "missing native dependency"
    else:
        runtime.recenter()
        backend._mpris = Mock()
        backend._mpris.read_volume.side_effect = RuntimeError("baseline read denied")
    backend.faults["close"] = "partial owner close denied"
    with pytest.raises(RuntimeError, match="missing native dependency|baseline read denied") as error:
        runtime.activate(live=True)
    assert "partial owner close denied" in str(error.value)
    assert "neutralize" in backend.calls and "close" in backend.calls
    assert not runtime.active
    with pytest.raises(RuntimeError):
        runtime.set_output(TraceOutput())
    with pytest.raises(RuntimeError):
        runtime.activate(live=True)
    backend.faults.clear()
    runtime.deactivate("retry")
    runtime.set_output(TraceOutput())


def test_pending_click_failure_attempts_neutralize_and_close_without_replaying_press():
    backend = Native()
    runtime = EmulatorRuntime(profile_by_name("mouse"), backend)
    runtime.activate(live=True)
    runtime.mapper.take_pending_click = Mock(return_value="mouse_left")
    backend.faults["apply"] = "pending click denied"
    backend.faults["neutralize"] = "release denied"
    backend.faults["close"] = "close denied"
    with pytest.raises(RuntimeError) as error:
        runtime.deactivate("stop")
    for detail in ("pending click denied", "release denied", "close denied"):
        assert detail in str(error.value)
    assert not runtime.active
    assert backend.held == {"mouse_left"}
    backend.faults.clear()
    runtime.deactivate("retry")
    assert backend.calls.count("apply") == 1
    assert not runtime.cleanup_pending


def test_profile_switch_failure_stops_and_blocks_replacement():
    backend = Native()
    session = session_for(backend)
    backend.faults["neutralize"] = "profile release denied"
    backend.faults["close"] = "profile close denied"
    assert "profile release denied" in session.set_profile("media")
    assert session.snapshot().output_mode == OutputMode.OFF
    assert not session._runtime.active
    assert session._runtime.profile.mode == "mouse"
    assert session.snapshot().profile_name == "mouse"
    assert session.start_output(live=True) is not None
    backend.faults.clear()
    session.stop_output()
    session.shutdown()


@pytest.mark.parametrize("detail", ["player: no running application audio sessions", "player read denied", "player write denied", "system: endpoint denied", "SendInput denied"])
def test_failure_receipt_reaches_existing_status_and_pipeline(detail):
    from dataclasses import replace
    backend = Native()
    session = session_for(backend)
    receipt = backend.apply(session._runtime._pulse_only("recenter"))
    receipt = replace(receipt, backend="windows", applied=False, detail=detail)
    session._note_mpris_errors(receipt)
    snapshot = session.snapshot()
    assert snapshot.error == detail
    assert snapshot.output_note == detail
    assert snapshot.pipeline["FINAL_OUTPUT"] == "error"
    session.shutdown()


@pytest.mark.parametrize("active_player", [None, "unreadable player"])
def test_native_no_player_is_meaningful_before_first_sample(active_player):
    backend = Native()
    backend._mpris = Mock()
    backend._mpris.describe_status.return_value = Mock(active_player=active_player, volume_writable=None,
                                                     volume=None, detail="player: no running sessions")
    session = ControllerSession(settings=GuiSettings(profile="media"),
                                output_factory=lambda live: backend if live else TraceOutput())
    _stream(session)
    assert session.start_output(live=True) is None
    assert "no running sessions" in (session.snapshot().error or "")
    assert session.snapshot().pipeline["FINAL_OUTPUT"] == "error"
    session.shutdown()


def test_runtime_dispatch_exception_disables_cli_and_cleans_independently():
    backend = Native()
    runtime = EmulatorRuntime(profile_by_name("mouse"), backend)
    runtime.activate(live=True)
    backend.faults["apply"] = "native dispatch denied"
    backend.faults["neutralize"] = "native release denied"
    with pytest.raises(RuntimeError, match="native dispatch denied"):
        runtime.feed(make_raw(accel=pose_level(), seq=1, t_ns=20_000_000))
    assert not runtime.active
    assert "close" in backend.calls
    backend.faults.clear()
    runtime.deactivate("retry")
