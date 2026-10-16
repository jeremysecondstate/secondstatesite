"""Small antialiased UI assets drawn locally for the Studio Tk theme."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

from catalogapp.studio_palette import STUDIO_COLORS


def _image(master, key, render):
    root = master._root()
    cache = getattr(root, "_studio_images", None)
    if cache is None:
        cache = root._studio_images = {}
    if key not in cache:
        cache[key] = ImageTk.PhotoImage(render(), master=root)
    return cache[key]


def rounded_image(master, fill, outline=None, *, radius=8, inset=0, width=1, background=None):
    """A transparent nine-slice tile; corners stay round when Tk stretches it."""
    size, scale = 28, 4
    background = background or STUDIO_COLORS["bg"]

    def render():
        image = Image.new("RGBA", (size * scale, size * scale), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (inset * scale, 0, (size - inset) * scale - 1, size * scale - 1),
            radius=radius * scale, fill=fill, outline=outline,
            width=width * scale if outline else 1,
        )
        return image.resize((size, size), Image.Resampling.LANCZOS)

    return _image(master, ("round", fill, outline, radius, inset, width, background), render)


def studio_icon(master, name, color=None, size=16):
    """Return a cached line icon, never dependent on emoji or an external font."""
    color = color or STUDIO_COLORS["ink"]

    def render():
        scale = 4
        image = Image.new("RGBA", (size * scale, size * scale))
        draw = ImageDraw.Draw(image)
        unit = size * scale / 24

        def points(coords):
            return [(x * unit, y * unit) for x, y in coords]

        def line(coords, weight=1.5, ink=color):
            draw.line(points(coords), fill=ink, width=max(1, round(weight * unit)), joint="curve")

        def box(coords, radius=0, fill=None, ink=color, weight=1.5):
            xy = tuple(value * unit for value in coords)
            if radius:
                draw.rounded_rectangle(xy, radius=radius * unit, fill=fill, outline=ink,
                                       width=max(1, round(weight * unit)))
            else:
                draw.rectangle(xy, fill=fill, outline=ink, width=max(1, round(weight * unit)))

        def circle(coords, fill=None, ink=color, weight=1.5):
            draw.ellipse(tuple(value * unit for value in coords), fill=fill, outline=ink,
                         width=max(1, round(weight * unit)))

        if name in {"brand", "step1", "step2"}:
            if name == "brand":
                box((0, 0, 23.8, 23.8), radius=6, fill=STUDIO_COLORS["accent"], ink=None)
                label, filename, text_size, ink = "ss", "georgia.ttf", size * .48, STUDIO_COLORS["on_accent"]
            else:
                circle((0, 0, 23.8, 23.8), fill=STUDIO_COLORS["soft"], ink=None)
                label, filename, text_size, ink = name[-1], "segoeui.ttf", size * .43, STUDIO_COLORS["accent"]
            try:
                font = ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), round(text_size * scale))
            except OSError:
                font = ImageFont.load_default(size=round(text_size * scale))
            draw.text((size * scale / 2, size * scale / 2), label, font=font, fill=ink, anchor="mm")
        elif name in {"grid", "rows"}:
            box((3, 3, 21, 21), radius=2)
            line([(3, 8), (21, 8)])
            if name == "grid":
                line([(9, 8), (9, 21)])
            else:
                line([(3, 14), (21, 14)])
        elif name in {"file", "export"}:
            line([(14, 2), (5, 2), (5, 22), (19, 22), (19, 7), (14, 2), (14, 7), (19, 7)])
            if name == "export":
                line([(12, 10), (12, 18), (9, 15)])
                line([(12, 18), (15, 15)])
            else:
                line([(8, 12), (16, 12)])
                line([(8, 16), (15, 16)])
        elif name == "text":
            for y, end in ((5, 21), (11, 17), (17, 21)):
                line([(3, y), (end, y)])
        elif name == "calendar":
            box((3, 5, 21, 22), radius=2)
            line([(3, 10), (21, 10)])
            line([(8, 2), (8, 8)])
            line([(16, 2), (16, 8)])
            for x in (8, 12, 16):
                for y in (14, 18):
                    circle((x - .6, y - .6, x + .6, y + .6), fill=color, ink=None)
        elif name == "search":
            circle((3, 3, 16, 16))
            line([(14.5, 14.5), (21, 21)])
        elif name == "database":
            circle((3, 2, 21, 9))
            line([(3, 5.5), (3, 18)])
            line([(21, 5.5), (21, 18)])
            draw.arc(tuple(v * unit for v in (3, 8, 21, 15)), 0, 180, fill=color, width=round(1.5 * unit))
            draw.arc(tuple(v * unit for v in (3, 14, 21, 21)), 0, 180, fill=color, width=round(1.5 * unit))
        elif name == "upload":
            line([(3, 15), (3, 21), (21, 21), (21, 15)])
            line([(12, 17), (12, 3), (7, 8)])
            line([(12, 3), (17, 8)])
        elif name == "sparkles":
            line([(9, 4), (11, 10), (17, 12), (11, 14), (9, 20), (7, 14), (1, 12), (7, 10), (9, 4)])
            line([(19, 1), (19, 8)])
            line([(15.5, 4.5), (22.5, 4.5)])
            line([(19, 17), (19, 23)])
            line([(16, 20), (22, 20)])
        elif name == "edit":
            line([(11, 4), (3, 4), (3, 21), (20, 21), (20, 13)])
            line([(9, 16), (10, 11), (19, 2), (23, 6), (14, 15), (9, 16)])
            line([(17, 4), (21, 8)])
        elif name == "trash":
            line([(3, 6), (21, 6)])
            line([(8, 6), (8, 3), (16, 3), (16, 6)])
            line([(5, 6), (6, 22), (18, 22), (19, 6)])
            line([(10, 10), (10, 18)])
            line([(14, 10), (14, 18)])
        elif name == "external":
            line([(11, 4), (3, 4), (3, 21), (20, 21), (20, 13)])
            line([(14, 2), (22, 2), (22, 10)])
            line([(10, 14), (22, 2)])
        elif name == "folder":
            line([(2, 7), (2, 4), (9, 4), (12, 7), (21, 7), (21, 10)])
            line([(2, 7), (2, 21), (20, 21), (23, 10), (5, 10), (2, 21)])
        elif name == "sync":
            draw.arc(tuple(v * unit for v in (3, 3, 21, 21)), 205, 365, fill=color, width=round(1.5 * unit))
            draw.arc(tuple(v * unit for v in (3, 3, 21, 21)), 25, 185, fill=color, width=round(1.5 * unit))
            line([(21, 3), (21, 9), (15, 9)])
            line([(3, 21), (3, 15), (9, 15)])
        elif name == "check":
            circle((2, 2, 22, 22))
            line([(7, 12), (10, 15), (17, 8)])
        elif name == "alert":
            line([(12, 2), (23, 21), (1, 21), (12, 2)])
            line([(12, 8), (12, 14)])
            circle((11.3, 17, 12.7, 18.4), fill=color, ink=None)
        elif name == "chevron_right":
            line([(8, 4), (16, 12), (8, 20)])
        elif name == "chevron_down":
            line([(4, 8), (12, 16), (20, 8)])
        return image.resize((size, size), Image.Resampling.LANCZOS)

    return _image(master, ("icon", name, color, size), render)


def row_separator(master, background, line):
    def render():
        image = Image.new("RGB", (2, 2), background)
        ImageDraw.Draw(image).line((0, 1, 1, 1), fill=line)
        return image

    return _image(master, ("row", background, line), render)
