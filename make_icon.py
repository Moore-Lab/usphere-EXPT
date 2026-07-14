"""
make_icon.py

Generate the usphere-EXPT desktop icon: a levitated microsphere held
between two counter-propagating vertical laser beams.

Renders at 512x512 and packs a multi-resolution .ico (16, 32, 48, 64,
128, 256) so Windows picks the right resolution for the desktop and the
taskbar automatically.

Requires: pillow  (pip install pillow)
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


SIZE = 512
OUT_PATH = Path(__file__).resolve().parent / "resources" / "icons" / "microsphere.ico"


def _render_sphere(radius: int, size: int) -> Image.Image:
    """3D-shaded silver sphere with a specular highlight (Lambert + Phong).

    Returns an RGBA image of *size* × *size*.  Light comes from the
    top-left.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px  = img.load()
    cx  = cy = size // 2

    # Light direction (from top-left, forward toward viewer)
    lvx, lvy, lvz = -0.5, -0.5, 0.85
    lm = math.sqrt(lvx * lvx + lvy * lvy + lvz * lvz)
    lvx, lvy, lvz = lvx / lm, lvy / lm, lvz / lm

    r2 = radius * radius
    for y in range(size):
        dy = y - cy
        for x in range(size):
            dx = x - cx
            d2 = dx * dx + dy * dy
            if d2 > r2:
                continue
            dz = math.sqrt(r2 - d2)
            # Surface normal
            nx, ny, nz = dx / radius, dy / radius, dz / radius
            # Diffuse (Lambertian)
            diff = max(0.0, nx * lvx + ny * lvy + nz * lvz)
            # Specular (Phong, sharp)
            spec = max(0.0, diff) ** 32
            # Base colour: slightly cool grey (fused-silica microsphere feel)
            base = 40
            shade = base + int((210 - base) * diff)
            r = min(255, shade + int(spec * 220))
            g = min(255, int(shade * 1.03) + int(spec * 230))
            b = min(255, int(shade * 1.10) + int(spec * 255))
            px[x, y] = (r, g, b, 255)
    return img


def _render_beam(size: int, direction: str, cy: int,
                 sphere_r: int, colour: tuple[int, int, int]) -> Image.Image:
    """Render one focused laser beam (top-down or bottom-up).

    The beam tapers from a wider marginal ray at the edge of the frame
    down to a tight waist right at the sphere, and its intensity ramps
    up toward the focus.
    """
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx   = size // 2

    beam_edge_w  = 55   # half-width at the far edge
    beam_waist_w = 10   # half-width right at the sphere

    if direction == "top":
        y0, y1 = 0, cy - sphere_r
    else:
        y0, y1 = cy + sphere_r, size

    span = max(1, y1 - y0)
    for y in range(y0, y1):
        # t=0 at frame edge, t=1 at sphere-adjacent tip
        t = (y - y0) / span if direction == "top" else 1.0 - (y - y0) / span
        half = int(beam_edge_w + (beam_waist_w - beam_edge_w) * t)
        alpha = int(90 + 140 * t)  # brighter near focus
        draw.line([(cx - half, y), (cx + half, y)],
                  fill=(*colour, alpha), width=1)
    return img


def _render_halo(size: int, cy: int, radius: int,
                 colour: tuple[int, int, int]) -> Image.Image:
    """Soft radial glow behind the sphere where the beams focus."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx   = size // 2
    for r in range(radius, 0, -2):
        a = int(120 * (1.0 - r / radius) ** 2)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, a))
    return img.filter(ImageFilter.GaussianBlur(size // 40))


def make_icon() -> Image.Image:
    size = SIZE
    cx   = cy = size // 2

    # Background — deep space navy with a subtle radial lift
    img = Image.new("RGBA", (size, size), (6, 8, 22, 255))
    bg  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(bg)
    for r in range(size // 2, 0, -8):
        d.ellipse((cx - r, cy - r, cx + r, cy + r),
                  fill=(20, 30, 55, max(0, int(35 * (1 - r / (size / 2))))))
    bg = bg.filter(ImageFilter.GaussianBlur(size // 12))
    img = Image.alpha_composite(img, bg)

    # Laser beams — bright 532 nm green, focused
    beam_colour = (110, 255, 90)
    sphere_r    = 62
    top    = _render_beam(size, "top",    cy, sphere_r, beam_colour)
    bottom = _render_beam(size, "bottom", cy, sphere_r, beam_colour)
    top    = top.filter(ImageFilter.GaussianBlur(1.5))
    bottom = bottom.filter(ImageFilter.GaussianBlur(1.5))
    img = Image.alpha_composite(img, top)
    img = Image.alpha_composite(img, bottom)

    # Halo at the trap centre
    halo = _render_halo(size, cy, radius=110, colour=(200, 255, 190))
    img  = Image.alpha_composite(img, halo)

    # The microsphere itself
    diam   = 2 * sphere_r
    sphere = _render_sphere(sphere_r, diam)
    img.paste(sphere, (cx - sphere_r, cy - sphere_r), sphere)

    # Subtle rim glow around the sphere so it "sits" in the glow
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd  = ImageDraw.Draw(rim)
    for r in range(sphere_r + 14, sphere_r, -1):
        a = int(120 * (1 - (r - sphere_r) / 14))
        rd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(200, 255, 200, a))
    rim = rim.filter(ImageFilter.GaussianBlur(3))
    img = Image.alpha_composite(img, rim)

    return img


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    # Also save a PNG preview alongside so it's easy to inspect the design.
    icon.save(OUT_PATH.with_suffix(".png"))
    icon.save(
        OUT_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icon written: {OUT_PATH}")
    print(f"Preview PNG : {OUT_PATH.with_suffix('.png')}")


if __name__ == "__main__":
    main()
