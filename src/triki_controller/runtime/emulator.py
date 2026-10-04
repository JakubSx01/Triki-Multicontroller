"""Active RAW → FILTERED → PROFILE → OUTPUT path for one profile at a time."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from triki_controller.core.models import (
    SCHEMA_VERSION,
    ConnectionEvent,
    ConnectionState,
    MappedState,
    MotionSample,
    OutputReceipt,
    ParseDiagnostic,
    PipelineStageStatus,
    RawSample,
    StageSnapshot,
)
from triki_controller.motion.orientation import DEFAULT_ORIENTATION, parse_orientation
from triki_controller.motion.tilt import CalibrationResult, TiltMotionProcessor
from triki_controller.output.trace import TraceOutput
from triki_controller.profiles.builtin import Profile
from triki_controller.profiles.devices import DeviceProfileMapper

_STILL_GYRO_DPS = 12.0
_ARM_STILL_SAMPLES = 8
_ARM_MAX_S = 0.5
_G = 9.80665


@dataclass
class EmulatorStep:
    motion: MotionSample
    mapped: MappedState
    receipt: OutputReceipt | None


@dataclass
class EmulatorRuntime:
    profile: Profile
    output: TraceOutput | object
    orientation: str = DEFAULT_ORIENTATION
    motion: TiltMotionProcessor = field(default_factory=TiltMotionProcessor)
    mapper: DeviceProfileMapper = field(default_factory=DeviceProfileMapper)
    _active: bool = False
    _armed: bool = False
    _still: int = 0
    _arm_t0_ns: int | None = None
    _epoch: int = 0
    _live: bool = False
    _button_down: bool = False

    def __post_init__(self) -> None:
        oid = parse_orientation(self.orientation)
        self.orientation = oid
        if self.motion.orientation.id != oid:
            self.motion.set_orientation(oid)

    def set_orientation(self, orientation: str) -> None:
        """Remap IMU axes for mounting. Does not touch BLE. Re-arms control origin."""
        oid = parse_orientation(orientation)
        if oid == self.orientation and self.motion.orientation.id == oid:
            return
        self.orientation = oid
        self.motion.set_orientation(oid)
        self.mapper.reset()
        self._armed = False
        self._still = 0
        self._arm_t0_ns = None

    def pipeline_status(self) -> StageSnapshot:
        if not self._active:
            return StageSnapshot(
                raw=PipelineStageStatus.AVAILABLE,
                filtered=PipelineStageStatus.DISABLED,
                profile_mapping=PipelineStageStatus.DISABLED,
                final_output=PipelineStageStatus.DISABLED,
            )
        return StageSnapshot(
            raw=PipelineStageStatus.AVAILABLE,
            filtered=PipelineStageStatus.AVAILABLE,
            profile_mapping=PipelineStageStatus.AVAILABLE,
            final_output=PipelineStageStatus.AVAILABLE,
        )

    def activate(self, *, live: bool = False) -> None:
        self._live = live
        self._epoch += 1
        self.output.open(self._capabilities())
        self._active = True
        # Capture player volume after the sink is open (live MPRIS, not dry-run stub).
        if self._armed:
            self._arm_media_baseline()

    def switch_profile(self, profile: Profile) -> None:
        """Neutralize the old device, then open the new profile. Does not touch BLE."""
        if self._active:
            self.output.neutralize("profile change")
            self.output.close()
            self._active = False
        self.mapper.reset()
        self.profile = profile.validated()
        self._armed = False
        self._still = 0
        self._arm_t0_ns = None
        self._button_down = False
        self.activate(live=self._live)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def live(self) -> bool:
        return self._active and self._live

    def set_output(self, output: TraceOutput | object) -> None:
        if self._active:
            raise RuntimeError("deactivate before replacing the output backend")
        self.output = output

    def set_profile(self, profile: Profile) -> None:
        """Change profile. Reopens the device only while active; never touches BLE."""
        profile = profile.validated()
        if self._active and profile.mode != self.profile.mode:
            self.switch_profile(profile)
            return
        if profile.mode != self.profile.mode:
            self.mapper.reset()
            self._button_down = False
        self.profile = profile

    def recenter(self) -> None:
        self.motion.recenter()
        self._arm_media_baseline()
        self._armed = True
        self._still = 0
        self._arm_t0_ns = None

    def _arm_media_baseline(self) -> None:
        """Home pose = connect/recenter pose; capture player volume as pot zero."""
        if self.profile.mode != "media":
            return
        baseline = 0.5
        mpris = getattr(self.output, "_mpris", None)
        if mpris is not None and hasattr(mpris, "read_volume"):
            reading = mpris.read_volume()
            if reading is not None:
                baseline = float(reading)
        self.mapper.set_media_baseline(baseline)

    def calibrate(self, stationary_window: list[RawSample]) -> CalibrationResult:
        return self.motion.calibrate(stationary_window)

    def deactivate(self, reason: str, *, keep_origin: bool = False) -> None:
        if self._active:
            pending = self.mapper.take_pending_click()
            if pending is not None:
                self.output.apply(self._pulse_only(pending))
            self.output.neutralize(reason)
            self.output.close()
        self._active = False
        if keep_origin:
            # Keep mapper pot baseline / click state and filter time across output reopen.
            return
        self.mapper.reset()
        self.motion.reset_time()
        self._armed = False
        self._still = 0
        self._arm_t0_ns = None
        self._button_down = False

    def handle_connection(self, event: ConnectionEvent) -> None:
        if event.state == ConnectionState.STREAMING:
            self.motion.reset_time()
            self._armed = False
            self._still = 0
            self._arm_t0_ns = None
            self._button_down = False
        if event.state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR):
            self.deactivate(event.reason or event.state.value)

    def feed(self, sample: RawSample) -> EmulatorStep:
        motion = self.motion.process(sample)
        recenter_pulse = False
        if not self._armed:
            self._observe_arm(motion, sample.received_monotonic_ns)
            mapped = self._neutral_mapped(sample, motion)
            self._button_down = bool(motion.button)
        else:
            motion, recenter_pulse = self._maybe_steering_button_recenter(motion)
            mapped = self.mapper.map(motion, self.profile)
            if recenter_pulse:
                mapped = replace(mapped, pulses=mapped.pulses + ("recenter",))
        mapped = replace(mapped, activation_epoch=self._epoch)
        receipt = None
        if self._active:
            receipt = self.output.apply(mapped)
        return EmulatorStep(motion=motion, mapped=mapped, receipt=receipt)

    def _maybe_steering_button_recenter(
        self, motion: MotionSample
    ) -> tuple[MotionSample, bool]:
        """Rising edge recenters steering origin (mouse uses clicks, not recenter)."""
        pressed = bool(motion.button)
        rising = pressed and not self._button_down
        self._button_down = pressed
        if not rising or self.profile.mode != "steering":
            return motion, False
        self.motion.recenter()
        return (
            replace(
                motion,
                tilt_pitch_deg=0.0 if motion.tilt_pitch_deg is not None else None,
                tilt_roll_deg=0.0 if motion.tilt_roll_deg is not None else None,
                tilt_yaw_deg=0.0 if motion.tilt_yaw_deg is not None else None,
                gravity_alignment=1.0,
            ),
            True,
        )

    def _observe_arm(self, motion: MotionSample, t_ns: int) -> None:
        if self._arm_t0_ns is None:
            self._arm_t0_ns = t_ns
        if _is_still(motion):
            self._still += 1
        else:
            self._still = 0
        elapsed = (t_ns - self._arm_t0_ns) / 1_000_000_000
        if self._still >= _ARM_STILL_SAMPLES or elapsed >= _ARM_MAX_S:
            self.motion.recenter()
            self._arm_media_baseline()
            self._armed = True

    def _neutral_mapped(self, sample: RawSample, motion: MotionSample) -> MappedState:
        axes: dict[str, float] = {}
        if self.profile.mode == "steering":
            axes = {"wheel": 0.0, "throttle": 0.0, "brake": 0.0}
        return MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id=sample.session_id,
            raw_connection_epoch=sample.connection_epoch,
            raw_sample_seq=sample.sample_seq,
            profile_id=self.profile.id,
            profile_revision=self.profile.revision,
            activation_epoch=self._epoch,
            held_buttons=(),
            held_keys=(),
            absolute_axes=axes,
            relative_deltas={},
            stage_status=PipelineStageStatus.AVAILABLE,
            pulses=(),
        )

    def _pulse_only(self, name: str) -> MappedState:
        return MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id="",
            raw_connection_epoch=0,
            raw_sample_seq=0,
            profile_id=self.profile.id,
            profile_revision=self.profile.revision,
            activation_epoch=self._epoch,
            held_buttons=(),
            held_keys=(),
            absolute_axes={},
            relative_deltas={},
            stage_status=PipelineStageStatus.AVAILABLE,
            pulses=(name,),
        )

    def _capabilities(self) -> dict[str, object]:
        names = {
            "steering": "Triki Steering",
            "mouse": "Triki Mouse",
            "plane": "Triki Joystick",
            "media": "Triki Media Keys",
        }
        return {
            "mode": self.profile.mode,
            "claim_uinput": self._live,
            "activation_epoch": self._epoch,
            "device_name": names[self.profile.mode],
            "dry_run": not self._live,
        }


def _is_still(motion: MotionSample) -> bool:
    if motion.accel_m_s2 is None or motion.gyro_rad_s is None:
        return False
    ax, ay, az = motion.accel_m_s2
    mag = math.sqrt(ax * ax + ay * ay + az * az)
    if not (0.85 * _G <= mag <= 1.15 * _G):
        return False
    gx, gy, gz = motion.gyro_rad_s
    gyro_dps = math.sqrt(gx * gx + gy * gy + gz * gz) * (180.0 / math.pi)
    return gyro_dps < _STILL_GYRO_DPS


# Re-export so callers can format diagnostics without importing models twice.
def format_step(step: EmulatorStep, *, orientation: str | None = None) -> str:
    motion = step.motion
    mapped = step.mapped
    pitch = _fmt(motion.tilt_pitch_deg)
    roll = _fmt(motion.tilt_roll_deg)
    yaw = _fmt(motion.tilt_yaw_deg)
    axes = " ".join(f"{k}={v:.2f}" for k, v in mapped.absolute_axes.items())
    deltas = " ".join(f"{k}={v:.1f}" for k, v in mapped.relative_deltas.items())
    pulses = ",".join(mapped.pulses) if mapped.pulses else "-"
    held = ",".join(mapped.held_buttons) if mapped.held_buttons else "-"
    applied = None if step.receipt is None else step.receipt.applied
    mount = f" orient={orientation}" if orientation else ""
    return (
        f"FILTERED pitch={pitch} roll={roll} yaw_rel={yaw}{mount} "
        f"button={motion.button} align={_fmt(motion.gravity_alignment)} "
        f"MAP {mapped.profile_id} held={held} {axes} {deltas} pulses={pulses} "
        f"OUT applied={applied}"
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return "null"
    return f"{value:.1f}"
