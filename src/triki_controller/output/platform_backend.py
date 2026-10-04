"""Select the host's live output, without importing other OS adapters.

Source and frozen entry points share this factory; dry-run callers keep using
TraceOutput directly. Native adapters validate supported modes in open().
"""

from __future__ import annotations

import sys

from triki_controller.output.base import OutputBackend


def create_live_output() -> OutputBackend:
    """Construct the current platform's adapter; never fall back to Linux."""
    if sys.platform.startswith("linux"):
        from triki_controller.output.uinput_backend import UInputBackend

        return UInputBackend()
    if sys.platform == "win32":
        from triki_controller.output.windows_backend import WindowsOutputBackend

        return WindowsOutputBackend()
    if sys.platform == "darwin":
        from triki_controller.output.macos_backend import MacOSOutputBackend

        return MacOSOutputBackend()
    raise RuntimeError(
        f"Live output is unsupported on platform {sys.platform!r}. "
        "Use dry-run (omit --live for emulate, or pass --dry-run for quick launch), "
        "or run on Linux, Windows, or macOS."
    )
