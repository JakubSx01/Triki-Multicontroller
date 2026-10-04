"""Acceptance guards and readback checks; fake adapters are not native certification."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from accept_windows_output import main
from triki_controller.output.windows_audio import Endpoint, PlayerSession


class AudioProbe:
    def __init__(self):
        self.player = PlayerSession("42:1", "test-player", True, .3, False)
        self.endpoint = Endpoint("test-endpoint", .6)
        self.writes = []
        self.closed = False

    def sessions(self):
        return (self.player,)

    def default_endpoint(self):
        return self.endpoint

    def set_player(self, key, level):
        self.writes.append(("player", key, level))
        self.player = replace(self.player, volume=level)

    def set_endpoint(self, key, level):
        self.writes.append(("system", key, level))
        self.endpoint = replace(self.endpoint, volume=level)

    def close(self):
        self.closed = True


def test_default_is_read_only_and_closes_adapter():
    probe = AudioProbe()
    assert main([], adapter_factory=lambda: probe, platform="win32") == 0
    assert probe.writes == []
    assert probe.closed


def test_unauthorized_write_rejects_before_native_calls():
    with pytest.raises(SystemExit) as error:
        main(["--player-level", "0.4"], adapter_factory=lambda: pytest.fail("must not open audio"), platform="win32")
    assert error.value.code == 2


def test_explicit_writes_are_separate_and_read_back():
    probe = AudioProbe()
    assert main(["--allow-write", "--player-level", ".4", "--system-level", ".7"],
                adapter_factory=lambda: probe, platform="win32") == 0
    assert probe.writes == [("player", "42:1", .4), ("system", "test-endpoint", .7)]
    assert probe.closed


def test_readback_failure_is_not_reported_as_success():
    probe = AudioProbe()
    probe.set_player = lambda *_: None
    assert main(["--allow-write", "--player-level", ".9"], adapter_factory=lambda: probe, platform="win32") == 1
    assert probe.closed


def test_linux_native_probe_rejected():
    with pytest.raises(SystemExit) as error:
        main([], adapter_factory=lambda: pytest.fail("must not call Windows API"), platform="linux")
    assert error.value.code == 2


def test_dry_run_makes_no_native_calls():
    assert main(["--dry-run"], adapter_factory=lambda: pytest.fail("no native calls"), platform="linux") == 0


@pytest.mark.parametrize("bad", ["nan", "inf", "-0.1", "1.1"])
def test_invalid_levels_rejected(bad):
    with pytest.raises(SystemExit) as error:
        main(["--allow-write", "--player-level", bad], platform="win32")
    assert error.value.code == 2
