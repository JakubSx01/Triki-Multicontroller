"""Task-first desktop shell; the original configurator keeps its own theme."""

from typing import Any, Callable
import tkinter as tk

import customtkinter as ctk

from triki_controller.gui.shell_icons import icon

BG = "#11151C"
SURFACE = "#1B222D"
TEXT = "#F0F4FC"
MUTED = "#ADBCD1"
ACCENT = "#285FCB"
BORDER = "#617590"
ICON_COLOR = "#82ADFF"
HOVER = "#293649"
SPACE = 16


def _wrap_label(label: ctk.CTkLabel) -> None:
    # Bind the frame, not CTk's text/canvas children, to avoid resize feedback loops.
    def resize(event):
        width = max(120, event.width - 8)
        if label.cget('wraplength') != width:
            label.configure(wraplength=width)
    tk.Misc.bind(label, '<Configure>', resize)


def _label(parent: Any, text: str = "", *, size: int = 14, bold: bool = False, **kwargs: Any) -> ctk.CTkLabel:
    label = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                         text_color=kwargs.pop("text_color", TEXT), **kwargs)
    if kwargs.get("justify") == "left":
        _wrap_label(label)
    return label


def _button(parent: Any, text: str, name: str, command: Callable, *, primary: bool = False,
            **kwargs: Any) -> ctk.CTkButton:
    button = ctk.CTkButton(
        parent, text=text, image=icon(name, 18, "#FFFFFF" if primary else TEXT),
        compound="left", command=command, height=44, corner_radius=8,
        fg_color=ACCENT if primary else SURFACE, text_color="#FFFFFF" if primary else TEXT,
        text_color_disabled=MUTED, font=ctk.CTkFont(size=14),
        hover_color="#3470DF" if primary else HOVER, border_width=2,
        border_color=ACCENT if primary else BORDER, **kwargs,
    )
    # CTk buttons are frames, so native Tab traversal needs explicit bindings.
    button.tk.call(button._w, "configure", "-takefocus", 1)
    def activate(_event):
        button.invoke()
        return "break"
    def focus_in(_event):
        from triki_controller.gui.control_options import _reveal_focus
        button.configure(border_color=TEXT)
        _reveal_focus(button)
    bindings = {
        "<Return>": activate,
        "<space>": activate,
        "<FocusIn>": focus_in,
        "<FocusOut>": lambda event: button.configure(border_color=ACCENT if primary else BORDER),
    }
    for sequence, callback in bindings.items():
        tk.Misc.bind(button, sequence, callback)
        button.bind(sequence, callback)
    return button


def _surface(parent: Any) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12,
                        border_width=1, border_color=BORDER)


def _shell_container(app: Any) -> ctk.CTkFrame:
    app._content.configure(fg_color=BG)
    outer = ctk.CTkFrame(app._content, fg_color=BG)
    outer.pack(fill="both", expand=True, padx=SPACE, pady=SPACE)
    return outer


def _navigation(app: Any, parent: Any, *, device: bool) -> None:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(0, SPACE))
    _label(row, "TRIKI", size=16, bold=True).pack(side="left")
    app._shell_navigation_buttons = []
    if device:
        button = _button(row, "Menu", "menu", app._back_to_menu_from_device, width=100)
        button.pack(side="left", padx=(SPACE, 8))
        app._shell_navigation_buttons.append(button)
    def configurator():
        if not app._dirty or app._confirm_discard():
            app._show_configurator()
    button = _button(row, "Konfigurator", "config", configurator if device else app._show_configurator, width=144)
    button.pack(side="right")
    app._shell_navigation_buttons.append(button)


def build_main_menu(app: Any, devices: dict) -> None:
    outer = _shell_container(app)
    _navigation(app, outer, device=False)
    _label(outer, "Co chcesz kontrolować?", size=26, bold=True).pack(anchor="w")
    _label(outer, "Wybierz funkcję. Połączenie uruchomimy w kolejnym kroku.",
           text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=(4, SPACE))
    cards = ctk.CTkScrollableFrame(outer, fg_color=BG, corner_radius=0)
    cards.pack(fill="both", expand=True)
    app._shell_launch_buttons = {}
    descriptions = {
        "steering": "Kierownica, gaz i hamulec",
        "mouse": "Ruch kursora i kliknięcia",
        "plane": "Wychylenie joysticka i spust",
        "media": "Odtwarzacz, muzyka i głośność",
    }
    current = app.session.current_settings().profile
    for profile, (_command, label, _hint) in devices.items():
        card = _surface(cards)
        card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card, text="", image=icon(profile, 28, ICON_COLOR), width=40).pack(side="left", padx=(12, 8), pady=16)
        copy = ctk.CTkFrame(card, fg_color="transparent")
        copy.pack(side="left", fill="x", expand=True, pady=12)
        _label(copy, label, size=16, bold=True, anchor="w").pack(fill="x")
        _label(copy, descriptions[profile], size=13, text_color=MUTED, anchor="w", justify="left").pack(fill="x")
        button = _button(card, "Otwórz", "launch", lambda p=profile: app._launch_device(p),
                         primary=profile == current, width=104)
        button.pack(side="right", padx=12, pady=12)
        app._shell_launch_buttons[profile] = button
    footer = ctk.CTkFrame(outer, fg_color="transparent")
    footer.pack(fill="x", pady=(8, 0))
    _label(footer, textvariable=app._conn, text_color=MUTED, anchor="w", justify="left").pack(fill="x")
    _button(footer, "Utwórz skróty pulpitu", "shortcuts", app._install_shortcuts, width=210).pack(anchor="w", pady=(8, 0))
    _label(outer, textvariable=app._status, text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=(8, 0))


def build_device_screen(app: Any, title: str, *, from_menu: bool) -> None:
    from triki_controller.gui.control_options import _keyboard_menu
    outer = _shell_container(app)
    _navigation(app, outer, device=True)
    profile = {"wheel": "steering", "music": "media"}.get(app._quick_command, app._quick_command or "steering")
    heading = ctk.CTkFrame(outer, fg_color="transparent")
    heading.pack(fill="x", pady=(0, 12))
    _label(heading, "Sterowanie", size=24, bold=True).pack(side="left")
    labels = {"Kierownica": "steering", "AirMouse": "mouse", "Joystick": "plane", "Multimedia": "media"}
    def choose(label):
        app._launch_device(labels[label])
        tk.Misc.focus_set(app._function_menu)
    app._function_menu = ctk.CTkOptionMenu(
        heading, values=list(labels), command=choose, height=40, width=200,
        fg_color=SURFACE, button_color=ACCENT, text_color=TEXT,
        dropdown_fg_color=SURFACE, dropdown_text_color=TEXT)
    app._function_menu.set(next(label for label, name in labels.items() if name == profile))
    app._function_menu.pack(side="right")
    _keyboard_menu(app._function_menu, choose)
    status = _surface(outer)
    status.pack(fill="x", pady=(0, 12))
    inner = ctk.CTkFrame(status, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=8)
    status_line = ctk.CTkFrame(inner, fg_color="transparent")
    status_line.pack(fill="x")
    status_line.grid_columnconfigure((0, 1), weight=1, uniform="status")
    _label(status_line, textvariable=app._conn, size=14, bold=True, anchor="w", justify="left").grid(row=0, column=0, sticky="ew")
    _label(status_line, textvariable=app._output, anchor="e", justify="left").grid(row=0, column=1, sticky="ew")
    app._shell_connection_hint = tk.StringVar(app.root)
    _label(inner, textvariable=app._shell_connection_hint, text_color=MUTED, anchor="w", justify="left", height=0).pack(fill="x", pady=(4, 0))

    tabs = ctk.CTkFrame(outer, fg_color="transparent")
    tabs.pack(fill="x", pady=(0, 8))
    page_names = ("Sterowanie", "Diagnostyka") if profile == "media" else ("Sterowanie", "Przypisania", "Diagnostyka")
    tabs.grid_columnconfigure(tuple(range(len(page_names))), weight=1, uniform="tabs")
    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="both", expand=True)
    app._shell_pages = {}
    app._shell_tab_buttons = {}
    for name in page_names:
        page = ctk.CTkScrollableFrame(body, fg_color=BG, corner_radius=0)
        app._shell_pages[name] = page
    def show(name):
        for key, page in app._shell_pages.items():
            page.pack_forget()
            app._shell_tab_buttons[key].configure(fg_color=HOVER if key == name else BG,
                                                 border_color=ICON_COLOR if key == name else BORDER)
        app._shell_pages[name].pack(fill="both", expand=True)
        app._shell_active_page = name
    app._show_shell_page = show
    glyphs = {"Sterowanie": "launch", "Przypisania": "config", "Diagnostyka": "retry"}
    for index, name in enumerate(page_names):
        button = _button(tabs, name, glyphs[name], lambda n=name: show(n), width=100)
        button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0 if index == len(page_names) - 1 else 4))
        app._shell_tab_buttons[name] = button

    control = app._shell_pages["Sterowanie"]
    _label(control, "Odtwarzacz i preferencje" if profile == "media" else "Gotowy do sterowania", size=18, bold=True, anchor="w").pack(fill="x", pady=(4, 8))
    if profile != "media":
        instructions = {
            "steering": "Obracaj nakładkę, aby skręcać. Gaz i hamulec zależą od mapowania profilu.",
            "mouse": "Przechyl nakładkę, aby ruszać kursorem. Domyślnie: jeden klik — lewy przycisk, dwa — prawy.",
            "plane": "Przechyl nakładkę, aby wychylić joystick. Przycisk odpowiada za spust profilu.",
        }
        _label(control, instructions[profile], text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=(0, 16))
        _label(control, "Reakcja profilu", size=16, bold=True, anchor="w").pack(fill="x")
        _label(control, textvariable=app._meter, anchor="w", justify="left").pack(fill="x", pady=8)
        _label(control, "Własne klawisze i kliknięcia znajdziesz w „Przypisania”. Mapowanie osi i kalibracja są w Konfiguratorze.",
               text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=8)
    app._options_parent = control if profile == "media" else app._shell_pages["Przypisania"]
    diagnostics = app._shell_pages["Diagnostyka"]
    _label(diagnostics, "Dane połączenia", size=18, bold=True, anchor="w").pack(fill="x", pady=(4, 8))
    for variable in (app._rate, app._detail, app._chips, app._meter):
        _label(diagnostics, textvariable=variable, text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=8)
    _label(diagnostics, "Ponowne połączenie rozłącza obecną sesję BLE. Zmiana funkcji jej nie rozłącza.",
           text_color=MUTED, anchor="w", justify="left").pack(fill="x", pady=8)
    app._diagnostic_action_buttons = []
    for label, glyph, command in (("Połącz ponownie", "retry", app._on_retry), ("Rozłącz", "disconnect", app._on_disconnect), ("Zamknij", "close", app.close)):
        button = _button(diagnostics, label, glyph, command)
        button.pack(fill="x", pady=4)
        app._diagnostic_action_buttons.append(button)

    footer = ctk.CTkFrame(outer, fg_color="transparent")
    footer.pack(side="bottom", fill="x", pady=(8, 0), before=body)
    # Full feedback scrolls independently, so long errors cannot evict safety actions.
    feedback = ctk.CTkTextbox(footer, height=64, wrap="word", fg_color=SURFACE,
                             text_color=MUTED, font=ctk.CTkFont(size=14),
                             border_width=2, border_color=BORDER)
    app._shell_feedback = feedback
    feedback.pack(fill="x")
    def update_feedback(*_args):
        feedback.configure(state="normal")
        feedback.delete("1.0", "end")
        feedback.insert("1.0", app._status.get())
        feedback.configure(state="disabled")
    update_feedback()
    trace = app._status.trace_add("write", update_feedback)
    def remove_feedback_trace(event):
        if event.widget == feedback:
            app._status.trace_remove("write", trace)
    tk.Misc.bind(feedback, "<Destroy>", remove_feedback_trace, add="+")
    feedback._textbox.configure(takefocus=1)
    feedback.bind("<FocusIn>", lambda event: feedback.configure(border_color=TEXT))
    feedback.bind("<FocusOut>", lambda event: feedback.configure(border_color=BORDER))
    _label(footer, textvariable=app._dirty_label, text_color=ICON_COLOR, anchor="w").pack(fill="x")
    actions = ctk.CTkFrame(footer, fg_color="transparent")
    actions.pack(fill="x", pady=(4, 0))
    actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="actions")
    def resume():
        from triki_controller.core.models import ConnectionState
        if app.session.snapshot().connection in {ConnectionState.DISCONNECTED, ConnectionState.ERROR}:
            app._on_retry()
        elif not app._autostart.live:
            app._on_dry()
        else:
            app._on_live()
    app._resume_button = _button(actions, "Wznów", "launch", resume, primary=True, width=100)
    app._stop_button = _button(actions, "Zatrzymaj", "stop", app._on_stop, width=100)
    app._save_button = _button(actions, "Zapisz", "save", app._save_config, width=100)
    app._device_action_buttons = [app._resume_button, app._stop_button, app._save_button]
    for index, button in enumerate(app._device_action_buttons):
        button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0 if index == 2 else 4))
    show("Sterowanie")
    refresh_device_actions(app)


def refresh_device_actions(app: Any) -> None:
    """Do not offer live output without streaming or disguise retry as resume."""
    from triki_controller.core.models import ConnectionState
    from triki_controller.gui.session import OutputMode
    if app._screen != "device":
        return
    snap = app.session.snapshot()
    stopped = snap.output_mode == OutputMode.OFF
    ready = snap.connection == ConnectionState.STREAMING
    disconnected = snap.connection in {ConnectionState.DISCONNECTED, ConnectionState.ERROR}
    label = "Połącz" if disconnected else ("Wznów" if app._autostart.live else "Wznów próbne")
    if not disconnected and not ready:
        label = "Łączenie…"
    elif ready and not stopped:
        label = "Działa"
    if snap.connection == ConnectionState.DISCONNECTED:
        hint = "Naciśnij Połącz, potem raz przycisk na nakładce."
    elif snap.connection == ConnectionState.ERROR:
        hint = "Błąd połączenia. Pełne szczegóły: Diagnostyka. Naciśnij Połącz, aby spróbować ponownie."
    elif not ready:
        hint = "Łączenie… naciśnij raz przycisk na nakładce."
    elif stopped:
        hint = "Połączono. Wznów sterowanie, gdy będziesz gotowy."
    else:
        hint = "Zmiana funkcji zachowuje BLE. Zatrzymaj wyłącza tylko sterowanie."
    if app._shell_connection_hint.get() != hint:
        app._shell_connection_hint.set(hint)
    current_state = "normal" if disconnected or (stopped and ready) else "disabled"
    if app._resume_button.cget('state') != current_state or app._resume_button.cget('text') != label:
        app._resume_button.configure(state=current_state, text=label)
    stop_state = "normal" if not stopped or app._autostart.enabled else "disabled"
    if app._stop_button.cget('state') != stop_state:
        app._stop_button.configure(state=stop_state)
