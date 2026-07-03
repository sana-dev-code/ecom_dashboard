from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont


def _linear_gradient(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        # Deep navy -> blue
        r = int(20 + (52 - 20) * t)
        g = int(35 + (120 - 35) * t)
        b = int(60 + (240 - 60) * t)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    return img


def build_icon(out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    base = _linear_gradient(512)
    d = ImageDraw.Draw(base)

    # Rounded rectangle inset
    pad = 42
    rr = [pad, pad, base.size[0] - pad, base.size[1] - pad]
    d.rounded_rectangle(rr, radius=88, outline=(255, 255, 255, 70), width=8)

    # "EC" text
    try:
        # Default Windows font (works when available)
        font = ImageFont.truetype("segoeui.ttf", 190)
    except Exception:
        font = ImageFont.load_default()

    text = "EC"
    tw, th = d.textbbox((0, 0), text, font=font)[2:]
    tx = (base.size[0] - tw) // 2
    ty = (base.size[1] - th) // 2 - 10

    # subtle shadow
    d.text((tx + 8, ty + 10), text, font=font, fill=(0, 0, 0, 80))
    d.text((tx, ty), text, font=font, fill=(255, 255, 255, 245))

    # Save multi-size ICO
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    imgs = [base.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    imgs[0].save(out_path, format="ICO", sizes=sizes)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    out = os.path.join(project_root, "assets", "app_icon.ico")
    build_icon(out)
    print(out)

