"""Portable logical input names shared by native output adapters."""
from collections.abc import Mapping

KEY_ACTIONS = frozenset('key_' + name for name in (
    *'abcdefghijklmnopqrstuvwxyz0123456789', 'up', 'down', 'left', 'right',
    'space', 'enter', 'escape', 'shift', 'ctrl', 'alt', 'tab', 'backspace'))
MOUSE_ACTIONS = frozenset({'mouse_left', 'mouse_right', 'mouse_middle'})
INPUT_ACTIONS = KEY_ACTIONS | MOUSE_ACTIONS

def has_bindings(capabilities):
    bindings = capabilities.get('control_bindings')
    return bool(isinstance(bindings, Mapping)
                and any(isinstance(action, str) and action in INPUT_ACTIONS
                        for action in bindings.values()))

def binding_only(capabilities):
    return capabilities.get('binding_only') is True and has_bindings(capabilities)

def dispatch(adapter, name, down):
    """Treat adapter error strings as failure, retaining release ownership."""
    error = (adapter.key if name in KEY_ACTIONS else adapter.button)(name, down)
    if error:
        raise RuntimeError(str(error))
