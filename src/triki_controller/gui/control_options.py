"""Additive, profile-scoped controls shared by the shell and configurator."""
from __future__ import annotations

from dataclasses import replace
import sys
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from triki_controller.gui.settings import GuiSettings
from triki_controller.gui.shell_presentation import SURFACE, TEXT, MUTED, ACCENT, BORDER
from triki_controller.profiles.control_bindings import BINDING_ACTIONS, BINDING_SOURCES

SOURCE_LABELS = {
    'button': 'Przycisk (trzymanie)', 'click': 'Jedno kliknięcie',
    'double_click': 'Dwa kliknięcia', 'triple_click': 'Trzy kliknięcia',
    'left': 'Ruch w lewo', 'right': 'Ruch w prawo',
    'forward': 'Ruch do przodu', 'backward': 'Ruch do tyłu',
}
_KEY_NAMES = {
    'up': '↑', 'down': '↓', 'left': '←', 'right': '→', 'space': 'Spacja',
    'enter': 'Enter', 'escape': 'Esc', 'shift': 'Shift', 'ctrl': 'Ctrl',
    'alt': 'Alt', 'tab': 'Tab', 'backspace': 'Backspace',
}
ACTION_LABELS = {
    'default': 'Domyślne', 'off': 'Wyłączone', 'mouse_left': 'Mysz: lewy',
    'mouse_right': 'Mysz: prawy', 'mouse_middle': 'Mysz: środkowy',
    **{action: 'Klawisz: ' + _KEY_NAMES.get(action[4:], action[4:].upper())
       for action in BINDING_ACTIONS if action.startswith('key_')},
}
_ACTION_VALUES = {label: action for action, label in ACTION_LABELS.items()}
_AUTO = 'Automatycznie'


def _focusable(widget, activate: Callable[[], object]) -> None:
    widget.tk.call(widget._w, 'configure', '-takefocus', 1)
    for sequence in ('<Return>', '<space>'):
        def invoke(_event, callback=activate):
            callback()
            return 'break'
        tk.Misc.bind(widget, sequence, invoke)
        widget.bind(sequence, invoke)


def _keyboard_menu(menu, choose: Callable[[str], object]) -> None:
    menu.tk.call(menu._w, 'configure', '-takefocus', 1)
    def move(event):
        values = menu.cget('values')
        index = values.index(menu.get()) if menu.get() in values else 0
        delta = -1 if event.keysym in {'Left', 'Up'} else 1
        label = values[(index + delta) % len(values)]
        menu.set(label)
        choose(label)
        return 'break'
    for sequence in ('<Left>', '<Right>', '<Up>', '<Down>'):
        tk.Misc.bind(menu, sequence, move)
        menu.bind(sequence, move)


class ControlOptions(ctk.CTkFrame):
    """Edits a settings value; callbacks never save files or arm output."""
    def __init__(self, parent, settings: GuiSettings, *,
                 on_change: Callable[[GuiSettings], str | None] | None = None,
                 list_players: Callable[[], list[tuple[str, str]]] | None = None):
        super().__init__(parent, fg_color=SURFACE, corner_radius=8,
                         border_width=1, border_color=BORDER)
        self.settings = settings
        self._on_change = on_change
        self._list_players = list_players
        self.binding_menus = {}
        self.player_menu = None
        self._player_values = {_AUTO: None}
        self.message = tk.StringVar(self, value='Zmiany działają w sesji. Tylko „Zapisz” utrwala plik.')
        self._build()

    def _label(self, parent, text, **kwargs):
        return ctk.CTkLabel(parent, text=text, text_color=kwargs.pop('text_color', TEXT), **kwargs)

    def _menu(self, parent, values, command):
        menu = ctk.CTkOptionMenu(parent, values=values, command=command, width=150,
                                fg_color='#26364D', button_color=ACCENT, text_color=TEXT,
                                dropdown_fg_color=SURFACE, dropdown_text_color=TEXT)
        _keyboard_menu(menu, command)
        return menu

    def _build(self):
        pad = ctk.CTkFrame(self, fg_color='transparent')
        pad.pack(fill='x', padx=10, pady=8)
        self._label(pad, 'Opcje sterowania', font=('', 14, 'bold'), anchor='w').pack(anchor='w')
        if self.settings.profile == 'media':
            self.gestures_enabled = tk.BooleanVar(self, value=self.settings.media_gestures_enabled)
            self.gesture_toggle = ctk.CTkCheckBox(
                pad, text='Potrząśnięcie zmienia odtwarzacz', variable=self.gestures_enabled,
                text_color=TEXT, fg_color=ACCENT,
                command=lambda: self._change(replace(self.settings, media_gestures_enabled=bool(self.gestures_enabled.get()))))
            self.gesture_toggle.pack(anchor='w', pady=5)
            _focusable(self.gesture_toggle, self.gesture_toggle.toggle)
            self._label(pad, 'Odtwarzacz (wybór ręczny)', anchor='w').pack(anchor='w')
            row = ctk.CTkFrame(pad, fg_color='transparent')
            row.pack(fill='x', pady=3)
            self.player_menu = self._menu(row, [_AUTO], self._choose_player)
            self.player_menu.pack(side='left', fill='x', expand=True)
            self.refresh_button = ctk.CTkButton(row, text='Odśwież', width=90,
                                              command=self.refresh_players, fg_color=ACCENT)
            self.refresh_button.pack(side='left', padx=(6, 0))
            _focusable(self.refresh_button, self.refresh_button.invoke)
            self.gesture_policy = tk.StringVar(self)
            ctk.CTkLabel(pad, textvariable=self.gesture_policy, text_color=MUTED,
                         anchor='w', justify='left', wraplength=560).pack(fill='x', pady=3)
            self.refresh_players()
        else:
            grid = ctk.CTkFrame(pad, fg_color='transparent')
            grid.pack(fill='x', pady=4)
            grid.grid_columnconfigure((1, 3), weight=1)
            for index, source in enumerate(BINDING_SOURCES):
                row, column = index // 2, (index % 2) * 2
                self._label(grid, SOURCE_LABELS[source], anchor='w').grid(row=row, column=column, sticky='w', padx=(0, 6), pady=2)
                choose = lambda label, s=source: self._choose_binding(s, label)
                menu = self._menu(grid, list(ACTION_LABELS.values()), choose)
                menu.set(ACTION_LABELS[self.settings.control_bindings.get(self.settings.profile, {}).get(source, 'default')])
                menu.grid(row=row, column=column + 1, sticky='ew', padx=(0, 8), pady=2)
                self.binding_menus[source] = menu
            hint = 'Kierunki: próg 20% po istniejącej martwej strefie. Przycisk: trzymanie; kliknięcia: po oknie ciszy. Własny przycisk zastępuje domyślne kliknięcia.'
            if sys.platform in {'win32', 'darwin'} and self.settings.profile in {'steering', 'plane'}:
                hint += ' Windows/macOS: tylko klawisze i przyciski myszy — bez wirtualnych osi analogowych. Wybierz własne działanie, aby użyć tego trybu. Domyślny spust joysticka jest wtedy nieaktywny; przypisz przycisk do klawisza lub myszy.'
            self._label(pad, hint, text_color=MUTED, anchor='w', justify='left', wraplength=560).pack(fill='x', pady=3)
        ctk.CTkLabel(pad, textvariable=self.message, text_color=MUTED,
                     anchor='w', justify='left', wraplength=560).pack(fill='x')

    def _change(self, settings):
        previous = self.settings
        self.settings = settings
        error = self._on_change(settings) if self._on_change is not None else None
        if isinstance(error, str) and error:
            self.settings = previous
            self.message.set(error)
            if self.player_menu is not None:
                self._show_selected_player()
                self.gestures_enabled.set(self.settings.media_gestures_enabled)
            else:
                for source, menu in self.binding_menus.items():
                    menu.set(ACTION_LABELS[self.settings.control_bindings.get(self.settings.profile, {}).get(source, 'default')])
            return
        self.settings = settings
        self.message.set('Niezapisane zmiany — użyj „Zapisz”, aby utrwalić.')

    def _choose_binding(self, source, label):
        mapping = {profile: dict(entries) for profile, entries in self.settings.control_bindings.items()}
        entries = mapping.setdefault(self.settings.profile, {})
        action = _ACTION_VALUES[label]
        if action == 'default':
            entries.pop(source, None)
            if not entries:
                mapping.pop(self.settings.profile)
        else:
            entries[source] = action
        self.binding_menus[source].set(label)
        self._change(replace(self.settings, control_bindings=mapping))

    def _choose_player(self, label):
        self._change(replace(self.settings, media_player=self._player_values[label]))
        self._show_selected_player()

    def _show_selected_player(self):
        player = self.settings.media_player
        manual = player is not None
        self.gesture_toggle.configure(state='disabled' if manual else 'normal')
        self.gesture_policy.set(
            'Wybór ręczny blokuje zmianę gestem. Wybierz „Automatycznie”, aby używać potrząśnięcia.'
            if manual else 'Gest zmiany odtwarzacza działa tylko w trybie „Automatycznie”.')
        for label, identifier in self._player_values.items():
            if identifier == player:
                self.player_menu.set(label)
                return
        label = f'{player} (niedostępny)'
        self._player_values[label] = player
        self.player_menu.configure(values=list(self._player_values))
        self.player_menu.set(label)

    def refresh_players(self):
        """Observation only: keep an unavailable pin and never call on_change."""
        try:
            players = self._list_players() if self._list_players is not None else []
        except Exception as exc:
            players = []
            self.message.set(f'Lista odtwarzaczy niedostępna: {exc}')
        values = {_AUTO: None}
        for identifier, name in players:
            label = name if name not in values else f'{name} [{identifier}]'
            values[label] = identifier
        self._player_values = values
        self.player_menu.configure(values=list(values))
        self._show_selected_player()

    def collect(self, settings: GuiSettings) -> GuiSettings:
        """Overlay only this editor's profile onto another settings draft."""
        if self.settings.profile == 'media':
            return replace(settings, media_player=self.settings.media_player,
                           media_gestures_enabled=self.settings.media_gestures_enabled)
        mapping = {profile: dict(entries) for profile, entries in settings.control_bindings.items()}
        entries = dict(self.settings.control_bindings.get(self.settings.profile, {}))
        if entries:
            mapping[self.settings.profile] = entries
        else:
            mapping.pop(self.settings.profile, None)
        return replace(settings, control_bindings=mapping)
