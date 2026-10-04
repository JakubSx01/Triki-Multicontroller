"""Default-sink volume used only while the media cap is inverted."""

from __future__ import annotations

import subprocess
import unittest

from triki_controller.output.system_volume import SystemMixer


class FakeRun:
    def __init__(self, percent: str = "40%") -> None:
        self.percent = percent
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        self.calls.append(list(argv))
        if "get-sink-volume" in argv:
            stdout = f"Volume: front-left: 26214 /  {self.percent} / -10 dB\n"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        if "set-sink-volume" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "set-sink-input-volume" in argv:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="forbidden")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")


class SystemMixerTests(unittest.TestCase):
    def test_entry_reads_sink_and_does_not_write(self) -> None:
        fake = FakeRun("40%")
        mixer = SystemMixer(run=fake, pactl_path="pactl")
        self.assertIsNone(mixer.apply_offset(0.0))
        self.assertEqual(fake.calls, [["pactl", "get-sink-volume", "@DEFAULT_SINK@"]])
        self.assertTrue(mixer.active)

    def test_twist_sets_default_sink_not_an_app_stream(self) -> None:
        fake = FakeRun("40%")
        mixer = SystemMixer(run=fake, pactl_path="pactl")
        self.assertIsNone(mixer.apply_offset(0.0))
        self.assertIsNone(mixer.apply_offset(0.25))
        self.assertIn(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "65%"],
            fake.calls,
        )
        self.assertFalse(any("set-sink-input-volume" in call for call in fake.calls))

    def test_unchanged_offset_does_not_write_again(self) -> None:
        fake = FakeRun("40%")
        mixer = SystemMixer(run=fake, pactl_path="pactl")
        mixer.apply_offset(0.0)
        mixer.apply_offset(0.25)
        before = len(fake.calls)
        self.assertIsNone(mixer.apply_offset(0.25))
        self.assertEqual(len(fake.calls), before)

    def test_leave_then_reenter_rereads_sink(self) -> None:
        fake = FakeRun("40%")
        mixer = SystemMixer(run=fake, pactl_path="pactl")
        mixer.apply_offset(0.0)
        mixer.apply_offset(0.2)
        mixer.leave()
        self.assertFalse(mixer.active)
        fake.percent = "70%"
        self.assertIsNone(mixer.apply_offset(0.0))
        reads = [call for call in fake.calls if "get-sink-volume" in call]
        self.assertEqual(len(reads), 2)
