"""Shell-only Phosphor icon font rendering; no global Tk font/theme changes."""

from functools import lru_cache
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).parent / "assets" / "phosphor" / "Phosphor.ttf"
GLYPHS = {
    "steering": 0xE9AC,
    "mouse": 0xE33A,
    "plane": 0xE002,
    "media": 0xE340,
    "config": 0xE434,
    "shortcuts": 0xE5DE,
    "bluetooth": 0xE0DA,
    "retry": 0xE036,
    "stop": 0xE46C,
    "disconnect": 0xE946,
    "menu": 0xE2C2,
    "close": 0xE4F6,
    "launch": 0xE06C,
    "star": 0xE46A,
    "save": 0xE248,
}


@lru_cache(maxsize=64)
def render_icon(name: str, size: int = 24, color: str = "#202735") -> Image.Image:
    """Rasterize the bundled outline font at 3× for crisp scaled CTk images."""
    glyph = chr(GLYPHS[name])
    pixels = size * 3
    font = ImageFont.truetype(str(FONT_PATH), pixels)
    image = Image.new("RGBA", (pixels, pixels))
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), glyph, font=font)
    draw.text(((pixels - right - left) / 2, (pixels - bottom - top) / 2),
              glyph, font=font, fill=color)
    return image


def icon(name: str, size: int = 24, color: str = "#202735") -> ctk.CTkImage:
    image = render_icon(name, size, color)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
