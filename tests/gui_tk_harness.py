"""Controlled Tk clients, not compositor policy or simulated widget geometry."""
import time


def settle(app):
    for timer in app.root.tk.call('after', 'info'):
        app.root.tk.call('after', 'cancel', timer)
    # Native Xwayland map/focus events arrive after Tk's idle queue is empty.
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.025)
    app.root.update()


def control_size(app, size):
    app.root.overrideredirect(True)
    # Let the managed-to-unmanaged remap finish before requesting client size.
    settle(app)
    app.root.geometry(f'{size[0]}x{size[1]}')
    settle(app)
    observed = (app.root.winfo_width(), app.root.winfo_height())
    assert observed == size, f'requested {size}, observed {observed}'
