"""
Generate assets/app_icon.ico — the Windows app icon.

Pure-Pillow drawing (no external assets needed):
  - circular blue gradient background
  - white silhouette of a person + tiny camera shutter
  - multi-resolution ICO (16/24/32/48/64/128/256)

Run once:
    python tools/make_app_icon.py
"""
import os
import sys
import math
from PIL import Image, ImageDraw, ImageFilter


SIZES = [16, 24, 32, 48, 64, 128, 256]


def _make_at(size: int) -> Image.Image:
    """Render a single-size icon."""
    # Use 4x supersampling for crisp small renders, then downscale
    s = max(size, 64) * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Circular gradient background (blue → indigo)
    cx = cy = s / 2
    r = s / 2 - s * 0.02
    for i in range(int(r), 0, -1):
        t = i / r
        col = (
            int(25 * (1 - t) + 64 * t),
            int(118 * (1 - t) + 36 * t),
            int(210 * (1 - t) + 142 * t),
            255,
        )
        d.ellipse((cx - i, cy - i, cx + i, cy + i), fill=col)

    # White silhouette of a person (head + shoulders)
    head_r = s * 0.15
    head_cx = s / 2
    head_cy = s * 0.42
    d.ellipse(
        (head_cx - head_r, head_cy - head_r,
         head_cx + head_r, head_cy + head_r),
        fill=(255, 255, 255, 240),
    )
    # Shoulders / body — rounded trapezoid via ellipse arc
    body_top = head_cy + head_r * 0.6
    body_w = s * 0.55
    body_h = s * 0.45
    d.ellipse(
        (s / 2 - body_w / 2, body_top,
         s / 2 + body_w / 2, body_top + body_h * 2),
        fill=(255, 255, 255, 240),
    )

    # Camera shutter — small circle outline lower right
    shutter_r = s * 0.12
    sx = s * 0.78
    sy = s * 0.78
    d.ellipse(
        (sx - shutter_r, sy - shutter_r, sx + shutter_r, sy + shutter_r),
        fill=(255, 255, 255, 255),
        outline=(15, 60, 140, 255),
        width=int(s * 0.012),
    )
    # Lens dot
    inner_r = shutter_r * 0.45
    d.ellipse(
        (sx - inner_r, sy - inner_r, sx + inner_r, sy + inner_r),
        fill=(15, 60, 140, 255),
    )

    # Subtle outer ring
    d.ellipse((cx - r, cy - r, cx + r, cy + r),
              outline=(255, 255, 255, 70), width=int(s * 0.012))

    img = img.filter(ImageFilter.SMOOTH_MORE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "assets")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app_icon.ico")

    layers = [_make_at(s) for s in SIZES]
    layers[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"[icon] wrote {out}  ({', '.join(str(s) for s in SIZES)} px)")

    # Also drop a 256-px PNG for installer banners etc.
    layers[-1].save(os.path.join(out_dir, "app_icon_256.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
