#!/usr/bin/env python3
"""Rasterize the official Triki emblem into PNG, ICO, and ICNS.

Canonical input (copied into the tree): 
``src/triki_controller/gui/assets/app_icon/source.jpg``

    python3 tools/render_app_icon.py
    python3 tools/render_app_icon.py --source /path/to/emblem.jpg
"""
from __future__ import annotations

import argparse
import io
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "triki_controller" / "gui" / "assets" / "app_icon"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# PNG-in-ICNS types understood by macOS 10.7+.
ICNS_TYPES = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"icp6", 64),
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic13", 256),
    (b"ic14", 512),
)


def _square(source: Image.Image) -> Image.Image:
    image = source.convert("RGBA")
    if image.width == image.height:
        return image
    side = max(image.width, image.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 255))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def _png_bytes(master: Image.Image, size: int) -> bytes:
    resized = master.resize((size, size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


def write_icns(path: Path, master: Image.Image) -> None:
    """Write an ICNS container. ImageMagick on this host has no ICNS encoder."""
    chunks: list[bytes] = []
    for ostype, size in ICNS_TYPES:
        payload = _png_bytes(master, size)
        chunks.append(ostype + struct.pack(">I", 8 + len(payload)) + payload)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def render(source: Path, out: Path = OUT) -> list[Path]:
    master = _square(Image.open(source))
    if master.width != 1024:
        master = master.resize((1024, 1024), Image.Resampling.LANCZOS)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for size in PNG_SIZES:
        path = out / (f"triki-controller-{size}.png" if size != 512 else "triki-controller.png")
        path.write_bytes(_png_bytes(master, size))
        written.append(path)
    ico = out / "triki-controller.ico"
    images = [master.resize((size, size), Image.Resampling.LANCZOS) for size in ICO_SIZES]
    images[-1].save(ico, format="ICO", sizes=[(size, size) for size in ICO_SIZES], append_images=images[:-1])
    written.append(ico)
    icns = out / "triki-controller.icns"
    try:
        master.save(icns, format="ICNS")
    except (KeyError, OSError, ValueError):
        write_icns(icns, master)
    written.append(icns)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=OUT / "source.jpg")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error(f"Missing source image: {args.source}")
    for path in render(args.source, args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
