"""MPRIS/playerctl player-volume adapter (mocked; no real player required)."""

from __future__ import annotations

import json
import subprocess
import unittest

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    PipelineStageStatus,
)
from triki_controller.output.mpris_volume import MprisPlayerVolume
from triki_controller.output.app_stream_volume import AppStreamVolume
from triki_controller.output.trace import TraceOutput
from triki_controller.output.uinput_backend import UInputBackend


class FakeRun:
    def __init__(
        self,
        volume: float = 0.5,
        *,
        players: list[str] | None = None,
        statuses: dict[str, str] | None = None,
        volumes: dict[str, float] | None = None,
        url: str = "https://example.com/track",
        transport_fail: set[str] | None = None,
        absorb_volume: bool = False,
        absorb_players: set[str] | None = None,
        positions: dict[str, float] | None = None,
        dbus_pids: dict[str, int] | None = None,
        sink_inputs: list[dict[str, object]] | None = None,
    ) -> None:
        self.volume = volume
        self.players = list(players if players is not None else ["fake.player"])
        self.statuses = dict(statuses or {})
        self.volumes = dict(volumes or {})
        self.positions = dict(positions or {})
        self.dbus_pids = dict(dbus_pids or {})
        self.sink_inputs = list(sink_inputs or [])
        self.url = url
        self.transport_fail = set(transport_fail or ())
        self.absorb_volume = absorb_volume
        self.absorb_players = set(absorb_players or ())
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        tool = argv[0] if argv else ""
        if tool.endswith("pactl") or tool == "pactl":
            return self._pactl(argv)
        if tool.endswith("busctl") or tool == "busctl":
            return self._busctl(argv)
        if len(argv) >= 2 and argv[1] == "-l":
            return subprocess.CompletedProcess(
                argv, 0, stdout="\n".join(self.players) + "\n", stderr=""
            )
        player = None
        args = argv[1:]
        if len(args) >= 2 and args[0] == "-p":
            player = args[1]
            args = args[2:]
        if not args:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")
        if args[0] == "status":
            status = self.statuses.get(player or "", "Playing")
            return subprocess.CompletedProcess(argv, 0, stdout=f"{status}\n", stderr="")
        if args[0] == "position":
            if player not in self.positions:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no position")
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"{self.positions[player]}\n", stderr=""
            )
        if len(args) >= 2 and args[0] == "metadata" and args[1] == "xesam:url":
            return subprocess.CompletedProcess(argv, 0, stdout=f"{self.url}\n", stderr="")
        if args[0] in {"play-pause", "next", "previous"}:
            cmd = args[0]
            if cmd in self.transport_fail:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="No player could handle this command"
                )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if args[0] == "volume" and len(args) == 1:
            value = self.volumes.get(player or "", self.volume)
            return subprocess.CompletedProcess(argv, 0, stdout=f"{value}\n", stderr="")
        if args[0] == "volume" and len(args) >= 2:
            absorb = self.absorb_volume or (player in self.absorb_players)
            if absorb:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            token = args[1]
            if token.endswith("+"):
                new = min(1.0, self.volumes.get(player or "", self.volume) + float(token[:-1]))
            elif token.endswith("-"):
                new = max(0.0, self.volumes.get(player or "", self.volume) - float(token[:-1]))
            else:
                new = float(token)
            if player:
                self.volumes[player] = new
            self.volume = new
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")

    def _busctl(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        if "GetConnectionUnixProcessID" in argv:
            bus = argv[-1]
            pid = self.dbus_pids.get(bus)
            if pid is None:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unknown")
            return subprocess.CompletedProcess(argv, 0, stdout=f"u {pid}\n", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")

    def _pactl(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        if "--format=json" in argv and "list" in argv and "sink-inputs" in argv:
            payload = []
            for item in self.sink_inputs:
                level = float(item.get("volume", 1.0))  # type: ignore[arg-type]
                raw = int(round(level * 65536))
                payload.append(
                    {
                        "index": int(item["index"]),  # type: ignore[arg-type]
                        "volume": {
                            "front-left": {"value": raw, "value_percent": f"{int(round(level * 100))}%"},
                            "front-right": {"value": raw, "value_percent": f"{int(round(level * 100))}%"},
                        },
                        "properties": {"application.process.id": str(item["pid"])},
                    }
                )
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(payload) + "\n", stderr=""
            )
        if "set-sink-input-volume" in argv:
            index = int(argv[argv.index("set-sink-input-volume") + 1])
            token = argv[argv.index("set-sink-input-volume") + 2]
            level = float(token.rstrip("%")) / 100.0
            for item in self.sink_inputs:
                if int(item["index"]) == index:  # type: ignore[arg-type]
                    item["volume"] = level
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")


def _pinned(calls: list[list[str]], player: str) -> list[list[str]]:
    return [c for c in calls if len(c) >= 3 and c[1] == "-p" and c[2] == player]


class MprisPlayerVolumeTests(unittest.TestCase):
    def test_volume_up_down_and_mute_restore(self) -> None:
        fake = FakeRun(0.40)
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_pulse("volume_up"))
        self.assertGreater(fake.volume, 0.40)
        self.assertIsNone(ctrl.apply_pulse("volume_down"))
        before_mute = fake.volume
        self.assertIsNone(ctrl.apply_pulse("mute"))
        self.assertAlmostEqual(fake.volume, 0.0, places=3)
        self.assertIsNone(ctrl.apply_pulse("mute"))
        self.assertAlmostEqual(fake.volume, before_mute, places=3)
        self.assertTrue(any(c[1] == "-p" for c in fake.calls if c[1] != "-l"))

    def test_dry_run_only_logs(self) -> None:
        called = False

        def boom(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            raise AssertionError("dry-run must not invoke playerctl")

        ctrl = MprisPlayerVolume(run=boom, dry_run=True)
        self.assertIsNone(ctrl.apply_pulse("volume_up"))
        self.assertFalse(called)
        self.assertEqual(ctrl.log, ["mpris dry-run volume_up"])
        self.assertIsNone(ctrl.apply_level(0.72))
        self.assertIn("mpris dry-run volume=0.720", ctrl.log)
        self.assertIsNone(ctrl.apply_transport("play_pause"))
        self.assertIn("mpris dry-run play_pause", ctrl.log)

    def test_apply_level_sets_absolute_and_pins_player(self) -> None:
        fake = FakeRun(0.40, players=["spotify"])
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_level(0.80))
        self.assertAlmostEqual(fake.volume, 0.80, places=2)
        pinned = _pinned(fake.calls, "spotify")
        self.assertTrue(any(c[3] == "volume" and len(c) >= 5 for c in pinned))
        self.assertIsNone(ctrl.apply_level(0.801))  # within epsilon — no rewrite

    def test_steady_volume_does_not_rescan_players_every_sample(self) -> None:
        fake = FakeRun(players=["spotify"], volumes={"spotify": 0.5})
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_level(0.50))
        before = len(fake.calls)
        self.assertIsNone(ctrl.apply_level(0.50))
        self.assertEqual(
            fake.calls[before:],
            [],
            "unchanged volume must not spawn playerctl; that scan stalls button pulses",
        )

    def test_apply_level_reselects_advancing_player_when_volume_unchanged(self) -> None:
        fake = FakeRun(
            players=["firefox.video", "spotify"],
            statuses={"firefox.video": "Playing", "spotify": "Playing"},
            volumes={"firefox.video": 0.5, "spotify": 0.5},
            positions={"firefox.video": 40.0, "spotify": 3.0},
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_level(0.50))
        self.assertEqual(ctrl._cached_player, "firefox.video")
        fake.positions["spotify"] = 5.2
        ctrl._volume_scan_mono = 0.0  # rescan interval elapsed
        self.assertIsNone(ctrl.apply_level(0.501))  # epsilon — must still reselect
        self.assertEqual(ctrl._cached_player, "spotify")
        self.assertAlmostEqual(fake.volumes["spotify"], 0.501, places=3)

    def test_selects_playing_over_paused_and_pins(self) -> None:
        fake = FakeRun(
            players=["chromium.instance1", "spotify"],
            statuses={"chromium.instance1": "Paused", "spotify": "Playing"},
            volumes={"chromium.instance1": 1.0, "spotify": 0.4},
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        status = ctrl.describe_status()
        self.assertEqual(status.active_player, "spotify")
        self.assertIsNone(ctrl.apply_level(0.55))
        self.assertAlmostEqual(fake.volumes["spotify"], 0.55, places=2)
        self.assertTrue(_pinned(fake.calls, "spotify"))

    def test_shake_cycles_and_pins_next_player(self) -> None:
        fake = FakeRun(
            players=["chromium.instance1", "spotify"],
            statuses={"chromium.instance1": "Playing", "spotify": "Paused"},
            volumes={"chromium.instance1": 1.0, "spotify": 0.4},
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertEqual(ctrl.describe_status().active_player, "chromium.instance1")
        self.assertIsNone(ctrl.apply_pulse("cycle_player"))
        self.assertEqual(ctrl.describe_status().active_player, "spotify")
        self.assertIn("przypięty", ctrl.describe_status().detail)
        self.assertIsNone(ctrl.apply_level(0.62))
        self.assertAlmostEqual(fake.volumes["spotify"], 0.62, places=2)
        self.assertIsNone(ctrl.apply_pulse("cycle_player"))
        self.assertEqual(ctrl.describe_status().active_player, "chromium.instance1")

    def test_chromium_stub_unwritable_is_per_player(self) -> None:
        fake = FakeRun(
            players=["chromium.instance1", "spotify"],
            statuses={"chromium.instance1": "Playing", "spotify": "Paused"},
            volumes={"chromium.instance1": 1.0, "spotify": 0.5},
            absorb_players={"chromium.instance1"},
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        err = ctrl.apply_level(0.55)
        self.assertIsNone(err)
        self.assertTrue(any("stream pending" in line for line in ctrl.log))
        # Chromium remains Playing so still preferred for status, but spotify
        # can still be written when it becomes the selected writable target
        # under a Paused/Playing tie-break after statuses change.
        fake.statuses["chromium.instance1"] = "Stopped"
        fake.statuses["spotify"] = "Playing"
        ctrl._volume_scan_mono = 0.0  # rescan interval elapsed
        self.assertIsNone(ctrl.apply_level(0.70))
        self.assertAlmostEqual(fake.volumes["spotify"], 0.70, places=2)

    def test_multiple_playing_prefers_non_chromium(self) -> None:
        fake = FakeRun(
            players=["chromium.instance1", "spotify"],
            statuses={"chromium.instance1": "Playing", "spotify": "Playing"},
            volumes={"chromium.instance1": 1.0, "spotify": 0.3},
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        status = ctrl.describe_status()
        self.assertEqual(status.active_player, "spotify")

    def test_missing_playerctl_soft_error(self) -> None:
        import triki_controller.output.mpris_volume as mod

        ctrl = MprisPlayerVolume(run=FakeRun())
        original = mod.shutil.which
        mod.shutil.which = lambda _name: None  # type: ignore[assignment]
        try:
            err = ctrl.apply_pulse("volume_up")
        finally:
            mod.shutil.which = original
        self.assertIsNotNone(err)
        assert err is not None
        self.assertIn("playerctl", err)

    def test_volume_verify_detects_chromium_stub(self) -> None:
        fake = FakeRun(
            1.0,
            players=["chromium.instance190161"],
            url="https://music.youtube.com/watch?v=abc",
            absorb_volume=True,
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        err = ctrl.apply_level(0.55)
        self.assertIsNone(err)
        self.assertEqual(fake.volume, 1.0)
        self.assertTrue(any("stream pending" in line for line in ctrl.log))
        err2 = ctrl.apply_level(0.70)
        self.assertIsNone(err2)
        self.assertEqual(fake.volume, 1.0)

    def test_pear_chromium_stub_uses_app_stream_volume(self) -> None:
        fake = FakeRun(
            1.0,
            players=["chromium.instance9640"],
            url="https://music.youtube.com/watch?v=abc",
            absorb_volume=True,
            dbus_pids={"org.mpris.MediaPlayer2.chromium.instance9640": 9640},
            sink_inputs=[{"index": 19307, "pid": 9892, "volume": 1.0}],
        )
        stream = AppStreamVolume(
            run=fake,
            pactl_path="pactl",
            busctl_path="busctl",
            read_ppid=lambda pid: {9892: 9640, 9640: 1}.get(pid, 1),
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl", stream=stream)
        self.assertIsNone(ctrl.apply_level(0.55))
        self.assertAlmostEqual(float(fake.sink_inputs[0]["volume"]), 0.55, places=2)
        self.assertEqual(fake.volume, 1.0)  # MPRIS stub unchanged
        status = ctrl.describe_status()
        self.assertEqual(status.volume_writable, True)
        assert status.volume is not None
        self.assertAlmostEqual(status.volume, 0.55, places=2)
        self.assertIn("strumień", status.detail)
        self.assertIn("Pear Desktop", status.detail)
        self.assertNotIn("niedostępne", status.detail)

    def test_writable_mpris_does_not_touch_system_sink(self) -> None:
        fake = FakeRun(0.40, players=["spotify"])
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_level(0.80))
        self.assertFalse(any(c and str(c[0]).endswith("pactl") for c in fake.calls))
        self.assertAlmostEqual(fake.volume, 0.80, places=2)

    def test_describe_status_names_pear_stub(self) -> None:
        fake = FakeRun(
            1.0,
            players=["chromium.instance1"],
            url="https://music.youtube.com/watch?v=abc",
        )
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        status = ctrl.describe_status()
        self.assertEqual(status.active_player, "chromium.instance1")
        self.assertIn("Pear Desktop", status.detail)
        self.assertIn("Shortcuts", status.detail)
        self.assertNotIn("niedostępna", status.detail.lower())
        self.assertNotIn("Volume niedostępne", status.detail)

    def test_describe_status_no_players(self) -> None:
        fake = FakeRun(players=[])
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        status = ctrl.describe_status()
        self.assertIsNone(status.active_player)
        self.assertIn("brak odtwarzacza MPRIS", status.detail)

    def test_transport_play_pause_and_next_failure(self) -> None:
        fake = FakeRun(transport_fail={"next"})
        ctrl = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        self.assertIsNone(ctrl.apply_transport("play_pause"))
        err = ctrl.apply_transport("next_track")
        self.assertIsNotNone(err)
        assert err is not None
        self.assertIn("No player could handle", err)
        self.assertTrue(any(c[1] == "-p" for c in fake.calls if len(c) > 2 and c[1] != "-l"))

    def test_trace_media_dry_run_logs_mpris(self) -> None:
        out = TraceOutput()
        out.open({"mode": "media", "activation_epoch": 1, "claim_uinput": False})
        state = MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id="s",
            raw_connection_epoch=1,
            raw_sample_seq=1,
            profile_id="media",
            profile_revision="builtin-1",
            activation_epoch=1,
            held_buttons=(),
            held_keys=(),
            absolute_axes={"player_volume": 0.65, "knob": 0.3},
            relative_deltas={},
            stage_status=PipelineStageStatus.AVAILABLE,
            pulses=("play_pause",),
        )
        receipt = out.apply(state)
        self.assertTrue(receipt.applied)
        self.assertIn("mpris", receipt.detail)
        assert out._mpris is not None
        self.assertIn("mpris dry-run volume=0.650", out._mpris.log)
        self.assertIn("mpris dry-run play_pause", out._mpris.log)
        self.assertEqual(out.pulses, ["play_pause"])

    def test_uinput_media_routes_volume_to_mpris(self) -> None:
        try:
            import evdev  # noqa: F401
        except ImportError:
            self.skipTest("evdev not installed")

        fake = FakeRun(0.5)
        mpris = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        backend = UInputBackend(mpris=mpris)
        try:
            backend.open(
                {
                    "claim_uinput": True,
                    "mode": "media",
                    "activation_epoch": 1,
                    "device_name": "Triki MPRIS Test",
                    "dry_run": False,
                }
            )
        except (OSError, PermissionError, RuntimeError) as exc:
            self.skipTest(f"uinput unavailable: {exc}")
        try:
            state = MappedState(
                schema_version=SCHEMA_VERSION,
                raw_session_id="s",
                raw_connection_epoch=1,
                raw_sample_seq=1,
                profile_id="media",
                profile_revision="builtin-1",
                activation_epoch=1,
                held_buttons=(),
                held_keys=(),
                absolute_axes={"player_volume": 0.77},
                relative_deltas={},
                stage_status=PipelineStageStatus.AVAILABLE,
                pulses=("play_pause",),
            )
            receipt = backend.apply(state)
            self.assertTrue(receipt.applied)
            self.assertAlmostEqual(fake.volume, 0.77, places=2)
            self.assertIn("mpris", receipt.detail)
            self.assertNotIn("ignored", receipt.detail)
            self.assertTrue(any(len(c) >= 4 and c[3] == "play-pause" for c in fake.calls))
        finally:
            backend.close()

    def test_uinput_transport_falls_back_when_mpris_rejects(self) -> None:
        try:
            import evdev  # noqa: F401
        except ImportError:
            self.skipTest("evdev not installed")

        fake = FakeRun(transport_fail={"next"})
        mpris = MprisPlayerVolume(run=fake, playerctl_path="playerctl")
        backend = UInputBackend(mpris=mpris)
        try:
            backend.open(
                {
                    "claim_uinput": True,
                    "mode": "media",
                    "activation_epoch": 1,
                    "device_name": "Triki MPRIS Fallback",
                    "dry_run": False,
                }
            )
        except (OSError, PermissionError, RuntimeError) as exc:
            self.skipTest(f"uinput unavailable: {exc}")
        try:
            state = MappedState(
                schema_version=SCHEMA_VERSION,
                raw_session_id="s",
                raw_connection_epoch=1,
                raw_sample_seq=1,
                profile_id="media",
                profile_revision="builtin-1",
                activation_epoch=1,
                held_buttons=(),
                held_keys=(),
                absolute_axes={},
                relative_deltas={},
                stage_status=PipelineStageStatus.AVAILABLE,
                pulses=("next_track",),
            )
            receipt = backend.apply(state)
            self.assertTrue(receipt.applied)
            self.assertIn("fallback uinput", receipt.detail)
            self.assertNotIn("ignored next_track", receipt.detail)
        finally:
            backend.neutralize("test done")
            backend.close()


if __name__ == "__main__":
    unittest.main()
