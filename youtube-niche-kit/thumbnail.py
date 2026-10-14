#!/usr/bin/env python3
"""
Make Work Rewired thumbnails (1280x720 JPG) from a short thumbnail.txt:

    text: $17 MISSING                 # big words on the bar; add more text: lines for A/B/C versions
    text: UBER'S CUT
    kicker: Where your fare goes      # small line at the top right (optional)
    background: photo: taxi city night   # free stock photo (Pixabay key), or a file: screenshots/x.png
    logo: logos/uber.png              # a logo file, or just a name (UBER) for a white text badge
    trend: down                       # red falling line (down), green rising line (up), or none
    strike: $31.40 -> $14.12          # old value crossed out, new value underneath (optional)
    bar: cyan                         # bar colour: cyan (default), yellow or red

    python thumbnail.py videos/02-uber/thumbnail.txt     ->  thumbnail-1.jpg, thumbnail-2.jpg ...

One template every time, so viewers recognise the channel: desaturated background, the
company's logo, one trend line, and a bright bar with 2-3 words. The bottom-right corner is
kept empty because YouTube puts the video length there.
"""

import argparse
import hashlib
import math
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_video as mv  # noqa: E402

SIZE = (1280, 720)
BARS = {"cyan": (mv.CYAN, mv.NAVY), "yellow": ((255, 214, 10), (10, 10, 10)), "red": ((214, 32, 39), mv.WHITE)}
RED, GREEN = (235, 40, 40), (40, 210, 110)
HEAVY_FONTS = [
    "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/Library/Fonts/Arial Black.ttf",
    "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf", "/usr/share/fonts/opentype/inter/Inter-Black.otf",
] + mv.FONT_CANDIDATES
KEYS = {"text", "kicker", "background", "logo", "trend", "strike", "bar"}


def parse_spec(text):
    """Read thumbnail.txt. 'text' may repeat (one thumbnail per line); the rest are single values."""
    spec = {"text": []}
    for n, raw in enumerate(text.splitlines(), 1):
        line = re.split(r"(?:^|\s)#(?:\s|$)", raw, maxsplit=1)[0].strip()  # "# note" is a comment; "#2" isn't
        if not line:
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not sep or key not in KEYS:
            raise ValueError(f"thumbnail.txt line {n}: expected one of {', '.join(sorted(KEYS))} — {raw!r}")
        if key == "text":
            spec["text"].append(value)
        else:
            spec[key] = value
    if not spec["text"]:
        raise ValueError("thumbnail.txt needs at least one 'text:' line")
    spec.setdefault("trend", "down")
    spec.setdefault("bar", "cyan")
    if spec["trend"] not in {"down", "up", "none"}:
        raise ValueError("trend must be down, up or none")
    if spec["bar"] not in BARS:
        raise ValueError(f"bar must be one of {', '.join(BARS)}")
    return spec


def heavy_font(px):
    from PIL import ImageFont
    for path in HEAVY_FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return mv._font(None, px)


def fit_font(draw, text, max_w, max_px, min_px=40):
    px = max_px
    while px > min_px and draw.textlength(text, font=heavy_font(px)) > max_w:
        px -= 4
    return heavy_font(px)


# ---------------------------------------------------------------- layers

def background(spec, base, keys, fetch=mv.fetch_asset):
    """Desaturated, darkened photo; navy gradient if there's no picture."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
    w, h = SIZE
    note, src = None, None
    value = spec.get("background", "")
    kind, _, rest = value.partition(":")
    if kind.strip().lower() == "photo" and rest.strip():
        got = fetch(rest.strip(), 0, base / "stock", keys, "photo")
        if got:
            src = got
        else:
            wanted = mv.stock_path(rest.strip(), 0, Path("stock"), ".jpg").as_posix()
            note = f"background photo '{rest.strip()}' -> save one as {wanted}"
    elif value:
        path = mv.resolve(value.removeprefix("file:").strip(), base)
        if path.exists():
            src = path
        else:
            note = f"missing background file {value}"
    if src is None:
        return mv._navy_background(SIZE), note
    img = mv.prepare_canvas(src, "cover", SIZE)
    img = ImageEnhance.Color(img).enhance(0.18)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Brightness(img).enhance(0.62)
    # navy tint + vignette so the bright elements pop
    tint = Image.new("RGB", SIZE, mv.NAVY)
    img = Image.blend(img, tint, 0.28)
    vignette = Image.new("L", SIZE, 0)
    ImageDraw.Draw(vignette).ellipse([(-w * 0.25, -h * 0.35), (w * 1.25, h * 1.35)], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(120))
    return Image.composite(img, Image.new("RGB", SIZE, (2, 8, 20)), vignette), note


def trend_points(direction, seed):
    """A jagged market-style line across the picture, falling (down) or rising (up)."""
    w, h = SIZE
    rnd = random.Random(seed)
    n = 38
    x0, x1 = w * 0.30, w * 0.88  # starts right of the logo card, ends above the empty corner
    y_start, y_end = (h * 0.20, h * 0.58) if direction == "down" else (h * 0.58, h * 0.24)
    pts, y = [], y_start
    for i in range(n + 1):
        t = i / n
        target = y_start + (y_end - y_start) * (t ** 1.6)
        y = target + rnd.uniform(-1, 1) * h * 0.035
        pts.append((x0 + (x1 - x0) * t, y))
    pts[-1] = (x1, y_end)
    return pts


def draw_trend(img, direction, seed):
    from PIL import Image, ImageDraw, ImageFilter
    if direction == "none":
        return
    color = RED if direction == "down" else GREEN
    pts = trend_points(direction, seed)
    k = 3
    layer = Image.new("RGBA", (SIZE[0] * k, SIZE[1] * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    big = [(x * k, y * k) for x, y in pts]
    d.line(big, fill=color + (255,), width=9 * k, joint="curve")
    # arrowhead along the last segment
    (ax, ay), (bx, by) = big[-2], big[-1]
    ang = math.atan2(by - ay, bx - ax)
    size = 34 * k
    tip = (bx + math.cos(ang) * size * 0.6, by + math.sin(ang) * size * 0.6)
    left = (bx + math.cos(ang + 2.5) * size, by + math.sin(ang + 2.5) * size)
    right = (bx + math.cos(ang - 2.5) * size, by + math.sin(ang - 2.5) * size)
    d.polygon([tip, left, right], fill=color + (255,))
    layer = layer.resize(SIZE, Image.LANCZOS)
    glow = layer.filter(ImageFilter.GaussianBlur(10))
    base = img.convert("RGBA")
    base.alpha_composite(glow)
    base.alpha_composite(glow)
    base.alpha_composite(layer)
    img.paste(base.convert("RGB"))


def white_card(size, radius=18):
    from PIL import Image, ImageDraw
    card = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)], radius=radius, fill=(255, 255, 255, 255))
    return card


def paste_shadowed(img, card, xy):
    from PIL import Image, ImageFilter
    shadow = Image.new("RGBA", (card.width + 40, card.height + 40), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (20, 26), card.getchannel("A"))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    img.paste(shadow, (xy[0] - 20, xy[1] - 20), shadow)
    img.paste(card, xy, card)


def draw_logo(img, value, base):
    """Logo file on a white card (top left), or the name as a bold badge. Returns the card's bottom y."""
    from PIL import Image, ImageDraw
    if not value:
        return 40
    path = mv.resolve(value, base)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and path.exists():
        logo = Image.open(path).convert("RGBA")
        logo.thumbnail((300, 110), Image.LANCZOS)
        card = white_card((logo.width + 48, logo.height + 36))
        card.alpha_composite(logo, (24, 18))
    else:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            raise FileNotFoundError(f"logo file {value} not found")
        font = heavy_font(64)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        tw = int(d.textlength(value, font=font))
        ascent, descent = font.getmetrics()
        card = white_card((min(tw + 56, 520), ascent + descent + 26))
        ImageDraw.Draw(card).text((28, 10), value, font=font, fill=mv.NAVY)
    paste_shadowed(img, card, (44, 40))
    return 40 + card.height


def draw_strike(img, value, top):
    """'$31.40 -> $14.12': old value crossed out in red, new value bold below, on a white card."""
    from PIL import Image, ImageDraw
    parts = re.split(r"\s*(?:->|→)\s*", value.strip(), maxsplit=1)
    old, new = parts[0], (parts[1] if len(parts) > 1 else "")
    old_font, new_font = heavy_font(54), heavy_font(46)
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w_old = d.textlength(old, font=old_font)
    w_new = d.textlength(new, font=new_font) if new else 0
    cw = int(max(w_old, w_new) + 60)
    ch = 90 + (70 if new else 0)
    card = white_card((cw, ch))
    cd = ImageDraw.Draw(card)
    cd.text((30, 16), old, font=old_font, fill=(25, 25, 25))
    ascent, _ = old_font.getmetrics()
    y_mid = 16 + ascent * 0.62
    cd.line([(24, y_mid), (36 + w_old, y_mid)], fill=RED, width=7)
    if new:
        tag_h = 58
        cd.rounded_rectangle([(18, 92), (cw - 18, 92 + tag_h)], radius=12, fill=(255, 225, 225))
        cd.text((30, 96), new, font=new_font, fill=(200, 20, 30))
    paste_shadowed(img, card, (44, top + 28))


def draw_kicker(img, value):
    from PIL import ImageDraw
    if not value:
        return
    d = ImageDraw.Draw(img)
    font = fit_font(d, value.upper(), 520, 50, 28)
    text = value.upper()
    tw = d.textlength(text, font=font)
    d.text((SIZE[0] - 44 - tw, 52), text, font=font, fill=mv.WHITE, stroke_width=5, stroke_fill=(0, 0, 0))


def draw_bar(img, text, color):
    """The bright bar along the bottom-left with the 2-3 big words. Never reaches the bottom-right corner."""
    from PIL import ImageDraw
    fill, ink = BARS[color]
    d = ImageDraw.Draw(img)
    text = text.upper()
    max_w = SIZE[0] * 0.70
    font = fit_font(d, text, max_w - 70, 150, 60)
    ascent, descent = font.getmetrics()
    tw = d.textlength(text, font=font)
    bar_h = int(ascent + descent * 0.4 + 44)
    top = SIZE[1] - bar_h - 26
    right = int(min(max_w, tw + 70))
    d.rectangle([(0, top), (right, top + bar_h)], fill=fill)
    d.text((34, top + 22 - descent * 0.1), text, font=font, fill=ink)
    return right


def make_thumbnail(spec, text, base, keys=None, fetch=mv.fetch_asset):
    """Return (image, notes) for one bar text."""
    notes = []
    img, note = background(spec, base, keys or {}, fetch)
    if note:
        notes.append(note)
    seed = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)
    draw_trend(img, spec["trend"], seed)
    try:
        bottom = draw_logo(img, spec.get("logo", ""), base)
    except FileNotFoundError as err:
        notes.append(str(err))
        bottom = draw_logo(img, Path(spec["logo"]).stem.upper(), base)
    if spec.get("strike"):
        draw_strike(img, spec["strike"], bottom)
    draw_kicker(img, spec.get("kicker", ""))
    draw_bar(img, text, spec["bar"])
    return img, notes


def make_thumbnails(spec_path, keys=None, fetch=mv.fetch_asset):
    spec_path = Path(spec_path)
    spec = parse_spec(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    outputs, notes = [], []
    for i, text in enumerate(spec["text"], 1):
        img, n = make_thumbnail(spec, text, base, keys, fetch)
        notes += n
        out = base / f"thumbnail-{i}.jpg"
        quality = 92
        while True:  # YouTube's limit is 2 MB
            img.save(out, "JPEG", quality=quality, optimize=True)
            if out.stat().st_size < 1_900_000 or quality <= 60:
                break
            quality -= 8
        outputs.append(out)
    return outputs, list(dict.fromkeys(notes))


def main(argv=None):
    p = argparse.ArgumentParser(description="Make Work Rewired thumbnails from thumbnail.txt")
    p.add_argument("spec", help="path to thumbnail.txt")
    args = p.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow isn't installed. Run:  pip install pillow")
    keys = {"pixabay": os.environ.get("PIXABAY_API_KEY"), "pexels": os.environ.get("PEXELS_API_KEY")}
    try:
        outputs, notes = make_thumbnails(args.spec, keys)
    except ValueError as err:
        sys.exit(str(err))
    for out in outputs:
        print(f"Thumbnail: {out}")
    for n in notes:
        print(f"  - {n}")


if __name__ == "__main__":
    main()
