"""Mockup-style live preview cards for the configurator Podgląd page."""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any

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
_BORDER = "#D5D9E0"
_GREEN = "#2F9E6B"
_RED = "#C44536"
_CARD_W = 280


class _Card(ctk.CTkFrame):
    def __init__(self, parent: Any, title: str) -> None:
        super().__init__(
            parent, fg_color=_SURFACE, corner_radius=12, border_width=1, border_color=_BORDER, width=_CARD_W
        )
        self.pack_propagate(False)
        pad = ctk.CTkFrame(self, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=14, pady=12)
        ctk.CTkLabel(pad, text=title, font=("", 15, "bold"), text_color=_TEXT, anchor="w").pack(
            anchor="w", pady=(0, 8)
        )
        self.body = ctk.CTkFrame(pad, fg_color="transparent")
        self.body.pack(fill="both", expand=True)


class SteeringPreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Kierownica")
        self._canvas = tk.Canvas(
            self.body, width=240, height=130, bg=_SURFACE, highlightthickness=0, bd=0
        )
        self._canvas.pack()
        self._angle = tk.StringVar(value="Wychylenie: —")
        ctk.CTkLabel(self.body, textvariable=self._angle, text_color=_TEXT).pack(pady=(4, 8))
        pedals = ctk.CTkFrame(self.body, fg_color="transparent")
        pedals.pack(fill="x")
        self._gas_canvas = tk.Canvas(pedals, width=40, height=100, bg=_SURFACE, highlightthickness=0)
        self._brake_canvas = tk.Canvas(pedals, width=40, height=100, bg=_SURFACE, highlightthickness=0)
        self._gas_canvas.pack(side="left", padx=(40, 20))
        self._brake_canvas.pack(side="left", padx=20)
        labels = ctk.CTkFrame(pedals, fg_color="transparent")
        labels.pack(side="left", fill="y")
        self._gas_pct = tk.StringVar(value="Gaz\n—")
        self._brake_pct = tk.StringVar(value="Hamulec\n—")
        ctk.CTkLabel(labels, textvariable=self._gas_pct, text_color=_MUTED, justify="left").pack(
            anchor="w"
        )
        ctk.CTkLabel(labels, textvariable=self._brake_pct, text_color=_MUTED, justify="left").pack(
            anchor="w", pady=(12, 0)
        )

    def update_mapped(self, mapped: object) -> None:
        values = steering_preview(mapped if hasattr(mapped, "absolute_axes") else None)
        wheel = values["wheel"]
        throttle = values["throttle"]
        brake = values["brake"]
        deg = None if wheel is None else float(wheel) * 90.0
        self._angle.set("Wychylenie: —" if deg is None else f"Wychylenie: {deg:+.0f}°")
        self._draw_gauge(deg)
        self._draw_pedal(self._gas_canvas, throttle, _GREEN)
        self._draw_pedal(self._brake_canvas, brake, _RED)
        self._gas_pct.set(
            "Gaz\n—" if throttle is None else f"Gaz\n{float(throttle) * 100:.0f}%"
        )
        self._brake_pct.set(
            "Hamulec\n—" if brake is None else f"Hamulec\n{float(brake) * 100:.0f}%"
        )

    def _draw_gauge(self, deg: float | None) -> None:
        c = self._canvas
        c.delete("all")
        cx, cy, r = 120, 110, 85
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=180, style=tk.ARC, outline=_BORDER, width=3)
        for mark, label in ((-90, "−90°"), (0, "0°"), (90, "+90°")):
            rad = math.radians(mark)
            x = cx + math.sin(rad) * (r + 4)
            y = cy - math.cos(rad) * (r + 4)
            c.create_text(x, y - 8, text=label, fill=_MUTED, font=("", 8))
        angle = 0.0 if deg is None else max(-90.0, min(90.0, deg))
        rad = math.radians(angle)
        c.create_line(
            cx,
            cy,
            cx + math.sin(rad) * (r - 12),
            cy - math.cos(rad) * (r - 12),
            fill=_ACCENT,
            width=4,
            arrow=tk.LAST,
        )
        c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=_ACCENT, outline="")

    def _draw_pedal(self, canvas: tk.Canvas, value: float | None, color: str) -> None:
        canvas.delete("all")
        canvas.create_rectangle(8, 4, 32, 96, outline=_BORDER, width=1)
        frac = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        top = 96 - frac * 92
        canvas.create_rectangle(8, top, 32, 96, fill=color, outline="")


class MousePreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Air Mouse")
        self._canvas = tk.Canvas(
            self.body, width=220, height=220, bg=_SURFACE, highlightthickness=0, bd=0
        )
        self._canvas.pack()
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=8)
        self._x = tk.StringVar(value="Oś X\n—")
        self._y = tk.StringVar(value="Oś Y\n—")
        for var in (self._x, self._y):
            box = ctk.CTkFrame(row, fg_color=_BG, corner_radius=8)
            box.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(box, textvariable=var, text_color=_TEXT, justify="center").pack(padx=8, pady=8)

    def update_motion(self, motion: object, mapped: object, pointer: tuple[float, float] | None) -> None:
        pitch = getattr(motion, "tilt_pitch_deg", None) if motion is not None else None
        roll = getattr(motion, "tilt_roll_deg", None) if motion is not None else None
        self._x.set("Oś X\n—" if pitch is None else f"Oś X\n{float(pitch):+.0f}°")
        self._y.set("Oś Y\n—" if roll is None else f"Oś Y\n{float(roll):+.0f}°")
        prev = mouse_preview(mapped if hasattr(mapped, "absolute_axes") else None, pointer)
        self._draw_radar(
            None if pitch is None else float(pitch),
            None if roll is None else float(roll),
            prev["dx"] if isinstance(prev["dx"], float) else None,
            prev["dy"] if isinstance(prev["dy"], float) else None,
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
        cx = cy = 110
        for radius in (30, 55, 80):
            c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=_BORDER)
        c.create_line(cx - 90, cy, cx + 90, cy, fill=_BORDER)
        c.create_line(cx, cy - 90, cx, cy + 90, fill=_BORDER)
        c.create_text(cx - 95, cy, text="lewo", fill=_MUTED, font=("", 8), anchor="e")
        c.create_text(cx + 95, cy, text="prawo", fill=_MUTED, font=("", 8), anchor="w")
        c.create_text(cx, cy - 95, text="przód", fill=_MUTED, font=("", 8))
        c.create_text(cx, cy + 95, text="tył", fill=_MUTED, font=("", 8))
        if roll is not None or pitch is not None:
            x = cx + max(-75, min(75, (0.0 if pitch is None else pitch) * 1.2))
            y = cy + max(-75, min(75, (0.0 if roll is None else roll) * 1.2))
        elif dx is not None and dy is not None:
            x = cx + max(-75, min(75, dx * 0.05))
            y = cy + max(-75, min(75, dy * 0.05))
        else:
            return
        c.create_oval(x - 7, y - 7, x + 7, y + 7, fill=_ACCENT, outline="")


class MediaPreviewCard(_Card):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Sterowanie multimediami")
        ctk.CTkLabel(
            self.body,
            text="Potrząśnij w osiach X i Y, żeby zmienić odtwarzacz. "
            "Przekręcenie (oś Z, jak głośność) nie przełącza. "
            "Pokrętło liczy się tylko gdy kapsel leży mniej więcej poziomo. "
            "Odwróć kapsel: muzyka cichnie, pokrętło steruje głośnością systemu. "
            "Odwróć z powrotem, żeby wróciła muzyka. "
            "Jedno potrząśnięcie = jedna zmiana.",
            text_color=_MUTED,
            wraplength=240,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        self._vol = tk.StringVar(value="Głośność: —")
        ctk.CTkLabel(self.body, textvariable=self._vol, text_color=_TEXT, anchor="w").pack(anchor="w")
        self._slider = ctk.CTkSlider(
            self.body, from_=0, to=100, number_of_steps=100, progress_color=_ACCENT, button_color=_ACCENT
        )
        self._slider.configure(state="disabled")
        self._slider.pack(fill="x", pady=8)
        self._action = tk.StringVar(value="Ostatnia akcja: —")
        action_box = ctk.CTkFrame(self.body, fg_color="#EAF1FE", corner_radius=8)
        action_box.pack(fill="x", pady=6)
        ctk.CTkLabel(
            action_box, textvariable=self._action, text_color=_TEXT, anchor="w", justify="left"
        ).pack(anchor="w", padx=10, pady=10)
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=6)
        for label in ("Play/Pause", "Następny", "Poprzedni", "Vol+", "Vol−"):
            chip = ctk.CTkFrame(row, fg_color=_BG, corner_radius=8, width=44, height=44)
            chip.pack(side="left", padx=3)
            chip.pack_propagate(False)
            ctk.CTkLabel(chip, text=label[:1], text_color=_MUTED).pack(expand=True)
        self._mpris = MprisPlayerVolume()
        self._last_mpris_poll = 0.0
        self._mpris_status = None
        self._last_action_text = "—"
        self._last_action_ts = ""

    def _media_status(self):
        now = time.monotonic()
        cached = self._mpris_status
        if cached is not None and (now - self._last_mpris_poll) < 1.0:
            return cached
        status = self._mpris.describe_status()
        self._mpris_status = status
        self._last_mpris_poll = now
        return status

    def update_mapped(self, mapped: object, recent_pulses: tuple[tuple[float, str], ...]) -> None:
        prev = media_preview(mapped if hasattr(mapped, "absolute_axes") else None)
        volume = prev["volume"]
        status = self._media_status()
        name = "—"
        if status.active_player:
            name = MprisPlayerVolume._friendly_name(status.active_player, status.identity)
        if prev.get("system"):
            self._vol.set(f"Głośność systemu · muzyka wyciszona · {name}")
            self._slider.set(0)
            self._action.set("Ostatnia akcja: kapsel odwrócony")
            return
        if volume is None:
            self._vol.set(f"Głośność: — · {name}")
            self._slider.set(0)
        else:
            pct = float(volume) * 100
            self._vol.set(f"Głośność: {pct:.0f}% · {name}")
            self._slider.set(pct)
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
        self._action.set(
            f"Ostatnia akcja\n{self._last_action_text}"
            + (f"\n{self._last_action_ts}" if self._last_action_ts else "")
        )


class PreviewDashboard(ctk.CTkFrame):
    """Three device cards side by side (Podgląd)."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, fg_color="transparent")
        ctk.CTkLabel(
            self, text="Podgląd elementów konfiguracji", font=("", 18, "bold"), text_color=_TEXT, anchor="w"
        ).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Sprawdź na żywo, jak urządzenie przekazuje dane po mapowaniu.",
            text_color=_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="both", expand=True)
        self.steering = SteeringPreviewCard(row)
        self.mouse = MousePreviewCard(row)
        self.media = MediaPreviewCard(row)
        self.steering.pack(side="left", fill="y", padx=(0, 10))
        self.mouse.pack(side="left", fill="y", padx=5)
        self.media.pack(side="left", fill="y", padx=(10, 0))

    def update_snapshot(self, snap: object, settings: object) -> None:
        from triki_controller.gui.session import SessionSnapshot

        if not isinstance(snap, SessionSnapshot):
            return
        motion = snap.motion
        steering_mapped = map_profile_preview(motion, profile_name="steering", settings=settings)
        mouse_mapped = map_profile_preview(motion, profile_name="mouse", settings=settings)
        media_mapped = map_profile_preview(motion, profile_name="media", settings=settings)
        # Prefer live mapped when that profile is active (includes click/mapper state).
        if snap.profile_name == "steering" and snap.mapped is not None:
            steering_mapped = snap.mapped
        if snap.profile_name == "mouse" and snap.mapped is not None:
            mouse_mapped = snap.mapped
        if snap.profile_name == "media" and snap.mapped is not None:
            media_mapped = snap.mapped
        self.steering.update_mapped(steering_mapped)
        self.mouse.update_motion(motion, mouse_mapped, snap.pointer_px_per_s)
        self.media.update_mapped(media_mapped, snap.recent_pulses)
