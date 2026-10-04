"""Official neon low-poly controller emblem (window, tray, shortcuts)."""
from __future__ import annotations

import sys
from pathlib import Path

_ASSET = "app_icon"
_FILES = {
    "png": "triki-controller.png",
    "ico": "triki-controller.ico",
    "icns": "triki-controller.icns",
}


def asset_dir() -> Path:
    """Directory of the bundled emblem. Works in a checkout and a PyInstaller onedir."""
    here = Path(__file__).resolve().parent / "assets" / _ASSET
    if any((here / name).is_file() for name in _FILES.values()):
        return here
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "triki_controller" / "gui" / "assets" / _ASSET
        if bundled.is_dir():
            return bundled
    return here


def icon_file(kind: str = "png") -> Path | None:
    """Return the PNG (Linux/.desktop/Tk), ICO (Windows), or ICNS (macOS) path."""
    name = _FILES.get(kind)
    if name is None:
        raise ValueError(f"Unknown icon kind {kind!r}")
    path = asset_dir() / name
    return path if path.is_file() else None


def apply_window_icon(root: object) -> None:
    """Set the Tk window icon. Keeps a Python reference so Tk does not drop it."""
    import tkinter as tk

    images: list[tk.PhotoImage] = []
    png = icon_file("png")
    if png is not None:
        try:
            image = tk.PhotoImage(file=str(png))
            images.append(image)
            iconphoto = getattr(root, "iconphoto", None)
            if iconphoto is not None:
                iconphoto(True, image)
        except tk.TclError:
            images.clear()
    setattr(root, "_triki_iconphoto", tuple(images))
    if sys.platform.startswith("win"):
        ico = icon_file("ico")
        iconbitmap = getattr(root, "iconbitmap", None)
        if ico is not None and iconbitmap is not None:
            try:
                iconbitmap(default=str(ico))
            except tk.TclError:
                return
