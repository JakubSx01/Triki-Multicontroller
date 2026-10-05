"""Additive, profile-scoped controls shared by the shell and configurator."""
from __future__ import annotations

from dataclasses import replace
import sys
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from triki_controller.gui.settings import GuiSettings
from triki_controller.gui.shell_icons import icon
from triki_controller.gui.shell_presentation import SURFACE, TEXT, MUTED, ACCENT, BORDER, ICON_COLOR
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


def _reveal_focus(widget) -> None:
    """Keep keyboard traversal inside a scrollable options area visible."""
    ancestor = widget.master
    while ancestor is not None:
        if isinstance(ancestor, ctk.CTkScrollableFrame):
            canvas = ancestor._parent_canvas
            canvas.update_idletasks()
            region = canvas.bbox('all')
            if region:
                top = widget.winfo_rooty() - canvas.winfo_rooty() + canvas.canvasy(0)
                bottom = top + widget.winfo_height()
                visible_top = canvas.canvasy(0)
                visible_bottom = visible_top + canvas.winfo_height()
                if top < visible_top or bottom > visible_bottom:
                    target = top if top < visible_top else bottom - canvas.winfo_height()
                    canvas.yview_moveto(max(0, target) / max(1, region[3]))
            break
        ancestor = ancestor.master


def _focusable(widget, activate: Callable[[], object]) -> None:
    widget.tk.call(widget._w, 'configure', '-takefocus', 1)
    original_border = widget.cget('border_color')
    for sequence, color in (('<FocusIn>', TEXT), ('<FocusOut>', original_border)):
        def callback(_event, c=color, focus=sequence == '<FocusIn>'):
            widget.configure(border_color=c)
            if focus:
                _reveal_focus(widget)
        tk.Misc.bind(widget, sequence, callback)
        widget.bind(sequence, callback)
    for sequence in ('<Return>', '<space>'):
        def invoke(_event, callback=activate):
            callback()
            return 'break'
        tk.Misc.bind(widget, sequence, invoke)
        widget.bind(sequence, invoke)


def _keyboard_menu(menu, choose: Callable[[str], object]) -> None:
    menu.tk.call(menu._w, 'configure', '-takefocus', 1,
                 '-highlightthickness', 2, '-highlightbackground', SURFACE,
                 '-highlightcolor', ICON_COLOR)
    tk.Misc.bind(menu, '<FocusIn>', lambda _event: _reveal_focus(menu))
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
                 on_player_select: Callable[[str | None], str | None] | None = None,
                 list_players: Callable[[], list[tuple[str, str]]] | None = None,
                 favorite_descriptor: Callable[[str], dict[str, str]] | None = None,
                 favorite_descriptors: Callable[[list[str]], dict[str, dict[str, str]]] | None = None,
                 active_favorite: Callable[[], dict[str, str] | None] | None = None):
        super().__init__(parent, fg_color=SURFACE, corner_radius=8,
                         border_width=1, border_color=BORDER)
        self.settings = settings
        self._on_change = on_change
        self._on_player_select = on_player_select
        self._list_players = list_players
        self._favorite_descriptor = favorite_descriptor
        self._favorite_descriptors = favorite_descriptors
        self._active_favorite = active_favorite
        self._player_descriptors: dict[str, dict[str, str]] = {}
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
            self.session_target = tk.StringVar(self)
            self._label(pad, text='', textvariable=self.session_target,
                        anchor='w', justify='left', wraplength=480).pack(fill='x', pady=3)
            self._label(pad, 'Odtwarzacz (wybór ręczny)', anchor='w').pack(anchor='w')
            row = ctk.CTkFrame(pad, fg_color='transparent')
            row.pack(fill='x', pady=3)
            self.player_menu = self._menu(row, [_AUTO], self._choose_player)
            self.player_menu.pack(side='left', fill='x', expand=True)
            self.refresh_button = ctk.CTkButton(row, text='Odśwież', width=90,
                                              command=self.refresh_players, fg_color=ACCENT)
            self.refresh_button.pack(side='left', padx=(6, 0))
            _focusable(self.refresh_button, self.refresh_button.invoke)
            favorite_row = ctk.CTkFrame(pad, fg_color='transparent')
            favorite_row.pack(fill='x', pady=(8, 4))
            self.favorite_button = ctk.CTkButton(
                favorite_row, text='Ustaw ulubiony', image=icon('star', 20, ICON_COLOR),
                command=self._toggle_favorite, height=36, width=168,
                fg_color=SURFACE, hover_color='#283A51', text_color=TEXT,
                border_width=2, border_color=BORDER)
            self.favorite_button.pack(side='left')
            _focusable(self.favorite_button, self.favorite_button.invoke)
            self.clear_favorite_button = ctk.CTkButton(
                favorite_row, text='Usuń ulubiony', command=self._clear_favorite,
                height=36, width=136, fg_color=SURFACE, hover_color='#283A51',
                text_color=TEXT, border_width=2, border_color=BORDER)
            self.clear_favorite_button.pack(side='left', padx=(8, 0))
            _focusable(self.clear_favorite_button, self.clear_favorite_button.invoke)
            self.favorite_status = tk.StringVar(self)
            self._label(pad, text='', textvariable=self.favorite_status, text_color=MUTED,
                        anchor='w', justify='left', wraplength=480).pack(fill='x', pady=(0, 4))
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
        player = self._player_values[label]
        if self._on_player_select is None:
            self._change(replace(self.settings, media_player=player))
        else:
            # Only an explicit menu action overrides the startup favorite.
            # Do not route this through draft apply (which preserves equal pins).
            error = self._on_player_select(player)
            if isinstance(error, str) and error:
                self.message.set(error)
            else:
                changed = player != self.settings.media_player
                self.settings = replace(self.settings, media_player=player)
                self.message.set('Niezapisane zmiany — użyj „Zapisz”, aby utrwalić.'
                                 if changed else 'Wybrano odtwarzacz w bieżącej sesji.')
        self._show_selected_player()

    def _show_selected_player(self):
        player = self.settings.media_player
        self._update_favorite_view()
        favorite = self._active_favorite() if self._active_favorite is not None else None
        manual = player is not None
        self.gestures_enabled.set(self.settings.media_gestures_enabled)
        self.gesture_toggle.configure(state='disabled' if favorite or manual else 'normal')
        if favorite:
            self.session_target.set(f"Cel sesji: ulubiony {favorite['label']} (priorytet startowy)")
            self.gesture_policy.set(
                'Ulubiony na start blokuje zmianę gestem. Wybierz „Automatycznie” ręcznie, '
                'aby zwolnić priorytet w tej sesji. Zapisana preferencja gestu pozostaje bez zmian.')
        elif manual:
            self.session_target.set(f'Cel sesji: wybór ręczny ({player})')
            self.gesture_policy.set(
                'Wybór ręczny blokuje zmianę gestem. Wybierz „Automatycznie”, aby używać potrząśnięcia.')
        else:
            self.session_target.set('Cel sesji: Automatycznie')
            self.gesture_policy.set('Tryb „Automatycznie”: potrząśnięcie zależy od zapisanej preferencji gestu.')
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
        self._player_descriptors = {}
        if self._favorite_descriptors is not None:
            try:
                self._player_descriptors = self._favorite_descriptors([key for key, _ in players])
            except Exception as exc:
                self.message.set(f'Tożsamość odtwarzaczy niedostępna: {exc}')
        elif self._favorite_descriptor is not None:
            # Legacy callbacks: inspect only the selected row, never N full scans.
            player = self.settings.media_player
            if player is not None and any(key == player for key, _ in players):
                try:
                    self._player_descriptors[player] = self._favorite_descriptor(player)
                except ValueError:
                    pass
        self.player_menu.configure(values=list(values))
        self._show_selected_player()

    @staticmethod
    def _same_favorite(first, second) -> bool:
        return bool(first and second and
                    first['platform'] == second['platform'] and first['app_id'] == second['app_id'])

    def _update_favorite_view(self) -> None:
        favorite = self.settings.media_favorite
        player = self.settings.media_player
        descriptor = self._player_descriptors.get(player) if player is not None else None
        selected = self._same_favorite(favorite, descriptor)
        self.favorite_button.configure(
            text='Ulubiony' if selected else 'Ustaw ulubiony',
            fg_color=ACCENT if selected else SURFACE,
            image=icon('star', 20, TEXT if selected else ICON_COLOR),
            state='normal' if player is not None and self._favorite_descriptor is not None else 'disabled')
        self.clear_favorite_button.configure(state='normal' if favorite else 'disabled')
        if favorite:
            available = any(self._same_favorite(favorite, descriptor)
                            for descriptor in self._player_descriptors.values())
            state = '' if available else ' (niedostępny)'
            self.favorite_status.set(
                f"Następny start: {favorite['label']}{state}. Użyj „Zapisz”, aby zapamiętać na następne uruchomienie.")
        else:
            self.favorite_status.set(
                'Brak ulubionego na start. Wybierz odtwarzacz, zaznacz gwiazdkę i użyj „Zapisz”. '
                'Trybu „Automatycznie” nie można oznaczyć jako ulubiony.')

    def _toggle_favorite(self) -> None:
        player = self.settings.media_player
        if player is None or self._favorite_descriptor is None:
            return
        try:
            descriptor = self._favorite_descriptor(player)
        except ValueError as exc:
            self.message.set(f'Nie można ustawić ulubionego: {exc}')
            return
        self._player_descriptors[player] = descriptor
        favorite = None if self._same_favorite(self.settings.media_favorite, descriptor) else descriptor
        self._change(replace(self.settings, media_favorite=favorite))
        self._update_favorite_view()

    def _clear_favorite(self) -> None:
        if self.settings.media_favorite is not None:
            self._change(replace(self.settings, media_favorite=None))
            self._update_favorite_view()

    def collect(self, settings: GuiSettings) -> GuiSettings:
        """Overlay only this editor's profile onto another settings draft."""
        if self.settings.profile == 'media':
            return replace(settings, media_player=self.settings.media_player,
                           media_favorite=self.settings.media_favorite,
                           media_gestures_enabled=self.settings.media_gestures_enabled)
        mapping = {profile: dict(entries) for profile, entries in settings.control_bindings.items()}
        entries = dict(self.settings.control_bindings.get(self.settings.profile, {}))
        if entries:
            mapping[self.settings.profile] = entries
        else:
            mapping.pop(self.settings.profile, None)
        return replace(settings, control_bindings=mapping)
