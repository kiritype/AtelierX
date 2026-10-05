"""Draw the app icon (speech bubble with a pen nib) as packaging/atelierx.ico.

The shapes follow web/src/assets/icon.svg on a 64-unit grid. Run it again after changing the SVG:
    uv run python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ACCENT = (59, 111, 214, 255)
WHITE = (255, 255, 255, 255)
SCALE = 16  # draw at 1024 px, then shrink for smooth edges
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(size):
    big = 64 * SCALE
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    def u(*values):
        return [v * SCALE for v in values]

    d.rounded_rectangle(u(0, 0, 64, 64), radius=14 * SCALE, fill=ACCENT)
    d.rounded_rectangle(u(8, 14, 56, 44), radius=4 * SCALE, fill=WHITE)
    d.polygon(u(18, 40, 28, 44, 18, 52, 18, 40), fill=WHITE)
    # Nib: flat top, point at the bottom, a slit from the hole to the point.
    d.polygon(u(26, 19, 38, 19, 39.5, 27.5, 32, 40, 24.5, 27.5), fill=ACCENT)
    if size >= 32:  # the slit and the hole only blur small sizes
        d.ellipse(u(30.4, 26.4, 33.6, 29.6), fill=WHITE)
        d.line(u(32, 29.5, 32, 40), fill=WHITE, width=round(1.3 * SCALE))
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    images = [draw(size) for size in SIZES]
    target = ROOT / 'packaging' / 'atelierx.ico'
    images[-1].save(target, format='ICO', sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(target)


if __name__ == '__main__':
    main()
