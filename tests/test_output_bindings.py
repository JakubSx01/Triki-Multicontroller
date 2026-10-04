"""Offline public output seams; no native events or hardware."""
import pytest
from triki_controller.core.models import MappedState
from triki_controller.output.windows_backend import WindowsOutputBackend
from triki_controller.output.macos_backend import MacOSOutputBackend

class Input:
    def __init__(self):
        self.events = []
        self.fail_release = False
    def open(self): pass
    def close(self): pass
    def relative(self, *args): pass
    def move(self, *args): pass
    def button(self, name, down): self.key(name, down)
    def key(self, name, down):
        if not down and self.fail_release: raise RuntimeError('release failed')
        self.events.append((name, down))

class Audio:
    def leave(self): pass

def state(keys=(), buttons=(), pulses=(), axes=None):
    return MappedState(1, 'test', 1, 1, 'test', '1', 1, buttons, keys, axes or {}, {}, pulses=pulses)

@pytest.fixture(params=[WindowsOutputBackend, MacOSOutputBackend])
def backend(request):
    inp = Input()
    if request.param is WindowsOutputBackend:
        obj = request.param(audio=Audio(), input_adapter=inp)
    else:
        obj = request.param(player=Audio(), system=Audio(), input_adapter=inp)
    return obj, inp

def test_keys_repeat_release_and_middle_mouse(backend):
    obj, inp = backend
    obj.open({'mode': 'mouse', 'claim_native': True})
    assert obj.apply(state(keys=('key_a',), buttons=('mouse_middle',))).applied
    assert obj.apply(state(keys=('key_a',), buttons=('mouse_middle',))).applied
    assert inp.events == [('key_a', True), ('mouse_middle', True)]
    assert obj.neutralize('Stop').applied
    assert inp.events[-2:] == [('key_a', False), ('mouse_middle', False)]

def test_click_failure_retains_release_for_stop_retry(backend):
    obj, inp = backend
    obj.open({'mode': 'mouse', 'claim_native': True})
    inp.fail_release = True
    assert not obj.apply(state(pulses=('key_space',))).applied
    assert not obj.neutralize('Stop').applied
    inp.fail_release = False
    assert obj.neutralize('Stop again').applied
    assert inp.events == [('key_space', True), ('key_space', False)]

def test_close_failure_disables_dispatch_and_retries_release(backend):
    obj, inp = backend
    obj.open({'mode': 'mouse', 'claim_native': True})
    assert obj.apply(state(keys=('key_ctrl',))).applied
    inp.fail_release = True
    with pytest.raises(RuntimeError): obj.close()
    with pytest.raises(RuntimeError): obj.apply(state())
    inp.fail_release = False
    obj.close()
    assert inp.events == [('key_ctrl', True), ('key_ctrl', False)]

@pytest.mark.parametrize('mode', ['steering', 'plane'])
def test_binding_only_requires_explicit_flag_and_configured_action(backend, mode):
    obj, inp = backend
    with pytest.raises(RuntimeError): obj.open({'mode': mode, 'claim_native': True})
    with pytest.raises(RuntimeError): obj.open({'mode': mode, 'binding_only': True, 'claim_native': True})
    obj.open({'mode': mode, 'binding_only': True, 'control_bindings': {'button': 'key_a'}, 'claim_native': True})
    assert obj.apply(state(keys=('key_a',), axes={'wheel': .5, 'stick_x': .4})).applied
    assert inp.events == [('key_a', True)]

class EvdevCodes:
    def __getattr__(self, name): return name

class VirtualInput:
    def __init__(self, **kwargs):
        self.events = []
        self.capabilities = kwargs['events']
        self.fail_release = False
        self.device = self
    def write(self, kind, code, value):
        if kind == 'EV_KEY' and value == 0 and self.fail_release:
            raise RuntimeError('release failed')
        self.events.append((kind, code, value))
    def syn(self): pass
    def close(self): pass

@pytest.mark.parametrize('mode', ['mouse', 'media', 'steering', 'plane'])
def test_linux_binding_capabilities_and_stop_retry(monkeypatch, mode):
    from triki_controller.output import uinput_backend as module
    monkeypatch.setattr(module, '_load_evdev', lambda: (EvdevCodes(), VirtualInput, lambda *a: a))
    monkeypatch.setattr(module, 'AbsoluteCursor', lambda: type('Cursor', (), {'open': lambda s: 'inert', 'close': lambda s: None})())
    obj = module.UInputBackend()
    obj.open({'mode': mode, 'claim_uinput': True})
    dev = obj.device
    assert 'KEY_A' in dev.capabilities['EV_KEY']
    assert 'BTN_MIDDLE' in dev.capabilities['EV_KEY']
    assert obj.apply(state(keys=('key_a',), buttons=('mouse_middle',))).applied
    assert obj.apply(state(keys=('key_a',), buttons=('mouse_middle',))).applied
    assert [e for e in dev.events if e[0] == 'EV_KEY'] == [('EV_KEY', 'KEY_A', 1), ('EV_KEY', 'BTN_MIDDLE', 1)]
    dev.fail_release = True
    assert not obj.neutralize('Stop').applied
    dev.fail_release = False
    assert obj.neutralize('retry').applied
    assert [e for e in dev.events if e[0] == 'EV_KEY'][-2:] == [('EV_KEY', 'KEY_A', 0), ('EV_KEY', 'BTN_MIDDLE', 0)]


def test_windows_sendinput_key_and_middle_events_remain_releaseable():
    from triki_controller.output.windows_input import WindowsInput
    events = []
    fail = [False]
    def send(items):
        if fail[0]: return 0
        item = items[0]
        events.append((item.type, item.ki.wVk, item.ki.dwFlags) if item.type == 1 else (item.type, item.mi.dwFlags))
        return 1
    adapter = WindowsInput(send_input=send)
    adapter.key('key_up', True)
    adapter.button('mouse_middle', True)
    fail[0] = True
    with pytest.raises(RuntimeError): adapter.neutralize()
    fail[0] = False
    adapter.neutralize()
    assert events == [(1, 0x26, 1), (0, 32), (1, 0x26, 3), (0, 64)]
    adapter.close()


def test_quartz_keys_middle_accessibility_and_cleanup_ownership():
    from types import SimpleNamespace
    from triki_controller.output.macos_input import QuartzMouseInput
    class Quartz:
        allowed = True
        events = []
        kCGHIDEventTap = 'tap'
        kCGMouseButtonCenter = 'middle'
        kCGEventOtherMouseDown = 'down'
        kCGEventOtherMouseUp = 'up'
        def CGPreflightPostEventAccess(self): return self.allowed
        def CGEventCreateKeyboardEvent(self, source, code, down): return ('key', code, down)
        def CGEventCreate(self, source): return object()
        def CGEventGetLocation(self, event): return SimpleNamespace(x=1, y=2)
        def CGEventCreateMouseEvent(self, source, kind, point, button): return (kind, button)
        def CGEventPost(self, tap, event): self.events.append(event)
    quartz = Quartz()
    adapter = QuartzMouseInput(quartz=quartz)
    adapter.open()
    adapter.key('key_a', True)
    adapter.button('mouse_middle', True)
    quartz.allowed = False
    with pytest.raises(RuntimeError): adapter.key('key_a', False)
    with pytest.raises(RuntimeError): adapter.close()
    quartz.allowed = True
    adapter.key('key_a', False)
    adapter.button('mouse_middle', False)
    adapter.close()
    assert quartz.events == [('key', 0, True), ('down', 'middle'), ('key', 0, False), ('up', 'middle')]
