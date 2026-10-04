"""Platform dispatch contracts without native OS APIs or physical BLE."""

import sys
import types
import unittest
from unittest.mock import patch


class PlatformOutputTests(unittest.TestCase):
    def test_native_platforms_select_only_their_adapter(self):
        from triki_controller.output.platform_backend import create_live_output

        for platform, module, name in (
            ("win32", "windows_backend", "WindowsOutputBackend"),
            ("darwin", "macos_backend", "MacOSOutputBackend"),
        ):
            with self.subTest(platform=platform):
                backend = type(name, (), {})
                stub = types.ModuleType(f"triki_controller.output.{module}")
                setattr(stub, name, backend)
                with patch.dict(sys.modules, {stub.__name__: stub}), patch.object(
                    sys, "platform", platform
                ):
                    self.assertIsInstance(create_live_output(), backend)

    def test_unsupported_platform_has_actionable_error(self):
        from triki_controller.output.platform_backend import create_live_output

        with patch.object(sys, "platform", "freebsd14"):
            with self.assertRaisesRegex(RuntimeError, "freebsd14.*dry-run"):
                create_live_output()

    def test_gui_default_factory_uses_native_backend_and_preserves_dry_run(self):
        from triki_controller.gui.session import default_output_factory
        from triki_controller.output.trace import TraceOutput

        backend = type("WindowsOutputBackend", (), {})
        stub = types.ModuleType("triki_controller.output.windows_backend")
        setattr(stub, "WindowsOutputBackend", backend)
        with patch.dict(sys.modules, {stub.__name__: stub}), patch.object(sys, "platform", "win32"):
            self.assertIsInstance(default_output_factory(True), backend)
            self.assertIsInstance(default_output_factory(False), TraceOutput)

    def test_native_media_status_does_not_claim_linux_services(self):

        from triki_controller.gui.session import ControllerSession
        from triki_controller.gui.settings import GuiSettings
        from triki_controller.output.trace import TraceOutput
        from tests.test_gui_session import _stream

        class NativeLive(TraceOutput):
            def open(self, capabilities):
                super().open({**capabilities, "claim_uinput": False})

        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                session = ControllerSession(settings=GuiSettings(profile="media"),
                                            output_factory=lambda live: NativeLive())
                try:
                    _stream(session)
                    self.assertIsNone(session.start_output(live=True))
                    note = session.snapshot().output_note
                    assert note is not None
                    self.assertNotIn("uinput", note)
                    self.assertNotIn("MPRIS", note)
                finally:
                    session.shutdown()

    def test_supported_native_platform_note_is_not_linux_only(self):
        from triki_controller.gui.launch import virtual_input_note

        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                note = virtual_input_note()
                assert note is not None
                self.assertNotIn("Linux uinput", note)
                self.assertIn("gamepad", note)

    def test_direct_cli_native_dispatch_source_and_frozen(self):
        import asyncio
        import contextlib
        import io
        from triki_controller.cli.main import build_parser, _run_emulate
        from triki_controller.output.trace import TraceOutput

        class EmptyBle:
            def __init__(self, **kwargs):
                pass

            async def events(self):
                if False:
                    yield

        for platform, module, name in (
            ("win32", "windows_backend", "WindowsOutputBackend"),
            ("darwin", "macos_backend", "MacOSOutputBackend"),
        ):
            for frozen in (False, True):
                opened = []

                class NativeLive(TraceOutput):
                    def open(self, capabilities):
                        opened.append(dict(capabilities))
                        super().open({**capabilities, "claim_uinput": False})

                stub = types.ModuleType(f"triki_controller.output.{module}")
                setattr(stub, name, NativeLive)
                args = build_parser().parse_args(["emulate", "--profile", "media", "--live"])
                stdout = io.StringIO()
                loop = asyncio.new_event_loop()
                with self.subTest(platform=platform, frozen=frozen), patch.dict(
                    sys.modules, {stub.__name__: stub}
                ), patch.object(sys, "platform", platform), patch.object(
                    sys, "frozen", frozen, create=True
                ), patch("triki_controller.transport.ble.BleTransport", EmptyBle), patch(
                    "triki_controller.cli.main._load_emulate_settings",
                    side_effect=lambda args, profile: (profile, {}, None),
                ), contextlib.redirect_stdout(stdout):
                    with asyncio.Runner(loop_factory=lambda: loop) as runner:
                        self.assertEqual(runner.run(_run_emulate(args)), 0)
                self.assertEqual(len(opened), 1)
                self.assertTrue(opened[0]["claim_uinput"])
                self.assertFalse(opened[0]["dry_run"])
                self.assertEqual(opened[0]["mode"], "media")
                self.assertNotIn("uinput", stdout.getvalue())
                self.assertNotIn("MPRIS", stdout.getvalue())

    def test_quick_autostart_uses_platform_factory_without_settings_writes(self):
        from triki_controller.gui.launch import OutputAutostart, apply_quick_profile
        from triki_controller.gui.session import ControllerSession, OutputMode
        from triki_controller.output.trace import TraceOutput
        from tests.test_gui_session import _stream

        for platform, module, name in (
            ("linux", "uinput_backend", "UInputBackend"),
            ("win32", "windows_backend", "WindowsOutputBackend"),
            ("darwin", "macos_backend", "MacOSOutputBackend"),
        ):
            for command, mode in (("music", "media"), ("mouse", "mouse"), ("wheel", "steering")):
                for frozen in (False, True):
                    opened = []

                    class NativeLive(TraceOutput):
                        def open(self, capabilities):
                            opened.append(dict(capabilities))
                            super().open({**capabilities, "claim_uinput": False})

                    stub = types.ModuleType(f"triki_controller.output.{module}")
                    setattr(stub, name, NativeLive)
                    with self.subTest(platform=platform, command=command, frozen=frozen), patch.dict(
                        sys.modules, {stub.__name__: stub}
                    ), patch.object(sys, "platform", platform), patch.object(
                        sys, "frozen", frozen, create=True
                    ), patch("triki_controller.gui.settings.save_settings") as save:
                        session = ControllerSession()
                        try:
                            self.assertIsNone(apply_quick_profile(session, command))
                            _stream(session)
                            auto = OutputAutostart(session, live=True)
                            self.assertIsNone(auto.tick())
                            self.assertIsNone(auto.tick())
                            self.assertEqual(session.snapshot().output_mode, OutputMode.LIVE)
                            self.assertEqual(len(opened), 1)
                            self.assertEqual(opened[0]["mode"], mode)
                            self.assertTrue(opened[0]["claim_uinput"])
                            save.assert_not_called()
                        finally:
                            session.shutdown()

    def test_gui_unknown_platform_leaves_output_off_with_actionable_note(self):
        from triki_controller.gui.session import ControllerSession, OutputMode
        from tests.test_gui_session import _stream

        with patch.object(sys, "platform", "freebsd14"):
            session = ControllerSession()
            try:
                _stream(session)
                error = session.start_output(live=True)
                assert error is not None
                self.assertIn("freebsd14", error)
                self.assertIn("dry-run", error)
                self.assertEqual(session.snapshot().output_mode, OutputMode.OFF)
                self.assertIsNone(session.start_output(live=False))
                self.assertEqual(session.snapshot().output_mode, OutputMode.DRY_RUN)
            finally:
                session.shutdown()

    def test_live_factory_does_not_import_other_platforms(self):
        import builtins
        from triki_controller.output.platform_backend import create_live_output

        original_import = builtins.__import__
        for platform, module, name in (
            ("linux", "uinput_backend", "UInputBackend"),
            ("win32", "windows_backend", "WindowsOutputBackend"),
            ("darwin", "macos_backend", "MacOSOutputBackend"),
        ):
            stub = types.ModuleType(f"triki_controller.output.{module}")
            setattr(stub, name, type(name, (), {}))
            imports = []

            def checked_import(name, *args, **kwargs):
                imports.append(name)
                if name.startswith("triki_controller.output.") and name.endswith("_backend"):
                    self.assertEqual(name, stub.__name__)
                return original_import(name, *args, **kwargs)

            with self.subTest(platform=platform), patch.dict(sys.modules, {stub.__name__: stub}), patch.object(
                sys, "platform", platform
            ), patch("builtins.__import__", side_effect=checked_import):
                create_live_output()
            self.assertIn(stub.__name__, imports)

    def test_native_gamepad_modes_are_rejected_before_os_dependencies(self):
        from triki_controller.output.platform_backend import create_live_output

        for platform in ("win32", "darwin"):
            for mode in ("steering", "plane"):
                with self.subTest(platform=platform, mode=mode), patch.object(sys, "platform", platform):
                    output = create_live_output()
                    try:
                        with self.assertRaisesRegex(RuntimeError, "virtual.*(driver|unsupported|unavailable)"):
                            output.open({"mode": mode, "claim_uinput": True, "dry_run": False})
                    finally:
                        output.close()

    def test_cli_reports_unknown_platform_and_unsupported_native_modes(self):
        import asyncio
        import contextlib
        import io
        from triki_controller.cli.main import build_parser, _run_emulate

        for platform, profile, expected in (
            ("freebsd14", "media", "dry-run"),
            ("win32", "steering", "virtual"),
            ("darwin", "plane", "unsupported"),
        ):
            args = build_parser().parse_args(["emulate", "--profile", profile, "--live"])
            stderr = io.StringIO()
            loop = asyncio.new_event_loop()
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), patch(
                "triki_controller.cli.main._load_emulate_settings",
                side_effect=lambda args, profile: (profile, {}, None),
            ), contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                with asyncio.Runner(loop_factory=lambda: loop) as runner:
                    self.assertEqual(runner.run(_run_emulate(args)), 2)
            self.assertIn(expected, stderr.getvalue())

    def test_direct_cli_dry_run_never_calls_live_factory(self):
        import asyncio
        import contextlib
        import io
        from triki_controller.cli.main import build_parser, _run_emulate

        class EmptyBle:
            def __init__(self, **kwargs):
                pass

            async def events(self):
                if False:
                    yield

        args = build_parser().parse_args(["emulate", "--profile", "media"])
        loop = asyncio.new_event_loop()
        with patch.object(sys, "platform", "freebsd14"), patch(
            "triki_controller.output.platform_backend.create_live_output",
            side_effect=AssertionError("dry-run must not construct a native backend"),
        ), patch("triki_controller.transport.ble.BleTransport", EmptyBle), patch(
            "triki_controller.cli.main._load_emulate_settings",
            side_effect=lambda args, profile: (profile, {}, None),
        ), contextlib.redirect_stdout(io.StringIO()):
            with asyncio.Runner(loop_factory=lambda: loop) as runner:
                self.assertEqual(runner.run(_run_emulate(args)), 0)

    def test_linux_selects_existing_backend(self):
        from triki_controller.output.platform_backend import create_live_output
        from triki_controller.output.uinput_backend import UInputBackend

        with patch.object(sys, "platform", "linux"):
            self.assertIsInstance(create_live_output(), UInputBackend)


if __name__ == "__main__":
    unittest.main()
