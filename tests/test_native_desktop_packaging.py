"""Native packaging mocks are not Windows/macOS runtime certification."""
from pathlib import Path
import ast
import json
import plistlib
import subprocess
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "packaging"))
import build_desktop
from build_desktop import build_command, required_modules
from macos_bundle import (APPLE_EVENTS_USAGE, ENTITLEMENTS, inject_bundle_metadata,
                          makespec_command, spec_build_command, verify_bundle_metadata,
                          write_entitlements)


def test_windows_collects_core_audio_without_linux_backend_dependencies():
    with patch.object(sys, "platform", "win32"):
        command = build_command(target="win32")
    assert "pycaw" in command
    assert "comtypes" in command
    assert "psutil" in command
    assert "evdev" not in command
    assert "pywayland" not in command
    assert "--windowed" in command


def test_linux_collection_remains_native():
    with patch.object(sys, "platform", "linux"):
        command = build_command(target="linux")
    assert "evdev" in command
    assert "pywayland" in command
    assert "pycaw" not in command
    assert "comtypes" not in command
    assert "--windowed" not in command


@pytest.mark.parametrize("target,modules", list(build_desktop.NATIVE_MODULES.items()))
def test_collection_and_preflight_share_platform_scoped_modules(target, modules):
    with patch.object(sys, "platform", target):
        command = build_command(target=target)
    for module in modules:
        assert module in required_modules(target)
        assert command[command.index(module) - 1] == "--collect-all"
    foreign = set().union(*build_desktop.NATIVE_MODULES.values()) - set(modules)
    assert not foreign.intersection(command)
    assert not foreign.intersection(required_modules(target))


@pytest.mark.parametrize("package,target", [
    ("evdev", "linux"), ("pywayland", "linux"),
    ("pycaw", "win32"), ("comtypes", "win32"), ("psutil", "win32"),
    ("pyobjc-framework-Cocoa", "darwin"), ("pyobjc-framework-ScriptingBridge", "darwin"),
    ("pyobjc-framework-Quartz", "darwin")])
def test_requirements_native_dependencies_have_exclusive_os_markers(package, target):
    from packaging.requirements import Requirement
    requirements = [Requirement(line) for line in (ROOT / "packaging/requirements-desktop.txt").read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    matching = [requirement for requirement in requirements if requirement.name == package]
    assert len(matching) == 1
    requirement = matching[0]
    assert requirement.marker is not None
    for host in ("linux", "win32", "darwin"):
        assert requirement.marker.evaluate({"sys_platform": host}) == (host == target)


def test_mac_spec_commands_and_console_scope(tmp_path):
    with patch.object(sys, "platform", "darwin"):
        command = build_command(root=tmp_path, target="darwin")
        console = build_command(root=tmp_path, target="darwin", console=True)
    assert "--windowed" in command
    assert "--osx-entitlements-file" in command
    assert "--windowed" not in console
    assert "--osx-entitlements-file" not in console
    generation = makespec_command(command)
    assert generation[2] == "PyInstaller.utils.cliutils.makespec"
    assert not {"--noconfirm", "--clean", "--distpath", "--workpath"}.intersection(generation)
    assert "--specpath" in generation
    assert "--osx-entitlements-file" in generation
    spec = tmp_path / "packaging/build/TrikiController.spec"
    execution = spec_build_command(command, spec)
    assert execution[-1] == str(spec)
    assert "--windowed" not in execution
    assert "--collect-all" not in execution
    assert "--distpath" in execution
    assert not (tmp_path / "packaging").exists()


@pytest.mark.parametrize("initial", [None, {}, {"CFBundleName": "Custom", "Nested": {"x": [1, True]}},
                                      {"NSAppleEventsUsageDescription": "Custom purpose"}])
def test_info_plist_merge_preserves_existing_metadata(tmp_path, initial):
    spec = tmp_path / "generated.spec"
    spec.write_text(f"app = BUNDLE(coll, name='Demo.app', icon='demo.icns', bundle_identifier='org.demo', info_plist={initial!r})\n")
    info = inject_bundle_metadata(spec)
    tree = ast.parse(spec.read_text())
    call = tree.body[0].value
    keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
    assert keywords["name"] == "Demo.app"
    assert keywords["icon"] == "demo.icns"
    assert keywords["bundle_identifier"] == "org.demo"
    assert keywords["info_plist"] == info
    for key, value in (initial or {}).items():
        assert info[key] == value
    assert info["NSAppleEventsUsageDescription"] == (initial or {}).get("NSAppleEventsUsageDescription", APPLE_EVENTS_USAGE)
    before = spec.read_bytes()
    inject_bundle_metadata(spec)
    assert spec.read_bytes() == before


def test_generated_spec_without_info_keyword_gets_metadata(tmp_path):
    spec = tmp_path / "generated.spec"
    spec.write_text("app = BUNDLE(coll, name='Demo.app')\n")
    assert inject_bundle_metadata(spec)["NSAppleEventsUsageDescription"] == APPLE_EVENTS_USAGE


@pytest.mark.parametrize("source", ["app = COLLECT(exe)", "app = BUNDLE(coll); other = BUNDLE(coll)",
    "app = BUNDLE(coll, info_plist=dynamic)", "app = BUNDLE(coll, info_plist=[])",
    "app = BUNDLE(coll, **options)", "app = BUNDLE(coll, info_plist={'NSAppleEventsUsageDescription': ''})",
    "app = BUNDLE(coll, info_plist={'NSAppleEventsUsageDescription': 123})"])
def test_unsafe_or_missing_bundle_metadata_fails_without_writing(tmp_path, source):
    spec = tmp_path / "generated.spec"
    spec.write_text(source)
    with pytest.raises(ValueError):
        inject_bundle_metadata(spec)
    assert spec.read_text() == source


def test_entitlements_and_final_plist_verification_are_read_only(tmp_path):
    entitlements = tmp_path / "packaging/build/macos-entitlements.plist"
    write_entitlements(entitlements)
    assert plistlib.loads(entitlements.read_bytes()) == ENTITLEMENTS
    bundle = tmp_path / "Demo.app"
    info = bundle / "Contents/Info.plist"
    info.parent.mkdir(parents=True)
    expected = {"NSAppleEventsUsageDescription": APPLE_EVENTS_USAGE}
    info.write_bytes(plistlib.dumps({**expected, "CFBundleName": "Demo"}))
    before = info.read_bytes()
    verify_bundle_metadata(bundle, expected)
    assert info.read_bytes() == before
    info.write_bytes(plistlib.dumps({"CFBundleName": "Demo"}))
    with pytest.raises(ValueError, match="missing or changed"):
        verify_bundle_metadata(bundle, expected)
    info.unlink()
    with pytest.raises(FileNotFoundError):
        verify_bundle_metadata(bundle, expected)


@pytest.mark.parametrize("target,missing", [("win32", "psutil"), ("darwin", "Quartz")])
def test_native_preflight_missing_module_fails_before_subprocess(tmp_path, target, missing):
    with patch.object(sys, "platform", target), patch.object(build_desktop, "ROOT", tmp_path), \
         patch("build_desktop.importlib.util.find_spec", side_effect=lambda name: None if name == missing else object()), \
         patch("build_desktop.subprocess.run") as run:
        with pytest.raises(SystemExit) as exc:
            build_desktop.main(["--target", target])
    assert exc.value.code == 2
    run.assert_not_called()
    assert not (tmp_path / "packaging").exists()


@pytest.mark.parametrize("target,module,symbol", [
    ("linux", "triki_controller.output.uinput_backend", "UInputBackend"),
    ("win32", "triki_controller.output.windows_backend", "WindowsOutputBackend"),
    ("darwin", "triki_controller.output.macos_backend", "MacOSOutputBackend")])
def test_source_and_frozen_use_same_platform_factory(target, module, symbol):
    import types
    from triki_controller.output.platform_backend import create_live_output
    sentinel = object()
    fake = types.ModuleType(module)
    setattr(fake, symbol, lambda: sentinel)
    for frozen in (False, True):
        with patch.object(sys, "platform", target), patch.object(sys, "frozen", frozen, create=True), \
             patch.dict(sys.modules, {module: fake}):
            assert create_live_output() is sentinel


def test_mac_main_injects_before_build_and_reports_actual_commands(tmp_path):
    build = tmp_path / "packaging/build"
    bundle = tmp_path / "packaging/dist/TrikiController.app"
    artifact = bundle / "Contents/MacOS/TrikiController"
    archive = tmp_path / "packaging/dist/test.zip"
    stages = []
    def run(command, **kwargs):
        stages.append(command)
        spec = build / "TrikiController.spec"
        if command[2] == "PyInstaller.utils.cliutils.makespec":
            assert command[command.index("--specpath") + 1] == str(build)
            assert command[command.index("--osx-entitlements-file") + 1] == str(build / "macos-entitlements.plist")
            assert plistlib.loads((build / "macos-entitlements.plist").read_bytes()) == ENTITLEMENTS
            spec.write_text("app = BUNDLE(coll, bundle_identifier='org.demo')\n")
        else:
            assert "NSAppleEventsUsageDescription" in spec.read_text()
            assert command[-1] == str(spec)
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"mock executable, not native certification")
            (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({"NSAppleEventsUsageDescription": APPLE_EVENTS_USAGE}))
            archive.write_bytes(b"mock archive")
        return subprocess.CompletedProcess(command, 0)
    with patch.object(sys, "platform", "darwin"), patch.object(build_desktop, "ROOT", tmp_path), \
         patch("build_desktop.importlib.util.find_spec", return_value=object()), \
         patch("build_desktop.subprocess.run", side_effect=run), \
         patch("build_desktop.artifact_path", return_value=artifact), \
         patch("build_desktop.create_archive", return_value=archive):
        assert build_desktop.main(["--target", "darwin"]) == 0
    report = json.loads((build / "build-report.json").read_text())
    assert report["spec_generation_command"] == stages[0]
    assert report["command"] == stages[1]
    assert report["entitlements_file"] == str(build / "macos-entitlements.plist")
    assert report["bundle_info_plist"]["NSAppleEventsUsageDescription"] == APPLE_EVENTS_USAGE
    assert report["notarized"] is False
    assert report["signing_mode"] == "pyinstaller-default-ad-hoc"


@pytest.mark.parametrize("generation_status,source", [(7, None), (0, None), (0, "app = COLLECT(exe)")])
def test_failed_generation_or_missing_bundle_never_runs_build(tmp_path, generation_status, source):
    build = tmp_path / "packaging/build"
    build.mkdir(parents=True)
    spec = build / "TrikiController.spec"
    spec.write_text("app = BUNDLE(coll)  # stale output must not be reused\n")
    def generate(command, **kwargs):
        assert not spec.exists()
        if source is not None:
            spec.write_text(source)
        return subprocess.CompletedProcess(command, generation_status)
    with patch.object(sys, "platform", "darwin"), patch.object(build_desktop, "ROOT", tmp_path), \
         patch("build_desktop.importlib.util.find_spec", return_value=object()), \
         patch("build_desktop.subprocess.run", side_effect=generate) as run:
        if generation_status:
            assert build_desktop.main(["--target", "darwin"]) == generation_status
        else:
            with pytest.raises((FileNotFoundError, ValueError)):
                build_desktop.main(["--target", "darwin"])
    assert run.call_count == 1
    assert not (build / "build-report.json").exists()


@pytest.mark.parametrize("target", ["linux", "win32", "darwin"])
def test_command_only_is_write_free_and_skips_preflight(tmp_path, target, capsys):
    with patch.object(sys, "platform", target), patch.object(build_desktop, "ROOT", tmp_path), \
         patch("build_desktop.importlib.util.find_spec") as find, \
         patch("build_desktop.subprocess.run") as run:
        assert build_desktop.main(["--target", target, "--command-only"]) == 0
    assert json.loads(capsys.readouterr().out)[2] == "PyInstaller"
    find.assert_not_called()
    run.assert_not_called()
    assert not (tmp_path / "packaging").exists()
