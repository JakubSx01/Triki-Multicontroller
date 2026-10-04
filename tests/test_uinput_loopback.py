"""Grabbed /dev/uinput loopback. Events are read from the virtual device, not a desktop app."""

from __future__ import annotations

import os
import select
import time
import unittest

from triki_controller.core.models import SCHEMA_VERSION, MappedState, PipelineStageStatus


def _mapped(**kwargs: object) -> MappedState:
    data: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "raw_session_id": "uinput-test",
        "raw_connection_epoch": 1,
        "raw_sample_seq": 1,
        "profile_id": "test",
        "profile_revision": "test",
        "activation_epoch": 1,
        "held_buttons": (),
        "held_keys": (),
        "absolute_axes": {},
        "relative_deltas": {},
        "stage_status": PipelineStageStatus.AVAILABLE,
        "pulses": (),
    }
    data.update(kwargs)
    return MappedState(**data)  # type: ignore[arg-type]


def _read(dev: object, timeout: float = 1.0) -> list[object]:
    found: list[object] = []
    deadline = time.monotonic() + timeout
    fd = dev.fd  # type: ignore[attr-defined]
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            if found:
                break
            continue
        found.extend(dev.read())  # type: ignore[attr-defined]
    return found


@unittest.skipUnless(os.access("/dev/uinput", os.W_OK), "/dev/uinput is not writable")
class UInputLoopbackTests(unittest.TestCase):
    def test_mouse_steering_and_media_roundtrip(self) -> None:
        from evdev import ecodes

        from triki_controller.output.uinput_backend import UInputBackend

        self._check_mouse(ecodes)
        self._check_steering(ecodes)
        self._check_media(ecodes)

    def _check_mouse(self, ecodes: object) -> None:
        from triki_controller.output.uinput_backend import UInputBackend

        backend = UInputBackend()
        dev = None
        try:
            backend.open(
                {
                    "claim_uinput": True,
                    "mode": "mouse",
                    "activation_epoch": 1,
                    "device_name": "Triki Mouse Test",
                }
            )
            dev = backend.device
            self.assertIsNotNone(dev)
            self.assertEqual(dev.name, "Triki Mouse Test")
            dev.grab()
            backend.apply(
                _mapped(pulses=("mouse_left",), relative_deltas={"pointer_x": 7, "pointer_y": -3})
            )
            events = _read(dev)
            pairs = {(ev.type, ev.code, ev.value) for ev in events}
            self.assertIn((ecodes.EV_REL, ecodes.REL_X, 7), pairs)
            self.assertIn((ecodes.EV_REL, ecodes.REL_Y, -3), pairs)
            self.assertIn((ecodes.EV_KEY, ecodes.BTN_LEFT, 1), pairs)
            self.assertIn((ecodes.EV_KEY, ecodes.BTN_LEFT, 0), pairs)
            backend.apply(_mapped(pulses=("mouse_right",)))
            right = {(ev.type, ev.code, ev.value) for ev in _read(dev)}
            self.assertIn((ecodes.EV_KEY, ecodes.BTN_RIGHT, 1), right)
            self.assertIn((ecodes.EV_KEY, ecodes.BTN_RIGHT, 0), right)
            backend.neutralize("test")
        finally:
            if dev is not None:
                dev.ungrab()
            backend.close()

    def _check_steering(self, ecodes: object) -> None:
        from triki_controller.output.uinput_backend import UInputBackend

        backend = UInputBackend()
        dev = None
        try:
            backend.open(
                {
                    "claim_uinput": True,
                    "mode": "steering",
                    "activation_epoch": 1,
                    "device_name": "Triki Steering Test",
                }
            )
            dev = backend.device
            self.assertIsNotNone(dev)
            dev.grab()
            _read(dev, timeout=0.2)
            backend.apply(_mapped(absolute_axes={"wheel": 0.5, "throttle": 1.0, "brake": 0.25}))
            events = _read(dev)
            values = {(ev.code, ev.value) for ev in events if ev.type == ecodes.EV_ABS}
            self.assertIn((ecodes.ABS_X, 16384), values)
            self.assertIn((ecodes.ABS_GAS, 255), values)
            self.assertIn((ecodes.ABS_BRAKE, 64), values)
            backend.neutralize("test")
            done = _read(dev)
            axes = {ev.code: ev.value for ev in done if ev.type == ecodes.EV_ABS}
            self.assertEqual(axes.get(ecodes.ABS_X), 0)
            self.assertEqual(axes.get(ecodes.ABS_GAS), 0)
            self.assertEqual(axes.get(ecodes.ABS_BRAKE), 0)
        finally:
            if dev is not None:
                dev.ungrab()
            backend.close()

    def _check_media(self, ecodes: object) -> None:
        from triki_controller.output.mpris_volume import MprisPlayerVolume
        from triki_controller.output.uinput_backend import UInputBackend

        calls: list[str] = []

        def fake_run(argv: list[str], timeout: float):  # noqa: ARG001
            import subprocess

            calls.append(" ".join(argv))
            # Volume player is present; transport next/play can still fail → uinput.
            if len(argv) >= 2 and argv[1] == "-l":
                return subprocess.CompletedProcess(argv, 0, stdout="fake.player\n", stderr="")
            if len(argv) >= 4 and argv[1] == "-p" and argv[3] == "status":
                return subprocess.CompletedProcess(argv, 0, stdout="Playing\n", stderr="")
            if len(argv) >= 4 and argv[1] == "-p" and argv[3] == "volume" and len(argv) == 4:
                return subprocess.CompletedProcess(argv, 0, stdout="0.40\n", stderr="")
            if len(argv) >= 4 and argv[1] == "-p" and argv[3] == "play-pause":
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="No player could handle this command"
                )
            if len(argv) >= 4 and argv[1] == "-p" and argv[3] == "volume":
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        mpris = MprisPlayerVolume(run=fake_run, dry_run=False, playerctl_path="playerctl")
        backend = UInputBackend(mpris=mpris)
        dev = None
        try:
            backend.open(
                {
                    "claim_uinput": True,
                    "mode": "media",
                    "activation_epoch": 1,
                    "device_name": "Triki Media Keys Test",
                }
            )
            dev = backend.device
            self.assertIsNotNone(dev)
            dev.grab()
            backend.apply(_mapped(pulses=("volume_up", "play_pause")))
            events = _read(dev)
            pairs = [(ev.code, ev.value) for ev in events if ev.type == ecodes.EV_KEY]
            # Volume is MPRIS — must not emit system KEY_VOLUMEUP.
            self.assertNotIn((ecodes.KEY_VOLUMEUP, 1), pairs)
            # Transport rejected by playerctl → falls back to uinput.
            self.assertIn((ecodes.KEY_PLAYPAUSE, 1), pairs)
            self.assertIn((ecodes.KEY_PLAYPAUSE, 0), pairs)
            self.assertTrue(any("-p fake.player" in c and "volume" in c for c in calls))
            backend.neutralize("loopback media done")
        finally:
            if dev is not None:
                dev.ungrab()
            backend.close()
