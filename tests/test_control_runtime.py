"""Control options through runtime/session boundaries; all outputs are inert."""
from triki_controller.profiles.builtin import profile_by_name
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.output.trace import TraceOutput


class PlayerOutput(TraceOutput):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.selected = None
        self._mpris = self

    def open(self, capabilities):
        self.calls.append(('open', dict(capabilities)))
        self.selected = capabilities.get('media_player')
        super().open({**capabilities, 'claim_uinput': False})
        self._mpris = self

    def select_media_player(self, player):
        self.calls.append(('select', player))
        self.selected = player

    def list_media_players(self):
        self.calls.append(('list',))
        return [('a', 'Pierwszy'), ('b', 'Drugi')]

    def read_volume(self):
        self.calls.append(('read', self.selected))
        return .23 if self.selected == 'b' else .8


def test_initial_pin_is_opened_before_reading_actual_baseline():
    output = PlayerOutput()
    runtime = EmulatorRuntime(profile_by_name('media'), output)
    runtime.select_media_player('b')
    runtime.recenter()
    output.calls.clear()
    runtime.activate(live=True)
    assert output.calls[0][0] == 'open'
    assert output.calls[0][1]['media_player'] == 'b'
    assert output.calls[1] == ('read', 'b')
    runtime.deactivate('done')


def test_live_binding_change_releases_old_input_and_rearms_before_reopen():
    output = PlayerOutput()
    runtime = EmulatorRuntime(profile_by_name('mouse'), output)
    runtime.activate(live=True)
    output.held_buttons.add('key_a')
    runtime.set_control_bindings({'mouse': {'button': 'key_b'}})
    assert output.held_buttons == set()
    assert runtime.active and runtime.live
    assert not runtime._armed
    assert output.calls[-1][0] == 'open'


def test_player_enumeration_is_observational_and_selection_reseeds_only_once():
    output = PlayerOutput()
    runtime = EmulatorRuntime(profile_by_name('media'), output)
    runtime.recenter()
    runtime.activate(live=True)
    runtime.select_media_player('b')
    assert output.calls[-2:] == [('select', 'b'), ('read', 'b')]
    output.calls.clear()
    assert runtime.list_media_players() == [('a', 'Pierwszy'), ('b', 'Drugi')]
    assert output.calls == [('list',)]
    runtime.select_media_player('b')
    assert output.calls == [('list',)]
    runtime.deactivate('done')


def test_session_preserves_options_across_profile_and_threshold_updates():
    from dataclasses import replace
    from triki_controller.gui.session import ControllerSession
    from triki_controller.gui.settings import GuiSettings
    settings = GuiSettings(profile='mouse', media_player='b', media_gestures_enabled=False,
                           control_bindings={'mouse': {'button': 'key_space'}, 'plane': {'left': 'key_a'}})
    session = ControllerSession(settings=settings, output_factory=lambda live: PlayerOutput())
    assert session.current_settings().control_bindings == settings.control_bindings
    assert session.current_settings().media_player == 'b'
    assert not session.current_settings().media_gestures_enabled
    assert session.set_profile('plane') is None
    assert session.set_threshold('deadzone_deg', 7) is None
    draft = replace(session.current_settings(), profile='mouse', media_player='a')
    assert session.apply_settings(draft) is None
    assert session.current_settings() == draft
    assert session.list_media_players() == [('a', 'Pierwszy'), ('b', 'Drugi')]
    assert session.select_media_player('missing') is None
    assert session.current_settings().media_player == 'missing'
    session.shutdown()


def test_offline_player_catalog_is_read_only_and_does_not_open_input():
    from triki_controller.gui.session import ControllerSession
    outputs = []
    def factory(live):
        output = PlayerOutput() if live else TraceOutput()
        outputs.append(output)
        return output
    session = ControllerSession(output_factory=factory)
    assert session.list_media_players() == [('a', 'Pierwszy'), ('b', 'Drugi')]
    assert len(outputs) == 2
    assert not any(output.opened for output in outputs)
    assert session.list_media_players() == [('a', 'Pierwszy'), ('b', 'Drugi')]
    assert len(outputs) == 2
    session.shutdown()


class InputAdapter:
    def __init__(self):
        self.events = []
        self.held = set()

    def open(self):
        pass

    def key(self, name, down):
        self.events.append((name, down))
        if down:
            self.held.add(name)
        else:
            self.held.discard(name)

    button = key

    def move(self, *args):
        pass

    relative = move
    absolute = move
    transport = move

    def neutralize(self):
        self.held.clear()

    def close(self):
        pass


def native_output(platform):
    from tests.test_native_media_baseline import AudioAdapter
    from triki_controller.output.windows_audio import WindowsAudio
    from triki_controller.output.windows_backend import WindowsOutputBackend
    from triki_controller.output.macos_backend import MacOSOutputBackend
    audio = AudioAdapter()
    inputs = InputAdapter()
    if platform == 'windows':
        output = WindowsOutputBackend(audio=WindowsAudio(adapter=audio, scan_interval=0, write_interval=0), input_adapter=inputs)
    else:
        output = MacOSOutputBackend(audio=audio, input_adapter=inputs)
    return output, audio, inputs


import pytest


@pytest.mark.parametrize('platform', ['windows', 'macos'])
@pytest.mark.parametrize('profile', ['mouse', 'steering', 'plane'])
@pytest.mark.parametrize('ending', ['stop', 'disconnect', 'edit'])
def test_real_runtime_mapped_holds_release_at_native_output_boundary(platform, profile, ending):
    from triki_controller.runtime.synthetic import make_raw, pose_level
    from triki_controller.core.models import ConnectionEvent, ConnectionState, SCHEMA_VERSION
    output, _audio, inputs = native_output(platform)
    runtime = EmulatorRuntime(profile_by_name(profile), output,
                              control_bindings={profile: {'button': 'key_a'}})
    runtime.activate(live=True)
    for seq in range(1, 14):
        step = runtime.feed(make_raw(accel=pose_level(), seq=seq, t_ns=seq * 20_000_000, button=seq >= 12))
        assert step.receipt.applied, step.receipt.detail
    assert step.mapped.held_keys == ('key_a',)
    assert inputs.held == {'key_a'}
    if ending == 'edit':
        runtime.set_control_bindings({profile: {'button': 'key_b'}})
    elif ending == 'stop':
        runtime.deactivate('Stop', keep_origin=True)
    else:
        runtime.handle_connection(ConnectionEvent(SCHEMA_VERSION, 'test', 1, 1, 1,
                                                  ConnectionState.DISCONNECTED, 'test disconnect'))
    assert inputs.held == set()
    assert ('key_a', False) in inputs.events
    if ending == 'edit':
        step = runtime.feed(make_raw(accel=pose_level(), seq=14, t_ns=280_000_000, button=True))
        assert step.mapped.held_keys == ()
        assert inputs.held == set()
        runtime.deactivate('done')


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_pinned_native_player_changes_real_adapter_without_volume_jump(platform):
    from triki_controller.runtime.synthetic import make_raw, pose_level
    output, audio, _inputs = native_output(platform)
    identifiers = {name: identifier for identifier, name in output.list_media_players()}
    runtime = EmulatorRuntime(profile_by_name('media'), output, media_player=identifiers['b'])
    runtime.activate(live=True)
    for seq in range(1, 15):
        step = runtime.feed(make_raw(accel=pose_level(), seq=seq, t_ns=seq * 20_000_000))
        assert step.receipt.applied, step.receipt.detail
    assert step.mapped.absolute_axes['player_volume'] == pytest.approx(.23)
    assert audio.players == {'a': .9, 'b': .23}
    assert runtime.list_media_players()
    runtime.select_media_player(identifiers['a'])
    for seq in range(15, 18):
        step = runtime.feed(make_raw(accel=pose_level(), seq=seq, t_ns=seq * 20_000_000))
        assert step.receipt.applied, step.receipt.detail
    assert step.mapped.absolute_axes['player_volume'] == pytest.approx(.9)
    assert audio.players == {'a': .9, 'b': .23}
    runtime.deactivate('done')


@pytest.mark.parametrize('enabled', [True, False])
def test_session_gesture_setting_changes_actual_runtime_shake_behavior(enabled):
    from triki_controller.gui.session import ControllerSession
    from triki_controller.gui.settings import GuiSettings
    from triki_controller.runtime.synthetic import make_raw, pose_level
    from tests.test_gui_desktop import _streaming
    session = ControllerSession(settings=GuiSettings(profile='media', media_gestures_enabled=enabled))
    _streaming(session)
    for seq in range(1, 15):
        session._on_sample(session._conn_id, make_raw(accel=pose_level(), seq=seq, t_ns=seq * 20_000_000))
    pulses = []
    for seq in range(15, 24):
        sample = make_raw(accel=pose_level(), gyro=(32767, 0, 0), seq=seq, t_ns=seq * 20_000_000)
        session._on_sample(session._conn_id, sample)
        pulses.extend(session.snapshot().mapped.pulses)
    assert ('cycle_player' in pulses) is enabled
    session.shutdown()


@pytest.mark.parametrize('platform', ['windows', 'macos'])
def test_apply_settings_can_leave_native_binding_only_profile_without_reopening_old_mode(platform):
    from dataclasses import replace
    from triki_controller.gui.session import ControllerSession
    from triki_controller.gui.settings import GuiSettings
    from tests.test_gui_desktop import _streaming
    output, _audio, _inputs = native_output(platform)
    session = ControllerSession(settings=GuiSettings(profile='steering', control_bindings={'steering': {'button': 'key_a'}}),
                                output_factory=lambda live: output if live else TraceOutput())
    _streaming(session)
    assert session.start_output(live=True) is None
    settings = replace(session.current_settings(), profile='mouse', control_bindings={'mouse': {'button': 'key_b'}})
    assert session.apply_settings(settings) is None
    assert session.snapshot().profile_name == 'mouse'
    assert session.snapshot().output_mode.value == 'live'
    session.shutdown()


def test_dry_run_player_selection_is_saved_without_touching_live_catalog():
    from triki_controller.gui.session import ControllerSession
    from tests.test_gui_desktop import _streaming
    session = ControllerSession()
    _streaming(session)
    assert session.start_output(live=False) is None
    assert session.select_media_player('b') is None
    assert session.current_settings().media_player == 'b'
    session.shutdown()


def test_runtime_copies_binding_settings_before_caller_mutates_them():
    mapping = {'mouse': {'button': 'key_a'}}
    runtime = EmulatorRuntime(profile_by_name('mouse'), TraceOutput(), control_bindings=mapping)
    mapping['mouse']['button'] = 'key_b'
    assert runtime.control_bindings == {'mouse': {'button': 'key_a'}}


def test_inactive_profile_binding_edit_also_releases_holds_before_mapper_reset():
    output = PlayerOutput()
    runtime = EmulatorRuntime(profile_by_name('mouse'), output)
    runtime.activate(live=True)
    output.held_buttons.add('mouse_left')
    runtime.set_control_bindings({'plane': {'button': 'key_b'}})
    assert output.held_buttons == set()
    assert runtime.active
    assert not runtime._armed
    runtime.deactivate('done')


def test_catalog_cleanup_failure_does_not_prevent_session_shutdown():
    from triki_controller.gui.session import ControllerSession
    class FailingCatalog(PlayerOutput):
        def close(self):
            raise RuntimeError('catalog close denied')
    session = ControllerSession(output_factory=lambda live: FailingCatalog() if live else TraceOutput())
    session.list_media_players()
    loop = session._ensure_loop()
    session.shutdown()
    assert not loop.is_running()
    assert 'catalog close denied' in session.snapshot().error
