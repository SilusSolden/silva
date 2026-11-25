"""Microsoft Paint-style glyphs for the planner ribbon (Fluent, dark toolbar)."""

from __future__ import annotations

from pathlib import Path

from silva.planner.icons import ICON_DIR, _rgb

TOOL_DIR = ICON_DIR / "tools"
SIZE = 32
SET_VERSION = "2"


def tool_icon_path(name: str) -> Path:
    ensure_tool_icons()
    path = TOOL_DIR / f"{name}.png"
    return path if path.exists() else TOOL_DIR / "select.png"


def ensure_tool_icons() -> Path:
    TOOL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = TOOL_DIR / ".v2"
    if stamp.exists() and (TOOL_DIR / "select.png").exists():
        return TOOL_DIR
    _generate()
    stamp.write_text("2", encoding="utf-8")
    old = TOOL_DIR / ".v1"
    if old.exists():
        old.unlink()
    return TOOL_DIR


def _generate() -> None:
    from PIL import Image, ImageDraw

    white = _rgb("#F3F3F3")
    muted = _rgb("#C8C8C8")
    blue = _rgb("#60CDFF")
    pink = _rgb("#F48FB1")
    copper = _rgb("#D4A574")
    water = _rgb("#4FC3F7")
    gas = _rgb("#FFD54F")
    drain = _rgb("#A1887F")
    red = _rgb("#FF8A80")

    def canvas():
        image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        return image, ImageDraw.Draw(image)

    def save(name: str, image) -> None:
        image.save(TOOL_DIR / f"{name}.png")

    def dashed_rect(draw, box, dash=3, gap=2, width=1, fill=white):
        x0, y0, x1, y1 = box

        def run(x_a, y_a, x_b, y_b):
            dx = x_b - x_a
            dy = y_b - y_a
            length = max(1, int((dx * dx + dy * dy) ** 0.5))
            pos = 0
            on = True
            while pos < length:
                step = dash if on else gap
                t0 = pos / length
                t1 = min(1.0, (pos + step) / length)
                if on:
                    draw.line(
                        (
                            x_a + dx * t0,
                            y_a + dy * t0,
                            x_a + dx * t1,
                            y_a + dy * t1,
                        ),
                        fill=fill,
                        width=width,
                    )
                pos += step
                on = not on

        run(x0, y0, x1, y0)
        run(x1, y0, x1, y1)
        run(x1, y1, x0, y1)
        run(x0, y1, x0, y0)

    image, draw = canvas()
    dashed_rect(draw, (6, 6, 25, 25), dash=3, gap=2, width=1)
    for x, y in ((5, 5), (23, 5), (5, 23), (23, 23)):
        draw.rectangle((x, y, x + 3, y + 3), fill=white)
    save("select", image)

    image, draw = canvas()
    draw.polygon([(8, 20), (14, 8), (24, 12), (18, 24)], fill=pink, outline=_rgb("#F8BBD0"))
    draw.line((10, 18, 16, 10), fill=_rgb("#FCE4EC"), width=1)
    save("eraser", image)

    image, draw = canvas()
    draw.ellipse((5, 5, 22, 22), outline=white, width=2)
    draw.line((19, 19, 28, 28), fill=white, width=3)
    save("orbit", image)

    image, draw = canvas()
    draw.line((7, 25, 25, 7), fill=white, width=2)
    save("line", image)

    image, draw = canvas()
    draw.rectangle((6, 8, 26, 24), outline=white, width=2)
    save("room", image)

    image, draw = canvas()
    # Fluent crop: two overlapping L corners, Paint-blue
    draw.line((8, 10, 8, 22, 20, 22), fill=blue, width=3)
    draw.line((12, 10, 24, 10, 24, 22), fill=blue, width=3)
    save("import", image)

    image, draw = canvas()
    draw.line((5, 22, 12, 10, 18, 20, 27, 8), fill=copper, width=3)
    save("electrical", image)

    image, draw = canvas()
    draw.line((5, 16, 27, 16), fill=water, width=4)
    draw.ellipse((4, 12, 12, 20), outline=_rgb("#29B6F6"), width=2)
    draw.ellipse((20, 12, 28, 20), outline=_rgb("#29B6F6"), width=2)
    save("water", image)

    image, draw = canvas()
    draw.line((5, 16, 11, 16, 15, 10, 19, 22, 23, 16, 27, 16), fill=gas, width=3)
    save("gas", image)

    image, draw = canvas()
    draw.line((5, 12, 27, 20), fill=drain, width=4)
    save("drain", image)

    image, draw = canvas()
    draw.rectangle((7, 7, 25, 25), outline=red, width=2)
    draw.line((11, 11, 21, 21), fill=red, width=2)
    draw.line((21, 11, 11, 21), fill=red, width=2)
    save("delete", image)

    image, draw = canvas()
    draw.rectangle((5, 7, 18, 20), outline=red, width=2)
    draw.rectangle((13, 12, 26, 25), outline=muted, width=2)
    draw.line((8, 10, 15, 17), fill=red, width=2)
    draw.line((15, 10, 8, 17), fill=red, width=2)
    save("delete_all", image)
