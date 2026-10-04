"""Windows native output, independent of Linux tools and imports.

Dispatcher entry point: WindowsOutputBackend().open(capabilities).
Install Windows-only pycaw/comtypes/psutil dependencies for Core Audio.
SendInput needs no third-party dependency. Steering/plane require a driver
and are deliberately unavailable rather than masquerading as gamepads.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, cast

from triki_controller.core.models import (
    SCHEMA_VERSION, MappedState, OutputReceipt, PipelineStageStatus,
)

_TRANSPORT = {'play_pause', 'next_track', 'previous_track'}
_VOLUME = {'volume_up', 'volume_down', 'mute', 'cycle_player'}
_BUTTONS = {'mouse_left', 'mouse_right'}
_TELEMETRY = {'knob', 'wheel_deg', 'pitch_deg', 'roll_deg', 'lean_x', 'lean_y',
              'yaw_rate_dps', 'pitch_rate_dps'}


class _PlayerBaseline:
    """Runtime baseline reads re-arm mapping; status reads stay observational."""
    def __init__(self, audio):
        self.audio = audio

    def read_volume(self):
        if hasattr(self.audio, 'reset_player'):
            self.audio.reset_player()
        return self.audio.read_volume()

    def __getattr__(self, name):
        return getattr(self.audio, name)


class WindowsOutputBackend:
    BACKEND_NAME = 'windows'

    def __init__(self, *, audio=None, input_adapter=None):
        self.audio: Any = audio
        self.input: Any = input_adapter
        self._owns_audio = audio is None
        self._owns_input = input_adapter is None
        self._mpris = _PlayerBaseline(audio) if audio is not None else None
        self.opened = False
        self.closed = False
        self._epoch = 0
        self._mode = None
        self._held = set()
        self._cleanup_pending = False
        self._input_cleanup_pending = False
        self._fx = self._fy = 0.0
        self._lock = threading.RLock()

    @property
    def media(self):
        return self.audio

    def take_media_baseline(self):
        """Consume a safe player-target baseline for the runtime mapper."""
        with self._lock:
            take = getattr(self.audio, 'take_media_baseline', None)
            return take() if take is not None else None

    def read_player_volume(self):
        with self._lock:
            return self.audio.read_volume() if self.audio else None

    def open(self, capabilities: dict[str, object]) -> None:
        with self._lock:
            mode = str(capabilities.get('mode') or '')
            if mode in {'steering', 'plane'}:
                raise RuntimeError('Windows virtual gamepad/steering unavailable: requires a virtual HID driver')
            if mode not in {'media', 'mouse'}:
                raise RuntimeError(f'unsupported Windows output mode {mode!r}')
            if capabilities.get('dry_run'):
                raise RuntimeError('WindowsOutputBackend is live-only; select TraceOutput for dry-run')
            if self.opened or self._cleanup_pending or (self.closed and (
                    (self._owns_audio and self.audio is not None) or
                    (self._owns_input and self.input is not None))):
                self.close()
            try:
                if self.input is None:
                    from triki_controller.output.windows_input import WindowsInput
                    self.input = WindowsInput()
                if mode == 'media' and self.audio is None:
                    from triki_controller.output.windows_audio import WindowsAudio
                    self.audio = WindowsAudio()
                self._mpris = _PlayerBaseline(self.audio) if self.audio is not None else None
                if self.audio is not None and hasattr(self.audio, 'reset_player'):
                    self.audio.reset_player()
                self._mode = mode
                self._epoch = int(cast(Any, capabilities.get('activation_epoch', 1)))
                self._held.clear()
                self._fx = self._fy = 0.0
                self.opened, self.closed = True, False
            except Exception as exc:
                try:
                    self.close()
                except Exception as cleanup:
                    raise RuntimeError(f'{exc}; failed-open cleanup: {cleanup}') from exc
                raise

    def apply(self, state: MappedState) -> OutputReceipt:
        with self._lock:
            if not self.opened or self.closed:
                raise RuntimeError('WindowsOutputBackend is not open')
            if state.activation_epoch != self._epoch:
                return self._receipt(state, False, f'stale activation_epoch {state.activation_epoch}!={self._epoch}')
            errors = []

            def perform(label, fn, *args):
                try:
                    error = fn(*args)
                    if error:
                        errors.append(f'{label}: {error}')
                        return False
                    return True
                except Exception as exc:
                    errors.append(f'{label}: {exc}')
                    return False

            desired = set(state.held_buttons) | set(state.held_keys)
            for name in sorted(self._held - desired):
                if perform(name, self.input.button, name, False):
                    self._held.remove(name)
            for name in sorted(desired - self._held):
                if name not in _BUTTONS or self._mode != 'mouse':
                    errors.append(f'unsupported held input {name}')
                elif perform(name, self.input.button, name, True):
                    self._held.add(name)
            for pulse in state.pulses:
                if pulse == 'recenter' and self._mode == 'media':
                    if hasattr(self.audio, 'reset_player'):
                        perform('player rebase', self.audio.reset_player)
                elif pulse in _VOLUME and self._mode == 'media':
                    perform('player', self.audio.apply_pulse, pulse)
                elif pulse in _TRANSPORT and self._mode == 'media':
                    # Native global media keys; routing is Windows/app dependent,
                    # not falsely advertised as transport pinned to selected audio.
                    perform('global media key', self.input.transport, pulse)
                elif pulse in _BUTTONS and self._mode == 'mouse':
                    if pulse in self._held:
                        errors.append(f'cannot pulse held button {pulse}')
                    elif perform(pulse, self.input.button, pulse, True):
                        self._held.add(pulse)
                        if perform(pulse, self.input.button, pulse, False):
                            self._held.remove(pulse)
                elif pulse != 'recenter':
                    errors.append(f'unsupported pulse {pulse}')
            for name, value in state.absolute_axes.items():
                if name in _TELEMETRY:
                    continue
                if name == 'player_volume' and self._mode == 'media':
                    perform('player', self.audio.apply_level, value)
                elif name == 'system_volume' and self._mode == 'media':
                    perform('system', self.audio.apply_offset, value)
                elif self._mode == 'mouse' and name in {'pointer_x', 'pointer_y'}:
                    continue
                else:
                    errors.append(f'unsupported axis {name}')
            if self._mode == 'media' and 'system_volume' not in state.absolute_axes:
                perform('system leave', self.audio.leave)
            if self._mode == 'mouse':
                try:
                    dx = float(state.relative_deltas.get('pointer_x', 0))
                    dy = float(state.relative_deltas.get('pointer_y', 0))
                    if not math.isfinite(dx) or not math.isfinite(dy):
                        raise ValueError('non-finite pointer delta')
                    self._fx += dx
                    self._fy += dy
                    ix, iy = int(self._fx), int(self._fy)
                    if (ix or iy) and perform('pointer', self.input.relative, ix, iy):
                        self._fx -= ix
                        self._fy -= iy
                    if {'pointer_x', 'pointer_y'} <= state.absolute_axes.keys():
                        perform('absolute pointer', self.input.absolute,
                                state.absolute_axes['pointer_x'], state.absolute_axes['pointer_y'])
                except Exception as exc:
                    errors.append(f'pointer: {exc}')
            detail = 'Windows SendInput/Core Audio apply'
            if errors:
                detail += '; ' + '; '.join(errors)
            return self._receipt(state, not errors, detail)

    def neutralize(self, reason: str) -> OutputReceipt:
        with self._lock:
            errors = []
            for name in sorted(self._held):
                try:
                    self.input.button(name, False)
                    self._held.remove(name)
                except Exception as exc:
                    errors.append(f'release {name}: {exc}')
            self._fx = self._fy = 0.0
            if self.input is not None and hasattr(self.input, 'neutralize'):
                try:
                    self.input.neutralize()  # Includes failed media-key releases.
                except Exception as exc:
                    errors.append(f'input release: {exc}')
            self._input_cleanup_pending = bool(errors)
            if self.audio is not None:
                if hasattr(self.audio, 'reset_player'):
                    try:
                        self.audio.reset_player()
                    except Exception as exc:
                        errors.append(f'player rebase: {exc}')
                try:
                    self.audio.leave()  # Never restore or zero player/system volume.
                except Exception as exc:
                    errors.append(f'system leave: {exc}')
            self._epoch += 1
            self._cleanup_pending = bool(errors)
            return self._receipt(None, not errors,
                                 '; '.join(errors) or 'released held inputs; volumes unchanged', reason)

    def close(self) -> None:
        with self._lock:
            errors = []
            if self.opened or self._cleanup_pending or self._held:
                receipt = self.neutralize('close')
                if not receipt.applied:
                    errors.append(receipt.detail)
            # Disable dispatch even if cleanup must be retried. Do not discard
            # native ownership until each independent close actually succeeds.
            self.opened, self.closed = False, True
            if self._owns_audio and self.audio is not None:
                try:
                    self.audio.close()
                except Exception as exc:
                    errors.append(f'audio close: {exc}')
                else:
                    self.audio = None
                    self._mpris = None
            if self._owns_input and self.input is not None and not self._input_cleanup_pending:
                try:
                    self.input.close()
                except Exception as exc:
                    errors.append(f'input close: {exc}')
                else:
                    self.input = None
            if errors:
                raise RuntimeError('; '.join(errors))

    def _receipt(self, state, applied, detail, reason=None):
        return OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id=state.raw_session_id if state else '',
            raw_connection_epoch=state.raw_connection_epoch if state else 0,
            raw_sample_seq=state.raw_sample_seq if state else 0,
            activation_epoch=state.activation_epoch if state else self._epoch,
            backend=self.BACKEND_NAME, emitted_monotonic_ns=time.monotonic_ns(),
            applied=applied, dry_run=False, neutralization_reason=reason,
            detail=detail, stage_status=PipelineStageStatus.AVAILABLE if applied else PipelineStageStatus.ERROR,
        )
