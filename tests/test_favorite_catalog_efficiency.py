"""Observational catalogue efficiency/safety at public adapter/session/UI seams."""
import json
import subprocess
import threading
import time

import pytest

from triki_controller.gui.session import ControllerSession
from triki_controller.output.mpris_volume import MprisPlayerVolume


class CatalogBus:
    def __init__(self, count=30):
        self.owners = {f'player{i}': f':1.{i + 1}' for i in range(count)}
        self.entries = {owner: f'app{i}.desktop' for i, owner in enumerate(self.owners.values())}
        self.calls = []
        self.after_metadata = None

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if argv[-1] == '-l':
            text = '\n'.join(self.owners)
        elif 'GetNameOwner' in argv:
            name = argv[-1].removeprefix('org.mpris.MediaPlayer2.')
            text = 's ' + json.dumps(self.owners[name])
        else:
            assert argv[2] == 'get-property' and argv[-1] == 'DesktopEntry'
            assert argv[3].startswith(':'), 'Metadata must address captured unique owner'
            text = 's ' + json.dumps(self.entries[argv[3]])
            if self.after_metadata:
                callback, self.after_metadata = self.after_metadata, None
                callback()
        return subprocess.CompletedProcess(argv, 0, text, '')


def test_thirty_players_one_scan_linear_metadata_and_owner_validation(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: name)
    bus = CatalogBus()
    audio = MprisPlayerVolume(run=bus, playerctl_path='playerctl')
    players = audio.list_media_players()
    descriptors = audio.favorite_media_descriptors([key for key, _ in players])
    assert len(descriptors) == 30
    assert descriptors['player0'] == {'platform': 'mpris', 'app_id': 'app0.desktop', 'label': 'player0'}
    assert sum(c[-1] == '-l' for c in bus.calls) == 1
    assert sum('get-property' in c for c in bus.calls) == 30
    assert sum('GetNameOwner' in c for c in bus.calls) == 60
    assert len(bus.calls) == 91


@pytest.mark.parametrize('operation', ['list', 'single', 'batch'])
@pytest.mark.parametrize('separate_catalog', [False, True])
def test_slow_observation_does_not_block_session_progress(operation, separate_catalog):
    from triki_controller.output.trace import TraceOutput
    entered, release, progressed = threading.Event(), threading.Event(), threading.Event()
    descriptor = {'platform': 'mpris', 'app_id': 'app.desktop', 'label': 'Player'}

    class SlowCatalog(TraceOutput):
        def pause(self):
            entered.set()
            assert release.wait(2), 'Test failed to release metadata probe'

        def list_media_players(self):
            if operation == 'list':
                self.pause()
            return [('player', 'Player')]

        def favorite_media_descriptor(self, key):
            self.pause()
            return descriptor

        def favorite_media_descriptors(self, keys=None):
            self.pause()
            return {'player': descriptor}

    catalog = SlowCatalog()
    session = ControllerSession(output_factory=lambda live: catalog if live or not separate_catalog else TraceOutput())
    results, errors = [], []

    def observe():
        try:
            result = (session.list_media_players() if operation == 'list' else
                      session.favorite_media_descriptor('player') if operation == 'single' else
                      session.favorite_media_descriptors(['player']))
            results.append(result)
        except Exception as exc:
            errors.append(exc)

    observer = threading.Thread(target=observe)
    worker = None
    observer.start()
    try:
        assert entered.wait(1), errors
        start = time.monotonic()
        def progress():
            session.current_settings()
            progressed.set()
        worker = threading.Thread(target=progress)
        worker.start()
        assert progressed.wait(.3), 'Metadata held the main session lock'
        assert time.monotonic() - start < .3
    finally:
        release.set()
        observer.join(2)
        if worker is not None:
            worker.join(2)
    assert not errors
    assert results
    if operation == 'batch':
        results[0]['player']['label'] = 'Mutated'
        assert descriptor['label'] == 'Player'


def test_picker_refresh_uses_one_batch_but_star_revalidates_fresh(monkeypatch):
    import customtkinter as ctk
    from triki_controller.gui.control_options import ControlOptions
    from triki_controller.gui.settings import GuiSettings
    from unittest.mock import Mock
    root = ctk.CTk()
    bus = CatalogBus()
    monkeypatch.setattr('shutil.which', lambda name: name)
    audio = MprisPlayerVolume(run=bus, playerctl_path='playerctl')
    single = Mock(wraps=audio.favorite_media_descriptor)
    changes = []
    try:
        options = ControlOptions(root, GuiSettings(profile='media', media_player='player0'),
                                 list_players=audio.list_media_players,
                                 favorite_descriptor=single,
                                 favorite_descriptors=audio.favorite_media_descriptors,
                                 on_change=lambda value: changes.append(value))
        assert len(bus.calls) == 91
        single.assert_not_called()
        assert changes == []
        # A duplicate starts after the observational snapshot. Star must refuse.
        bus.owners['new'] = ':1.999'
        bus.entries[':1.999'] = 'app0.desktop'
        options.favorite_button.invoke()
        single.assert_called_once_with('player0')
        assert changes == []
        assert 'ambiguous' in options.message.get()
    finally:
        for timer in root.tk.call('after', 'info'):
            root.tk.call('after', 'cancel', timer)
        root.destroy()


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_native_batch_observes_metadata_once_and_omits_ambiguity(platform):
    from triki_controller.output.windows_audio import WindowsAudio, PlayerSession
    from triki_controller.output.macos_audio import MacOSPlayerVolume
    calls = []
    class Adapter:
        def sessions(self):
            calls.append('sessions')
            return (PlayerSession('one', 'One', True, .2, False, 'same.exe'),
                    PlayerSession('two', 'Two', True, .3, False, 'same.exe'),
                    PlayerSession('three', 'Three', True, .4, False, 'unique.exe'))
        def list_players(self):
            calls.append('list')
            return ['one', 'two', 'three']
        def player_identity(self, key):
            calls.append(key)
            return ('unique.bundle' if key == 'three' else 'same.bundle', key)
    audio = WindowsAudio(adapter=Adapter()) if platform == 'windows' else MacOSPlayerVolume(adapter=Adapter())
    descriptors = audio.favorite_media_descriptors(['one', 'two', 'three'])
    assert set(descriptors) == {'three'}
    assert descriptors['three']['platform'] == platform
    assert calls == (['sessions'] if platform == 'windows' else ['one', 'two', 'three'])


def test_batch_omits_missing_ambiguous_and_replaced_owner(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: name)
    bus = CatalogBus(5)
    bus.entries[':1.1'] = bus.entries[':1.2'] = 'duplicate.desktop'
    bus.entries[':1.3'] = ''
    bus.after_metadata = lambda: bus.owners.update({'player3': ':1.999'})
    audio = MprisPlayerVolume(run=bus, playerctl_path='playerctl')
    descriptors = audio.favorite_media_descriptors()
    assert descriptors == {'player4': {'platform': 'mpris', 'app_id': 'app4.desktop', 'label': 'player4'}}
    # No owner replacement metadata or guessed aliases may qualify other apps.
    assert all(c[3] != ':1.999' for c in bus.calls if 'get-property' in c)


def test_closed_catalog_discovery_is_a_helpful_error_without_session_side_effects():
    from triki_controller.output.trace import TraceOutput
    class ClosedCatalog(TraceOutput):
        def list_media_players(self):
            raise RuntimeError('catalogue closed')
        def favorite_media_descriptors(self, keys=None):
            raise RuntimeError('catalogue closed')
    catalog = ClosedCatalog()
    session = ControllerSession(output_factory=lambda live: catalog)
    before = session.current_settings()
    with pytest.raises(ValueError, match='catalogue.*closed'):
        session.favorite_media_descriptors(['player'])
    assert session.current_settings() == before
    assert not catalog.opened


def test_session_production_mpris_catalogue_is_linear_and_observational(monkeypatch):
    from triki_controller.output.uinput_backend import UInputBackend
    monkeypatch.setattr('shutil.which', lambda name: name)
    bus = CatalogBus()
    audio = MprisPlayerVolume(run=bus, playerctl_path='playerctl')
    backend = UInputBackend(mpris=audio)
    session = ControllerSession(output_factory=lambda live: backend)
    before = dict(vars(audio))
    players = session.list_media_players()
    descriptors = session.favorite_media_descriptors([key for key, _ in players])
    assert len(descriptors) == 30
    assert len(bus.calls) == 91
    assert vars(audio) == before
    assert backend.device is None and not backend.opened


def test_legacy_picker_refresh_checks_only_selected_player():
    import customtkinter as ctk
    from unittest.mock import Mock
    from triki_controller.gui.control_options import ControlOptions
    from triki_controller.gui.settings import GuiSettings
    root = ctk.CTk()
    single = Mock(return_value={'platform': 'mpris', 'app_id': 'app0.desktop', 'label': 'Player'})
    try:
        ControlOptions(root, GuiSettings(profile='media', media_player='player0'),
                       list_players=lambda: [(f'player{i}', f'Player {i}') for i in range(30)],
                       favorite_descriptor=single)
        single.assert_called_once_with('player0')
    finally:
        for timer in root.tk.call('after', 'info'):
            root.tk.call('after', 'cancel', timer)
        root.destroy()
