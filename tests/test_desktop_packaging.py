"""Public packaging seams: routing, asset manifest, build command, shortcuts."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "tools"))


class DesktopPackagingTests(unittest.TestCase):
    def test_default_entrypoint_forwards_gui_arguments(self):
        from desktop_entry import main
        with patch("triki_controller.gui.launch.gui_main", return_value=17) as gui:
            self.assertEqual(main(["--auto-close", "0.1"]), 17)
        gui.assert_called_once_with(["--auto-close", "0.1"])


    def test_quick_commands_forward_without_losing_options(self):
        from desktop_entry import main
        for command in ("gui", "config", "mouse", "wheel", "music"):
            argv = [command, "--settings", "/tmp/explicit settings.json", "--auto-close", "1"]
            with self.subTest(command=command), patch("triki_controller.cli.main.main", return_value=0) as cli:
                self.assertEqual(main(argv), 0)
                cli.assert_called_once_with(argv)

    def test_tray_route_preserves_arguments(self):
        from desktop_entry import main
        argv = ["music", "--dry-run", "--tray"]
        with patch("desktop_entry.run_tray", return_value=0) as tray:
            self.assertEqual(main(argv), 0)
            tray.assert_called_once_with(argv)

    def test_assets_are_recursive_and_keep_relative_paths(self):
        from build_desktop import asset_manifest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "src/triki_controller/gui/assets/nested"
            assets.mkdir(parents=True)
            (assets / "font.ttf").write_bytes(b"test asset")
            (assets / "LICENSE").write_text("license", encoding="utf-8")
            (assets / "helper.py").write_text("# code", encoding="utf-8")
            found = [(p.name, dest) for p, dest in asset_manifest(root)]
            self.assertEqual(found, [("LICENSE", "triki_controller/gui/assets/nested"),
                                     ("font.ttf", "triki_controller/gui/assets/nested")])

    def test_cross_compilation_is_rejected(self):
        from build_desktop import build_command
        other = "win32" if sys.platform != "win32" else "linux"
        with self.assertRaisesRegex(ValueError, "not a cross-compiler"):
            build_command(target=other)

    def test_native_build_collects_gui_tray_and_assets(self):
        from build_desktop import build_command
        command = build_command()
        self.assertIn("--onedir", command)
        self.assertIn("customtkinter", command)
        self.assertIn("pystray", command)
        self.assertIn("bleak", command)
        self.assertTrue(command[-1].endswith("packaging/desktop_entry.py"))
        self.assertIn(str(ROOT / "packaging/build"), command)

    def test_artifact_names_match_native_formats(self):
        from build_desktop import artifact_path
        self.assertEqual(artifact_path(target="win32").name, "TrikiController.exe")
        self.assertEqual(artifact_path(target="darwin").parts[-4:],
                         ("TrikiController.app", "Contents", "MacOS", "TrikiController"))
        self.assertNotIn("TrikiController.app", artifact_path(target="darwin", console=True).parts)

    def test_linux_native_launchers_target_frozen_binary(self):
        from desktop_shortcuts import install_shortcuts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "binary with spaces"
            exe.write_text("test only", encoding="utf-8")
            paths = install_shortcuts(exe, root / "shortcuts", platform="linux")
            self.assertEqual(len(paths), 7)
            self.assertIn(" plane\n", (root / "shortcuts/Triki-Plane.desktop").read_text())
            self.assertIn(" gui --tray\n", (root / "shortcuts/Triki-Tray.desktop").read_text())
            for path in paths:
                contents = path.read_text()
                self.assertIn(f'Exec="{exe}"', contents)
                self.assertNotIn("python", contents)
                self.assertIn("Terminal=false", contents)

    def test_shortcuts_reject_missing_executable(self):
        from desktop_shortcuts import install_shortcuts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                install_shortcuts(root / "missing", root / "dest", platform="linux")
            self.assertFalse((root / "dest").exists())

    def test_smoke_isolates_settings_and_restores_environment(self):
        import os
        from desktop_entry import smoke
        previous = os.environ.get("HOME")
        observed = []
        def gui(argv):
            settings = Path(argv[argv.index("--settings") + 1])
            self.assertEqual(settings.parent, Path(os.environ["HOME"]))
            self.assertFalse(settings.exists())
            self.assertNotIn("--connect", argv)
            self.assertIn("--dry-run", argv)
            observed.append(settings)
            return 0
        with patch("triki_controller.cli.main.main", return_value=0) as cli, \
             patch("triki_controller.gui.launch.gui_main", side_effect=gui):
            self.assertEqual(smoke(), 0)
        cli.assert_called_once_with(["monitor", "--transport", "fake", "--samples", "4"])
        self.assertEqual(os.environ.get("HOME"), previous)
        self.assertFalse(observed[0].parent.exists())


    def test_smoke_rejects_app_settings_writes(self):
        import os
        from desktop_entry import smoke
        def gui(argv):
            path = Path(argv[argv.index("--settings") + 1])
            path.write_text("{}", encoding="utf-8")
            return 0
        previous = os.environ.get("HOME")
        with patch("triki_controller.cli.main.main", return_value=0), \
             patch("triki_controller.gui.launch.gui_main", side_effect=gui):
            with self.assertRaisesRegex(RuntimeError, "wrote app settings"):
                smoke()
        self.assertEqual(os.environ.get("HOME"), previous)

    def test_linux_archive_preserves_whole_bundle_and_permissions(self):
        import tarfile
        from build_desktop import create_archive
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "packaging/dist/TrikiController"
            internal = bundle / "_internal"
            internal.mkdir(parents=True)
            (internal / "asset.ttf").write_bytes(b"font-test")
            exe = bundle / "TrikiController"
            exe.write_bytes(b"executable-test")
            exe.chmod(0o755)
            with patch("build_desktop.ROOT", root):
                archive = create_archive(exe, target="linux")
            with tarfile.open(archive) as source:
                self.assertIn("TrikiController/_internal/asset.ttf", source.getnames())
                self.assertEqual(source.getmember("TrikiController/TrikiController").mode, 0o755)

    def test_mac_command_launcher_is_native_executable_wrapper(self):
        from desktop_shortcuts import install_shortcuts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "app with spaces"
            exe.write_bytes(b"test")
            paths = install_shortcuts(exe, root / "shortcuts", platform="darwin")
            self.assertEqual(len(paths), 7)
            plane = root / "shortcuts/Triki Plane.command"
            self.assertEqual(plane.read_text(), f"#!/bin/sh\nexec '{exe}' plane \"$@\"\n")
            self.assertTrue(plane.stat().st_mode & 0o111)


    def test_frozen_gui_shortcut_adapter_uses_native_binary(self):
        from desktop_shortcuts import activate_frozen_shortcuts
        from triki_controller.gui import shortcuts as existing
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "TrikiController"
            exe.write_bytes(b"test")
            dest = root / "desktop"
            with patch.object(existing, "install_shortcuts"), patch.object(existing, "plan_shortcuts"), \
                 patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(exe)):
                activate_frozen_shortcuts()
                planned = existing.plan_shortcuts(platform="linux", python="ignored-python",
                                                  pythonpath="ignored-src", directories=[dest])
                self.assertEqual(len(planned), 7)
                self.assertFalse(dest.exists())
                written = existing.install_shortcuts(platform="linux", python="ignored-python",
                                                      pythonpath="ignored-src", directories=[dest])
                self.assertEqual([p.path for p in planned], written)
                for path in written:
                    self.assertIn(f'Exec="{exe}"', path.read_text())
                    self.assertNotIn("triki_controller.cli.main", path.read_text())


if __name__ == "__main__":
    unittest.main()
