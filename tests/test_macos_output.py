"""Adapter/contract tests; these do NOT validate native macOS behavior."""
import unittest

from triki_controller.output.macos_audio import MacOSSystemVolume, MacOSPlayerVolume
from triki_controller.output.macos_backend import MacOSOutputBackend
from triki_controller.core.models import MappedState, PipelineStageStatus
from triki_controller.output.macos_audio import NativeMacOSAudio, MacOSAudioError
from triki_controller.output.macos_input import QuartzMouseInput
from unittest.mock import patch
from types import SimpleNamespace
import subprocess
import ctypes

from triki_controller.profiles.builtin import profile_by_name
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.runtime.synthetic import make_raw, pose_level


class RuntimeBaselineTests(unittest.TestCase):
    def test_connect_and_recenter_query_actual_music_and_spotify_volume_without_writes(self):
        for player, bundle in NativeMacOSAudio.BUNDLES.items():
            with self.subTest(player=player):
                calls = []
                volume = [37]
                app = SimpleNamespace(
                    isRunning=lambda: True,
                    setTimeout_=lambda value: calls.append(("timeout", value)),
                    soundVolume=lambda: calls.append(("read",)) or volume[0],
                    lastError=lambda: None,
                )
                process = SimpleNamespace(
                    isTerminated=lambda: False,
                    processIdentifier=lambda: 123,
                    launchDate=lambda: SimpleNamespace(timeIntervalSince1970=lambda: 1000.0),
                    bundleURL=lambda: SimpleNamespace(path=lambda: f"/Applications/{player}.app"),
                )
                running = SimpleNamespace(runningApplicationsWithBundleIdentifier_=
                    lambda identifier: [process] if identifier == bundle else [])
                scripting = SimpleNamespace(applicationWithProcessIdentifier_=
                    lambda pid: calls.append(("pid", pid)) or app)
                def run(argv, **kwargs):
                    calls.append(tuple(argv))
                    return subprocess.CompletedProcess(argv, 0,
                        '<dictionary><suite><property name="sound volume" access="rw"/>'
                        '</suite></dictionary>', "")
                audio = NativeMacOSAudio(run=run)
                backend = MacOSOutputBackend(audio=audio)
                runtime = EmulatorRuntime(profile_by_name("media"), backend)
                with patch.object(audio, "_frameworks", return_value=(running, scripting)), \
                     patch.object(runtime.mapper, "set_media_baseline",
                                  wraps=runtime.mapper.set_media_baseline) as baseline:
                    runtime.activate(live=True)
                    for seq in range(8):
                        runtime.feed(make_raw(accel=pose_level(), seq=seq,
                                              t_ns=seq * 20_000_000))
                    baseline.assert_called_once_with(0.37)
                    volume[0] = 82
                    runtime.recenter()
                    baseline.assert_called_with(0.82)
                    self.assertEqual(baseline.call_count, 2)
                    # Reopening an already armed runtime must refresh the same baseline.
                    runtime.deactivate("reopen", keep_origin=True)
                    volume[0] = 19
                    runtime.activate(live=True)
                    baseline.assert_called_with(0.19)
                    self.assertEqual(baseline.call_count, 3)
                    runtime.deactivate("done")
                self.assertEqual(calls, [
                    ("/usr/bin/sdef", f"/Applications/{player}.app"),
                    ("pid", 123), ("timeout", 120), ("read",),
                    ("pid", 123), ("timeout", 120), ("read",),
                    ("pid", 123), ("timeout", 120), ("read",),
                ])

    def test_no_player_and_query_error_use_runtime_default_without_writes(self):
        for unavailable in ("no player", "Automation denied (-1743)"):
            with self.subTest(unavailable=unavailable):
                audio = AudioAdapter()
                if unavailable == "no player":
                    audio.players = {}
                backend = MacOSOutputBackend(audio=audio)
                runtime = EmulatorRuntime(profile_by_name("media"), backend)
                with patch.object(audio, "read_player", side_effect=MacOSAudioError(unavailable)), \
                     patch.object(runtime.mapper, "set_media_baseline",
                                  wraps=runtime.mapper.set_media_baseline) as baseline:
                    runtime.activate(live=True)
                    for seq in range(8):
                        runtime.feed(make_raw(accel=pose_level(), seq=seq,
                                              t_ns=seq * 20_000_000))
                    baseline.assert_called_once_with(0.5)
                    runtime.recenter()
                    baseline.assert_called_with(0.5)
                    self.assertEqual(baseline.call_count, 2)
                    runtime.deactivate("done")
                self.assertIsNotNone(backend.player.last_error)
                self.assertEqual(audio.writes, [])
                self.assertEqual(audio.commands, [])


class CoreAudioABI:
    """Inert C-pointer boundary, not evidence of native HAL behavior."""
    def __init__(self):
        self.default = 41
        self.levels = {41: 0.4, 42: 0.2}
        self.writes = []
        self.releases = self.uid_reads = 0
        self.settable = True
        self.no_scalar = self.status = self.bad_size = self.null_uid = False
        self.bad_utf8 = self.nan = self.switch_on_volume = self.ignore_write = False
        self.switch_on_write = False
        self.uids = {41: b"speakers-uid", 42: b"headphones-uid"}
        def exported(fn):
            return lambda *args: fn(*args)
        self.ca = SimpleNamespace(AudioObjectGetPropertyData=exported(self.get),
            AudioObjectHasProperty=exported(lambda *args: not self.no_scalar),
            AudioObjectIsPropertySettable=exported(self.can_set),
            AudioObjectSetPropertyData=exported(self.set))
        self.cf = SimpleNamespace(CFStringGetLength=exported(lambda ref: 20),
            CFStringGetMaximumSizeForEncoding=exported(lambda length, encoding: 80),
            CFStringGetCString=exported(self.string), CFRelease=exported(self.release))

    @staticmethod
    def address(pointer):
        return ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 3)).contents[:]

    def get(self, device, address, qualifier_size, qualifier, size, data):
        selector, scope, element = self.address(address)
        assert qualifier_size == 0 and qualifier is None and element == 0
        if self.status:
            return -2000
        if selector == int.from_bytes(b"dOut", "big"):
            assert device == 1 and scope == int.from_bytes(b"glob", "big")
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))[0] = self.default
        elif selector == int.from_bytes(b"uid ", "big"):
            assert scope == int.from_bytes(b"glob", "big")
            ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0] = None if self.null_uid else device
            self.uid_reads += not self.null_uid
        elif selector == int.from_bytes(b"volm", "big"):
            assert scope == int.from_bytes(b"outp", "big")
            ctypes.cast(data, ctypes.POINTER(ctypes.c_float))[0] = float("nan") if self.nan else self.levels[device]
            if self.switch_on_volume:
                self.default = 41 if self.default == 42 else 42
        else:
            raise AssertionError(selector)
        if self.bad_size:
            ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32))[0] = 1
        return 0

    def can_set(self, device, address, result):
        ctypes.cast(result, ctypes.POINTER(ctypes.c_ubyte))[0] = self.settable
        return 0

    def set(self, device, address, qualifier_size, qualifier, size, data):
        assert self.address(address) == [int.from_bytes(b"volm", "big"), int.from_bytes(b"outp", "big"), 0]
        assert size == 4 and qualifier_size == 0 and qualifier is None
        value = ctypes.cast(data, ctypes.POINTER(ctypes.c_float))[0]
        self.writes.append((device, value))
        if self.switch_on_write:
            self.default = 42
        if not self.ignore_write:
            self.levels[device] = value
        return 0

    def string(self, ref, buffer, size, encoding):
        assert encoding == 0x08000100 and size == 81
        if self.bad_utf8:
            return False
        buffer.value = self.uids[ref.value]
        return True

    def release(self, ref):
        self.releases += 1


class NativeAdapterTests(unittest.TestCase):
    def test_coreaudio_reads_identity_and_writes_captured_object_with_abi(self):
        from triki_controller.output.macos_audio import CoreAudioSystem
        fake = CoreAudioABI()
        system = CoreAudioSystem(coreaudio=fake.ca, corefoundation=fake.cf)
        audio = NativeMacOSAudio(system=system)
        endpoint, level = audio.read_system_endpoint()
        self.assertEqual((endpoint.device_id, endpoint.uid), (41, "speakers-uid"))
        self.assertAlmostEqual(level, 0.4)
        audio.write_system_endpoint(endpoint, 0.65)
        self.assertEqual(fake.writes[0][0], 41)
        self.assertAlmostEqual(fake.levels[41], 0.65)
        self.assertEqual(fake.releases, fake.uid_reads)
        self.assertEqual(fake.ca.AudioObjectGetPropertyData.restype, ctypes.c_int32)
        self.assertEqual(fake.ca.AudioObjectGetPropertyData.argtypes[4],
                         ctypes.POINTER(ctypes.c_uint32))
        self.assertEqual(fake.ca.AudioObjectSetPropertyData.argtypes[4], ctypes.c_uint32)
        self.assertEqual(fake.cf.CFStringGetCString.argtypes[2], ctypes.c_long)

    def test_coreaudio_default_switch_during_read_or_before_write_fails_closed(self):
        from triki_controller.output.macos_audio import CoreAudioSystem
        fake = CoreAudioABI()
        audio = NativeMacOSAudio(system=CoreAudioSystem(coreaudio=fake.ca, corefoundation=fake.cf))
        endpoint, _ = audio.read_system_endpoint()
        fake.default = 42
        with self.assertRaisesRegex(MacOSAudioError, "changed"):
            audio.write_system_endpoint(endpoint, 0.8)
        self.assertEqual(fake.writes, [])
        fake.switch_on_volume = True
        with self.assertRaisesRegex(MacOSAudioError, "changed"):
            audio.read_system_endpoint()
        self.assertEqual(fake.writes, [])

    def test_coreaudio_reused_object_uid_and_switch_at_set_never_write_new_default(self):
        from triki_controller.output.macos_audio import CoreAudioSystem
        fake = CoreAudioABI()
        system = CoreAudioSystem(coreaudio=fake.ca, corefoundation=fake.cf)
        endpoint, _ = system.read_endpoint()
        fake.uids[41] = b"replacement-uid"
        with self.assertRaisesRegex(MacOSAudioError, "changed"):
            system.write_endpoint(endpoint, 0.8)
        self.assertEqual(fake.writes, [])
        endpoint, _ = system.read_endpoint()
        fake.switch_on_write = True
        with self.assertRaisesRegex(MacOSAudioError, "changed"):
            system.write_endpoint(endpoint, 0.8)
        self.assertEqual(fake.writes[0][0], 41)
        self.assertEqual(fake.levels[42], 0.2)

    def test_coreaudio_unsupported_status_size_and_failed_readback_are_explicit(self):
        from triki_controller.output.macos_audio import CoreAudioSystem
        for fault, message in (("no_scalar", "scalar"), ("status", "OSStatus"),
                               ("bad_size", "size"), ("null_uid", "identity"),
                               ("bad_utf8", "identity"), ("nan", "finite")):
            fake = CoreAudioABI()
            setattr(fake, fault, True)
            system = CoreAudioSystem(coreaudio=fake.ca, corefoundation=fake.cf)
            with self.subTest(fault=fault), self.assertRaisesRegex(MacOSAudioError, message):
                system.read_endpoint()
            self.assertEqual(fake.writes, [])
        fake = CoreAudioABI()
        system = CoreAudioSystem(coreaudio=fake.ca, corefoundation=fake.cf)
        endpoint, _ = system.read_endpoint()
        fake.settable = False
        with self.assertRaisesRegex(MacOSAudioError, "writable"):
            system.write_endpoint(endpoint, 0.8)
        self.assertEqual(fake.writes, [])
        fake.settable = True
        fake.ignore_write = True
        with self.assertRaisesRegex(MacOSAudioError, "not applied"):
            system.write_endpoint(endpoint, 0.8)

    def test_player_dictionary_and_pid_addressing_without_launch(self):
        calls = []
        class App:
            def isRunning(self): return True
            def setTimeout_(self, value): calls.append(("timeout", value))
            def soundVolume(self): return 35
            def lastError(self): return None
            def nextTrack(self): calls.append(("next",))
        process = SimpleNamespace(isTerminated=lambda: False,
                                  processIdentifier=lambda: 123,
                                  launchDate=lambda: SimpleNamespace(timeIntervalSince1970=lambda: 1000.0),
                                  bundleURL=lambda: SimpleNamespace(path=lambda: "/Applications/Music.app"))
        running = SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda bundle:
                                  [process] if bundle == "com.apple.Music" else [])
        scripting = SimpleNamespace(applicationWithProcessIdentifier_=lambda pid:
                                    calls.append(("pid", pid)) or App())
        def run(argv, **kwargs):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0,
                '<dictionary><suite><property name="sound volume" access="rw"/>'
                '<command name="next track"/></suite></dictionary>', "")
        audio = NativeMacOSAudio(run=run)
        with patch.object(audio, "_frameworks", return_value=(running, scripting)):
            self.assertEqual(audio.list_players(), ("Music",))
            self.assertEqual(audio.read_player("Music"), 0.35)
            audio.transport("Music", "next_track")
            with self.assertRaisesRegex(MacOSAudioError, "not running"):
                audio.read_player("Spotify")
            with self.assertRaisesRegex(MacOSAudioError, "unsupported"):
                audio.read_player("Chrome")
            with self.assertRaisesRegex(MacOSAudioError, "dictionary"):
                audio.transport("Music", "previous_track")
        self.assertIn(("pid", 123), calls)
        self.assertIn(("timeout", 120), calls)
        self.assertIn(("next",), calls)
        self.assertEqual(sum(call[:1] == ("/usr/bin/sdef",) for call in calls), 1)

    def test_native_player_write_rejects_restart_without_launch_or_setter(self):
        calls = []
        started = [1000.0]
        process = SimpleNamespace(isTerminated=lambda: False,
            processIdentifier=lambda: 123,
            launchDate=lambda: SimpleNamespace(timeIntervalSince1970=lambda: started[0]),
            bundleURL=lambda: SimpleNamespace(path=lambda: "/Applications/Music.app"))
        running = SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda bundle: [process])
        scripting = SimpleNamespace(applicationWithProcessIdentifier_=lambda pid: calls.append(pid))
        audio = NativeMacOSAudio(run=lambda *args, **kwargs: calls.append("sdef"))
        with patch.object(audio, "_frameworks", return_value=(running, scripting)):
            identity = audio.player_identity("Music")
            started[0] = 2000.0  # Same PID, different LaunchServices process generation.
            with self.assertRaisesRegex(MacOSAudioError, "changed"):
                audio.write_player_target("Music", identity, 0.8)
            self.assertEqual(calls, [])
            process.launchDate = lambda: None
            with self.assertRaisesRegex(MacOSAudioError, "identity"):
                audio.player_identity("Music")
        self.assertEqual(calls, [])

    def test_quartz_preflight_and_permission_revocation(self):
        allowed = [False]
        posts = []
        quartz = SimpleNamespace(CGPreflightPostEventAccess=lambda: allowed[0],
            CGEventPost=lambda tap, event: posts.append(event), kCGHIDEventTap=0,
            CGEventCreate=lambda source: object(),
            CGEventGetLocation=lambda event: SimpleNamespace(x=20, y=30),
            CGEventCreateMouseEvent=lambda *args: object(),
            kCGEventMouseMoved=5, kCGMouseButtonLeft=0)
        with patch("sys.platform", "darwin"), patch.dict("sys.modules", {"Quartz": quartz}):
            pointer = QuartzMouseInput()
            with self.assertRaisesRegex(RuntimeError, "Accessibility"):
                pointer.open()
            allowed[0] = True
            pointer.open()
            allowed[0] = False
            with self.assertRaisesRegex(RuntimeError, "Accessibility"):
                pointer.move(1, 0)
        self.assertEqual(posts, [])


def mapped(*, axes=None, pulses=(), buttons=(), deltas=None, epoch=3):
    return MappedState(1, "raw", 7, 11, "test", "1", epoch, buttons, (),
                       axes or {}, deltas or {}, PipelineStageStatus.AVAILABLE, pulses)


class InputAdapter:
    def __init__(self):
        self.events = []

    def open(self):
        self.events.append(("open",))

    def button(self, name, down):
        self.events.append((name, down))

    def move(self, x, y):
        self.events.append(("move", x, y))

    def close(self):
        self.events.append(("close",))


class BackendTests(unittest.TestCase):
    def test_release_failure_reports_error_and_can_retry_without_volume_reset(self):
        class FailingInput(InputAdapter):
            fail = True
            def button(self, name, down):
                if not down and self.fail:
                    raise RuntimeError("Accessibility revoked")
                super().button(name, down)
        pointer = FailingInput()
        backend = MacOSOutputBackend(input_adapter=pointer)
        backend.open({"mode": "mouse", "claim_native": True})
        backend.apply(mapped(buttons=("mouse_left",), epoch=1))
        receipt = backend.neutralize("disconnect")
        self.assertFalse(receipt.applied)
        self.assertIn("Accessibility", receipt.detail)
        with self.assertRaisesRegex(RuntimeError, "Accessibility"):
            backend.close()
        pointer.fail = False
        backend.close()
        self.assertEqual(pointer.events.count(("mouse_left", False)), 1)
        self.assertTrue(backend.closed)

    def test_live_claim_is_required_and_unknown_outputs_are_explicit(self):
        with self.assertRaisesRegex(RuntimeError, "claim"):
            MacOSOutputBackend().open({"mode": "media"})
        backend = MacOSOutputBackend(audio=AudioAdapter())
        with self.assertRaisesRegex(RuntimeError, "not open"):
            backend.apply(mapped())
        backend.open({"mode": "media", "claim_native": True})
        receipt = backend.apply(mapped(axes={"arbitrary_app_volume": 0.2}, epoch=1))
        self.assertFalse(receipt.applied)
        self.assertIn("unsupported absolute axis", receipt.detail)
        backend.close()

    def test_media_receipts_offsets_epochs_and_neutralization(self):
        audio = AudioAdapter()
        backend = MacOSOutputBackend(audio=audio)
        backend.open({"mode": "media", "claim_uinput": True, "activation_epoch": 3})
        receipt = backend.apply(mapped(axes={"player_volume": 0.5}))
        self.assertEqual((receipt.raw_session_id, receipt.raw_connection_epoch,
                          receipt.raw_sample_seq, receipt.activation_epoch, receipt.backend),
                         ("raw", 7, 11, 3, "macos"))
        backend.apply(mapped(axes={"player_volume": 0.6}))
        self.assertAlmostEqual(audio.players["Music"], 0.8)
        backend.apply(mapped(axes={"system_volume": 0}, pulses=("mute",)))
        backend.apply(mapped(axes={"system_volume": 0.2}))
        self.assertAlmostEqual(audio.system, 0.6)
        before = list(audio.writes)
        self.assertFalse(backend.apply(mapped(epoch=2)).applied)
        backend.neutralize("disconnect")
        backend.close()
        self.assertEqual(audio.writes, before)
        self.assertFalse(backend.system.active)

    def test_mouse_fractional_movement_click_release_and_unsupported_mode(self):
        pointer = InputAdapter()
        backend = MacOSOutputBackend(input_adapter=pointer)
        backend.open({"mode": "mouse", "claim_uinput": True, "activation_epoch": 3})
        backend.apply(mapped(buttons=("mouse_left",), deltas={"pointer_x": 0.6}))
        backend.apply(mapped(buttons=("mouse_left",), deltas={"pointer_x": 0.6}))
        self.assertEqual(pointer.events.count(("mouse_left", True)), 1)
        self.assertIn(("move", 1, 0), pointer.events)
        backend.close()
        self.assertIn(("mouse_left", False), pointer.events)
        for mode in ("steering", "plane"):
            with self.assertRaisesRegex(RuntimeError, "virtual"):
                MacOSOutputBackend().open({"mode": mode, "claim_uinput": True})

    def test_errors_are_not_success_and_dry_run_never_calls_adapters(self):
        audio = AudioAdapter()
        audio.players = {}
        backend = MacOSOutputBackend(audio=audio)
        backend.open({"mode": "media", "claim_uinput": True})
        receipt = backend.apply(mapped(axes={"player_volume": 0.5}, epoch=1))
        self.assertFalse(receipt.applied)
        self.assertEqual(receipt.stage_status, PipelineStageStatus.ERROR)
        self.assertIn("browser", receipt.detail)
        backend.close()
        pointer = InputAdapter()
        backend = MacOSOutputBackend(audio=audio, input_adapter=pointer)
        backend.open({"mode": "mouse", "dry_run": True})
        receipt = backend.apply(mapped(buttons=("mouse_left",), epoch=1))
        self.assertTrue(receipt.dry_run)
        self.assertIn("no native", receipt.detail)
        backend.close()
        self.assertEqual(pointer.events, [])
        self.assertEqual(audio.writes, [])


class PlayerTests(unittest.TestCase):
    def test_cycle_same_frame_and_late_availability_rebase_preserving_endless_deltas(self):
        adapter = AudioAdapter()
        backend = MacOSOutputBackend(audio=adapter)
        backend.open({"mode": "media", "claim_native": True, "activation_epoch": 3})
        backend.apply(mapped(axes={"player_volume": 0.7}))
        self.assertEqual(adapter.writes, [])
        backend.apply(mapped(axes={"player_volume": 0.7}, pulses=("cycle_player",)))
        self.assertEqual(adapter.writes, [])
        backend.apply(mapped(axes={"player_volume": 0.8}))
        self.assertAlmostEqual(adapter.players["Spotify"], 0.4)
        backend.apply(mapped(axes={"player_volume": 1.8}))
        self.assertEqual(adapter.players["Spotify"], 1)
        backend.apply(mapped(axes={"player_volume": 1.7}))
        self.assertAlmostEqual(adapter.players["Spotify"], 0.9)
        adapter.players = {}
        self.assertFalse(backend.apply(mapped(axes={"player_volume": 1.7})).applied)
        adapter.players = {"Music": 0.23}
        before = list(adapter.writes)
        self.assertTrue(backend.apply(mapped(axes={"player_volume": 1.7})).applied)
        self.assertEqual(adapter.writes, before)
        backend.apply(mapped(axes={"player_volume": 1.8}))
        self.assertAlmostEqual(adapter.players["Music"], 0.33)
        backend.close()

    def test_player_failure_and_subthreshold_deltas_rebase_without_jump(self):
        adapter = AudioAdapter()
        player = MacOSPlayerVolume(adapter=adapter)
        player.apply_level(0.5)
        for incoming in (0.502, 0.504, 0.506):
            player.apply_level(incoming)
        self.assertEqual(adapter.writes, [])
        player.apply_level(0.51)
        self.assertAlmostEqual(adapter.players["Music"], 0.71)
        with patch.object(adapter, "write_player_target", side_effect=MacOSAudioError("denied")):
            self.assertIn("denied", player.apply_level(0.6))
        adapter.players["Music"] = 0.23
        before = list(adapter.writes)
        self.assertIsNone(player.apply_level(0.7))
        self.assertEqual(adapter.writes, before)
        player.apply_level(0.8)
        self.assertAlmostEqual(adapter.players["Music"], 0.33)

    def test_status_read_does_not_reset_target_translation(self):
        adapter = AudioAdapter()
        player = MacOSPlayerVolume(adapter=adapter)
        player.apply_level(0.5)
        player.apply_level(0.6)
        self.assertAlmostEqual(adapter.players["Music"], 0.8)
        status = player.describe_status()
        self.assertEqual(status.active_player, "Music")
        self.assertTrue(status.volume_writable)
        player.apply_level(0.7)
        self.assertAlmostEqual(adapter.players["Music"], 0.9)

    def test_clamped_mapper_handshake_reaches_full_range_after_cycle(self):
        adapter = AudioAdapter()
        backend = MacOSOutputBackend(audio=adapter)
        backend.open({"mode": "media", "claim_native": True, "activation_epoch": 3})
        backend.apply(mapped(axes={"player_volume": 0.7}))
        backend.take_media_baseline()
        backend.apply(mapped(axes={"player_volume": 0.7}, pulses=("cycle_player",)))
        baseline = backend.take_media_baseline()
        self.assertEqual(baseline, 0.3)
        # Runtime reseeds its existing clamped mapper using the returned actual level.
        for incoming in (0.3, 0.5, 0.8, 1.0, 0.9):
            self.assertTrue(backend.apply(mapped(axes={"player_volume": incoming})).applied)
        self.assertAlmostEqual(adapter.players["Spotify"], 0.9)
        self.assertIsNone(backend.take_media_baseline())
        backend.close()

    def test_restart_and_readonly_recenter_reset_translation_and_muted_generation(self):
        adapter = AudioAdapter()
        player = MacOSPlayerVolume(adapter=adapter)
        player.apply_level(0.7)
        player.apply_level(0.8)
        self.assertAlmostEqual(adapter.players["Music"], 0.8)
        player.apply_pulse("mute")
        adapter.generations["Music"] = 2
        adapter.players["Music"] = 0.23
        before = list(adapter.writes)
        player.apply_level(0.8)
        self.assertEqual(adapter.writes, before)
        player.apply_level(0.9)
        self.assertAlmostEqual(adapter.players["Music"], 0.33)
        adapter.players["Music"] = 0.61
        self.assertAlmostEqual(player.read_volume(), 0.61)
        before = list(adapter.writes)
        player.apply_level(0.61)
        self.assertEqual(adapter.writes, before)
        player.apply_level(0.71)
        self.assertAlmostEqual(adapter.players["Music"], 0.71)

    def test_absolute_player_axis_mute_cycle_and_no_system_fallback(self):
        adapter = AudioAdapter()
        player = MacOSPlayerVolume(adapter=adapter)
        self.assertIsNone(player.apply_level(0.5))
        self.assertEqual(adapter.writes, [])
        self.assertIsNone(player.apply_level(0.6))
        self.assertAlmostEqual(adapter.players["Music"], 0.8)
        self.assertIsNone(player.apply_pulse("mute"))
        self.assertEqual(adapter.players["Music"], 0)
        player.apply_level(0.9)
        self.assertEqual(adapter.players["Music"], 0)
        player.apply_pulse("cycle_player")
        player.apply_level(0.9)
        self.assertAlmostEqual(adapter.players["Spotify"], 0.3)
        player.apply_level(1.0)
        self.assertAlmostEqual(adapter.players["Spotify"], 0.4)
        player.apply_transport("next_track")
        self.assertEqual(adapter.commands, [("Spotify", "next_track")])
        player.apply_pulse("cycle_player")
        player.apply_pulse("mute")
        self.assertAlmostEqual(adapter.players["Music"], 0.8)
        self.assertFalse(any(name == "system" for name, _ in adapter.writes))
        adapter.players = {}
        self.assertIn("browser", player.apply_level(0.5))


class AudioAdapter:
    def __init__(self):
        self.system = 0.4
        self.endpoint = "speakers"
        self.writes = []
        self.players = {"Music": 0.7, "Spotify": 0.3}
        self.commands = []
        self.generations = {"Music": 1, "Spotify": 1}

    def read_system_endpoint(self):
        return self.endpoint, self.system

    def write_system_endpoint(self, endpoint, level):
        if endpoint != self.endpoint:
            raise MacOSAudioError("default output changed")
        self.write_system(level)

    def read_system(self):
        return self.system

    def write_system(self, level):
        self.system = level
        self.writes.append(("system", level))

    def list_players(self):
        return tuple(self.players)

    def player_identity(self, player):
        return player, self.generations[player]

    def read_player(self, player):
        return self.players[player]

    def write_player_target(self, player, identity, level):
        if self.player_identity(player) != identity:
            raise MacOSAudioError("player restarted")
        self.write_player(player, level)

    def write_player(self, player, level):
        self.players[player] = level
        self.writes.append((player, level))

    def transport(self, player, pulse):
        self.commands.append((player, pulse))


class SystemTests(unittest.TestCase):
    def test_default_device_change_first_frame_captures_level_and_offset(self):
        adapter = AudioAdapter()
        system = MacOSSystemVolume(adapter=adapter)
        system.apply_offset(0)
        system.apply_offset(0.1)
        adapter.endpoint = "headphones"
        adapter.system = 0.2
        before = list(adapter.writes)
        self.assertIsNone(system.apply_offset(0.11))
        self.assertEqual(adapter.writes, before)
        self.assertIsNone(system.apply_offset(0.12))
        self.assertAlmostEqual(adapter.system, 0.21)

    def test_identity_unavailable_fails_closed_and_write_failure_rebases(self):
        adapter = AudioAdapter()
        system = MacOSSystemVolume(adapter=adapter)
        system.apply_offset(0)
        with patch.object(adapter, "read_system_endpoint", return_value=(None, 0.4)):
            self.assertIn("identity", system.apply_offset(0.1))
        self.assertEqual(adapter.writes, [])
        system.apply_offset(0.2)
        with patch.object(adapter, "write_system_endpoint", side_effect=MacOSAudioError("gone")):
            self.assertIn("gone", system.apply_offset(0.3))
        adapter.system = 0.23
        self.assertIsNone(system.apply_offset(0.4))
        self.assertEqual(adapter.writes, [])
        system.apply_offset(0.5)
        self.assertAlmostEqual(adapter.system, 0.33)

    def test_offset_clamps_and_nonfinite_values_do_not_write(self):
        adapter = AudioAdapter()
        system = MacOSSystemVolume(adapter=adapter)
        system.apply_offset(0)
        system.apply_offset(3)
        self.assertEqual(adapter.system, 1)
        system.apply_offset(-3)
        self.assertEqual(adapter.system, 0)
        before = list(adapter.writes)
        self.assertIn("finite", system.apply_offset(float("nan")))
        self.assertEqual(adapter.writes, before)

    def test_offset_entry_is_read_only_and_leave_keeps_user_volume(self):
        adapter = AudioAdapter()
        system = MacOSSystemVolume(adapter=adapter)
        self.assertIsNone(system.apply_offset(0.8))
        self.assertEqual(adapter.writes, [])
        self.assertIsNone(system.apply_offset(1.05))
        self.assertAlmostEqual(adapter.system, 0.65)
        system.leave()
        self.assertFalse(system.active)
        self.assertAlmostEqual(adapter.system, 0.65)
        system.apply_offset(-0.9)
        self.assertEqual(len(adapter.writes), 1)
