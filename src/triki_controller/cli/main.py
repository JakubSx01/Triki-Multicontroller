"""triki-controller CLI — fake and provisional BLE monitor/record.

The preferred UI is the CustomTkinter desktop app
(`gui`, `config`, `mouse`, `wheel`, `music`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from triki_controller import __version__
from triki_controller.core.models import ConnectionEvent, ConnectionState, Notification, ParseDiagnostic, RawSample
from triki_controller.protocol.cap001_hypothesis import Cap001HypothesisFrameParser
from triki_controller.protocol.parser import SyntheticFrameParser
from triki_controller.recording.csv_export import RawCsvWriter, SessionSidecar, utc_now_iso
from triki_controller.runtime.controller import RuntimeController
from triki_controller.transport.fake import FakeTransport, SyntheticStreamSpec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triki-controller",
        description=(
            "Triki Controller. Preferred UI is the CustomTkinter app "
            "(gui, config, mouse, wheel, music); requires 'triki-controller[gui]'. "
            "Default transport is offline fake. "
            "BLE uses TrikiScope reference-hypothesis framing (not measured). "
            "`emulate` maps gravity tilt to a steering wheel, mouse, or media keys. "
            "Live Linux input requires /dev/uinput."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    monitor = sub.add_parser("monitor", help="Print RAW connection state and numeric fields")
    _add_stream_args(monitor)

    record = sub.add_parser("record", help="Record RAW samples to CSV + session.json")
    _add_stream_args(record)
    record.add_argument(
        "--out",
        type=Path,
        default=Path("recordings/latest"),
        help="Output directory for raw_samples.csv and session.json",
    )

    emulate = sub.add_parser(
        "emulate",
        help="Map Triki tilt to a steering wheel, mouse, or media keys",
    )
    emulate.add_argument(
        "--profile",
        choices=("steering", "mouse", "plane", "media"),
        required=True,
        help="steering: roll twist=wheel (vertical mount), forward=throttle, back=brake, button=recenter; "
        "mouse: device X/Y tilt moves the cursor left/right and front/back (horizontal), 1 click=LMB 2=RMB; "
        "plane: held tilt is the stick and the cursor (level = center, 45° ≈ halfway to the edge); "
        "media: endless yaw knob=player volume, "
        "clicks=pause/next/previous, flip=mute and system volume",
    )
    emulate.add_argument(
        "--transport",
        choices=("ble",),
        default="ble",
        help="ble=live CAP001",
    )
    emulate.add_argument(
        "--live",
        action="store_true",
        help="Create a real /dev/uinput device. Omit for a dry-run trace.",
    )
    emulate.add_argument("--invert-pitch", action="store_true")
    emulate.add_argument("--invert-roll", action="store_true")
    emulate.add_argument(
        "--orientation",
        "--rotation",
        dest="orientation",
        default=None,
        metavar="NAME",
        help=(
            "Mounting frame remap before tilt filter "
            "(horizontal, yaw_90, yaw_180, yaw_270, vertical, vertical_180). "
            "Default: horizontal. Ignored for media/mouse (always horizontal) "
            "and steering (always vertical). "
            "Polish aliases: poziomo, pionowo. Separate from --invert-*. "
            "Axis signs remain reference-hypothesis, not HOM-27 measured."
        ),
    )
    emulate.add_argument(
        "--samples",
        type=int,
        default=0,
        help="BLE only: stop after N samples (0 = until disconnect)",
    )
    emulate.add_argument("--scan-timeout", type=float, default=30.0)
    emulate.add_argument("--session-id", default=None)
    emulate.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="gui-settings.json (default: ~/.config/triki-controller/gui-settings.json when it exists)",
    )

    gui = sub.add_parser(
        "gui",
        help="CustomTkinter panel (recommended; requires [gui] extra)",
    )
    add_gui_args(gui)
    gui.add_argument("--live", action="store_true", help="Arm live output once the stream is up")
    gui.add_argument("--dry-run", action="store_true", help="Arm dry-run output once the stream is up")

    config = sub.add_parser(
        "config",
        help="CustomTkinter axis configurator; saves gui-settings.json",
    )
    add_gui_args(config)

    mouse = sub.add_parser("mouse", help="Quick AirMouse: BLE, live output, small status window")
    _add_quick_args(mouse)
    wheel = sub.add_parser("wheel", help="Quick steering wheel: BLE, live output, small status window")
    _add_quick_args(wheel)
    music = sub.add_parser("music", help="Quick media control: BLE, live output, small status window")
    _add_quick_args(music)

    shortcuts = sub.add_parser(
        "shortcuts",
        help="Create desktop launchers for the panel, mouse, wheel, and music",
    )
    shortcuts.add_argument("--dest", type=Path, default=None, help="Write every launcher into this directory")
    shortcuts.add_argument("--platform", choices=("linux", "windows", "darwin"), default=None)
    shortcuts.add_argument("--dry-run", action="store_true", help="Print paths without writing files")
    shortcuts.add_argument("--python", default=None, help=argparse.SUPPRESS)

    return parser


def _add_quick_args(p: argparse.ArgumentParser) -> None:
    add_gui_args(p)
    p.set_defaults(transport="ble")
    p.add_argument(
        "--live",
        action="store_true",
        help="Arm live output when streaming (this is already the quick-launch default)",
    )
    p.add_argument("--dry-run", action="store_true", help="Watch the stream without system input events")
    p.add_argument("--no-window", action="store_true", help="Print status on the console instead of a window")


def add_gui_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--transport", choices=("ble",), default="ble")
    p.add_argument("--connect", action="store_true", help="Connect at startup")
    p.add_argument("--settings", type=Path, default=None, help="Settings JSON path")
    p.add_argument("--scan-timeout", type=float, default=30.0)
    p.add_argument("--auto-close", type=float, default=None, help=argparse.SUPPRESS)


def _add_stream_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--transport",
        choices=("fake", "ble"),
        default="fake",
        help="fake=synthetic offline stream; ble=provisional Bleak NUS (requires [ble] extra)",
    )
    p.add_argument(
        "--samples",
        type=int,
        default=8,
        help="Sample count for fake; optional max samples for ble (0=until disconnect)",
    )
    p.add_argument(
        "--scan-timeout",
        type=float,
        default=30.0,
        help="BLE scan timeout seconds (default 30)",
    )
    p.add_argument(
        "--reconnect-after",
        type=int,
        default=None,
        help="Fake only: simulate disconnect/reconnect after N samples",
    )
    p.add_argument(
        "--malformed",
        action="store_true",
        help="Fake only: inject malformed bytes before valid frames",
    )
    p.add_argument(
        "--split-frames",
        action="store_true",
        help="Fake only: split frames across notifications",
    )
    p.add_argument(
        "--session-id",
        default=None,
        help="Session id (default: generated uuid4)",
    )


def _spec_from_args(args: argparse.Namespace) -> SyntheticStreamSpec:
    return SyntheticStreamSpec(
        sample_count=args.samples,
        reconnect_after=args.reconnect_after,
        include_malformed=args.malformed,
        split_frames=args.split_frames,
    )


def _print_pipeline(controller: RuntimeController) -> None:
    status = controller.pipeline_status().as_dict()
    print("PIPELINE " + " → ".join(f"{k}={v}" for k, v in status.items()), flush=True)


def _print_connection(event: ConnectionEvent) -> None:
    print(
        f"CONN epoch={event.connection_epoch} seq={event.event_seq} "
        f"state={event.state.value} reason={event.reason!r} t_ns={event.host_monotonic_ns}",
        flush=True,
    )


def _print_sample(sample: RawSample) -> None:
    print(
        f"RAW seq={sample.sample_seq} epoch={sample.connection_epoch} "
        f"t_ns={sample.received_monotonic_ns} "
        f"accel={sample.accel_counts} gyro={sample.gyro_counts} "
        f"button={sample.button} tick={sample.device_tick} "
        f"battery={sample.battery_percent} rssi={sample.rssi_dbm} "
        f"rev={sample.protocol_revision} "
        f"not_measured={sample.quality_flags.not_measured} "
        f"frame_hex={sample.raw_frame.hex()} "
        f"notif={list(sample.source_notification_seqs)}",
        flush=True,
    )


def _print_diag(diag: ParseDiagnostic) -> None:
    print(
        f"PARSE kind={diag.kind} epoch={diag.connection_epoch} "
        f"discarded={diag.discarded_bytes} detail={diag.detail!r}",
        flush=True,
    )


def _build_transport_and_controller(args: argparse.Namespace, session_id: str):
    if args.transport == "fake":
        transport = FakeTransport(session_id=session_id, spec=_spec_from_args(args))
        controller = RuntimeController(parser=SyntheticFrameParser())
        label = "fake synthetic-v0"
        return transport, controller, label

    from triki_controller.transport.ble import BleTransport, BleTransportConfig

    transport = BleTransport(
        session_id=session_id,
        config=BleTransportConfig(scan_timeout_seconds=args.scan_timeout),
    )
    controller = RuntimeController(parser=Cap001HypothesisFrameParser())
    label = "ble reference-hypothesis (not measured)"
    return transport, controller, label


async def _run_stream(
    *,
    args: argparse.Namespace,
    record_dir: Path | None,
) -> int:
    session_id = args.session_id or str(uuid.uuid4())
    transport, controller, label = _build_transport_and_controller(args, session_id)
    _print_pipeline(controller)
    print(f"SESSION id={session_id} transport={args.transport} {label}", flush=True)

    csv_writer: RawCsvWriter | None = None
    if record_dir is not None:
        record_dir.mkdir(parents=True, exist_ok=True)
        csv_writer = RawCsvWriter(record_dir / "raw_samples.csv")
        csv_writer.open()

    max_samples = None
    if args.transport == "ble" and args.samples > 0:
        max_samples = args.samples

    try:
        async for event in transport.events():
            if isinstance(event, ConnectionEvent):
                controller.handle_connection(event)
                _print_connection(event)
                continue
            if isinstance(event, Notification):
                for item in controller.handle_notification(event):
                    if isinstance(item, RawSample):
                        _print_sample(item)
                        if csv_writer is not None:
                            csv_writer.write_sample(item)
                        if max_samples is not None and controller.stats.samples >= max_samples:
                            await transport.disconnect()
                    elif isinstance(item, ParseDiagnostic):
                        _print_diag(item)
    finally:
        await transport.disconnect()
        controller.deactivate("cli stop")
        if csv_writer is not None and record_dir is not None:
            csv_writer.close()
            protocol_ref = (
                "synthetic-v0 (not HOM-27 measured)"
                if args.transport == "fake"
                else "reference-hypothesis from TrikiScope (not measured; pending HOM-27)"
            )
            device_meta = (
                {"kind": "fake_synthetic", "note": "No physical CAP001; addresses omitted"}
                if args.transport == "fake"
                else {
                    "kind": "ble_provisional",
                    "note": "Addresses omitted from shared fixtures; not HOM-27 validated",
                }
            )
            sidecar = SessionSidecar(
                session_id=session_id,
                started_at_utc=utc_now_iso(),
                application_version=__version__,
                dependency_versions={"python": ".".join(map(str, sys.version_info[:3]))},
                device_metadata=device_meta,
                protocol_evidence_reference=protocol_ref,
                recording_complete=True,
                sample_count=controller.stats.samples,
                parse_error_count=controller.stats.parse_diagnostics,
                reconnect_count=controller.stats.reconnects,
                notes=[
                    f"transport={args.transport}",
                    protocol_ref,
                    "battery_percent and rssi_dbm intentionally null when absent",
                ],
            )
            sidecar.write(record_dir / "session.json")
            print(
                f"RECORDED dir={record_dir} samples={controller.stats.samples} "
                f"parse_diag={controller.stats.parse_diagnostics} "
                f"reconnects={controller.stats.reconnects}",
                flush=True,
            )

    print(
        "SUMMARY "
        + json.dumps(
            {
                "samples": controller.stats.samples,
                "parse_diagnostics": controller.stats.parse_diagnostics,
                "reconnects": controller.stats.reconnects,
                "transport": args.transport,
                "last_state": (
                    controller.stats.last_state.value if controller.stats.last_state else None
                ),
            }
        ),
        flush=True,
    )
    return 0


def _should_print_step(step: object, *, last: dict[str, float], index: int) -> bool:
    from triki_controller.runtime.emulator import EmulatorStep

    if not isinstance(step, EmulatorStep):
        return False
    if step.mapped.pulses or step.mapped.held_buttons:
        return True
    if index % 10 == 0:
        return True
    interesting = False
    for name, value in step.mapped.absolute_axes.items():
        if abs(value - last.get(name, 0.0)) >= 0.08:
            interesting = True
        last[name] = value
    return interesting


def _load_emulate_settings(
    args: argparse.Namespace,
    profile: object,
) -> tuple[object, dict[str, dict[str, str | float]], Path | None] | None:
    """Apply gui-settings.json to the emulate profile. None means a hard error."""
    from triki_controller.gui.settings import SettingsError, default_settings_path, load_settings
    from triki_controller.profiles.builtin import Profile, profile_by_name, with_overrides

    if not isinstance(profile, Profile):
        raise TypeError("profile must be a Profile")
    explicit = args.settings is not None
    path = args.settings if explicit else default_settings_path()
    if not explicit and not path.is_file():
        return profile, {}, None
    try:
        loaded = load_settings(path)
    except (OSError, SettingsError) as exc:
        if not explicit:
            print(f"note: pominięto {path}: {exc}", file=sys.stderr)
            return profile, {}, None
        print(f"error: {exc}", file=sys.stderr)
        return None
    if loaded is None:
        print(f"error: settings file not found: {path}", file=sys.stderr)
        return None
    built = profile_by_name(
        profile.id,
        invert_pitch=bool(args.invert_pitch or loaded.invert_pitch),
        invert_roll=bool(args.invert_roll or loaded.invert_roll),
    )
    overrides = {key: float(value) for key, value in loaded.thresholds.get(profile.id, {}).items()}
    if overrides:
        built = with_overrides(built, **overrides)
    return built, {name: dict(values) for name, values in loaded.axis_map.items()}, path


async def _run_emulate(args: argparse.Namespace) -> int:
    from triki_controller.motion.orientation import get_orientation, parse_orientation
    from triki_controller.output.trace import TraceOutput
    from triki_controller.profiles.builtin import profile_by_name
    from triki_controller.runtime.emulator import EmulatorRuntime, format_step

    try:
        if args.profile == "media":
            orientation = "horizontal"
            if args.orientation is not None:
                print(
                    "note: media always uses horizontal mounting; ignoring --orientation",
                    flush=True,
                )
        elif args.profile == "steering":
            orientation = "vertical"
            if args.orientation is not None:
                print(
                    "note: steering always uses vertical mounting; ignoring --orientation",
                    flush=True,
                )
        elif args.profile == "mouse":
            orientation = "horizontal"
            if args.orientation is not None:
                print(
                    "note: mouse always uses horizontal mounting; ignoring --orientation",
                    flush=True,
                )
        elif args.orientation is None:
            orientation = "horizontal"
        else:
            orientation = parse_orientation(args.orientation)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    profile = profile_by_name(
        args.profile,
        invert_pitch=args.invert_pitch,
        invert_roll=args.invert_roll,
    )
    loaded = _load_emulate_settings(args, profile)
    if loaded is None:
        return 2
    profile, axis_map, settings_path = loaded
    live = bool(args.live)
    if live:
        from triki_controller.output.uinput_backend import UInputBackend

        output: object = UInputBackend()
        print(
            "LIVE uinput — disconnect, Ctrl+C, or process exit releases buttons and centers axes.",
            flush=True,
        )
        if profile.mode == "media":
            print(
                "Media: play/next/prev via uinput keys; volume/mute via MPRIS (playerctl) "
                "for the active player — not system-wide Pulse volume.",
                flush=True,
            )
    else:
        output = TraceOutput()
        print("DRY-RUN — no Linux input events. Pass --live to use /dev/uinput.", flush=True)

    session_id = args.session_id or str(uuid.uuid4())
    runtime = EmulatorRuntime(profile=profile, output=output, orientation=orientation)
    if axis_map:
        runtime.mapper.set_axis_map(axis_map)
    if settings_path is not None:
        from triki_controller.profiles.axis_map import resolve_axis_map

        active = resolve_axis_map(axis_map)[profile.mode]
        print(f"settings={settings_path} axis_map={json.dumps(active)}", flush=True)
    runtime.activate(live=live)
    _print_pipeline(runtime)
    mount = get_orientation(orientation)
    print(
        f"EMULATE profile={profile.id} transport={args.transport} "
        f"orientation={orientation} ({mount.label_pl}) "
        f"pitch_sign={profile.pitch_sign:+.0f} roll_sign={profile.roll_sign:+.0f} "
        f"session={session_id}",
        flush=True,
    )
    print(
        "Orientation remaps accel/gyro before FILTERED. Invert flags are separate. "
        "Axis mapping is reference-hypothesis, not HOM-27 measured.",
        flush=True,
    )
    if profile.mode == "steering":
        print(
            "Steering is always vertical. Hold still at connect: that pose is pot zero. "
            "Twist the cap like a wheel (absolute pot on the twist axis). "
            "Tip forward = throttle, tip back = brake (shared pitch). Button recenters the pot. "
            "Six-axis IMUs drift; press the button if the center wanders.",
            flush=True,
        )
    elif profile.mode == "mouse":
        print(
            "Mouse is always horizontal. Device axis X (left/right) moves the cursor "
            "left/right; device axis Y (front/back) moves it up/down. "
            "Gyro rate does not move the pointer. One click = left button, two = right.",
            flush=True,
        )
    elif profile.mode == "plane":
        print(
            "Joystick holds tilt like a stick. Level is the center of the focused screen "
            "and a neutral stick. 45° left sits about halfway to the edge and stays there "
            "until the cap comes back to level. The button is the trigger.",
            flush=True,
        )
    else:
        print(
            "Media is always horizontal. Twist right/left changes player volume (MPRIS) "
            "from the level at connect — clamped 0–100%, no unwind past the ends. "
            "Gravity lean does not change volume. One click pauses, two next, three previous. "
            "Flip the cap to mute the player and steer system volume; flip back to restore music.",
            flush=True,
        )

    try:
        from triki_controller.protocol.cap001_hypothesis import Cap001HypothesisFrameParser
        from triki_controller.transport.ble import BleTransport, BleTransportConfig

        parser = Cap001HypothesisFrameParser()
        transport = BleTransport(
            session_id=session_id,
            config=BleTransportConfig(scan_timeout_seconds=args.scan_timeout),
        )
        max_samples = args.samples if args.samples > 0 else None
        seen = 0
        last = {}
        async for event in transport.events():
            if isinstance(event, ConnectionEvent):
                if event.state == ConnectionState.STREAMING:
                    parser.reset(event.connection_epoch)
                runtime.handle_connection(event)
                _print_connection(event)
                if event.state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR):
                    break
                continue
            if not isinstance(event, Notification):
                continue
            for item in parser.feed(event):
                if isinstance(item, ParseDiagnostic):
                    _print_diag(item)
                    continue
                if isinstance(item, RawSample):
                    step = runtime.feed(item)
                    if _should_print_step(step, last=last, index=seen):
                        print(format_step(step, orientation=orientation), flush=True)
                    seen += 1
                    if max_samples is not None and seen >= max_samples:
                        await transport.disconnect()
        return 0
    finally:
        runtime.deactivate("cli stop")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "monitor":
        return asyncio.run(_run_stream(args=args, record_dir=None))
    if args.command == "record":
        return asyncio.run(_run_stream(args=args, record_dir=args.out))
    if args.command == "emulate":
        return asyncio.run(_run_emulate(args))
    if args.command in ("gui", "config", "mouse", "wheel", "music") and getattr(
        args, "live", False
    ) and getattr(args, "dry_run", False):
        print("error: --live i --dry-run wykluczają się", file=sys.stderr)
        return 2
    if args.command == "shortcuts":
        from triki_controller.gui.shortcuts import run_shortcuts_cli

        return run_shortcuts_cli(args)
    if args.command in ("mouse", "wheel", "music") and getattr(args, "no_window", False):
        from triki_controller.gui.launch import run_headless

        return run_headless(args)
    if args.command in ("gui", "config", "mouse", "wheel", "music"):
        try:
            from triki_controller.gui.desktop import run_desktop
        except ImportError as exc:
            from triki_controller.gui.launch import GUI_MISSING_MESSAGE

            print(GUI_MISSING_MESSAGE, file=sys.stderr)
            print(exc, file=sys.stderr)
            return 1
        return run_desktop(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
