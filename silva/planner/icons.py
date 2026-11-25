"""Detailed top-down planner pictures. Regenerated when the icon set version changes."""

from __future__ import annotations

from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent / "icons"
SIZE = 128
SET_VERSION = "3"


def _rgb(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) == 8:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), int(value[6:8], 16)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


def ensure_icons() -> Path:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    stamp = ICON_DIR / ".set_version"
    if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == SET_VERSION and (ICON_DIR / "sofa.png").exists():
        return ICON_DIR
    _generate_all()
    stamp.write_text(SET_VERSION, encoding="utf-8")
    return ICON_DIR


def icon_path(name: str) -> Path:
    ensure_icons()
    path = ICON_DIR / f"{name}.png"
    if path.exists():
        return path
    fallback = ICON_DIR / "mark.png"
    return fallback if fallback.exists() else path


def _generate_all() -> None:
    from PIL import Image, ImageDraw, ImageFilter

    def make(bg: str = "#EEF1F4"):
        image = Image.new("RGBA", (SIZE, SIZE), _rgb(bg))
        return image, ImageDraw.Draw(image, "RGBA")

    def shadow(draw, xy, radius=18):
        draw.rounded_rectangle(xy, radius=radius, fill=_rgb("#000000", 28))

    def wood(draw, xy, fill="#8D6E63", radius=10):
        draw.rounded_rectangle(xy, radius=radius, fill=_rgb(fill), outline=_rgb("#4E342E"), width=2)
        x1, y1, x2, y2 = xy
        for i, y in enumerate(range(y1 + 8, y2 - 4, 10)):
            shade = "#A1887F" if i % 2 == 0 else "#6D4C41"
            draw.line((x1 + 8, y, x2 - 8, y), fill=_rgb(shade, 90), width=1)

    def metal(draw, xy, fill="#90A4AE", radius=8):
        draw.rounded_rectangle(xy, radius=radius, fill=_rgb(fill), outline=_rgb("#37474F"), width=2)
        draw.rectangle((xy[0] + 6, xy[1] + 6, xy[2] - 6, xy[1] + 14), fill=_rgb("#ECEFF1", 160))

    def save(name: str, image) -> None:
        image.filter(ImageFilter.SMOOTH).save(ICON_DIR / f"{name}.png")

    image, draw = make("#E7EDF2")
    shadow(draw, (18, 54, 118, 118), 22)
    draw.rounded_rectangle((14, 48, 114, 108), 18, fill=_rgb("#5D6D7E"), outline=_rgb("#263238"), width=3)
    draw.rounded_rectangle((20, 36, 48, 62), 10, fill=_rgb("#78909C"), outline=_rgb("#263238"), width=2)
    draw.rounded_rectangle((80, 36, 108, 62), 10, fill=_rgb("#78909C"), outline=_rgb("#263238"), width=2)
    draw.rounded_rectangle((28, 58, 62, 98), 12, fill=_rgb("#90A4AE"))
    draw.rounded_rectangle((66, 58, 100, 98), 12, fill=_rgb("#90A4AE"))
    save("sofa", image)

    image, draw = make("#E7EDF2")
    draw.rounded_rectangle((10, 40, 78, 112), 16, fill=_rgb("#4A6274"), outline=_rgb("#263238"), width=3)
    draw.rounded_rectangle((48, 16, 118, 78), 16, fill=_rgb("#4A6274"), outline=_rgb("#263238"), width=3)
    draw.rounded_rectangle((22, 52, 66, 98), 10, fill=_rgb("#90A4AE"))
    draw.rounded_rectangle((62, 28, 104, 66), 10, fill=_rgb("#90A4AE"))
    save("sectional", image)

    image, draw = make("#EFE6DC")
    shadow(draw, (40, 86, 90, 118), 12)
    wood(draw, (38, 42, 90, 104), "#7B5E57", 16)
    draw.ellipse((48, 18, 80, 52), fill=_rgb("#D7CCC8"), outline=_rgb("#5D4037"), width=2)
    draw.ellipse((54, 24, 74, 44), fill=_rgb("#A1887F"))
    save("chair", image)

    image, draw = make("#EFE6DC")
    wood(draw, (24, 36, 104, 108), "#6D4C41", 18)
    draw.rounded_rectangle((20, 32, 40, 100), 10, fill=_rgb("#8D6E63"))
    draw.rounded_rectangle((88, 32, 108, 100), 10, fill=_rgb("#8D6E63"))
    draw.ellipse((48, 14, 80, 48), fill=_rgb("#D7CCC8"), outline=_rgb("#5D4037"), width=2)
    save("armchair", image)

    image, draw = make("#F3E9DC")
    wood(draw, (18, 40, 110, 92), "#A1887F", 8)
    for x, y in ((28, 48), (100, 48), (28, 84), (100, 84)):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=_rgb("#5D4037"))
    save("table", image)

    image, draw = make("#F3E9DC")
    wood(draw, (12, 34, 116, 96), "#8D6E63", 10)
    for x in (32, 64, 96):
        draw.ellipse((x - 10, 18, x + 10, 38), fill=_rgb("#D7CCC8"), outline=_rgb("#5D4037"))
        draw.ellipse((x - 10, 92, x + 10, 112), fill=_rgb("#D7CCC8"), outline=_rgb("#5D4037"))
    save("dining_table", image)

    image, draw = make("#F3E9DC")
    wood(draw, (22, 44, 106, 88), "#A1887F", 8)
    save("coffee_table", image)

    image, draw = make("#EFE6DC")
    draw.rounded_rectangle((32, 36, 96, 100), 24, fill=_rgb("#8D6E63"), outline=_rgb("#4E342E"), width=2)
    draw.ellipse((48, 52, 80, 84), fill=_rgb("#D7CCC8", 120))
    save("ottoman", image)

    image, draw = make("#E8EAF6")
    shadow(draw, (18, 20, 118, 118), 12)
    draw.rounded_rectangle((16, 18, 112, 116), 10, fill=_rgb("#5C6BC0"), outline=_rgb("#283593"), width=3)
    draw.rounded_rectangle((22, 22, 106, 52), 8, fill=_rgb("#C5CAE9"))
    draw.line((64, 52, 64, 112), fill=_rgb("#3949AB"), width=3)
    draw.ellipse((50, 28, 78, 44), fill=_rgb("#E8EAF6"))
    save("bed", image)

    image, draw = make("#E8EAF6")
    draw.rounded_rectangle((8, 10, 120, 118), 10, fill=_rgb("#3F51B5"), outline=_rgb("#1A237E"), width=3)
    draw.rounded_rectangle((14, 14, 114, 50), 8, fill=_rgb("#C5CAE9"))
    draw.line((64, 50, 64, 114), fill=_rgb("#303F9F"), width=3)
    save("king_bed", image)

    image, draw = make("#E8EAF6")
    draw.rounded_rectangle((24, 28, 104, 100), 8, fill=_rgb("#9FA8DA"), outline=_rgb("#3949AB"), width=2)
    for x in range(32, 100, 12):
        draw.line((x, 34, x, 94), fill=_rgb("#C5CAE9"), width=2)
    save("crib", image)

    image, draw = make("#EFE6DC")
    wood(draw, (10, 40, 118, 92), "#795548", 8)
    draw.rectangle((18, 48, 110, 84), fill=_rgb("#EFEBE9"))
    save("desk", image)

    image, draw = make("#EFE6DC")
    draw.ellipse((36, 28, 92, 100), fill=_rgb("#37474F"), outline=_rgb("#212121"), width=3)
    draw.ellipse((50, 42, 78, 70), fill=_rgb("#90A4AE"))
    draw.rectangle((60, 70, 68, 112), fill=_rgb("#263238"))
    save("office_chair", image)

    image, draw = make("#EFE6DC")
    wood(draw, (36, 36, 92, 96), "#8D6E63", 8)
    draw.rectangle((44, 48, 84, 58), fill=_rgb("#D7CCC8"))
    save("nightstand", image)

    image, draw = make("#EFE6DC")
    wood(draw, (16, 28, 112, 104), "#6D4C41", 8)
    draw.line((64, 36, 64, 96), fill=_rgb("#D7CCC8"), width=3)
    for y in (48, 64, 80):
        draw.line((24, y, 104, y), fill=_rgb("#A1887F"), width=2)
    save("dresser", image)

    image, draw = make("#EFE6DC")
    wood(draw, (28, 12, 100, 116), "#5D4037", 8)
    draw.line((64, 20, 64, 108), fill=_rgb("#D7CCC8"), width=3)
    save("wardrobe", image)

    image, draw = make("#EFE6DC")
    wood(draw, (32, 10, 96, 118), "#6D4C41", 6)
    for y in (28, 48, 68, 88, 108):
        draw.line((40, y, 88, y), fill=_rgb("#D7CCC8"), width=3)
        draw.rectangle((44, y - 10, 84, y - 2), fill=_rgb("#5D4037"))
    save("bookshelf", image)

    image, draw = make("#E3E7EA")
    metal(draw, (12, 56, 116, 104), "#455A64", 6)
    draw.rounded_rectangle((22, 18, 106, 58), 6, fill=_rgb("#11181D"), outline=_rgb("#000000"), width=2)
    draw.rectangle((30, 26, 98, 50), fill=_rgb("#263238"))
    save("tv_stand", image)

    image, draw = make("#EFE6DC")
    wood(draw, (16, 48, 112, 84), "#8D6E63", 8)
    save("bench", image)

    image, draw = make("#F3E9DC")
    draw.rounded_rectangle((10, 28, 118, 100), 20, fill=_rgb("#BCAAA4"), outline=_rgb("#8D6E63"), width=3)
    draw.ellipse((28, 40, 48, 56), fill=_rgb("#A1887F", 80))
    save("rug", image)

    image, draw = make("#FFF8E1")
    draw.ellipse((44, 12, 84, 52), fill=_rgb("#FFF59D"), outline=_rgb("#F9A825"), width=3)
    draw.rectangle((60, 50, 68, 108), fill=_rgb("#6D4C41"))
    draw.ellipse((52, 100, 76, 118), fill=_rgb("#5D4037"))
    save("lamp", image)

    image, draw = make("#ECEFF1")
    metal(draw, (36, 10, 92, 118), "#90A4AE", 8)
    draw.rectangle((44, 18, 84, 48), fill=_rgb("#CFD8DC"))
    draw.rectangle((80, 28, 86, 44), fill=_rgb("#37474F"))
    draw.rectangle((80, 70, 86, 96), fill=_rgb("#37474F"))
    save("fridge", image)

    image, draw = make("#ECEFF1")
    metal(draw, (28, 10, 100, 118), "#78909C", 8)
    draw.line((64, 18, 64, 110), fill=_rgb("#ECEFF1"), width=4)
    draw.rectangle((36, 18, 60, 56), fill=_rgb("#CFD8DC"))
    draw.rectangle((68, 18, 92, 56), fill=_rgb("#CFD8DC"))
    save("french_fridge", image)

    image, draw = make("#ECEFF1")
    metal(draw, (24, 36, 104, 108), "#546E7A", 8)
    for x, y in ((42, 52), (64, 52), (86, 52), (42, 76), (64, 76), (86, 76)):
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=_rgb("#263238"), outline=_rgb("#90A4AE"), width=2)
    save("stove", image)
    Image.open(ICON_DIR / "stove.png").save(ICON_DIR / "range.png")

    image, draw = make("#ECEFF1")
    metal(draw, (20, 40, 108, 92), "#90A4AE", 10)
    draw.polygon([(40, 40), (88, 40), (100, 20), (28, 20)], fill=_rgb("#78909C"), outline=_rgb("#37474F"))
    save("range_hood", image)

    image, draw = make("#ECEFF1")
    metal(draw, (28, 28, 100, 108), "#607D8B", 8)
    draw.rectangle((40, 44, 88, 92), fill=_rgb("#90A4AE"))
    draw.rectangle((58, 70, 70, 78), fill=_rgb("#37474F"))
    save("dishwasher", image)

    image, draw = make("#ECEFF1")
    metal(draw, (28, 22, 100, 110), "#78909C", 16)
    draw.ellipse((44, 40, 84, 80), fill=_rgb("#B0BEC5"), outline=_rgb("#455A64"), width=4)
    draw.ellipse((56, 52, 72, 68), fill=_rgb("#ECEFF1"))
    save("washer", image)
    Image.open(ICON_DIR / "washer.png").save(ICON_DIR / "dryer.png")

    image, draw = make("#ECEFF1")
    metal(draw, (22, 40, 106, 92), "#455A64", 8)
    draw.rectangle((32, 50, 96, 82), fill=_rgb("#263238"))
    save("microwave", image)

    image, draw = make("#ECEFF1")
    metal(draw, (14, 40, 114, 96), "#B0BEC5", 10)
    draw.ellipse((44, 50, 84, 86), fill=_rgb("#90A4AE"), outline=_rgb("#546E7A"), width=3)
    draw.ellipse((56, 60, 72, 76), fill=_rgb("#ECEFF1"))
    save("sink", image)

    image, draw = make("#ECEFF1")
    wood(draw, (10, 36, 118, 96), "#B0BEC5", 8)
    draw.line((64, 44, 64, 88), fill=_rgb("#78909C"), width=3)
    save("cabinet", image)

    image, draw = make("#F5F5F5")
    draw.rounded_rectangle((40, 16, 88, 52), 8, fill=_rgb("#ECEFF1"), outline=_rgb("#90A4AE"), width=3)
    draw.ellipse((34, 44, 94, 112), fill=_rgb("#FAFAFA"), outline=_rgb("#90A4AE"), width=3)
    draw.ellipse((48, 58, 80, 98), fill=_rgb("#CFD8DC"))
    save("toilet", image)

    image, draw = make("#E1F5FE")
    draw.rounded_rectangle((22, 18, 106, 110), 8, fill=_rgb("#B3E5FC"), outline=_rgb("#0277BD"), width=3)
    draw.rectangle((30, 26, 98, 102), outline=_rgb("#4FC3F7"), width=2)
    draw.line((64, 26, 64, 102), fill=_rgb("#4FC3F7"), width=2)
    save("shower", image)

    image, draw = make("#E1F5FE")
    draw.rounded_rectangle((8, 36, 120, 96), 28, fill=_rgb("#E1F5FE"), outline=_rgb("#0277BD"), width=3)
    draw.ellipse((28, 48, 100, 84), fill=_rgb("#B3E5FC"))
    save("bathtub", image)

    image, draw = make("#EFEBE9")
    wood(draw, (16, 40, 112, 96), "#D7CCC8", 8)
    draw.ellipse((48, 52, 80, 84), fill=_rgb("#B0BEC5"), outline=_rgb("#78909C"), width=2)
    save("vanity", image)

    image, draw = make("#EFEBE9")
    wood(draw, (6, 44, 122, 88), "#D7CCC8", 6)
    save("counter", image)

    image, draw = make("#EFEBE9")
    wood(draw, (16, 32, 112, 100), "#BCAAA4", 10)
    draw.rectangle((36, 48, 92, 84), fill=_rgb("#EFEBE9"))
    save("island", image)

    image, draw = make("#F4F6F8")
    draw.rectangle((54, 12, 74, 116), fill=_rgb("#A1887F"), outline=_rgb("#5D4037"), width=3)
    draw.arc((18, 12, 74, 80), 90, 270, fill=_rgb("#8D6E63"), width=6)
    save("door", image)

    image, draw = make("#E3F2FD")
    draw.rounded_rectangle((16, 32, 112, 96), 4, fill=_rgb("#BBDEFB"), outline=_rgb("#1565C0"), width=3)
    draw.line((64, 32, 64, 96), fill=_rgb("#1565C0"), width=3)
    draw.line((16, 64, 112, 64), fill=_rgb("#1565C0"), width=2)
    save("window", image)

    image, draw = make("#EFEBE9")
    for i in range(8):
        y = 20 + i * 12
        draw.polygon([(24, y), (104, y + 8), (104, y + 16), (24, y + 8)], fill=_rgb("#A1887F"), outline=_rgb("#5D4037"))
    save("stairs", image)

    image, draw = make("#EFEBE9")
    draw.rounded_rectangle((28, 40, 100, 112), 6, fill=_rgb("#5D4037"), outline=_rgb("#3E2723"), width=3)
    draw.polygon([(64, 12), (28, 48), (100, 48)], fill=_rgb("#E64A19"), outline=_rgb("#BF360C"), width=2)
    draw.rectangle((48, 64, 80, 100), fill=_rgb("#212121"))
    save("fireplace", image)

    image, draw = make("#FFF8E1")
    draw.rounded_rectangle((36, 36, 92, 92), 8, fill=_rgb("#FFFDE7"), outline=_rgb("#F57F17"), width=3)
    draw.rectangle((48, 52, 58, 70), fill=_rgb("#F57F17"))
    draw.rectangle((70, 52, 80, 70), fill=_rgb("#F57F17"))
    save("outlet", image)

    image, draw = make("#FFF8E1")
    draw.rounded_rectangle((40, 28, 88, 100), 8, fill=_rgb("#FFF8E1"), outline=_rgb("#F9A825"), width=3)
    draw.ellipse((52, 48, 76, 72), fill=_rgb("#F9A825"))
    save("switch", image)

    image, draw = make("#FFFDE7")
    draw.ellipse((28, 28, 100, 100), fill=_rgb("#FFF59D"), outline=_rgb("#FBC02D"), width=3)
    draw.ellipse((48, 48, 80, 80), fill=_rgb("#FFFDE7"))
    save("light", image)

    image, draw = make("#ECEFF1")
    draw.ellipse((44, 44, 84, 84), fill=_rgb("#90A4AE"), outline=_rgb("#455A64"), width=3)
    for start in (20, 110, 200, 290):
        draw.pieslice((16, 16, 112, 112), start, start + 50, fill=_rgb("#CFD8DC"), outline=_rgb("#607D8B"))
    save("ceiling_fan", image)

    image, draw = make("#ECEFF1")
    metal(draw, (36, 16, 92, 112), "#455A64", 6)
    for y in (36, 52, 68, 84):
        draw.rectangle((46, y, 82, y + 8), fill=_rgb("#263238"))
    save("panel", image)

    image, draw = make("#E3F2FD")
    draw.line((12, 96, 36, 40, 64, 80, 92, 28, 116, 64), fill=_rgb("#B87333"), width=8)
    draw.ellipse((108, 56, 120, 72), fill=_rgb("#E65100"))
    save("copper_wire", image)

    image, draw = make("#E3F2FD")
    draw.line((10, 64, 118, 64), fill=_rgb("#1976D2"), width=10)
    draw.ellipse((8, 52, 28, 76), outline=_rgb("#0D47A1"), width=3)
    draw.ellipse((100, 52, 120, 76), outline=_rgb("#0D47A1"), width=3)
    save("water_line", image)

    image, draw = make("#FFF8E1")
    draw.line((10, 64, 30, 64, 44, 40, 64, 88, 84, 64, 118, 64), fill=_rgb("#F9A825"), width=6)
    save("gas_line", image)

    image, draw = make("#EFEBE9")
    draw.line((10, 48, 118, 80), fill=_rgb("#5D4037"), width=10)
    save("drain_line", image)

    image, draw = make("#ECEFF1")
    metal(draw, (36, 16, 92, 112), "#90A4AE", 20)
    draw.ellipse((52, 36, 76, 60), fill=_rgb("#78909C"))
    save("water_heater", image)

    image, draw = make("#E3F2FD")
    draw.rectangle((52, 28, 76, 96), fill=_rgb("#1976D2"), outline=_rgb("#0D47A1"), width=2)
    draw.ellipse((48, 88, 80, 112), fill=_rgb("#1565C0"))
    save("hose_bib", image)

    image, draw = make("#EFEBE9")
    metal(draw, (20, 40, 108, 88), "#BCAAA4", 6)
    for x in range(28, 100, 12):
        draw.line((x, 48, x, 80), fill=_rgb("#8D6E63"), width=2)
    save("vent", image)

    image, draw = make("#FFF3E0")
    draw.rounded_rectangle((40, 32, 88, 96), 8, fill=_rgb("#FFCC80"), outline=_rgb("#EF6C00"), width=3)
    draw.ellipse((54, 48, 74, 68), fill=_rgb("#FFF3E0"))
    save("thermostat", image)

    image, draw = make("#E8F5E9")
    draw.rounded_rectangle((8, 40, 120, 88), 18, fill=_rgb("#546E7A"), outline=_rgb("#263238"), width=3)
    draw.ellipse((18, 52, 42, 76), fill=_rgb("#212121"))
    draw.ellipse((86, 52, 110, 76), fill=_rgb("#212121"))
    draw.polygon([(28, 40), (100, 40), (88, 24), (40, 24)], fill=_rgb("#90A4AE"))
    save("car", image)

    image, draw = make("#E8F5E9")
    draw.ellipse((22, 12, 106, 92), fill=_rgb("#2E7D32"), outline=_rgb("#1B5E20"), width=3)
    draw.ellipse((40, 28, 88, 76), fill=_rgb("#43A047"))
    draw.rectangle((58, 84, 70, 118), fill=_rgb("#5D4037"))
    save("tree", image)

    image, draw = make("#E8F5E9")
    for y in (32, 56, 80):
        draw.line((10, y, 118, y), fill=_rgb("#6D4C41"), width=6)
    for x in range(18, 118, 16):
        draw.line((x, 24, x, 88), fill=_rgb("#8D6E63"), width=4)
    save("fence", image)

    image, draw = make("#EFEBE9")
    wood(draw, (8, 20, 120, 108), "#A1887F", 6)
    for y in range(32, 100, 12):
        draw.line((16, y, 112, y), fill=_rgb("#6D4C41", 80), width=1)
    save("deck", image)

    for name, color in (
        ("mark", "#C0392B"),
        ("electrical", "#F1C40F"),
        ("plumbing", "#2980B9"),
        ("note_pin", "#8E44AD"),
    ):
        image, draw = make()
        draw.ellipse((36, 20, 92, 108), fill=_rgb(color), outline=_rgb("#212121"), width=3)
        draw.polygon([(64, 8), (52, 28), (76, 28)], fill=_rgb(color), outline=_rgb("#212121"))
        save(name, image)

    image, draw = make("#FFF3E0")
    draw.rounded_rectangle((20, 20, 108, 108), 16, fill=_rgb("#FFB74D"), outline=_rgb("#E65100"), width=4)
    draw.line((40, 64, 88, 64), fill=_rgb("#E65100"), width=6)
    draw.line((64, 40, 64, 88), fill=_rgb("#E65100"), width=6)
    save("custom", image)
