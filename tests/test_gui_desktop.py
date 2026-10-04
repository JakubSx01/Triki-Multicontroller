"""Tkinter desktop wiring: settings draft, quick modes, shortcuts. No uinput."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from triki_controller.core.models import SCHEMA_VERSION, ConnectionEvent, ConnectionState
from triki_controller.gui.config_form import resolved_draft, settings_from_draft
from triki_controller.gui.launch import OutputAutostart, apply_quick_profile
from triki_controller.gui.present import (
    battery_label,
    button_label,
    format_measure,
    friendly_connection_detail,
    rssi_label,
    sensor_channels,
)
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings, SettingsError, load_settings, save_settings
from triki_controller.gui.shortcuts import (
    bundled_source_path,
    desktop_directory,
    install_shortcuts,
    normalize_platform,
    plan_shortcuts,
    windows_lnk_command,
)
from triki_controller.output.trace import TraceOutput


class _Factory:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def __call__(self, live: bool) -> TraceOutput:
        self.calls.append(live)
        return TraceOutput()


def _streaming(session: ControllerSession) -> None:
    session._on_connection(
        session._conn_id,
        ConnectionEvent(
            schema_version=SCHEMA_VERSION,
            session_id="t",
            connection_epoch=1,
            event_seq=1,
            host_monotonic_ns=0,
            state=ConnectionState.STREAMING,
            reason="test",
        ),
    )


class PresentTests(unittest.TestCase):
    def test_missing_measurements_stay_unavailable(self) -> None:
        self.assertEqual(format_measure(None, 2), "niedostępne")
        self.assertEqual(format_measure(float("nan"), 1), "niedostępne")
        self.assertEqual(button_label(None), "Przycisk: niedostępny")
        self.assertEqual(battery_label(None), "Bateria: niedostępna")
        self.assertEqual(rssi_label(None), "RSSI: niedostępne")
        session = ControllerSession()
        channels = sensor_channels(session.snapshot())
        self.assertIsNone(channels["accel_counts"])
        self.assertIsNone(channels["gyro_dps"])
        self.assertIsNone(channels["battery_percent"])
        self.assertIsNone(channels["rssi_dbm"])
        session.shutdown()

    def test_friendly_detail_hides_bleak_repr(self) -> None:
        detail = friendly_connection_detail(
            "error",
            "ble error: BleakGATTProtocolError(<BleakGATTProtocolErrorCode.UNLIKELY_ERROR: 14>, "
            "'GATT Protocol Error: Unlikely Error')",
        )
        self.assertNotIn("BleakGATTProtocolError", detail)
        self.assertIn("przycisk", detail.lower())


class DraftSettingsTests(unittest.TestCase):
    def test_draft_round_trip_saves_axis_map(self) -> None:
        draft = resolved_draft(GuiSettings(profile="mouse", invert_roll=True))
        axis_map = draft["axis_map"]
        assert isinstance(axis_map, dict)
        axis_map["steering"]["wheel"] = "roll"
        axis_map["steering"]["brake"] = "off"
        axis_map["mouse"]["x"] = "yaw"
        restored = settings_from_draft(draft, profile="steering")
        self.assertEqual(restored.profile, "steering")
        self.assertTrue(restored.invert_roll)
        self.assertEqual(restored.axis_map["steering"]["wheel"], "roll")
        self.assertEqual(restored.axis_map["mouse"]["x"], "yaw")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(restored, path)
            loaded = load_settings(path)
            assert loaded is not None
            self.assertEqual(loaded.axis_map["steering"]["wheel"], "roll")
            self.assertEqual(loaded.axis_map["steering"]["brake"], "off")
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["schema_version"], 1)
            self.assertEqual(on_disk["axis_map"]["mouse"]["x"], "yaw")

    def test_draft_rejects_bad_sign(self) -> None:
        draft = resolved_draft(GuiSettings())
        axis_map = draft["axis_map"]
        assert isinstance(axis_map, dict)
        axis_map["steering"]["wheel_sign"] = 2
        with self.assertRaises(SettingsError):
            settings_from_draft(draft)


class QuickLaunchTests(unittest.TestCase):
    def test_apply_quick_profile_keeps_session_api(self) -> None:
        session = ControllerSession(settings=GuiSettings(profile="steering"))
        self.assertEqual(session.snapshot().profile_name, "steering")
        self.assertIsNone(apply_quick_profile(session, "mouse"))
        self.assertEqual(session.snapshot().profile_name, "mouse")
        self.assertEqual(session.snapshot().orientation, "horizontal")
        self.assertIsNone(apply_quick_profile(session, "wheel"))
        self.assertEqual(session.snapshot().profile_name, "steering")
        self.assertEqual(session.snapshot().orientation, "vertical")
        self.assertIsNone(apply_quick_profile(session, "music"))
        self.assertEqual(session.snapshot().profile_name, "media")
        self.assertEqual(apply_quick_profile(session, "nope"), "Nieznany tryb 'nope'")
        session.shutdown()

    def test_autostart_arms_once_per_connection(self) -> None:
        factory = _Factory()
        session = ControllerSession(output_factory=factory)
        auto = OutputAutostart(session, live=False)
        # The session builds one idle dry-run sink at startup.
        self.assertEqual(factory.calls, [False])
        self.assertIsNone(auto.tick())
        self.assertEqual(factory.calls, [False])
        _streaming(session)
        self.assertIsNone(auto.tick())
        self.assertEqual(factory.calls, [False, False])
        self.assertEqual(session.snapshot().output_mode, OutputMode.DRY_RUN)
        auto.tick()
        self.assertEqual(factory.calls, [False, False])
        session._on_connection(
            session._conn_id,
            ConnectionEvent(
                schema_version=SCHEMA_VERSION,
                session_id="t",
                connection_epoch=1,
                event_seq=2,
                host_monotonic_ns=1,
                state=ConnectionState.DISCONNECTED,
                reason="test",
            ),
        )
        auto.tick()
        _streaming(session)
        auto.tick()
        self.assertEqual(factory.calls, [False, False, False])
        session.shutdown()

    def test_parser_and_headless_quick_mode_does_not_rewrite_settings(self) -> None:
        from triki_controller.cli.main import build_parser, main

        args = build_parser().parse_args(["mouse", "--dry-run"])
        self.assertEqual(args.command, "mouse")
        self.assertEqual(args.transport, "ble")
        self.assertTrue(args.dry_run)
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["mouse", "--transport", "demo"])
        gui = build_parser().parse_args(["gui", "--transport", "ble", "--connect"])
        self.assertFalse(gui.live)
        help_text = build_parser().format_help()
        self.assertNotIn("--web", help_text)
        self.assertNotIn("\n  web ", help_text)
        # WebUI removed: `web` is not a subcommand.
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["web"])
        self.assertEqual(main(["gui", "--live", "--dry-run"]), 2)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(
                GuiSettings(
                    profile="steering",
                    axis_map={"steering": {"wheel": "roll"}},
                ),
                path,
            )
            before = path.read_text(encoding="utf-8")
            from triki_controller.gui.launch import apply_quick_profile, open_session

            session, _loaded, note = open_session(
                build_parser().parse_args(["music", "--dry-run", "--settings", str(path)])
            )
            self.assertIsNone(note)
            self.assertIsNone(apply_quick_profile(session, "music"))
            session.shutdown()
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            loaded = load_settings(path)
            assert loaded is not None
            self.assertEqual(loaded.profile, "steering")
            self.assertEqual(loaded.axis_map["steering"]["wheel"], "roll")


class ShortcutTests(unittest.TestCase):
    def test_platform_files_mention_quick_commands(self) -> None:
        self.assertEqual(normalize_platform("linux"), "linux")
        self.assertEqual(normalize_platform("win32"), "windows")
        self.assertEqual(normalize_platform("darwin"), "darwin")
        home = Path("/tmp/triki-home")
        common = dict(python="/usr/bin/python3", pythonpath="/src/checkout", directories=[home])
        linux = plan_shortcuts(platform="linux", **common)
        self.assertTrue(any(item.path.name == "triki-mouse.desktop" for item in linux))
        mouse = next(item for item in linux if item.path.name == "triki-mouse.desktop")
        self.assertIn("mouse", mouse.content)
        self.assertIn("--transport", mouse.content)
        self.assertIn("ble", mouse.content)
        self.assertIn("PYTHONPATH=/src/checkout", mouse.content)
        self.assertIn("triki_controller.cli.main", mouse.content)
        self.assertNotIn("dry-run", mouse.content)
        windows = plan_shortcuts(platform="windows", **common)
        music = next(item for item in windows if item.path.name == "triki-music.bat")
        self.assertIn("music", music.content)
        self.assertIn("triki_controller.cli.main", music.content)
        darwin = plan_shortcuts(platform="darwin", **common)
        wheel = next(item for item in darwin if "Kierownica" in item.path.name)
        self.assertIn("wheel", wheel.content)
        self.assertTrue(wheel.executable)
        bat = home / "triki-mouse.bat"
        lnk = home / "triki-mouse.lnk"
        command = windows_lnk_command(bat, lnk)
        self.assertEqual(command[0], "powershell")
        self.assertIn("triki-mouse.bat", command[-1])

    def test_install_and_desktop_dir(self) -> None:
        source = bundled_source_path()
        self.assertIsNotNone(source)
        assert source is not None
        self.assertTrue((Path(source) / "triki_controller").is_dir())
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config = home / ".config"
            config.mkdir()
            (config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Pulpit"\n', encoding="utf-8")
            self.assertEqual(desktop_directory(home), home / "Pulpit")
            dest = home / "launchers"
            written = install_shortcuts(
                platform="linux",
                python=sys.executable,
                pythonpath=None,
                directories=[dest],
            )
            names = sorted(path.name for path in written)
            self.assertEqual(
                names,
                [
                    "triki-controller.desktop",
                    "triki-mouse.desktop",
                    "triki-music.desktop",
                    "triki-wheel.desktop",
                ],
            )
            commands = install_shortcuts(
                platform="darwin",
                python=sys.executable,
                pythonpath=None,
                directories=[dest / "mac"],
            )
            self.assertTrue(commands)
            self.assertTrue(all(path.stat().st_mode & 0o111 for path in commands))
            from triki_controller.cli.main import main

            code = main(
                [
                    "shortcuts",
                    "--dry-run",
                    "--dest",
                    str(home / "unused"),
                    "--platform",
                    "linux",
                    "--python",
                    sys.executable,
                ]
            )
            self.assertEqual(code, 0)
            self.assertFalse((home / "unused").exists())


class LiveDraftApplyTests(unittest.TestCase):
    def test_apply_settings_does_not_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(GuiSettings(profile="steering"), path)
            before = path.read_text(encoding="utf-8")
            session = ControllerSession(settings=load_settings(path))
            draft = resolved_draft(session.current_settings())
            axis_map = draft["axis_map"]
            assert isinstance(axis_map, dict)
            axis_map["steering"]["throttle"] = "roll"
            thresholds = draft["thresholds"]
            assert isinstance(thresholds, dict)
            thresholds["steering"]["brake_full_scale_deg"] = 45.0
            settings = settings_from_draft(draft, profile="steering")
            self.assertIsNone(session.apply_settings(settings))
            self.assertEqual(session.snapshot().profile.brake_full_scale_deg, 45.0)
            from triki_controller.profiles.axis_map import resolve_axis_map

            resolved = resolve_axis_map(session.current_settings().axis_map)
            self.assertEqual(resolved["steering"]["throttle"], "roll")
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            session.shutdown()

    def test_steering_defaults_match_saved_ranges(self) -> None:
        from triki_controller.profiles.builtin import steering_profile
        from triki_controller.profiles.axis_map import DEFAULT_AXIS_MAP

        profile = steering_profile()
        self.assertEqual(profile.brake_full_scale_deg, 40.0)
        self.assertEqual(profile.throttle_full_scale_deg, 40.0)
        self.assertEqual(profile.full_scale_deg, 90.0)
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["wheel"], "roll")
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["throttle"], "pitch")
        draft = resolved_draft(GuiSettings())
        self.assertEqual(draft["thresholds"]["steering"]["brake_full_scale_deg"], 40.0)
        self.assertEqual(draft["thresholds"]["steering"]["throttle_full_scale_deg"], 40.0)

    def test_per_profile_thresholds_survive_profile_switch(self) -> None:
        draft = resolved_draft(GuiSettings(profile="steering"))
        thresholds = draft["thresholds"]
        axis_map = draft["axis_map"]
        assert isinstance(thresholds, dict)
        assert isinstance(axis_map, dict)
        thresholds["steering"]["deadzone_deg"] = 12.0
        thresholds["mouse"]["deadzone_deg"] = 4.0
        thresholds["media"]["volume_tilt_deg"] = 55.0
        thresholds["media"]["player_cycle_timeout_s"] = 3.5
        axis_map["steering"]["wheel"] = "roll"
        axis_map["mouse"]["x"] = "yaw"
        session = ControllerSession(settings=settings_from_draft(draft, profile="steering"))
        self.assertEqual(session.snapshot().profile_name, "steering")
        self.assertEqual(session.thresholds()["deadzone_deg"], 12.0)
        self.assertIsNone(session.apply_settings(settings_from_draft(draft, profile="mouse")))
        self.assertEqual(session.snapshot().profile_name, "mouse")
        self.assertEqual(session.thresholds()["deadzone_deg"], 4.0)
        self.assertIsNone(session.apply_settings(settings_from_draft(draft, profile="media")))
        self.assertEqual(session.snapshot().profile_name, "media")
        self.assertEqual(session.thresholds()["volume_tilt_deg"], 55.0)
        self.assertEqual(session.thresholds()["player_cycle_timeout_s"], 3.5)
        stored = session.current_settings()
        self.assertEqual(stored.thresholds["steering"]["deadzone_deg"], 12.0)
        self.assertEqual(stored.thresholds["mouse"]["deadzone_deg"], 4.0)
        self.assertEqual(stored.axis_map["steering"]["wheel"], "roll")
        self.assertEqual(stored.axis_map["mouse"]["x"], "yaw")
        session.shutdown()


class GuiSmokeTests(unittest.TestCase):
    def test_customtkinter_import_path(self) -> None:
        try:
            import customtkinter  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"customtkinter missing: {exc}")
        import triki_controller.gui.desktop as desktop

        self.assertTrue(callable(desktop.run_desktop))

    def test_panel_builds_when_display_exists(self) -> None:
        try:
            import tkinter as tk
            import customtkinter  # noqa: F401
            from triki_controller.gui.desktop import TrikiDesktop
        except ImportError as exc:
            self.skipTest(f"gui deps missing: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            titles = {
                "panel": "Triki Controller",
                "config": "Konfigurator urządzenia",
                "quick": "Triki AirMouse",
            }
            for view, command, title in (
                ("panel", None, titles["panel"]),
                ("config", None, titles["config"]),
                ("quick", "mouse", titles["quick"]),
            ):
                session = ControllerSession()
                if command:
                    self.assertIsNone(apply_quick_profile(session, command))
                try:
                    app = TrikiDesktop(
                        session,
                        path,
                        view=view,
                        transport="ble",
                        connect=False,
                        live=False,
                        dry_run=False,
                        auto_close=None,
                        quick_command=command,
                    )
                except tk.TclError as exc:
                    session.shutdown()
                    self.skipTest(f"no display: {exc}")
                self.assertEqual(app.root.title(), title)
                app.root.update_idletasks()
                app.close()

    def test_config_layout_sliders_above_preview(self) -> None:
        try:
            import tkinter as tk
            import customtkinter  # noqa: F401
            from triki_controller.gui.config_form import PROFILE_LABELS
            from triki_controller.gui.desktop import TrikiDesktop
        except ImportError as exc:
            self.skipTest(f"gui deps missing: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            session = ControllerSession(settings=GuiSettings(profile="steering"))
            try:
                app = TrikiDesktop(
                    session,
                    path,
                    view="config",
                    transport="ble",
                    connect=False,
                    live=False,
                    dry_run=False,
                    auto_close=None,
                    quick_command=None,
                )
            except tk.TclError as exc:
                session.shutdown()
                self.skipTest(f"no display: {exc}")
            try:
                app.root.update_idletasks()
                self.assertEqual(app._screen, "configurator")
                self.assertIsNotNone(app._dashboard)
                app._select_config_nav("konfiguracja")
                app.root.update_idletasks()
                form = app._config_form
                preview = app._preview
                sensors = app._sensors
                assert form is not None and preview is not None and sensors is not None
                self.assertLess(form.winfo_rooty(), preview.winfo_rooty())
                self.assertLess(preview.winfo_rooty(), sensors.winfo_rooty())
                self.assertEqual(form.selected_profile(), "steering")
                form.tabs.set(PROFILE_LABELS["mouse"])
                err = app._apply_live_draft()
                self.assertIsNone(err)
                self.assertEqual(session.snapshot().profile_name, "mouse")
                self.assertEqual(preview._mode, "mouse")
                form.tabs.set(PROFILE_LABELS["media"])
                self.assertIsNone(app._apply_live_draft())
                self.assertEqual(session.snapshot().profile_name, "media")
                self.assertEqual(preview._mode, "media")
            finally:
                app.close()

    def test_panel_main_menu_has_devices_and_configurator(self) -> None:
        try:
            import tkinter as tk
            import customtkinter  # noqa: F401
            from triki_controller.gui.desktop import TrikiDesktop
        except ImportError as exc:
            self.skipTest(f"gui deps missing: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            session = ControllerSession()
            try:
                app = TrikiDesktop(
                    session,
                    path,
                    view="panel",
                    transport="ble",
                    connect=False,
                    live=False,
                    dry_run=False,
                    auto_close=None,
                    quick_command=None,
                )
            except tk.TclError as exc:
                session.shutdown()
                self.skipTest(f"no display: {exc}")
            try:
                app.root.update_idletasks()
                self.assertEqual(app._screen, "menu")
                app._show_configurator()
                app.root.update_idletasks()
                self.assertEqual(app._screen, "configurator")
                self.assertEqual(app.root.title(), "Konfigurator urządzenia")
                app._show_main_menu()
                app.root.update_idletasks()
                self.assertEqual(app._screen, "menu")
                texts: list[str] = []

                def walk(widget: object) -> None:
                    try:
                        texts.append(str(widget.cget("text")))  # type: ignore[union-attr]
                    except (tk.TclError, ValueError):
                        pass
                    for child in widget.winfo_children():  # type: ignore[union-attr]
                        walk(child)

                walk(app.root)
                self.assertTrue(any("Kierownica" in t for t in texts))
                self.assertFalse(any("Demo" in t for t in texts))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
