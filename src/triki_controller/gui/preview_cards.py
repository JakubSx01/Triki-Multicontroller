"""Compact live preview cards for the configurator Podgląd page."""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any

from triki_controller.gui.media_preferences import load_default_player, save_default_player
from triki_controller.gui.present import (
    map_profile_preview,
    media_preview,
    mouse_preview,
    steering_preview,
)
from triki_controller.output.mpris_volume import MprisPlayerVolume

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover
    from triki_controller.gui.launch import GUI_MISSING_MESSAGE

    raise ImportError(GUI_MISSING_MESSAGE) from exc

_BG = "#F5F6F8"
_SURFACE = "#FFFFFF"
_TEXT = "#1A1D23"
_MUTED = "#5C6370"
_ACCENT = "#2F6FED"
_ACCENT_SOFT = "#EAF1FE"
_BORDER = "#D5D9E0"
_GREEN = "#2F9E6B"
_RED = "#C44536"
_CARD_W = 390
_CARD_H = 245


class _Card(ctk.CTkFrame):
    def __init__(self, parent: Any, title: str, *, height: int = _CARD_H) -> None:
        super().__init__(
            parent,
            fg_color=_SURFACE,
            corner_radius=12,
            border_width=1,
            border_color=_BORDER,
            width=_CARD_W,
            height=height,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        pad = ctk.CTkFrame(self, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=14, pady=11)
        ctk.CTkLabel(
            pad,
            text=title,
            font=("", 15, "bold"),
            text_color=_TEXT,
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        self.body = ctk.CTkFrame(pad, fg_color="transparent")
        self.body.pack(fill="both", expand=True)


def _meter_canvas(parent: Any, *, width: int, height: int) -> tk.Canvas:
    return tk.Canvas(
        parent,
        width=width,
        height=height,
        bg=_SURFACE,
        highlightthickness=0,
        bd=0,
    )


class SteeringPreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Kierownica")
        content = ctk.CTkFrame(self.body, fg_color="transparent")
        content.pack(fill="both", expand=True)

        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        self._canvas = _meter_canvas(left, width=235, height=145)
        self._canvas.pack(anchor="w")
        self._angle = tk.StringVar(value="Wychylenie —")
        ctk.CTkLabel(
            left,
            textvariable=self._angle,
            text_color=_TEXT,
            font=("", 13, "bold"),
            anchor="center",
        ).pack(fill="x", pady=(0, 2))

        pedals = ctk.CTkFrame(content, fg_color="transparent")
        pedals.pack(side="right", fill="y", padx=(10, 0), pady=(4, 0))
        self._gas_canvas = _meter_canvas(pedals, width=44, height=105)
        self._brake_canvas = _meter_canvas(pedals, width=44, height=105)
        self._gas_canvas.grid(row=0, column=0, padx=(0, 8))
        self._brake_canvas.grid(row=0, column=1)
        self._gas_pct = tk.StringVar(value="Gaz\n—")
        self._brake_pct = tk.StringVar(value="Hamulec\n—")
        ctk.CTkLabel(
            pedals, textvariable=self._gas_pct, text_color=_MUTED, font=("", 10), justify="center"
        ).grid(row=1, column=0, pady=(2, 0))
        ctk.CTkLabel(
            pedals, textvariable=self._brake_pct, text_color=_MUTED, font=("", 10), justify="center"
        ).grid(row=1, column=1, pady=(2, 0))

    def update_mapped(self, mapped: object) -> None:
        values = steering_preview(mapped if hasattr(mapped, "absolute_axes") else None)
        wheel = values["wheel"]
        throttle = values["throttle"]
        brake = values["brake"]
        deg = None if wheel is None else float(wheel) * 90.0
        self._angle.set("Wychylenie —" if deg is None else f"Wychylenie {deg:+.0f}°")
        self._draw_gauge(deg)
        self._draw_pedal(self._gas_canvas, throttle, _GREEN)
        self._draw_pedal(self._brake_canvas, brake, _RED)
        self._gas_pct.set("Gaz\n—" if throttle is None else f"Gaz\n{float(throttle) * 100:.0f}%")
        self._brake_pct.set(
            "Hamulec\n—" if brake is None else f"Hamulec\n{float(brake) * 100:.0f}%"
        )

    def _draw_gauge(self, deg: float | None) -> None:
        c = self._canvas
        c.delete("all")
        cx, cy, radius = 116, 123, 88
        c.create_arc(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            start=0,
            extent=180,
            style=tk.ARC,
            outline=_BORDER,
            width=4,
        )
        for mark, label in ((-90, "−90°"), (-45, "−45°"), (0, "0°"), (45, "+45°"), (90, "+90°")):
            rad = math.radians(mark)
            x = cx + math.sin(rad) * (radius + 5)
            y = cy - math.cos(rad) * (radius + 5)
            c.create_text(x, y - 5, text=label, fill=_MUTED, font=("", 8))
        c.create_line(cx, cy - radius + 3, cx, cy - radius + 14, fill=_TEXT, width=2)
        angle = 0.0 if deg is None else max(-90.0, min(90.0, deg))
        rad = math.radians(angle)
        end_x = cx + math.sin(rad) * (radius - 16)
        end_y = cy - math.cos(rad) * (radius - 16)
        c.create_line(cx, cy, end_x, end_y, fill=_ACCENT, width=4, arrow=tk.LAST)
        c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=_ACCENT, outline="")

    @staticmethod
    def _draw_pedal(canvas: tk.Canvas, value: float | None, color: str) -> None:
        canvas.delete("all")
        left, top, right, bottom = 10, 4, 34, 96
        canvas.create_rectangle(left, top, right, bottom, outline=_BORDER, width=1)
        frac = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        fill_top = bottom - frac * (bottom - top)
        canvas.create_rectangle(left, fill_top, right, bottom, fill=color, outline="")


class MousePreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Air Mouse")
        content = ctk.CTkFrame(self.body, fg_color="transparent")
        content.pack(fill="both", expand=True)
        self._canvas = _meter_canvas(content, width=190, height=165)
        self._canvas.pack(side="left", padx=(4, 10))

        info = ctk.CTkFrame(content, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=(16, 0))
        self._x = tk.StringVar(value="X  —")
        self._y = tk.StringVar(value="Y  —")
        self._motion = tk.StringVar(value="Ruch kursora: —")
        for var in (self._x, self._y):
            ctk.CTkLabel(
                info,
                textvariable=var,
                text_color=_TEXT,
                font=("", 13, "bold"),
                anchor="w",
            ).pack(fill="x", pady=2)
        ctk.CTkLabel(
            info,
            textvariable=self._motion,
            text_color=_MUTED,
            wraplength=155,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            info,
            text="1× klik: LPM   2× klik: PPM",
            text_color=_MUTED,
            font=("", 10),
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

    def update_motion(self, motion: object, mapped: object, pointer: tuple[float, float] | None) -> None:
        pitch = getattr(motion, "tilt_pitch_deg", None) if motion is not None else None
        roll = getattr(motion, "tilt_roll_deg", None) if motion is not None else None
        self._x.set("X  —" if pitch is None else f"X  {float(pitch):+.0f}°")
        self._y.set("Y  —" if roll is None else f"Y  {float(roll):+.0f}°")
        prev = mouse_preview(mapped if hasattr(mapped, "absolute_axes") else None, pointer)
        dx = prev["dx"] if isinstance(prev["dx"], float) else None
        dy = prev["dy"] if isinstance(prev["dy"], float) else None
        if dx is None or dy is None:
            self._motion.set("Ruch kursora: —")
        else:
            self._motion.set(f"Ruch kursora\nΔx {dx:+.0f} · Δy {dy:+.0f} px/s")
        self._draw_radar(
            None if pitch is None else float(pitch),
            None if roll is None else float(roll),
            dx,
            dy,
        )

    def _draw_radar(
        self,
        pitch: float | None,
        roll: float | None,
        dx: float | None,
        dy: float | None,
    ) -> None:
        c = self._canvas
        c.delete("all")
        cx, cy = 95, 82
        for radius in (26, 48, 68):
            c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=_BORDER)
        c.create_line(cx - 76, cy, cx + 76, cy, fill=_BORDER)
        c.create_line(cx, cy - 76, cx, cy + 76, fill=_BORDER)
        c.create_text(cx - 78, cy, text="L", fill=_MUTED, font=("", 8), anchor="e")
        c.create_text(cx + 78, cy, text="P", fill=_MUTED, font=("", 8), anchor="w")
        c.create_text(cx, cy - 79, text="G", fill=_MUTED, font=("", 8))
        c.create_text(cx, cy + 79, text="D", fill=_MUTED, font=("", 8))
        if roll is not None or pitch is not None:
            x = cx + max(-62, min(62, (0.0 if pitch is None else pitch) * 1.0))
            y = cy + max(-62, min(62, (0.0 if roll is None else roll) * 1.0))
        elif dx is not None and dy is not None:
            x = cx + max(-62, min(62, dx * 0.04))
            y = cy + max(-62, min(62, dy * 0.04))
        else:
            return
        c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=_ACCENT, outline="")


class PlanePreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Joystick")
        content = ctk.CTkFrame(self.body, fg_color="transparent")
        content.pack(fill="both", expand=True)
        self._canvas = _meter_canvas(content, width=190, height=165)
        self._canvas.pack(side="left", padx=(4, 10))

        info = ctk.CTkFrame(content, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=(20, 0))
        self._x = tk.StringVar(value="X  —")
        self._y = tk.StringVar(value="Y  —")
        self._trigger = tk.StringVar(value="Spust: —")
        for var in (self._x, self._y):
            ctk.CTkLabel(
                info,
                textvariable=var,
                text_color=_TEXT,
                font=("", 13, "bold"),
                anchor="w",
            ).pack(fill="x", pady=2)
        trigger_box = ctk.CTkFrame(info, fg_color=_BG, corner_radius=7)
        trigger_box.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(
            trigger_box,
            textvariable=self._trigger,
            text_color=_TEXT,
            anchor="w",
        ).pack(fill="x", padx=9, pady=6)

    def update_mapped(self, mapped: object) -> None:
        axes = getattr(mapped, "absolute_axes", {}) if mapped is not None else {}
        sx = axes.get("stick_x") if isinstance(axes, dict) else None
        sy = axes.get("stick_y") if isinstance(axes, dict) else None
        held = getattr(mapped, "held_buttons", frozenset()) if mapped is not None else frozenset()
        self._x.set("X  —" if sx is None else f"X  {float(sx):+.2f}")
        self._y.set("Y  —" if sy is None else f"Y  {float(sy):+.2f}")
        self._trigger.set("Spust: aktywny" if "trigger" in held else "Spust: —")
        self._draw_stick(
            None if sx is None else float(sx),
            None if sy is None else float(sy),
        )

    def _draw_stick(self, sx: float | None, sy: float | None) -> None:
        c = self._canvas
        c.delete("all")
        cx, cy = 95, 82
        radius = 67
        c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=_BORDER, width=2)
        c.create_oval(cx - 34, cy - 34, cx + 34, cy + 34, outline=_BORDER)
        c.create_line(cx - radius, cy, cx + radius, cy, fill=_BORDER)
        c.create_line(cx, cy - radius, cx, cy + radius, fill=_BORDER)
        x = cx if sx is None else cx + max(-1.0, min(1.0, sx)) * 57
        y = cy if sy is None else cy + max(-1.0, min(1.0, sy)) * 57
        c.create_line(cx, cy, x, y, fill=_ACCENT, width=3)
        c.create_oval(x - 8, y - 8, x + 8, y + 8, fill=_ACCENT, outline="")


class MediaPreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Sterowanie multimediami", height=285)
        self._mpris = MprisPlayerVolume()
        self._last_mpris_poll = 0.0
        self._mpris_status = None
        self._last_action_text = "—"
        self._last_action_ts = ""
        self._default_player = load_default_player()
        self._source_signature: tuple[tuple[str, ...], str | None, str | None] | None = None
        self._source_buttons: dict[str, tuple[ctk.CTkButton, ctk.CTkButton]] = {}

        self._vol = tk.StringVar(value="Odtwarzacz —   Głośność —")
        ctk.CTkLabel(
            self.body,
            textvariable=self._vol,
            text_color=_TEXT,
            font=("", 12, "bold"),
            anchor="w",
        ).pack(fill="x")
        self._volume_bar = tk.Canvas(
            self.body,
            height=12,
            bg=_SURFACE,
            highlightthickness=0,
            bd=0,
        )
        self._volume_bar.pack(fill="x", pady=(2, 7))
        self._draw_volume(None)

        ctk.CTkLabel(
            self.body,
            text="Źródła multimedialne",
            text_color=_MUTED,
            font=("", 10),
            anchor="w",
        ).pack(fill="x")
        self._sources = ctk.CTkScrollableFrame(
            self.body,
            fg_color=_BG,
            corner_radius=8,
            height=82,
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_MUTED,
        )
        self._sources.pack(fill="x", pady=(3, 7))

        bottom = ctk.CTkFrame(self.body, fg_color="transparent")
        bottom.pack(fill="x")
        self._action = tk.StringVar(value="Ostatnia akcja: —")
        ctk.CTkLabel(
            bottom,
            textvariable=self._action,
            text_color=_TEXT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            bottom,
            text="klik ▶/⏸   przechył ⏮/⏭   obrót = głośność",
            text_color=_MUTED,
            font=("", 9),
            anchor="e",
        ).pack(side="right")

    def _media_status(self, *, force: bool = False):
        now = time.monotonic()
        cached = self._mpris_status
        if not force and cached is not None and (now - self._last_mpris_poll) < 1.0:
            return cached
        status = self._mpris.describe_status()
        self._mpris_status = status
        self._last_mpris_poll = now
        return status

    def _select_source(self, player: str) -> None:
        status = self._media_status(force=True)
        if player not in status.players:
            return
        # The configurator owns this MPRIS selector. Pinning makes subsequent
        # status/volume reads follow the clicked source instead of list order.
        self._mpris._pinned_player = player  # type: ignore[attr-defined]
        self._mpris._cached_player = player  # type: ignore[attr-defined]
        self._mpris_status = None
        self._last_mpris_poll = 0.0
        self._source_signature = None
        self._refresh_sources(self._media_status(force=True))

    def _toggle_default_source(self, player: str) -> None:
        self._default_player = None if self._default_player == player else player
        save_default_player(self._default_player)
        if self._default_player is not None:
            self._select_source(player)
        else:
            self._source_signature = None
            self._refresh_sources(self._media_status(force=True))

    def _refresh_sources(self, status: object) -> None:
        players = tuple(getattr(status, "players", ()) or ())
        active = getattr(status, "active_player", None)
        if self._default_player in players and getattr(self._mpris, "_pinned_player", None) is None:
            self._mpris._pinned_player = self._default_player  # type: ignore[attr-defined]
            self._mpris._cached_player = self._default_player  # type: ignore[attr-defined]
            active = self._default_player
        signature = (players, active, self._default_player)
        if signature == self._source_signature:
            return
        self._source_signature = signature
        for child in self._sources.winfo_children():
            child.destroy()
        self._source_buttons.clear()
        if not players:
            ctk.CTkLabel(
                self._sources,
                text="Brak wykrytych źródeł MPRIS",
                text_color=_MUTED,
                anchor="w",
            ).pack(fill="x", padx=4, pady=4)
            return
        identity = getattr(status, "identity", None)
        for player in players:
            row = ctk.CTkFrame(self._sources, fg_color="transparent")
            row.pack(fill="x", pady=1)
            label = MprisPlayerVolume._friendly_name(
                player,
                identity if player == active else None,
            )
            selected = player == active
            source_btn = ctk.CTkButton(
                row,
                text=label,
                anchor="w",
                height=26,
                fg_color=_ACCENT_SOFT if selected else "transparent",
                hover_color=_ACCENT_SOFT,
                text_color=_ACCENT if selected else _TEXT,
                command=lambda key=player: self._select_source(key),
            )
            source_btn.pack(side="left", fill="x", expand=True)
            star_btn = ctk.CTkButton(
                row,
                text="★" if player == self._default_player else "☆",
                width=30,
                height=26,
                fg_color="transparent",
                hover_color=_ACCENT_SOFT,
                text_color=_ACCENT if player == self._default_player else _MUTED,
                command=lambda key=player: self._toggle_default_source(key),
            )
            star_btn.pack(side="right", padx=(4, 0))
            self._source_buttons[player] = (source_btn, star_btn)

    def _draw_volume(self, value: float | None) -> None:
        c = self._volume_bar
        c.delete("all")
        width = max(40, c.winfo_width())
        if width <= 40:
            width = 330
        y0, y1 = 3, 9
        c.create_rectangle(1, y0, width - 1, y1, fill=_BG, outline=_BORDER)
        frac = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        c.create_rectangle(1, y0, 1 + frac * (width - 2), y1, fill=_ACCENT, outline="")

    def update_mapped(self, mapped: object, recent_pulses: tuple[tuple[float, str], ...]) -> None:
        prev = media_preview(mapped if hasattr(mapped, "absolute_axes") else None)
        volume = prev["volume"]
        status = self._media_status()
        self._refresh_sources(status)
        name = "—"
        if status.active_player:
            name = MprisPlayerVolume._friendly_name(status.active_player, status.identity)
        if prev.get("system"):
            self._vol.set(f"System · muzyka wyciszona · {name}")
            self._draw_volume(0.0)
            self._action.set("Ostatnia akcja: kapsel odwrócony")
            return
        if volume is None:
            self._vol.set(f"{name}   ·   Głośność —")
            self._draw_volume(None)
        else:
            pct = float(volume) * 100
            self._vol.set(f"{name}   ·   Głośność {pct:.0f}%")
            self._draw_volume(float(volume))
        pulse_names = {p for _t, p in recent_pulses}
        for pulse in prev["pulses"]:  # type: ignore[union-attr]
            pulse_names.add(str(pulse))
        label = None
        if "play_pause" in pulse_names:
            label = "Play / Pause"
        elif "next_track" in pulse_names:
            label = "Następny utwór"
        elif "previous_track" in pulse_names:
            label = "Poprzedni utwór"
        elif "cycle_player" in pulse_names:
            label = "Zmiana odtwarzacza"
        if label:
            self._last_action_text = label
            self._last_action_ts = time.strftime("%H:%M:%S")
        suffix = f" · {self._last_action_ts}" if self._last_action_ts else ""
        self._action.set(f"Ostatnia akcja: {self._last_action_text}{suffix}")


class PreviewDashboard(ctk.CTkFrame):
    """Compact 2×2 device dashboard for the configurator preview page."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color="transparent")
        ctk.CTkLabel(
            self,
            text="Podgląd elementów konfiguracji",
            font=("", 18, "bold"),
            text_color=_TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Wartości są aktualizowane na żywo po mapowaniu profilu.",
            text_color=_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure(0, weight=1, uniform="preview")
        grid.grid_columnconfigure(1, weight=1, uniform="preview")
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_rowconfigure(1, weight=1)

        self.steering = SteeringPreviewCard(grid)
        self.mouse = MousePreviewCard(grid)
        self.plane = PlanePreviewCard(grid)
        self.media = MediaPreviewCard(grid)
        self.steering.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        self.mouse.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        self.plane.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(6, 0))
        self.media.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(6, 0))

    def update_snapshot(self, snap: object, settings: object) -> None:
        from triki_controller.gui.session import SessionSnapshot

        if not isinstance(snap, SessionSnapshot):
            return
        motion = snap.motion
        steering_mapped = map_profile_preview(motion, profile_name="steering", settings=settings)
        mouse_mapped = map_profile_preview(motion, profile_name="mouse", settings=settings)
        plane_mapped = map_profile_preview(motion, profile_name="plane", settings=settings)
        media_mapped = map_profile_preview(motion, profile_name="media", settings=settings)
        if snap.profile_name == "steering" and snap.mapped is not None:
            steering_mapped = snap.mapped
        if snap.profile_name == "mouse" and snap.mapped is not None:
            mouse_mapped = snap.mapped
        if snap.profile_name == "plane" and snap.mapped is not None:
            plane_mapped = snap.mapped
        if snap.profile_name == "media" and snap.mapped is not None:
            media_mapped = snap.mapped
        self.steering.update_mapped(steering_mapped)
        self.mouse.update_motion(motion, mouse_mapped, snap.pointer_px_per_s)
        self.plane.update_mapped(plane_mapped)
        self.media.update_mapped(media_mapped, snap.recent_pulses)
