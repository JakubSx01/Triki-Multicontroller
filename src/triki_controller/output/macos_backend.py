"""Native macOS output contract; no Linux imports or virtual-HID promises."""
from __future__ import annotations

import math
import time

from triki_controller.core.models import (
    SCHEMA_VERSION, MappedState, OutputReceipt, PipelineStageStatus,
)
from triki_controller.output.macos_audio import (
    MacOSPlayerVolume, MacOSSystemVolume, NativeMacOSAudio,
)
from triki_controller.output.macos_input import QuartzMouseInput

_METADATA = frozenset({"knob", "wheel_deg", "pitch_deg", "roll_deg", "lean_x", "lean_y",
                       "yaw_rate_dps", "pitch_rate_dps"})
_VOLUME = frozenset({"volume_up", "volume_down", "mute", "cycle_player"})
_TRANSPORT = frozenset({"play_pause", "next_track", "previous_track"})
_MOUSE = frozenset({"mouse_left", "mouse_right"})


class MacOSOutputBackend:
    BACKEND_NAME = "macos"

    def __init__(self, *, audio=None, input_adapter=None, player=None, system=None):
        adapter = audio or NativeMacOSAudio()
        self.player = player or MacOSPlayerVolume(adapter=adapter)
        self.system = system or MacOSSystemVolume(adapter=adapter)
        self._input = input_adapter or QuartzMouseInput()
        self.opened = False
        self.closed = False
        self._mode = None
        self._epoch = 0
        self._held = set()
        self._fx = self._fy = 0.0
        self._dry_run = False
        self._dirty = False

    @property
    def _mpris(self):
        # Compatibility seam used by EmulatorRuntime to capture the player baseline.
        return self.player

    def take_media_baseline(self):
        return self.player.take_media_baseline()

    @property
    def device(self):
        # Quartz posts events, not a discoverable joystick/device.
        return None

    def open(self, capabilities):
        if self.opened and not self.closed:
            raise RuntimeError("MacOSOutputBackend is already open")
        mode = str(capabilities.get("mode") or "")
        if mode in {"plane", "steering"}:
            raise RuntimeError(f"macOS {mode}: virtual joystick/steering unsupported; "
                               "no supported virtual HID driver is included")
        if mode not in {"mouse", "media"}:
            raise RuntimeError(f"unsupported macOS mode {mode!r}")
        dry_run = bool(capabilities.get("dry_run", False))
        # Legacy claim name is kept compatible with the existing session contract;
        # it grants live output, not use of Linux uinput on macOS.
        if not dry_run and not (capabilities.get("claim_native") or
                                capabilities.get("claim_uinput")):
            raise RuntimeError("macOS live output requires claim_native or claim_uinput")
        if mode == "mouse" and not dry_run:
            self._input.open()
        self._mode = mode
        self._epoch = int(capabilities.get("activation_epoch", 1))
        self._dry_run = dry_run
        self._held.clear()
        self._fx = self._fy = 0.0
        self.player.leave()
        self.system.leave()
        self.opened, self.closed = True, False
        self._dirty = False

    def apply(self, state: MappedState) -> OutputReceipt:
        if not self.opened or self.closed:
            raise RuntimeError("MacOSOutputBackend is not open")
        if state.activation_epoch != self._epoch:
            return self._receipt(state, False, "stale activation_epoch "
                                 f"{state.activation_epoch}!={self._epoch}",
                                 status=PipelineStageStatus.AVAILABLE)
        if self._dry_run:
            return self._receipt(state, True, "dry-run: no native output emitted")
        errors = []
        self._dirty = True
        desired = set(state.held_buttons) | set(state.held_keys)
        if self._mode == "mouse":
            for name in sorted(self._held - desired):
                try:
                    self._input.button(name, False)
                    self._held.remove(name)
                except Exception as exc:  # Includes Objective-C bridge errors; never BaseException.
                    errors.append(f"release {name}: {exc}")
            for name in sorted(desired - self._held):
                if name not in _MOUSE:
                    errors.append(f"unsupported held input {name}")
                    continue
                try:
                    self._input.button(name, True)
                    self._held.add(name)
                except Exception as exc:  # Includes Objective-C bridge errors; never BaseException.
                    errors.append(f"press {name}: {exc}")
            try:
                x = float(state.relative_deltas.get("pointer_x", 0))
                y = float(state.relative_deltas.get("pointer_y", 0))
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("pointer delta must be finite")
                self._fx += x
                self._fy += y
                ix, iy = int(self._fx), int(self._fy)
                if ix or iy:
                    self._input.move(ix, iy)
                self._fx -= ix
                self._fy -= iy
            except Exception as exc:  # Includes Objective-C bridge errors; never BaseException.
                errors.append(f"mouse: {exc}")
        elif desired:
            errors.append("media held inputs unsupported; use mapped pulses")
        for name in state.relative_deltas:
            if self._mode != "mouse" or name not in {"pointer_x", "pointer_y"}:
                errors.append(f"unsupported relative delta {name}")
        # Pulses precede level writes: mute must not be overwritten by this frame's axis.
        for pulse in state.pulses:
            if self._mode == "media" and pulse in _VOLUME:
                err = self.player.apply_pulse(pulse)
                if err:
                    errors.append(err)
            elif self._mode == "media" and pulse in _TRANSPORT:
                err = self.player.apply_transport(pulse)
                if err:
                    errors.append(err)
            elif self._mode == "mouse" and pulse in _MOUSE:
                try:
                    if pulse not in self._held:
                        self._input.button(pulse, True)
                        self._held.add(pulse)
                        self._input.button(pulse, False)
                        self._held.remove(pulse)
                except Exception as exc:  # Includes Objective-C bridge errors; never BaseException.
                    errors.append(f"pulse {pulse}: {exc}")
            else:
                errors.append(f"unsupported pulse {pulse}")
        axes = state.absolute_axes
        inverted = self._mode == "media" and "system_volume" in axes
        for name, value in axes.items():
            if self._mode == "media" and name == "system_volume":
                err = self.system.apply_offset(value)
                if err:
                    errors.append(err)
            elif self._mode == "media" and name == "player_volume":
                if inverted:
                    errors.append("conflicting player_volume/system_volume axes")
                    continue
                err = self.player.apply_level(value)
                if err:
                    errors.append(err)
            elif name not in _METADATA:
                errors.append(f"unsupported absolute axis {name}")
        if not inverted:
            self.system.leave()
        if inverted or "player_volume" not in axes:
            self.player.leave()
        detail = "native macOS output submitted" if not errors else "; ".join(errors)
        return self._receipt(state, not errors, detail)

    def neutralize(self, reason):
        errors = []
        if not self._dry_run:
            for name in sorted(self._held):
                try:
                    self._input.button(name, False)
                    self._held.remove(name)
                except Exception as exc:  # Includes Objective-C bridge errors; never BaseException.
                    errors.append(f"release {name}: {exc}")
        self._fx = self._fy = 0.0
        self.system.leave()
        self.player.leave()
        self._dirty = bool(self._held)
        self._epoch += 1
        return OutputReceipt(
            SCHEMA_VERSION, "", 0, 0, self._epoch, self.BACKEND_NAME,
            time.monotonic_ns(), not errors, self._dry_run, reason,
            "; ".join(errors) if errors else "released held inputs; volume left unchanged",
            PipelineStageStatus.ERROR if errors else PipelineStageStatus.AVAILABLE,
        )

    def close(self):
        if self.opened and not self.closed:
            if self._dirty:
                receipt = self.neutralize("close")
                if not receipt.applied:
                    raise RuntimeError(receipt.detail)
            if self._mode == "mouse" and not self._dry_run:
                self._input.close()
            self.system.leave()
            self.player.leave()
        self.closed, self.opened = True, False

    def _receipt(self, state, applied, detail, *, status=None):
        return OutputReceipt(
            SCHEMA_VERSION, state.raw_session_id, state.raw_connection_epoch,
            state.raw_sample_seq, state.activation_epoch, self.BACKEND_NAME,
            time.monotonic_ns(), applied, self._dry_run, None, detail,
            status or (PipelineStageStatus.AVAILABLE if applied else PipelineStageStatus.ERROR),
        )
