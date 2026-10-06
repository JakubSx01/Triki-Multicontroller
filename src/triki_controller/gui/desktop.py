"""CustomTkinter main menu, configurator submenu, and quick-launch status.

Main menu: device launch + shortcuts + entry to the in-process configurator.
Configurator: sidebar (Podgląd / Konfiguracja / …) with mockup preview cards.
Quick CLI modes keep a small status window. Config never arms live uinput.
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox
from typing import Any, Callable

from triki_controller.core.models import ConnectionState
from triki_controller.gui.app_icon import apply_window_icon
from triki_controller.gui.config_form import (
    MAP_FIELDS,
    PROFILE_LABELS,
    SIGN_CHOICES,
    SLIDER_FIELDS,
    source_labels,
    MapField,
    SliderField,
    default_profile_slice,
    resolved_draft,
    settings_from_draft,
    snap_step,
)
from triki_controller.gui.launch import (
    GUI_MISSING_MESSAGE,
    QUICK_PROFILES,
    OutputAutostart,
    apply_quick_profile,
    open_session,
    virtual_input_note,
)
from triki_controller.gui.present import (
    battery_label,
    button_label,
    connection_label,
    format_mapped,
    format_measure,
    friendly_connection_detail,
    media_preview,
    mouse_preview,
    output_label,
    rssi_label,
    sensor_channels,
    steering_preview,
)
from triki_controller.gui.preview_cards import PreviewDashboard
from triki_controller.gui.control_options import ControlOptions
from triki_controller.gui.session import ControllerSession
from triki_controller.gui.settings import (
    PROFILE_NAMES,
    GuiSettings,
    SettingsError,
    save_settings,
)
from triki_controller.output.mpris_volume import MprisPlayerVolume

_DEVICE_LAUNCH = {
    "steering": ("wheel", "Kierownica", "Uruchom kierownicę (BLE + Live)"),
    "mouse": ("mouse", "AirMouse", "Uruchom mysz powietrzną (BLE + Live)"),
    "plane": ("plane", "Joystick", "Uruchom joystick samolotu (BLE + Live)"),
    "media": ("music", "Multimedia", "Uruchom sterowanie muzyką (BLE + Live)"),
}
_CONFIG_NAV = (
    ("podglad", "Podgląd"),
    ("konfiguracja", "Konfiguracja"),
    ("profile", "Profile"),
    ("ustawienia", "Ustawienia"),
    ("informacje", "Informacje"),
)

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - exercised via CLI ImportError path
    raise ImportError(GUI_MISSING_MESSAGE) from exc

POLL_MS = 40
_AXIS = ("X", "Y", "Z")
_BG = "#F5F6F8"
_SURFACE = "#FFFFFF"
_TEXT = "#1A1D23"
_MUTED = "#5C6370"
_ACCENT = "#2F6FED"
_BORDER = "#D5D9E0"
_SENSOR_ROWS = (
    ("Akcelerometr, zliczenia", "accel_counts", 8192.0, 0),
    ("Żyroskop, zliczenia", "gyro_counts", 32768.0, 0),
    ("Akcelerometr, m/s²", "accel_m_s2", 20.0, 2),
    ("Żyroskop, rad/s", "gyro_rad_s", 4.0, 3),
    ("Żyroskop, °/s", "gyro_dps", 250.0, 1),
)
_TILT_ROWS = (
    ("Pitch", "tilt_pitch_deg", 180.0, 1, "°"),
    ("Roll", "tilt_roll_deg", 180.0, 1, "°"),
    ("Yaw", "tilt_yaw_deg", 180.0, 1, "°"),
)


def _apply_theme() -> None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")


class BiMeter(ctk.CTkFrame):
    """Compact bipolar bar. None draws an empty center, not a fake zero."""

    def __init__(self, parent: Any, label: str) -> None:
        super().__init__(parent, fg_color="transparent")
        ctk.CTkLabel(self, text=label, width=140, anchor="w", text_color=_TEXT).pack(side="left")
        self._var = tk.StringVar(value="niedostępne")
        ctk.CTkLabel(self, textvariable=self._var, width=90, anchor="e", text_color=_MUTED).pack(
            side="left"
        )
        self._canvas = tk.Canvas(
            self,
            width=150,
            height=14,
            bg=_SURFACE,
            highlightthickness=1,
            highlightbackground=_BORDER,
            bd=0,
        )
        self._canvas.pack(side="left", padx=6)
        self._bar = self._canvas.create_rectangle(75, 2, 75, 12, fill=_ACCENT, width=0)
        self._last: tuple[str, float | None] | None = None

    def update_value(self, value: object, scale: float, digits: int, suffix: str = "") -> None:
        text = format_measure(value, digits)
        if text != "niedostępne" and suffix:
            text = f"{text}{suffix}"
        fraction: float | None
        if text == "niedostępne" or scale == 0:
            fraction = None
        else:
            fraction = max(-1.0, min(1.0, float(value) / scale))  # type: ignore[arg-type]
        key = (text, None if fraction is None else round(fraction, 3))
        if key == self._last:
            return
        self._last = key
        self._var.set(text)
        if fraction is None or fraction == 0:
            self._canvas.coords(self._bar, 75, 2, 75, 12)
            return
        if fraction > 0:
            self._canvas.coords(self._bar, 75, 2, 75 + fraction * 72, 12)
        else:
            self._canvas.coords(self._bar, 75 + fraction * 72, 2, 75, 12)


class UniMeter(ctk.CTkFrame):
    """0–1 bar for throttle/brake/volume."""

    def __init__(self, parent: Any, label: str) -> None:
        super().__init__(parent, fg_color="transparent")
        ctk.CTkLabel(self, text=label, width=100, anchor="w", text_color=_TEXT).pack(side="left")
        self._var = tk.StringVar(value="—")
        ctk.CTkLabel(self, textvariable=self._var, width=56, anchor="e", text_color=_MUTED).pack(
            side="left"
        )
        self._canvas = tk.Canvas(
            self,
            width=160,
            height=14,
            bg=_SURFACE,
            highlightthickness=1,
            highlightbackground=_BORDER,
            bd=0,
        )
        self._canvas.pack(side="left", padx=6)
        self._bar = self._canvas.create_rectangle(2, 2, 2, 12, fill=_ACCENT, width=0)
        self._last: str | None = None

    def update_fraction(self, value: float | None, *, percent: bool = True) -> None:
        if value is None:
            text = "—"
            fraction = 0.0
        else:
            clamped = max(0.0, min(1.0, float(value)))
            text = f"{clamped * 100:.0f}%" if percent else f"{clamped:.2f}"
            fraction = clamped
        if text == self._last:
            return
        self._last = text
        self._var.set(text)
        self._canvas.coords(self._bar, 2, 2, 2 + fraction * 156, 12)


class SensorBoard(ctk.CTkFrame):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color=_SURFACE, corner_radius=8, border_width=1, border_color=_BORDER)
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        self._meters: dict[str, BiMeter] = {}
        for title, key, _scale, _digits in _SENSOR_ROWS:
            block = ctk.CTkFrame(inner, fg_color="transparent")
            block.pack(fill="x", pady=3)
            ctk.CTkLabel(block, text=title, text_color=_MUTED, anchor="w").pack(anchor="w")
            for index, axis in enumerate(_AXIS):
                meter = BiMeter(block, axis)
                meter.pack(fill="x")
                self._meters[f"{key}:{index}"] = meter
        tilt = ctk.CTkFrame(inner, fg_color="transparent")
        tilt.pack(fill="x", pady=3)
        ctk.CTkLabel(tilt, text="Pochylenie po filtrze", text_color=_MUTED, anchor="w").pack(
            anchor="w"
        )
        for label, key, _scale, _digits, _suffix in _TILT_ROWS:
            meter = BiMeter(tilt, label)
            meter.pack(fill="x")
            self._meters[key] = meter
        self.meta = tk.StringVar(value="Brak próbki")
        self.scalars = tk.StringVar(value="")
        self.mapped = tk.StringVar(value="Brak zmapowanych osi.")
        ctk.CTkLabel(inner, textvariable=self.meta, text_color=_TEXT, anchor="w").pack(
            anchor="w", pady=(6, 0)
        )
        ctk.CTkLabel(
            inner, textvariable=self.scalars, text_color=_MUTED, anchor="w", wraplength=640, justify="left"
        ).pack(anchor="w")
        ctk.CTkLabel(
            inner, textvariable=self.mapped, text_color=_TEXT, anchor="w", wraplength=640, justify="left"
        ).pack(anchor="w")

    def update_snapshot(self, snap: object) -> None:
        from triki_controller.gui.session import SessionSnapshot

        if not isinstance(snap, SessionSnapshot):
            return
        channels = sensor_channels(snap)
        for title_key, key, scale, digits in _SENSOR_ROWS:
            del title_key
            values = channels[key]
            for index in range(3):
                value = None if not isinstance(values, tuple) else values[index]
                self._meters[f"{key}:{index}"].update_value(value, scale, digits)
        for _label, key, scale, digits, suffix in _TILT_ROWS:
            self._meters[key].update_value(channels[key], scale, digits, suffix)
        connected = snap.connection == ConnectionState.STREAMING
        if connected:
            protocol = channels["protocol_revision"] or "protokół ?"
            self.meta.set(f"{protocol} · {channels['frame_bytes']} B · próbka {channels['sample_seq']}")
        else:
            self.meta.set("Brak próbki")
        quat = channels["relative_orientation"]
        quat_text = "Kwaternion: niedostępny"
        if isinstance(quat, tuple):
            quat_text = "Kwaternion: " + " ".join(format_measure(part, 3) for part in quat)
        tick = channels["device_tick"]
        tick_text = "Tick: niedostępny" if tick is None else f"Tick: {tick}"
        gravity = channels["gravity_alignment"]
        gravity_text = (
            "Grawitacja: niedostępna"
            if gravity is None
            else f"Grawitacja: {format_measure(gravity, 3)}"
        )
        dt = channels["dt_s"]
        dt_text = "dt: niedostępne" if dt is None else f"dt: {format_measure(float(dt) * 1000, 1)} ms"
        button = channels["button"]
        button_state = button if isinstance(button, bool) or button is None else None
        self.scalars.set(
            " · ".join(
                (
                    button_label(button_state),
                    battery_label(snap.battery_percent),
                    rssi_label(snap.rssi_dbm),
                    tick_text,
                    gravity_text,
                    dt_text,
                    quat_text,
                )
            )
        )
        self.mapped.set(format_mapped(snap.mapped))


class OutputPreview(ctk.CTkFrame):
    """Bars + simple diagram from PROFILE MAPPING (mapped), not raw IMU."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color=_SURFACE, corner_radius=8, border_width=1, border_color=_BORDER)
        pad = ctk.CTkFrame(self, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=10, pady=10)
        self._pad = pad
        ctk.CTkLabel(pad, text="Podgląd wyjścia (mapowanie)", text_color=_TEXT, font=("", 14, "bold")).pack(
            anchor="w"
        )
        self._hint = tk.StringVar(value="Połącz źródło — wartości z PROFILE MAPPING, bez uinput.")
        ctk.CTkLabel(pad, textvariable=self._hint, text_color=_MUTED, anchor="w").pack(anchor="w")
        self._steering_box = ctk.CTkFrame(pad, fg_color="transparent")
        self._wheel = UniMeter(self._steering_box, "Kierownica L/R")
        self._throttle = UniMeter(self._steering_box, "Gaz")
        self._brake = UniMeter(self._steering_box, "Hamulec")
        self._wheel.pack(fill="x", pady=2)
        self._throttle.pack(fill="x", pady=2)
        self._brake.pack(fill="x", pady=2)
        self._diagram = tk.Canvas(
            pad, width=220, height=70, bg=_SURFACE, highlightthickness=1, highlightbackground=_BORDER, bd=0
        )
        self._mouse_label = tk.StringVar(value="Mysz: —")
        self._media_label = tk.StringVar(value="Media: —")
        self._chips = tk.StringVar(value="")
        self._mouse_row = ctk.CTkLabel(pad, textvariable=self._mouse_label, text_color=_TEXT, anchor="w")
        self._media_row = ctk.CTkLabel(pad, textvariable=self._media_label, text_color=_TEXT, anchor="w")
        self._chips_row = ctk.CTkLabel(pad, textvariable=self._chips, text_color=_MUTED, anchor="w")
        self._mpris = MprisPlayerVolume()
        self._last_mpris_poll = 0.0
        self._mpris_status = None
        self._mode: str | None = None
        self._show_mode("steering")

    def _show_mode(self, profile: str) -> None:
        if profile == self._mode:
            return
        self._mode = profile
        self._steering_box.pack_forget()
        self._diagram.pack_forget()
        self._mouse_row.pack_forget()
        self._media_row.pack_forget()
        self._chips_row.pack_forget()
        if profile == "steering":
            self._steering_box.pack(fill="x", pady=2)
            self._diagram.pack(anchor="w", pady=6)
        elif profile == "mouse":
            self._mouse_row.pack(anchor="w")
            self._diagram.pack(anchor="w", pady=6)
            self._chips_row.pack(anchor="w")
        elif profile == "plane":
            self._mouse_row.pack(anchor="w")
            self._chips_row.pack(anchor="w")
        else:
            self._media_row.pack(anchor="w")
            self._diagram.pack(anchor="w", pady=6)
            self._chips_row.pack(anchor="w")

    def _media_status(self):
        """MPRIS identity at 1 Hz. Every UI tick was blocking the window in playerctl."""
        now = time.monotonic()
        cached = self._mpris_status
        if cached is not None and (now - self._last_mpris_poll) < 1.0:
            return cached
        status = self._mpris.describe_status()
        self._mpris_status = status
        self._last_mpris_poll = now
        return status

    def update_snapshot(self, snap: object) -> None:
        from triki_controller.gui.session import SessionSnapshot

        if not isinstance(snap, SessionSnapshot):
            return
        profile = snap.profile_name
        self._show_mode(profile)
        if profile == "steering":
            values = steering_preview(snap.mapped)
            wheel = values["wheel"]
            # Map [-1,1] wheel to 0–1 bar centered conceptually via absolute.
            wheel_frac = None if wheel is None else (float(wheel) + 1.0) / 2.0
            self._wheel.update_fraction(wheel_frac, percent=True)
            self._throttle.update_fraction(values["throttle"])
            self._brake.update_fraction(values["brake"])
            self._draw_steering(wheel, values["throttle"], values["brake"])
            self._hint.set("Kierownica: L/R, gaz %, hamulec % (mapped)")
            self._chips.set("")
            return
        if profile == "mouse":
            prev = mouse_preview(snap.mapped, snap.pointer_px_per_s)
            dx = prev["dx"]
            dy = prev["dy"]
            if dx is None or dy is None:
                self._mouse_label.set("Mysz: brak ruchu")
                self._draw_mouse(None, None)
            else:
                self._mouse_label.set(f"Mysz: Δx {float(dx):+.0f} px/s · Δy {float(dy):+.0f} px/s")
                self._draw_mouse(float(dx), float(dy))
            pulses = set(prev["pulses"])  # type: ignore[arg-type]
            recent = {p for _t, p in snap.recent_pulses}
            chips = []
            if "mouse_left" in pulses or "mouse_left" in recent:
                chips.append("LPM")
            if "mouse_right" in pulses or "mouse_right" in recent:
                chips.append("PPM")
            self._chips.set(" · ".join(chips) if chips else "Kliknięcia: —")
            self._hint.set(
                "AirMouse: oś X kapsli (lewo/prawo) rusza kursorem w lewo/prawo, "
                "oś Y (przód/tył) w górę/dół. Jeden klik LPM, dwa PPM."
            )
            return
        if profile == "plane":
            axes = {} if snap.mapped is None else snap.mapped.absolute_axes
            sx = axes.get("stick_x")
            sy = axes.get("stick_y")
            if sx is None or sy is None:
                self._mouse_label.set("Joystick: brak wychylenia")
            else:
                self._mouse_label.set(
                    f"Joystick: X {float(sx):+.2f} · Y {float(sy):+.2f}"
                )
            trigger = bool(snap.mapped and "trigger" in snap.mapped.held_buttons)
            self._chips.set("spust" if trigger else "Spust: —")
            self._hint.set(
                "Joystick trzyma pochylenie. Poziomo gałka i kursor są na środku. "
                "45° w lewo zostawia kursor mniej więcej w połowie drogi do krawędzi. "
                "Zatrzymanie ruchu nic nie cofa."
            )
            return
        # media
        prev = media_preview(snap.mapped)
        volume = prev["volume"]
        status = self._media_status()
        name = "—"
        if status.active_player:
            name = MprisPlayerVolume._friendly_name(status.active_player, status.identity)
        if prev.get("system"):
            self._media_label.set(f"Media: {name} · wyciszone, głośność systemu")
            self._chips.set("kapsel")
            self._draw_media(None)
            self._hint.set("Odwrócony kapsel: pokrętło zmienia głośność systemu. Odwróć z powrotem, żeby wróciła muzyka.")
            return
        vol_text = "—" if volume is None else f"{float(volume) * 100:.0f}%"
        err = ""
        if status.detail and (
            status.active_player is None
            or status.volume_writable is False
            or not status.playerctl_available
        ):
            err = f" · {status.detail}"
        self._media_label.set(f"Media: {name} · {vol_text}{err}")
        pulses = list(prev["pulses"])  # type: ignore[arg-type]
        recent = [p for _t, p in snap.recent_pulses]
        chips = []
        if "play_pause" in pulses or "play_pause" in recent:
            chips.append("klik")
        if "mute" in pulses or "mute" in recent:
            chips.append("mute")
        self._chips.set(" · ".join(chips) if chips else "Impulsy: —")
        self._draw_media(volume if isinstance(volume, float) else None)
        self._hint.set("Głośność z mapowania; nazwa odtwarzacza z MPRIS (bez uinput)")

    def _draw_steering(
        self, wheel: float | None, throttle: float | None, brake: float | None
    ) -> None:
        c = self._diagram
        c.delete("all")
        c.create_oval(70, 8, 150, 62, outline=_BORDER, width=2)
        angle = 0.0 if wheel is None else max(-1.0, min(1.0, float(wheel))) * 50
        # Simple hub + spoke.
        import math

        rad = math.radians(angle - 90)
        cx, cy = 110, 35
        c.create_line(cx, cy, cx + math.cos(rad) * 28, cy + math.sin(rad) * 28, fill=_ACCENT, width=3)
        t = 0.0 if throttle is None else float(throttle)
        b = 0.0 if brake is None else float(brake)
        c.create_rectangle(10, 50 - t * 40, 28, 55, fill=_ACCENT, outline="")
        c.create_rectangle(192, 50 - b * 40, 210, 55, fill="#C44536", outline="")
        c.create_text(19, 62, text="G", fill=_MUTED, font=("", 8))
        c.create_text(201, 62, text="H", fill=_MUTED, font=("", 8))

    def _draw_mouse(self, dx: float | None, dy: float | None) -> None:
        c = self._diagram
        c.delete("all")
        c.create_oval(85, 20, 135, 55, outline=_BORDER, width=2)
        if dx is None or dy is None:
            return
        scale = 0.08
        ex = 110 + max(-40, min(40, dx * scale))
        ey = 37 + max(-20, min(20, dy * scale))
        c.create_line(110, 37, ex, ey, fill=_ACCENT, width=3, arrow=tk.LAST)

    def _draw_media(self, volume: float | None) -> None:
        c = self._diagram
        c.delete("all")
        frac = 0.0 if volume is None else max(0.0, min(1.0, volume))
        c.create_rectangle(30, 28, 190, 48, outline=_BORDER)
        c.create_rectangle(30, 28, 30 + frac * 160, 48, fill=_ACCENT, outline="")
        c.create_text(110, 18, text="player_volume", fill=_MUTED, font=("", 9))


class ConfigForm(ctk.CTkFrame):
    """Manual axis map and thresholds. Save writes gui-settings.json."""

    def __init__(
        self,
        parent: Any,
        settings: GuiSettings,
        *,
        on_draft: Callable[[GuiSettings], str | None] | None = None,
        on_player_select: Callable[[str | None], str | None] | None = None,
        list_players: Callable[[], list[tuple[str, str]]] | None = None,
        favorite_descriptor: Callable[[str], dict[str, str]] | None = None,
        favorite_descriptors: Callable[[list[str]], dict[str, dict[str, str]]] | None = None,
        active_favorite: Callable[[], dict[str, str] | None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self._on_draft = on_draft
        self._settings = settings
        self.control_options: dict[str, ControlOptions] = {}
        self._draft = resolved_draft(settings)
        self._suppress = False
        self.invert_pitch = tk.BooleanVar(value=bool(self._draft["invert_pitch"]))
        self.invert_roll = tk.BooleanVar(value=bool(self._draft["invert_roll"]))
        flags = ctk.CTkFrame(self, fg_color="transparent")
        flags.pack(fill="x", pady=4)
        ctk.CTkCheckBox(
            flags,
            text="Odwróć pitch",
            variable=self.invert_pitch,
            command=self._emit_draft,
            text_color=_TEXT,
            fg_color=_ACCENT,
        ).pack(side="left")
        ctk.CTkCheckBox(
            flags,
            text="Odwróć roll",
            variable=self.invert_roll,
            command=self._emit_draft,
            text_color=_TEXT,
            fg_color=_ACCENT,
        ).pack(side="left", padx=12)
        # Each tab owns that profile's axis_map + thresholds; switching tabs
        # re-applies the draft so the live preview uses the selected device.
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=_SURFACE,
            segmented_button_selected_color=_ACCENT,
            command=self._emit_draft,
        )
        self.tabs.pack(fill="both", expand=True)
        self._maps: dict[tuple[str, str], ctk.CTkOptionMenu] = {}
        self._scales: dict[tuple[str, str], tuple[ctk.CTkSlider, tk.StringVar, float, SliderField]] = {}
        self._signs: dict[tuple[str, str], ctk.CTkOptionMenu] = {}
        self._tab_names: dict[str, str] = {}
        thresholds = self._draft["thresholds"]
        axis_map = self._draft["axis_map"]
        assert isinstance(thresholds, dict)
        assert isinstance(axis_map, dict)
        for name in PROFILE_NAMES:
            page = self.tabs.add(PROFILE_LABELS[name])
            self._tab_names[PROFILE_LABELS[name]] = name
            profile_map = axis_map[name]
            profile_thresholds = thresholds[name]
            assert isinstance(profile_map, dict)
            assert isinstance(profile_thresholds, dict)
            for field in MAP_FIELDS[name]:
                self._add_map(page, name, field, profile_map)
            for field in SLIDER_FIELDS[name]:
                self._add_slider(page, name, field, profile_thresholds)
            options = ControlOptions(page, replace(settings, profile=name),
                                     on_change=lambda _settings: self._emit_draft(),
                                     on_player_select=on_player_select,
                                     list_players=list_players,
                                     favorite_descriptor=favorite_descriptor,
                                     favorite_descriptors=favorite_descriptors,
                                     active_favorite=active_favorite)
            options.pack(fill="x", pady=(8, 0))
            self.control_options[name] = options
        initial = PROFILE_LABELS.get(str(self._draft["profile"]), PROFILE_LABELS["steering"])
        try:
            self.tabs.set(initial)
        except ValueError:
            pass
        self.message = tk.StringVar(
            value="Zmiany działają od razu w sesji. Zapisz zapisuje gui-settings.json."
        )
        ctk.CTkLabel(
            self, textvariable=self.message, text_color=_MUTED, wraplength=640, justify="left", anchor="w"
        ).pack(anchor="w", pady=4)

    def _add_map(self, page: Any, profile: str, field: MapField, values: dict) -> None:
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=field.label, width=180, anchor="w", text_color=_TEXT).pack(side="left")
        current = values[field.key]
        if field.choices is None:
            labels = [label for label, _sign in SIGN_CHOICES]
            initial = "Odwrócony" if float(current) < 0 else "Standardowy"
        else:
            labels_for = source_labels(profile)
            labels = [labels_for[choice] for choice in field.choices]
            initial = labels_for.get(str(current), str(current))
        menu = ctk.CTkOptionMenu(
            row,
            values=labels,
            command=lambda _value: self._emit_draft(),
            fg_color=_SURFACE,
            button_color=_ACCENT,
            button_hover_color="#2558C7",
            text_color=_TEXT,
            dropdown_fg_color=_SURFACE,
            dropdown_text_color=_TEXT,
            width=260,
        )
        menu.set(initial)
        menu.pack(side="left", fill="x", expand=True)
        self._maps[(profile, field.key)] = menu

    def _add_slider(self, page: Any, profile: str, field: SliderField, values: dict) -> None:
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=field.label, width=180, anchor="w", text_color=_TEXT).pack(side="left")
        current = float(values[field.key])
        if field.low is None or field.high is None or field.step is None:
            labels = [label for label, _sign in SIGN_CHOICES]
            menu = ctk.CTkOptionMenu(
                row,
                values=labels,
                command=lambda _value: self._emit_draft(),
                fg_color=_SURFACE,
                button_color=_ACCENT,
                text_color=_TEXT,
                width=180,
            )
            menu.set("Odwrócony" if current < 0 else "Standardowy")
            menu.pack(side="left")
            self._signs[(profile, field.key)] = menu
            return
        shown = tk.StringVar(value=self._slider_text(current, field))
        slider = ctk.CTkSlider(
            row,
            from_=field.low,
            to=field.high,
            number_of_steps=max(1, int(round((field.high - field.low) / field.step))),
            command=lambda _raw, p=profile, f=field, var=shown: self._on_scale(p, f, var),
            progress_color=_ACCENT,
            button_color=_ACCENT,
            width=220,
        )
        slider.set(current)
        slider.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkLabel(row, textvariable=shown, width=80, anchor="w", text_color=_MUTED).pack(side="left")
        self._scales[(profile, field.key)] = (slider, shown, field.step, field)

    def _on_scale(self, profile: str, field: SliderField, shown: tk.StringVar) -> None:
        slider, _var, step, _field = self._scales[(profile, field.key)]
        value = snap_step(float(slider.get()), step)
        shown.set(self._slider_text(value, field))
        self._emit_draft()

    @staticmethod
    def _slider_text(value: float, field: SliderField) -> str:
        digits = 0 if field.step is not None and field.step >= 1 else 2
        return f"{value:.{digits}f} {field.unit}".strip()

    def selected_profile(self) -> str:
        label = self.tabs.get()
        return self._tab_names.get(label, PROFILE_NAMES[0])

    def reset_selected(self) -> None:
        name = self.selected_profile()
        thresholds, axis_map = default_profile_slice(name)
        self._suppress = True
        try:
            for field in MAP_FIELDS[name]:
                box = self._maps[(name, field.key)]
                current = axis_map[field.key]
                if field.choices is None:
                    box.set("Odwrócony" if float(current) < 0 else "Standardowy")
                else:
                    box.set(source_labels(name)[str(current)])
            for field in SLIDER_FIELDS[name]:
                current = float(thresholds[field.key])
                if (name, field.key) in self._signs:
                    self._signs[(name, field.key)].set(
                        "Odwrócony" if current < 0 else "Standardowy"
                    )
                    continue
                slider, shown, _step, _field = self._scales[(name, field.key)]
                slider.set(current)
                shown.set(self._slider_text(current, field))
        finally:
            self._suppress = False
        self.message.set(
            f"Przywrócono domyślne wartości profilu {PROFILE_LABELS[name]}. Zapisz, aby utrwalić."
        )
        self._emit_draft()

    def collect(self, *, profile: str, orientation: str) -> GuiSettings:
        base = resolved_draft(GuiSettings(profile=profile, orientation=orientation))
        thresholds = base["thresholds"]
        axis_map = base["axis_map"]
        assert isinstance(thresholds, dict)
        assert isinstance(axis_map, dict)
        for name in PROFILE_NAMES:
            profile_map = dict(axis_map[name])
            profile_thresholds = dict(thresholds[name])
            for field in MAP_FIELDS[name]:
                label = self._maps[(name, field.key)].get()
                if field.choices is None:
                    profile_map[field.key] = self._sign_value(label)
                else:
                    profile_map[field.key] = self._source_value(label, field.choices, name)
            for field in SLIDER_FIELDS[name]:
                if field.low is None:
                    profile_thresholds[field.key] = self._sign_value(
                        self._signs[(name, field.key)].get()
                    )
                else:
                    slider, _shown, step, _field = self._scales[(name, field.key)]
                    profile_thresholds[field.key] = snap_step(float(slider.get()), step)
            axis_map[name] = profile_map
            thresholds[name] = profile_thresholds
        draft = {
            "profile": profile,
            "orientation": orientation,
            "invert_pitch": bool(self.invert_pitch.get()),
            "invert_roll": bool(self.invert_roll.get()),
            "thresholds": thresholds,
            "axis_map": axis_map,
        }
        collected = replace(settings_from_draft(draft, profile=profile),
                            media_gestures_enabled=self._settings.media_gestures_enabled,
                            media_player=self._settings.media_player,
                            media_favorite=self._settings.media_favorite,
                            control_bindings=self._settings.control_bindings)
        for options in self.control_options.values():
            collected = options.collect(collected)
        return collected

    def _emit_draft(self) -> str | None:
        if self._suppress or self._on_draft is None:
            return None
        return self._on_draft(GuiSettings())

    @staticmethod
    def _sign_value(label: str) -> float:
        for text, value in SIGN_CHOICES:
            if text == label:
                return value
        return 1.0

    @staticmethod
    def _source_value(label: str, choices: tuple[str, ...], profile: str) -> str:
        labels_for = source_labels(profile)
        for choice in choices:
            if labels_for[choice] == label:
                return choice
        return choices[0]


class TrikiDesktop:
    def __init__(
        self,
        session: ControllerSession,
        settings_path,
        *,
        view: str,
        transport: str,
        connect: bool,
        live: bool,
        dry_run: bool,
        auto_close: float | None,
        quick_command: str | None,
    ) -> None:
        _apply_theme()
        self.session = session
        self.settings_path = settings_path
        self.view = view
        self.transport = transport
        self.live = live
        self.dry_run = dry_run
        self._closed = False
        self._tray = None
        self._dirty = False
        self._saved_settings = session.current_settings()
        self._config_form: ConfigForm | None = None
        self._control_options: ControlOptions | None = None
        self._sensors: SensorBoard | None = None
        self._preview: OutputPreview | None = None
        self._dashboard: PreviewDashboard | None = None
        self._content: ctk.CTkFrame | None = None
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._config_page = "podglad"
        self._screen = "menu"
        self._quick_command = quick_command
        # Config never arms live uinput; device launch / quick do.
        autostart = view == "quick" or (view == "panel" and (live or dry_run))
        output_live = (not dry_run) if view == "quick" else bool(live and not dry_run)
        self._autostart = OutputAutostart(session, live=output_live, enabled=autostart)
        self.root = ctk.CTk()
        self.root.configure(fg_color=_BG)
        apply_window_icon(self.root)
        title = "Triki Controller"
        if view == "config":
            title = "Konfigurator urządzenia"
        elif quick_command == "mouse":
            title = "Triki AirMouse"
        elif quick_command == "wheel":
            title = "Triki Kierownica"
        elif quick_command == "music":
            title = "Triki Multimedia"
        self.root.title(title)
        self.root.minsize(420, 280)
        self._status = tk.StringVar(value="Gotowy")
        self._detail = tk.StringVar(value="")
        self._rate = tk.StringVar(value="— Hz")
        self._conn = tk.StringVar(value="Rozłączono")
        self._output = tk.StringVar(value="Wyłączone")
        self._chips = tk.StringVar(value="")
        self._meter = tk.StringVar(value="Połącz źródło, aby zobaczyć reakcję profilu.")
        self._dirty_label = tk.StringVar(value="")
        self._transport = tk.StringVar(value="ble")
        self._profile = tk.StringVar(value=session.snapshot().profile_name)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(POLL_MS, self._tick)
        if connect or view == "quick":
            self.root.after(80, self._startup_connect)
        if auto_close:
            self.root.after(int(float(auto_close) * 1000), self.close)
        if view == "quick":
            from triki_controller.gui.tray import QuickLaunchTray

            self._tray = tray = QuickLaunchTray(self.root, on_quit=self.close)
            self.root.protocol("WM_DELETE_WINDOW", lambda: tray.hide() or self.close())
            tray.start()

    def _clear_content(self) -> None:
        if self._content is not None:
            self._content.destroy()
        self._content = ctk.CTkFrame(self.root, fg_color=_BG)
        self._content.pack(fill="both", expand=True)
        self._config_form = None
        self._sensors = None
        self._preview = None
        self._dashboard = None
        self._nav_buttons = {}
        self._control_options = None

    def _build(self) -> None:
        if self.view == "quick":
            self._show_device_screen(from_menu=False)
        elif self.view == "config":
            self._show_configurator()
        else:
            self._show_main_menu()

    def _show_main_menu(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        self.session.stop_output()
        self._autostart.enabled = False
        self._screen = "menu"
        self._dirty = False
        self._dirty_label.set("")
        self.root.title("Triki Controller")
        self.root.geometry("640x680")
        self.root.minsize(520, 600)
        self._clear_content()
        assert self._content is not None
        from triki_controller.gui.shell_presentation import build_main_menu

        build_main_menu(self, _DEVICE_LAUNCH)

    def _launch_device(self, profile: str) -> None:
        command, _label, _hint = _DEVICE_LAUNCH[profile]
        err = apply_quick_profile(self.session, command)
        if err:
            self._flash(err)
            return
        self._transport.set("ble")
        self._quick_command = command
        self._autostart.live = not self.dry_run
        self._autostart.enabled = True
        # A profile change may already have rebuilt running output in session.
        # Only a stopped output needs the normal one-shot streaming autostart.
        from triki_controller.gui.session import OutputMode
        self._autostart._armed = self.session.snapshot().output_mode != OutputMode.OFF
        self._show_device_screen(from_menu=True)
        if self.session.snapshot().connection in {ConnectionState.DISCONNECTED, ConnectionState.ERROR}:
            self.root.after(80, self._connect_device_if_needed)

    def _connect_device_if_needed(self) -> None:
        # A scheduled launch belongs to the current device intent, not a stale
        # screen which the user may already have left.
        if self._screen == "device" and self._autostart.enabled:
            self._startup_connect()

    def _show_device_screen(self, *, from_menu: bool) -> None:
        retain_geometry = self._screen == "device"
        self._screen = "device"
        title = self.root.title()
        if self._quick_command == "mouse":
            title = "Triki AirMouse"
        elif self._quick_command == "wheel":
            title = "Triki Kierownica"
        elif self._quick_command == "music":
            title = "Triki Multimedia"
        elif self._quick_command == "plane":
            title = "Triki Joystick"
        self.root.title(title)
        if not retain_geometry:
            self.root.geometry("660x820")
        self.root.minsize(520, 600)
        self._clear_content()
        assert self._content is not None
        from triki_controller.gui.shell_presentation import build_device_screen

        build_device_screen(self, title, from_menu=from_menu)
        self._control_options = ControlOptions(
            self._options_parent, self.session.current_settings(), compact=True,
            on_change=self._apply_control_options,
            on_player_select=self._select_media_player,
            list_players=self.session.list_media_players,
            favorite_descriptor=self.session.favorite_media_descriptor,
            favorite_descriptors=self.session.favorite_media_descriptors,
            active_favorite=self.session.active_media_favorite)
        self._control_options.pack(fill="x")

    def _select_media_player(self, player: str | None) -> str | None:
        previous = self.session.current_settings().media_player
        error = self.session.select_media_player(player)
        if error is None and player != previous:
            self._dirty = True
            self._dirty_label.set("Niezapisane zmiany")
        return error

    def _apply_control_options(self, settings: GuiSettings) -> str | None:
        # Apply only added controls onto the latest session draft.
        current = self.session.current_settings()
        candidate = replace(current, control_bindings=settings.control_bindings,
                            media_player=settings.media_player,
                            media_favorite=settings.media_favorite,
                            media_gestures_enabled=settings.media_gestures_enabled)
        error = self.session.apply_settings(candidate)
        if error is None:
            self._dirty = True
            self._dirty_label.set("Niezapisane zmiany")
        return error

    def _back_to_menu_from_device(self) -> None:
        # The menu owns dirty confirmation before releasing any held output.
        # Navigation is not a BLE disconnect; only the explicit action is.
        self._show_main_menu()

    def _show_configurator(self) -> None:
        self._screen = "configurator"
        self.root.title("Konfigurator urządzenia")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self._autostart.enabled = False
        self.session.stop_output()
        self._clear_content()
        assert self._content is not None
        shell = ctk.CTkFrame(self._content, fg_color=_BG)
        shell.pack(fill="both", expand=True)
        sidebar = ctk.CTkFrame(shell, fg_color=_SURFACE, width=180, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar, text="Konfigurator\nurządzenia", font=("", 14, "bold"), text_color=_TEXT, justify="left"
        ).pack(anchor="w", padx=16, pady=(20, 16))
        for key, label in _CONFIG_NAV:
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                fg_color="transparent",
                text_color=_TEXT,
                hover_color=_BG,
                command=lambda k=key: self._select_config_nav(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[key] = btn
        if self.view == "panel":
            ctk.CTkButton(
                sidebar,
                text="← Menu główne",
                anchor="w",
                fg_color="transparent",
                text_color=_ACCENT,
                hover_color=_BG,
                command=self._show_main_menu,
            ).pack(side="bottom", fill="x", padx=8, pady=16)
        self._config_main = ctk.CTkFrame(shell, fg_color=_BG)
        self._config_main.pack(side="left", fill="both", expand=True)
        self._select_config_nav("podglad")

    def _select_config_nav(self, key: str) -> None:
        self._config_page = key
        for name, btn in self._nav_buttons.items():
            if name == key:
                btn.configure(fg_color="#EAF1FE", text_color=_ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color=_TEXT)
        for child in self._config_main.winfo_children():
            child.destroy()
        self._config_form = None
        self._sensors = None
        self._preview = None
        self._dashboard = None
        page = ctk.CTkScrollableFrame(self._config_main, fg_color=_BG)
        page.pack(fill="both", expand=True, padx=20, pady=16)
        if key == "podglad":
            self._build_connect(page)
            self._build_output(page)
            self._dashboard = PreviewDashboard(page)
            self._dashboard.pack(fill="both", expand=True, pady=8)
        elif key == "konfiguracja":
            self._build_connect(page)
            self._build_output(page)
            self._fill_config_body(page)
        elif key == "profile":
            self._build_profiles(page)
            ctk.CTkLabel(
                page,
                text="Aktywny profil wpływa na wyjście Live z menu głównego. "
                "W konfiguracji zakładki mapowania przełączają podgląd niezależnie.",
                text_color=_MUTED,
                wraplength=640,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=8)
        elif key == "ustawienia":
            self._build_connect(page)
            ctk.CTkLabel(
                page,
                text=f"Plik ustawień:\n{self.settings_path}",
                text_color=_TEXT,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=8)
            ctk.CTkLabel(page, textvariable=self._dirty_label, text_color=_ACCENT, anchor="w").pack(
                anchor="w"
            )
            ctk.CTkButton(
                page, text="Utwórz skróty pulpitu", command=self._install_shortcuts, fg_color=_ACCENT
            ).pack(anchor="w", pady=8)
        else:
            from triki_controller import __version__

            ctk.CTkLabel(
                page, text="Informacje", font=("", 18, "bold"), text_color=_TEXT, anchor="w"
            ).pack(anchor="w")
            ctk.CTkLabel(
                page,
                text=(
                    f"Triki Controller {__version__}\n"
                    "Linux CAP001 → RAW → FILTERED → PROFILE → FINAL OUTPUT.\n"
                    "Po połączeniu BLE „Na żywo” wysyła sterowanie do systemu."
                ),
                text_color=_MUTED,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=8)
        ctk.CTkLabel(page, textvariable=self._status, text_color=_MUTED, anchor="w").pack(
            anchor="w", pady=(12, 0)
        )

    def _section(self, parent: Any, title: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(
            parent, fg_color=_SURFACE, corner_radius=8, border_width=1, border_color=_BORDER
        )
        box.pack(fill="x", pady=4)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(inner, text=title, text_color=_MUTED, anchor="w").pack(anchor="w")
        return inner

    def _build_connect(self, outer: Any) -> None:
        box = self._section(outer, "Połączenie")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkButton(row, text="Połącz", command=self._on_retry, fg_color=_ACCENT, width=110).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            row,
            text="Rozłącz",
            command=self._on_disconnect,
            fg_color=_SURFACE,
            text_color=_TEXT,
            border_width=1,
            border_color=_BORDER,
            width=90,
        ).pack(side="left")
        ctk.CTkLabel(
            box,
            text="BLE: naciśnij raz przycisk na nakładce podczas skanowania. Nie używaj jednocześnie TrikiScope.",
            text_color=_MUTED,
            wraplength=640,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

    def _build_profiles(self, outer: Any) -> None:
        box = self._section(outer, "Profil")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x")
        for name in PROFILE_NAMES:
            ctk.CTkRadioButton(
                row,
                text=PROFILE_LABELS[name],
                value=name,
                variable=self._profile,
                command=lambda n=name: self._on_profile(n),
                text_color=_TEXT,
                fg_color=_ACCENT,
            ).pack(side="left", padx=4)

    def _build_output(self, outer: Any) -> None:
        box = self._section(outer, "Wyjście emulatora")
        ctk.CTkLabel(
            box,
            text=(
                "Najpierw połącz BLE. „Na żywo” puszcza ten profil do systemu "
                "(AirMouse rusza kursorem). „Próbne” tylko podgląda mapowanie."
            ),
            text_color=_MUTED,
            wraplength=640,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkButton(
            row, text="Próbne", command=self._on_dry, fg_color=_SURFACE, text_color=_TEXT, border_width=1, border_color=_BORDER
        ).pack(side="left")
        ctk.CTkButton(row, text="Na żywo", command=self._on_live, fg_color=_ACCENT).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="Stop", command=self._on_stop, fg_color=_SURFACE, text_color=_TEXT, border_width=1, border_color=_BORDER
        ).pack(side="left")

    def _fill_config_body(self, parent: Any) -> None:
        # Calibration / mapping first; motion + mapped output preview below.
        self._build_config_editor(parent)
        self._preview = OutputPreview(parent)
        self._preview.pack(fill="x", pady=6)
        self._sensors = SensorBoard(parent)
        self._sensors.pack(fill="x", pady=6)

    def _build_config_editor(self, parent: Any) -> None:
        editor = ctk.CTkFrame(
            parent, fg_color=_SURFACE, corner_radius=8, border_width=1, border_color=_BORDER
        )
        editor.pack(fill="both", expand=True, pady=6)
        pad = ctk.CTkFrame(editor, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=10, pady=8)
        ctk.CTkLabel(pad, text="Mapowanie i progi", text_color=_MUTED, anchor="w").pack(anchor="w")
        self._config_form = ConfigForm(
            pad, self.session.current_settings(), on_draft=self._apply_draft_from_form,
            on_player_select=self._select_media_player,
            list_players=self.session.list_media_players,
            favorite_descriptor=self.session.favorite_media_descriptor,
            favorite_descriptors=self.session.favorite_media_descriptors,
            active_favorite=self.session.active_media_favorite,
        )
        self._config_form.pack(fill="both", expand=True)
        # Rebind on_draft properly — ConfigForm calls with GuiSettings(); use wrapper.
        self._config_form._on_draft = lambda _ignored: self._apply_live_draft()
        row = ctk.CTkFrame(pad, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkButton(row, text="Zapisz", command=self._save_config, fg_color=_ACCENT).pack(side="left")
        ctk.CTkButton(
            row,
            text="Domyślne tego profilu",
            command=self._config_form.reset_selected,
            fg_color=_SURFACE,
            text_color=_TEXT,
            border_width=1,
            border_color=_BORDER,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row,
            text="Wyzeruj pozycję",
            command=self._on_recenter,
            fg_color=_SURFACE,
            text_color=_TEXT,
            border_width=1,
            border_color=_BORDER,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row,
            text="Kalibruj żyroskop",
            command=self._on_calibrate,
            fg_color=_SURFACE,
            text_color=_TEXT,
            border_width=1,
            border_color=_BORDER,
        ).pack(side="left")
        hint = (
            "Akcelerometr jest na podglądzie. Profile czytają pochylenie i żyroskop. "
            "Zmiany mapowania działają od razu; Zapisz utrwala plik. "
            "„Na żywo” uzbraja wyjście do systemu."
        )
        ctk.CTkLabel(pad, text=hint, text_color=_MUTED, wraplength=640, justify="left", anchor="w").pack(
            anchor="w"
        )

    def _apply_draft_from_form(self, _settings: GuiSettings) -> str | None:
        return self._apply_live_draft()

    def _apply_live_draft(self) -> str | None:
        form = self._config_form
        if form is None:
            return None
        current = self.session.current_settings()
        try:
            # Selected device tab drives the active mapping used for preview.
            # collect() still packs every profile's thresholds/axis_map overlays.
            settings = form.collect(
                profile=form.selected_profile(),
                orientation=current.orientation,
            )
        except SettingsError as exc:
            form.message.set(str(exc))
            return str(exc)
        err = self.session.apply_settings(settings)
        if err:
            form.message.set(err)
            return err
        self._profile.set(settings.profile)
        self._dirty = True
        self._dirty_label.set("Niezapisane zmiany")
        form.message.set(
            f"Zastosowano {PROFILE_LABELS.get(settings.profile, settings.profile)} "
            "(bez zapisu pliku)."
        )
        snap = self.session.snapshot()
        if self._preview is not None:
            self._preview.update_snapshot(snap)
        if self._sensors is not None:
            self._sensors.update_snapshot(snap)
        return None

    def _startup_connect(self) -> None:
        if self._closed:
            return
        if self.session.snapshot().connection not in {ConnectionState.DISCONNECTED, ConnectionState.ERROR}:
            return
        self._on_connect()

    def _on_connect(self) -> None:
        source = self._transport.get()
        err = self.session.connect(source)
        if source == "ble" and err is None:
            self._flash("Skanowanie… naciśnij raz przycisk na nakładce Triki.")
        else:
            self._flash(err or "Łączenie…")

    def _on_retry(self) -> None:
        snap = self.session.snapshot()
        if snap.connection.value not in ("disconnected", "error"):
            self.session.disconnect()
        self._flash("Ponawiam połączenie… naciśnij raz przycisk na nakładce.")
        self.root.after(700, self._on_connect)

    def _on_disconnect(self) -> None:
        self._autostart.enabled = False
        self.session.disconnect()
        self._flash("Rozłączono.")

    def _on_profile(self, name: str) -> None:
        err = self.session.set_profile(name)
        if err:
            self._flash(err)
            self._profile.set(self.session.snapshot().profile_name)
            return
        self._dirty = True
        self._dirty_label.set("Niezapisane zmiany")
        self._flash(f"Profil: {PROFILE_LABELS.get(name, name)}")

    def _on_dry(self) -> None:
        self._flash(self.session.start_output(live=False) or "Wyjście próbne.")

    def _on_live(self) -> None:
        self._flash(self.session.start_output(live=True) or "Wyjście na żywo.")

    def _on_stop(self) -> None:
        from triki_controller.gui.session import OutputMode
        mode = self.session.snapshot().output_mode
        # Retain the running intent for Resume; pending intent already lives here.
        if mode != OutputMode.OFF:
            self._autostart.live = mode == OutputMode.LIVE
        self._autostart.enabled = False
        self.session.stop_output()
        self._flash("Sterowanie zatrzymane.")

    def _on_recenter(self) -> None:
        self._flash(self.session.recenter() or "Pozycja wyzerowana.")

    def _on_calibrate(self) -> None:
        self._flash(self.session.begin_calibration() or "Kalibracja — nie ruszaj nakładką.")

    def _persist_quiet(self) -> None:
        try:
            save_settings(self.session.current_settings(), self.settings_path)
            self._saved_settings = self.session.current_settings()
            self._dirty = False
            self._dirty_label.set("")
        except (OSError, SettingsError) as exc:
            self._flash(f"Profil działa, zapis pliku się nie udał: {exc}")

    def _save_config(self) -> None:
        form = self._config_form
        if form is None:
            self._persist_quiet()
            if self._control_options is not None and not self._dirty:
                self._control_options.message.set(f"Zapisano {self.settings_path}")
            return
        current = self.session.current_settings()
        try:
            settings = form.collect(profile=form.selected_profile(), orientation=current.orientation)
        except SettingsError as exc:
            form.message.set(str(exc))
            return
        err = self.session.apply_settings(settings)
        if err:
            form.message.set(err)
            return
        try:
            path = save_settings(self.session.current_settings(), self.settings_path)
        except (OSError, SettingsError) as exc:
            form.message.set(f"Zmiany działają, zapis pliku się nie udał: {exc}")
            return
        self._saved_settings = self.session.current_settings()
        self._dirty = False
        self._dirty_label.set("")
        self._profile.set(self.session.snapshot().profile_name)
        form.message.set(f"Zapisano {path}")
        self._flash(f"Zapisano {path}")

    def _confirm_discard(self) -> bool:
        return bool(
            messagebox.askyesno(
                "Niezapisane zmiany",
                "Masz niezapisane zmiany mapowania. Zamknąć bez zapisu?",
                parent=self.root,
            )
        )

    def _install_shortcuts(self) -> None:
        from pathlib import Path

        from triki_controller.gui.shortcuts import (
            bundled_source_path,
            default_directories,
            install_shortcuts,
            normalize_platform,
        )

        platform = normalize_platform()
        try:
            written = install_shortcuts(
                platform=platform,
                python=sys.executable,
                pythonpath=bundled_source_path(),
                directories=default_directories(Path.home(), platform),
            )
        except OSError as exc:
            messagebox.showerror("Skróty", f"Nie udało się zapisać skrótów: {exc}", parent=self.root)
            return
        messagebox.showinfo(
            "Skróty",
            "Utworzono:\n" + "\n".join(str(path) for path in written),
            parent=self.root,
        )

    def _flash(self, text: str | None) -> None:
        if text:
            self._status.set(text)

    def _refresh(self) -> None:
        self._autostart.tick()
        snap = self.session.snapshot()
        rate = "— Hz" if snap.sample_rate_hz is None else f"{snap.sample_rate_hz:.0f} Hz"
        self._set(self._rate, rate)
        self._set(self._conn, f"Połączenie: {connection_label(snap.connection.value)}")
        output = f"Sterowanie: {output_label(snap.output_mode.value)}"
        self._set(self._output, output)
        chips = " · ".join(
            (
                button_label(None if snap.raw is None else snap.raw.button),
                battery_label(snap.battery_percent),
                rssi_label(snap.rssi_dbm),
                f"Próbki: {snap.samples}",
            )
        )
        self._set(self._chips, chips)
        detail = friendly_connection_detail(
            snap.connection.value,
            snap.error or snap.connection_reason or snap.output_note,
        )
        if snap.connection.value == "error" and "Ponów" not in detail:
            detail = f"{detail} Użyj „Połącz ponownie”."
        self._set(self._detail, detail or "")
        self._set(self._meter, _meter_text(snap))
        if self._screen == "device":
            from triki_controller.gui.shell_presentation import refresh_device_actions
            refresh_device_actions(self)
        if self._profile.get() != snap.profile_name:
            self._profile.set(snap.profile_name)
        if self._sensors is not None:
            self._sensors.update_snapshot(snap)
        if self._preview is not None:
            self._preview.update_snapshot(snap)
        if self._dashboard is not None:
            self._dashboard.update_snapshot(snap, self.session.current_settings())

    def _set(self, var: tk.StringVar, value: str) -> None:
        if var.get() != value:
            var.set(value)

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self._refresh()
        finally:
            if not self._closed:
                self.root.after(POLL_MS, self._tick)

    def attach_shell_extension(self, attach: Callable[[Any], Any]) -> Any:
        """Attach an optional shell integration without altering configurator UI."""
        return attach(self)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        if self._dirty and not self._confirm_discard():
            return
        self._closed = True
        try:
            if self._tray is not None:
                self._tray.stop()
            self.session.shutdown()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass


def _meter_text(snap) -> str:
    profile = snap.profile_name
    mapped = snap.mapped
    if mapped is None:
        return "Połącz źródło, aby zobaczyć reakcję profilu."
    axes = mapped.absolute_axes
    if profile == "steering":
        wheel = axes.get("wheel_deg")
        wheel_text = "niedostępna" if wheel is None else f"{format_measure(wheel, 1)}°"
        throttle = axes.get("throttle")
        brake = axes.get("brake")
        throttle_text = "niedostępne" if throttle is None else f"{float(throttle) * 100:.0f}%"
        brake_text = "niedostępne" if brake is None else f"{float(brake) * 100:.0f}%"
        return f"Kierownica {wheel_text} · gaz {throttle_text} · hamulec {brake_text}"
    if profile == "mouse":
        pointer = snap.pointer_px_per_s
        if pointer is None:
            return "Kursor: brak ruchu"
        return f"Kursor X {pointer[0]:+.0f} px/s · Y {pointer[1]:+.0f} px/s"
    if profile == "plane":
        sx = axes.get("stick_x")
        sy = axes.get("stick_y")
        if sx is None or sy is None:
            return "Joystick: brak wychylenia"
        return f"Joystick X {float(sx):+.2f} · Y {float(sy):+.2f}"
    if "system_volume" in axes:
        return "Muzyka wyciszona · pokrętło steruje głośnością systemu"
    volume = axes.get("player_volume")
    if volume is None:
        return "Głośność: niedostępna"
    return f"Głośność odtwarzacza {float(volume) * 100:.0f}%"


def run_desktop(args: argparse.Namespace) -> int:
    if getattr(args, "live", False) and getattr(args, "dry_run", False):
        print("error: --live i --dry-run wykluczają się", file=sys.stderr)
        return 2
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        print(GUI_MISSING_MESSAGE, file=sys.stderr)
        return 1
    session, path, note = open_session(args)
    if note:
        print(note, file=sys.stderr)
    command = args.command
    view = "panel"
    if command == "config":
        view = "config"
    elif command in QUICK_PROFILES:
        view = "quick"
        err = apply_quick_profile(session, command)
        if err:
            print(err, file=sys.stderr)
            session.shutdown()
            return 2
    try:
        app = TrikiDesktop(
            session,
            path,
            view=view,
            transport=args.transport,
            connect=bool(getattr(args, "connect", False)),
            live=bool(getattr(args, "live", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            auto_close=getattr(args, "auto_close", None),
            quick_command=command if command in QUICK_PROFILES else None,
        )
    except tk.TclError as exc:
        session.shutdown()
        print(f"Nie udało się otworzyć okna: {exc}", file=sys.stderr)
        print("Użyj --no-window (mouse/wheel/music) albo sprawdź DISPLAY.", file=sys.stderr)
        return 1
    app.run()
    return 0
