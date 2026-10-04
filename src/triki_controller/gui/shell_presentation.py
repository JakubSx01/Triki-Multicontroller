"""Modern menu and quick-status presentation, isolated from the configurator."""

from typing import Any, Callable
import tkinter as tk

import customtkinter as ctk

from triki_controller.gui.shell_icons import icon

BG = "#101722"
SURFACE = "#1A2433"
TEXT = "#F0F4FC"
MUTED = "#ADBCD1"
ACCENT = "#285FCB"
BORDER = "#5B7090"
ICON_COLOR = "#82ADFF"


def _label(parent: Any, text: str = "", *, size: int = 14, bold: bool = False, **kwargs: Any) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                        text_color=kwargs.pop("text_color", TEXT), **kwargs)


def _button(parent: Any, text: str, name: str, command: Callable, *, primary: bool = False,
            **kwargs: Any) -> ctk.CTkButton:
    button = ctk.CTkButton(
        parent, text=text, image=icon(name, 18, "#FFFFFF" if primary else TEXT),
        compound="left", command=command, height=44, corner_radius=10,
        fg_color=ACCENT if primary else SURFACE, text_color="#FFFFFF" if primary else TEXT,
        hover_color="#3470DF" if primary else "#283A51", border_width=1,
        border_color=ACCENT if primary else BORDER, **kwargs,
    )
    # CTk's frame-backed buttons need explicit keyboard traversal/activation.
    button.tk.call(button._w, "configure", "-takefocus", 1)
    bindings = {
        "<Return>": lambda event: button.invoke(),
        "<space>": lambda event: button.invoke(),
        "<FocusIn>": lambda event: button.configure(border_color=TEXT),
        "<FocusOut>": lambda event: button.configure(border_color=ACCENT if primary else BORDER),
    }
    for sequence, callback in bindings.items():
        tk.Misc.bind(button, sequence, callback)
        button.bind(sequence, callback)
    return button


def _surface(parent: Any) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=14,
                        border_width=1, border_color=BORDER)


def _shell_container(app: Any) -> ctk.CTkFrame:
    app._content.configure(fg_color=BG)
    outer = ctk.CTkFrame(app._content, fg_color=BG, width=640)
    outer.pack(fill="y", expand=True, padx=24, pady=20)
    outer.pack_propagate(False)
    return outer


def build_main_menu(app: Any, devices: dict) -> None:
    outer = _shell_container(app)
    _label(outer, "TRIKI / MULTICONTROLLER", size=12, text_color=MUTED).pack(anchor="w")
    _label(outer, "Wybierz sposób sterowania", size=25, bold=True).pack(anchor="w", pady=(4, 0))
    _label(outer, "Jedna nakładka. Cztery możliwości.", text_color=MUTED).pack(anchor="w", pady=(0, 16))
    source = _surface(outer)
    source.pack(fill="x", pady=(0, 12))
    ctk.CTkLabel(source, text="", image=icon("bluetooth", 22, ICON_COLOR), width=32).pack(side="left", padx=(14, 8), pady=14)
    _label(source, "BLE · naciśnij raz przycisk na nakładce przed połączeniem.",
           text_color=MUTED, wraplength=430, justify="left", anchor="w").pack(side="left", padx=(0, 12), pady=10)
    cards = ctk.CTkScrollableFrame(outer, fg_color=BG, corner_radius=0)
    cards.pack(fill="both", expand=True)
    app._shell_launch_buttons = {}
    descriptions = {
        "steering": "Kierownica, gaz i hamulec",
        "mouse": "Ruch kursora i kliknięcia",
        "plane": "Wychylenie joysticka i spust",
        "media": "Muzyka i głośność",
    }
    for profile, (_command, label, hint) in devices.items():
        card = _surface(cards)
        card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card, text="", image=icon(profile, 28, ICON_COLOR), width=40).pack(side="left", padx=(14, 8), pady=16)
        copy = ctk.CTkFrame(card, fg_color="transparent")
        copy.pack(side="left", fill="x", expand=True, pady=12)
        _label(copy, label, size=16, bold=True, anchor="w").pack(anchor="w")
        _label(copy, descriptions[profile], size=13, text_color=MUTED, anchor="w").pack(anchor="w")
        button = _button(card, "Uruchom", "launch", lambda p=profile: app._launch_device(p),
                         primary=True, width=112)
        button.pack(side="right", padx=14, pady=14)
        app._shell_launch_buttons[profile] = button
    actions = ctk.CTkFrame(outer, fg_color="transparent")
    actions.pack(fill="x", pady=(12, 0))
    actions.grid_columnconfigure((0, 1), weight=1)
    _button(actions, "Konfigurator", "config", app._show_configurator).grid(row=0, column=0, sticky="ew", padx=(0, 6))
    _button(actions, "Utwórz skróty", "shortcuts", app._install_shortcuts).grid(row=0, column=1, sticky="ew", padx=(6, 0))
    _label(outer, textvariable=app._status, text_color=MUTED, anchor="w",
           wraplength=520, justify="left").pack(fill="x", pady=(8, 0))


def build_device_screen(app: Any, title: str, *, from_menu: bool) -> None:
    outer = _shell_container(app)
    header = ctk.CTkFrame(outer, fg_color="transparent")
    header.pack(fill="x", pady=(0, 16))
    profile = {"wheel": "steering", "music": "media"}.get(app._quick_command, app._quick_command or "steering")
    ctk.CTkLabel(header, text="", image=icon(profile, 28, ICON_COLOR), width=36).pack(side="left", padx=(0, 10))
    _label(header, title, size=23, bold=True).pack(side="left")
    _label(header, textvariable=app._rate, text_color=MUTED).pack(side="right")
    status = _surface(outer)
    status.pack(fill="x", pady=(0, 12))
    inner = ctk.CTkFrame(status, fg_color="transparent")
    inner.pack(fill="x", padx=18, pady=16)
    _label(inner, "STAN URZĄDZENIA", size=12, text_color=MUTED).pack(anchor="w", pady=(0, 8))
    for variable in (app._conn, app._output):
        _label(inner, textvariable=variable, size=16, anchor="w").pack(fill="x")
    for variable in (app._chips, app._detail):
        _label(inner, textvariable=variable, text_color=MUTED, wraplength=510,
               justify="left", anchor="w").pack(fill="x", pady=(4, 0))
    meter = _surface(outer)
    meter.pack(fill="both", expand=True, pady=(0, 12))
    _label(meter, textvariable=app._meter, wraplength=510, justify="left", anchor="w").pack(fill="both", expand=True, padx=18, pady=16)
    actions = ctk.CTkFrame(outer, fg_color="transparent")
    actions.pack(fill="x")
    actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="actions")
    entries = [
        ("Połącz ponownie", "retry", app._on_retry, True),
        ("Zatrzymaj sterowanie", "stop", app._on_stop, False),
        ("Rozłącz", "disconnect", app._on_disconnect, False),
    ]
    if from_menu or app.view == "panel":
        entries.append(("Menu", "menu", app._back_to_menu_from_device, False))
    entries.append(("Zamknij", "close", app.close, False))
    for index, (label, name, command, primary) in enumerate(entries):
        _button(actions, label, name, command, primary=primary, width=140).grid(
            row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4)
    _label(outer, textvariable=app._status, text_color=MUTED, anchor="w",
           wraplength=510, justify="left").pack(fill="x", pady=(8, 0))
