"""Linux uinput backend. Translates logical MappedState names to evdev events.

Import of evdev is deferred so offline tests do not require it.

Media volume_up/volume_down/mute go through MPRIS (playerctl) so they change
the active player's volume, not the system mixer. Transport keys prefer MPRIS
when the active player accepts the command, then fall back to uinput media
keys for global XF86 handling. Soft-fails with receipt detail when MPRIS
volume is unavailable or not writable.
"""

from __future__ import annotations

import time

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    OutputReceipt,
    PipelineStageStatus,
)
from triki_controller.output.mpris_volume import MprisPlayerVolume
from triki_controller.output.system_volume import SystemMixer
from triki_controller.output.virtual_pointer import AbsoluteCursor

_KEYS = {
    "volume_up": "KEY_VOLUMEUP",
    "volume_down": "KEY_VOLUMEDOWN",
    "mute": "KEY_MUTE",
    "play_pause": "KEY_PLAYPAUSE",
    "next_track": "KEY_NEXTSONG",
    "previous_track": "KEY_PREVIOUSSONG",
}
_MEDIA_TRANSPORT = frozenset({"play_pause", "next_track", "previous_track"})
_MEDIA_VOLUME = frozenset({"volume_up", "volume_down", "mute", "cycle_player"})
from triki_controller.output.binding_input import KEY_ACTIONS, MOUSE_ACTIONS
_KEYS.update({name: 'KEY_' + name[4:].upper() for name in KEY_ACTIONS})
_KEYS.update({'key_enter': 'KEY_ENTER', 'key_ctrl': 'KEY_LEFTCTRL',
              'key_shift': 'KEY_LEFTSHIFT', 'key_alt': 'KEY_LEFTALT', 'key_escape': 'KEY_ESC'})
_BUTTONS = {"mouse_left": "BTN_LEFT", "mouse_right": "BTN_RIGHT", "mouse_middle": "BTN_MIDDLE", "trigger": "BTN_TRIGGER"}


class UInputBackend:
    """Creates one virtual device for the active profile mode.

    Joystick mode also opens a Wayland absolute pointer: stick 0 is the
    center of the focused screen, and the same deflection offsets the cursor.
    """

    BACKEND_NAME = "uinput"

    def __init__(
        self,
        *,
        mpris: MprisPlayerVolume | None = None,
        system: SystemMixer | None = None,
    ) -> None:
        self.opened = False
        self.closed = False
        self._ui = None
        self._epoch = 0
        self._mode: str | None = None
        self._held: set[str] = set()
        self._axes: dict[str, int] = {}
        self._fx = 0.0
        self._fy = 0.0
        self._ecodes = None
        self._dirty = False
        self._mpris = mpris
        self._mpris_owned = mpris is None
        self._system = system
        self._system_owned = system is None
        self._cursor: AbsoluteCursor | None = None
        self._cursor_note: str | None = None
        self._stick = {"stick_x": 0.0, "stick_y": 0.0}

    @property
    def device(self):
        if self._ui is None:
            return None
        return self._ui.device

    @property
    def mpris(self) -> MprisPlayerVolume | None:
        return self._mpris

    def read_player_volume(self):
        return self._mpris.read_volume() if self._mpris is not None else None

    def list_media_players(self) -> list[tuple[str, str]]:
        if self._mpris is None:
            self._mpris = MprisPlayerVolume()
            self._mpris_owned = True
        return self._mpris.list_media_players()

    def favorite_media_descriptors(self, player_ids=None) -> dict[str, dict[str, str]]:
        if self._mpris is None:
            self._mpris = MprisPlayerVolume()
            self._mpris_owned = True
        return self._mpris.favorite_media_descriptors(player_ids)

    def favorite_media_descriptor(self, player_id: str) -> dict[str, str]:
        self.list_media_players()  # Lazily construct only the observational adapter.
        return self._mpris.favorite_media_descriptor(player_id)

    def select_media_player(self, player_id: str | None) -> None:
        self._media_player = player_id
        if self._mpris is not None:
            self._mpris.select_media_player(player_id)

    def take_media_baseline(self):
        return self._mpris.take_media_baseline() if self._mpris is not None else None

    def open(self, capabilities: dict[str, object]) -> None:
        if not capabilities.get("claim_uinput"):
            raise RuntimeError("UInputBackend requires claim_uinput")
        mode = str(capabilities.get("mode") or "")
        if mode not in {"steering", "mouse", "plane", "media"}:
            raise RuntimeError(f"unsupported uinput mode {mode!r}")
        if self._ui is not None:
            self.close()  # Never replace a device with unresolved key releases.
        ecodes, UInput, AbsInfo = _load_evdev()
        self._ecodes = ecodes
        events = _capabilities(ecodes, AbsInfo, mode)
        events.setdefault(ecodes.EV_KEY, []).extend(
            getattr(ecodes, _KEYS.get(name) or _BUTTONS[name])
            for name in sorted(KEY_ACTIONS | MOUSE_ACTIONS)
            if getattr(ecodes, _KEYS.get(name) or _BUTTONS[name]) not in events[ecodes.EV_KEY])
        name = str(capabilities.get("device_name") or f"Triki {mode}")
        self._ui = UInput(
            events=events,
            name=name,
            vendor=0x1209,
            product={"steering": 0x0001, "mouse": 0x0002, "media": 0x0003, "plane": 0x0004}[mode],
            version=1,
            bustype=ecodes.BUS_VIRTUAL,
            phys="triki-controller/virtual",
        )
        self._mode = mode
        self._epoch = int(capabilities.get("activation_epoch", 1))
        self._held.clear()
        self._axes.clear()
        self._fx = 0.0
        self._fy = 0.0
        self.opened = True
        self.closed = False
        if mode == "media":
            dry_run = bool(capabilities.get("dry_run", False))
            if self._mpris is None or self._mpris_owned:
                self._mpris = MprisPlayerVolume(dry_run=dry_run)
                self._mpris_owned = True
            if self._system is None or self._system_owned:
                self._system = SystemMixer(dry_run=dry_run)
                self._system_owned = True
            if 'media_player' in capabilities:
                self.select_media_player(capabilities['media_player'])
            elif hasattr(self, '_media_player'):
                self._mpris.select_media_player(self._media_player)
        elif self._mpris_owned:
            self._mpris = None
            if self._system is not None:
                self._system.leave()
            if self._system_owned:
                self._system = None
        if mode == "steering":
            self._write_axis("wheel", 0.0)
            self._write_axis("throttle", 0.0)
            self._write_axis("brake", 0.0)
            self._ui.syn()
        if mode == "plane":
            self._stick = {"stick_x": 0.0, "stick_y": 0.0}
            cursor = AbsoluteCursor()
            err = cursor.open()
            if err:
                self._cursor_note = err
                cursor.close()
            else:
                self._cursor = cursor
                where = cursor.output_name or "ekran"
                self._cursor_note = f"kursor na środku: {where}"
                try:
                    cursor.place(0.0, 0.0)
                except Exception as exc:
                    self._cursor_note = f"kursor absolutny: {exc}"
                    cursor.close()
                    self._cursor = None
        self._dirty = True

    def apply(self, state: MappedState) -> OutputReceipt:
        if not self.opened or self.closed or self._ui is None or self._ecodes is None:
            raise RuntimeError("UInputBackend is not open")
        if state.activation_epoch != self._epoch:
            return self._receipt(
                state,
                applied=False,
                reason=None,
                detail=f"stale activation_epoch {state.activation_epoch}!={self._epoch}",
            )
        ignored: list[str] = []
        notes: list[str] = []
        input_errors = []
        desired = set(state.held_buttons) | set(state.held_keys)
        for name in sorted(self._held - desired):
            try:
                if self._write_button(name, 0):
                    self._held.remove(name)
                else:
                    ignored.append(name)
            except Exception as exc:
                input_errors.append(f'release {name}: {exc}')
        for name in sorted(desired - self._held):
            try:
                if self._write_button(name, 1):
                    self._held.add(name)
                else:
                    ignored.append(name)
            except Exception as exc:
                input_errors.append(f'press {name}: {exc}')
        pending_volume: float | None = None
        pending_system: float | None = None
        for name, value in state.absolute_axes.items():
            if name == "player_volume" and self._mode == "media":
                pending_volume = float(value)
                continue
            if name == "system_volume" and self._mode == "media":
                pending_system = float(value)
                continue
            if name in {"stick_x", "stick_y"} and self._mode == "plane":
                if not self._write_stick(name, value):
                    ignored.append(name)
                continue
            if name in {
                "knob",
                "wheel_deg",
                "pitch_deg",
                "roll_deg",
                "lean_x",
                "lean_y",
                "yaw_rate_dps",
                "pitch_rate_dps",
            }:
                continue
            if not self._write_axis(name, value):
                ignored.append(name)
        self._write_pointer(state.relative_deltas)
        for pulse in state.pulses:
            if self._mode == "media" and pulse in _MEDIA_VOLUME:
                if self._mpris is None:
                    notes.append(f"mpris: unavailable for {pulse}")
                    continue
                err = self._mpris.apply_pulse(pulse)
                if err:
                    notes.append(err)
                continue
            if self._mode == "media" and pulse in _MEDIA_TRANSPORT:
                err = "mpris: transport unavailable"
                try:
                    if self._mpris is not None and self._mpris.handles_transport(pulse):
                        err = self._mpris.apply_transport(pulse)
                        if err is None:
                            continue
                except Exception as exc:
                    err = f"mpris: transport {pulse}: {exc}"
                # A manual identity is a routing constraint, not a preference.
                # No discovery/runtime failure may escape to global media keys.
                manual_player = getattr(self, "_media_player",
                                        getattr(self._mpris, "_manual_player", None))
                if manual_player is not None:
                    input_errors.append(err)
                    continue
                if self._mpris is not None:
                    notes.append(f"{err}; fallback uinput {pulse}")
                try:
                    if not self._pulse(pulse):
                        ignored.append(pulse)
                except Exception as exc:
                    input_errors.append(f'pulse {pulse}: {exc}')
                continue
            try:
                if not self._pulse(pulse):
                    ignored.append(pulse)
            except Exception as exc:
                input_errors.append(f'pulse {pulse}: {exc}')
        if pending_volume is not None:
            if self._mpris is None:
                notes.append("mpris: unavailable for player_volume")
            else:
                err = self._mpris.apply_level(pending_volume)
                if err:
                    notes.append(err)
        if self._mode == "media" and self._system is not None:
            if pending_system is not None:
                err = self._system.apply_offset(pending_system)
                if err:
                    notes.append(err)
            elif self._system.active:
                self._system.leave()
        self._ui.syn()
        self._dirty = True
        detail = "uinput apply"
        if self._mode == "media":
            detail = "uinput+mpris apply"
        if ignored:
            detail += "; ignored " + ",".join(ignored)
        applied = not ignored and not input_errors
        notes.extend(input_errors)
        if self._cursor_note:
            notes.append(self._cursor_note)
        if notes:
            detail += "; " + "; ".join(notes)
        return self._receipt(state, applied=applied, reason=None, detail=detail)

    def neutralize(self, reason: str) -> OutputReceipt:
        errors = []
        if self._ui is not None and self._ecodes is not None:
            for name in sorted(self._held):
                try:
                    self._write_button(name, 0)
                    self._ui.syn()
                    self._held.remove(name)
                except Exception as exc:
                    errors.append(f'release {name}: {exc}')
            if self._mode == "steering":
                for name in ("wheel", "throttle", "brake"):
                    self._write_axis(name, 0.0)
            if self._mode == "plane":
                self._write_stick("stick_x", 0.0)
                self._write_stick("stick_y", 0.0)
            self._fx = 0.0
            self._fy = 0.0
            self._ui.syn()
        if self._cursor is not None:
            try:
                self._cursor.place(0.0, 0.0)
            except Exception as exc:
                self._cursor_note = f"kursor absolutny: {exc}"
        if self._system is not None:
            self._system.leave()
        if self._mpris is not None and hasattr(self._mpris, 'reset_player'):
            self._mpris.reset_player()
        self._dirty = bool(self._held)
        self._epoch += 1
        receipt = OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id="",
            raw_connection_epoch=0,
            raw_sample_seq=0,
            activation_epoch=self._epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=not errors,
            dry_run=False,
            neutralization_reason=reason,
            detail="; ".join(errors) or "released held inputs; axes neutral",
            stage_status=PipelineStageStatus.AVAILABLE if not errors else PipelineStageStatus.ERROR,
        )
        return receipt

    def close(self) -> None:
        # Disarm immediately, but retain the device and held set for retries.
        # closed means all owned resources actually closed, not merely requested.
        self.opened = False
        if self._dirty or self._held:
            receipt = self.neutralize("close")
            if not receipt.applied:
                raise RuntimeError(receipt.detail)
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None
        if self._ui is not None:
            self._ui.close()
            self._ui = None
        self.closed = True
        self.opened = False

    def _write_button(self, name: str, value: int) -> bool:
        code_name = _BUTTONS.get(name) or _KEYS.get(name)
        if code_name is None or self._ui is None or self._ecodes is None:
            return False
        # Media transport only — volume keys are not registered on the device.
        if self._mode == "media" and name in _MEDIA_VOLUME:
            return False
        if name in KEY_ACTIONS or name in MOUSE_ACTIONS:
            self._ui.write(self._ecodes.EV_KEY, getattr(self._ecodes, code_name), value)
            return True
        if self._mode == "media" and name not in _MEDIA_TRANSPORT and name not in _BUTTONS:
            return False
        if self._mode == "plane" and name != "trigger":
            return False
        if self._mode == "mouse" and name == "trigger":
            return False
        code = getattr(self._ecodes, code_name)
        self._ui.write(self._ecodes.EV_KEY, code, value)
        return True

    def _pulse(self, name: str) -> bool:
        if name in self._held:
            return False
        if not self._write_button(name, 1):
            return False
        self._held.add(name)
        self._ui.syn()
        self._write_button(name, 0)
        self._ui.syn()
        self._held.remove(name)
        return True

    def _write_axis(self, name: str, value: float) -> bool:
        if self._ui is None or self._ecodes is None or self._mode != "steering":
            return False
        spec = {
            "wheel": (self._ecodes.ABS_X, -32767, 32767),
            "throttle": (self._ecodes.ABS_GAS, 0, 255),
            "brake": (self._ecodes.ABS_BRAKE, 0, 255),
        }.get(name)
        if spec is None:
            return False
        code, lo, hi = spec
        if lo < 0:
            raw = int(round(max(-1.0, min(1.0, value)) * hi))
        else:
            raw = int(round(max(0.0, min(1.0, value)) * hi))
        raw = max(lo, min(hi, raw))
        if self._axes.get(name) == raw:
            return True
        self._axes[name] = raw
        self._ui.write(self._ecodes.EV_ABS, code, raw)
        return True

    def _write_pointer(self, deltas: object) -> None:
        if self._mode != "mouse" or self._ui is None or self._ecodes is None:
            return
        if not isinstance(deltas, dict):
            return
        self._fx += float(deltas.get("pointer_x", 0.0))
        self._fy += float(deltas.get("pointer_y", 0.0))
        ix = int(self._fx)
        iy = int(self._fy)
        self._fx -= ix
        self._fy -= iy
        if ix:
            self._ui.write(self._ecodes.EV_REL, self._ecodes.REL_X, ix)
        if iy:
            self._ui.write(self._ecodes.EV_REL, self._ecodes.REL_Y, iy)

    def _write_stick(self, name: str, value: float) -> bool:
        if self._ui is None or self._ecodes is None or self._mode != "plane":
            return False
        code = {"stick_x": self._ecodes.ABS_X, "stick_y": self._ecodes.ABS_Y}.get(name)
        if code is None:
            return False
        clamped = max(-1.0, min(1.0, float(value)))
        self._ui.write(self._ecodes.EV_ABS, code, int(round(clamped * 32767)))
        self._stick[name] = clamped
        if self._cursor is not None:
            try:
                self._cursor.place(self._stick["stick_x"], self._stick["stick_y"])
            except Exception as exc:
                self._cursor_note = f"kursor absolutny: {exc}"
                self._cursor.close()
                self._cursor = None
        return True

    def _receipt(
        self,
        state: MappedState,
        *,
        applied: bool,
        reason: str | None,
        detail: str,
    ) -> OutputReceipt:
        return OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id=state.raw_session_id,
            raw_connection_epoch=state.raw_connection_epoch,
            raw_sample_seq=state.raw_sample_seq,
            activation_epoch=state.activation_epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=applied,
            dry_run=False,
            neutralization_reason=reason,
            detail=detail,
            stage_status=PipelineStageStatus.AVAILABLE if applied else PipelineStageStatus.ERROR,
        )


def _load_evdev():
    try:
        from evdev import UInput, ecodes
        from evdev.device import AbsInfo
    except ImportError as exc:
        raise ImportError(
            "Live virtual input needs python-evdev "
            "(install the 'uinput' extra or the system evdev package)."
        ) from exc
    return ecodes, UInput, AbsInfo


def _capabilities(ecodes, AbsInfo, mode: str) -> dict:
    if mode == "mouse":
        return {
            ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT],
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
        }
    if mode == "media":
        # Transport only — volume is MPRIS/playerctl (player volume, not system).
        return {
            ecodes.EV_KEY: [
                ecodes.KEY_PLAYPAUSE,
                ecodes.KEY_NEXTSONG,
                ecodes.KEY_PREVIOUSSONG,
            ]
        }
    if mode == "plane":
        return {
            ecodes.EV_KEY: [ecodes.BTN_TRIGGER],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(0, -32767, 32767, 0, 0, 0)),
                (ecodes.ABS_Y, AbsInfo(0, -32767, 32767, 0, 0, 0)),
            ],
        }
    return {
        ecodes.EV_KEY: [ecodes.BTN_JOYSTICK],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, AbsInfo(0, -32767, 32767, 0, 0, 0)),
            (ecodes.ABS_GAS, AbsInfo(0, 0, 255, 0, 0, 0)),
            (ecodes.ABS_BRAKE, AbsInfo(0, 0, 255, 0, 0, 0)),
        ],
    }
