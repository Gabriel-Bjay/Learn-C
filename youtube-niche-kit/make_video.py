#!/usr/bin/env python3
"""
Auto-edit a Work Rewired video: voiceover + shot list -> finished 1080p MP4.

  python make_video.py quibi_voiceover.wav shots.txt
  python make_video.py quibi_voiceover.wav shots.txt --preview      # fast, low-res check
  python make_video.py quibi_voiceover.wav shots.txt --music bg.mp3

Needs: ffmpeg on PATH, Pillow (pip install pillow), and the .timings.json that
voiceover.py writes next to the .wav. Stock footage ("stock:" lines) is downloaded
automatically with a free PIXABAY_API_KEY (or PEXELS_API_KEY), or you can save
clips by hand into the stock/ folder — the run tells you the exact file names.

Shot list format (one visual per line; see SHOTS.md):
  1: screenshot: https://site.com/article | phrase to highlight
  1: screenshot: screenshots/my_capture.png
  2: text: $1.75 BILLION | raised before a single customer paid
  3: stock: person watching phone on train >> 1.7M DOWNLOADS | in week one
  4: photo: hollywood film set
  5: person: Jeffrey Katzenberg >> Jeffrey Katzenberg | Founder
  6: chart: charts/chart1.png
  7: video: clips/my_clip.mp4
">>" puts a text overlay (headline | smaller line) on top of any visual; ">> @subscribe"
places the animated subscribe button (otherwise it appears where the voiceover says "subscribe").
Text animates in, numbers count up, charts draw in, and screenshots zoom to their highlighted phrase.
Several lines for the same paragraph split its time evenly, in order.
Paragraphs with no line keep showing the previous visual.
"""

import argparse
import concurrent.futures
import functools
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FPS = 30
NAVY = (6, 23, 51)
NAVY_2 = (12, 44, 99)
CYAN = (47, 211, 240)
WHITE = (255, 255, 255)
MUTED = (185, 200, 230)

IMAGE_TYPES = {"image", "chart", "screenshot", "img"}
VIDEO_TYPES = {"video", "clip"}
STOCK_TYPES = {"stock", "pexels", "pixabay"}
PHOTO_TYPES = {"photo"}
PERSON_TYPES = {"person"}
ALL_TYPES = IMAGE_TYPES | VIDEO_TYPES | STOCK_TYPES | PHOTO_TYPES | PERSON_TYPES | {"text"}

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


# ---------------------------------------------------------------- shot list

def parse_shots(text):
    """Return {paragraph_number: [(type, value), ...]} from the shot-list text."""
    shots = {}
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"(\d+)(?:\s*[-–]\s*(\d+))?\s*:\s*([A-Za-z]+)\s*:\s*(.+)", line)
        if not m:
            raise ValueError(f"shot list line {line_no} isn't 'N: type: value' — {raw!r}")
        first, last, kind, value = int(m[1]), int(m[2] or m[1]), m[3].lower(), m[4].strip()
        if kind not in ALL_TYPES:
            raise ValueError(f"shot list line {line_no}: unknown type '{kind}' "
                             f"(use screenshot, chart, image, video, text, stock, photo or person)")
        if last < first:
            raise ValueError(f"shot list line {line_no}: range {first}-{last} goes backwards")
        if first == last:
            shots.setdefault(first, []).append((kind, value))
        else:
            # A range = one continuous visual spanning those paragraphs.
            shots.setdefault(first, []).append((kind, value))
            for n in range(first + 1, last + 1):
                shots.setdefault(n, [])  # explicitly "continue previous visual"
    return shots


def build_timeline(timings, shots, title="WORK REWIRED"):
    """Turn paragraph timings + shots into [(start_s, end_s, kind, value)] covering the audio."""
    paras = timings["paragraphs"]
    total = timings["duration"]
    bounds = []
    for i, p in enumerate(paras):
        start = 0.0 if i == 0 else p["start"]
        end = paras[i + 1]["start"] if i + 1 < len(paras) else total
        bounds.append((p["n"], start, end))

    timeline = []
    for n, start, end in bounds:
        visuals = shots.get(n, [])
        if not visuals:
            if timeline:
                s, _, kind, value = timeline[-1]
                timeline[-1] = (s, end, kind, value)  # extend previous visual
            else:
                timeline.append((start, end, "text", title))
            continue
        step = (end - start) / len(visuals)
        for k, (kind, value) in enumerate(visuals):
            timeline.append((start + k * step, start + (k + 1) * step, kind, value))
    return timeline


def frame_counts(timeline, fps=FPS):
    """Frames per segment, rounded on cumulative boundaries so there's no drift."""
    counts = []
    for start, end, *_ in timeline:
        counts.append(max(1, round(end * fps) - round(start * fps)))
    return counts


# ---------------------------------------------------------------- assets

def find_font(explicit=None):
    for path in ([explicit] if explicit else []) + FONT_CANDIDATES:
        if path and os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------- layouts & animation

def _font(font_path, px):
    from PIL import ImageFont
    if font_path:
        return ImageFont.truetype(font_path, px)
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def _metrics(font, px):
    try:
        return font.getmetrics()
    except AttributeError:
        return px, int(px * 0.25)


def _navy_background(size):
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGB", (w, h), NAVY)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = 1 - abs(y - h / 2) / (h / 2)
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t * 0.6) for a, b in zip(NAVY, NAVY_2)))
    return img


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def progress(t, start, dur):
    """0 before start, 1 after start+dur, linear in between."""
    return _clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(x):
    return 1 - (1 - _clamp(x)) ** 3


def ease_in_out(x):
    x = _clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_back(x):
    """Ease out with a small overshoot - for things that 'pop' in."""
    x, c = _clamp(x), 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _faded(sprite, k):
    if k >= 0.999:
        return sprite
    out = sprite.copy()
    out.putalpha(sprite.getchannel("A").point(lambda v: int(v * k)))
    return out


def _paste(frame, sprite, x, y, k=1.0):
    """Paste an RGBA sprite onto an RGB frame at (x, y) with extra opacity k."""
    if k <= 0.003:
        return
    s = _faded(sprite, k)
    frame.paste(s, (round(x), round(y)), s)


def _text_sprite(text, font, px, fill):
    from PIL import Image, ImageDraw
    ascent, descent = _metrics(font, px)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = max(1, int(d.textlength(text, font=font)) + 4)
    img = Image.new("RGBA", (w, ascent + descent + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((0, 0), text, font=font, fill=fill)
    return img


COUNT_RE = re.compile(r"^(\D*?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?=$|[\s+%MBKkx])(.*)$")


def count_up(text, p):
    """'$1.75 BILLION' at p=0.5 -> '$0.88 BILLION'. Only for a headline with one number >= 10
    (or with decimals); anything else is returned unchanged."""
    m = COUNT_RE.match(text)
    if not m or re.search(r"\d", m[4]):
        return text
    whole, frac = m[2], m[3] or ""
    value = float(whole.replace(",", "") + frac)
    if value < 10 and not frac:
        return text
    if p >= 1:
        return text
    decimals = len(frac) - 1 if frac else 0
    v = value * _clamp(p)
    shown = f"{v:,.{decimals}f}" if "," in whole else f"{v:.{decimals}f}"
    return m[1] + shown + m[4]


class TextBlock:
    """'Headline | subline' with a cyan accent bar. Pre-rendered once, animated in per frame:
    the bar grows, lines slide up and fade in one after another, and a number in the
    headline counts up."""

    def __init__(self, text, size, font_path, *, x, max_w, y_bottom=None, y_center=None,
                 align="left", head=0.07, sub=0.036, max_lines=2, start=0.15):
        from PIL import Image, ImageDraw
        w, h = size
        self.h, self.start, self.font_path = h, start, font_path
        headline, _, subline = (part.strip() for part in text.partition("|"))
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        head_px = int(h * head)
        while True:
            head_font = _font(font_path, head_px)
            head_lines = _wrap(draw, headline, head_font, max_w)
            if len(head_lines) <= max_lines or head_px <= int(h * head * 0.5):
                break
            head_px = int(head_px * 0.88)
        sub_px = int(h * sub)
        sub_font = _font(font_path, sub_px)
        sub_lines = _wrap(draw, subline, sub_font, max_w) if subline else []
        ascent, descent = _metrics(head_font, head_px)
        line_h, sub_h = ascent + descent, int(sub_px * 1.35)
        bar_h, space = max(4, int(h * 0.007)), int(h * 0.018)
        bar_w = int(w * 0.06)
        centered = align == "center"

        # Lower-thirds put the bar above the headline; centred cards put it between headline and subline.
        items = []  # (kind, payload, x, y)

        def line_x(width):
            return x - width / 2 if centered else x

        if centered:
            block = len(head_lines) * line_h + (2 * space + bar_h + len(sub_lines) * sub_h if sub_lines else 0)
        else:
            block = bar_h + space + len(head_lines) * line_h + (space + len(sub_lines) * sub_h if sub_lines else 0)
        y = (y_center - block / 2) if y_center is not None else (y_bottom - block)
        if not centered:
            items.append(("bar", None, x, y))
            y += bar_h + space
        for k, line in enumerate(head_lines):
            sprite = _text_sprite(line, head_font, head_px, WHITE)
            if k == 0 and count_up(line, 0) != line:
                items.append(("count", (line, head_font, head_px), line_x(sprite.width), y))
            else:
                items.append(("line", sprite, line_x(sprite.width), y))
            y += line_h
        if sub_lines:
            if centered:
                y += space
                items.append(("bar", None, x - bar_w / 2, y))
                y += bar_h + space
            else:
                y += space
            for line in sub_lines:
                sprite = _text_sprite(line, sub_font, sub_px, MUTED)
                items.append(("line", sprite, line_x(sprite.width), y))
                y += sub_h
        self.items, self.bar_w, self.bar_h = items, bar_w, bar_h
        self.top = items[0][3] if items else 0

    def draw(self, frame, t):
        from PIL import ImageDraw
        t -= self.start
        rise = self.h * 0.035
        delay = 0.0
        for kind, payload, x, y in self.items:
            if kind == "bar":
                p = ease_out(progress(t, delay, 0.35))
                if p > 0:
                    ImageDraw.Draw(frame).rounded_rectangle(
                        [(round(x), round(y)), (round(x + max(self.bar_h, self.bar_w * p)), round(y + self.bar_h))],
                        radius=self.bar_h // 2, fill=CYAN)
                delay += 0.12
                continue
            p = ease_out(progress(t, delay, 0.45))
            if kind == "count":
                line, font, px = payload
                sprite = _text_sprite(count_up(line, ease_out(progress(t, delay, 1.1))), font, px, WHITE)
            else:
                sprite = payload
            _paste(frame, sprite, x, y + (1 - p) * rise, p)
            delay += 0.12


@functools.lru_cache(maxsize=4)
def _lower_third_shade(size):
    from PIL import Image, ImageDraw
    w, h = size
    top = int(h * 0.42)
    shade = Image.new("RGBA", (w, h - top), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(h - top):
        sd.line([(0, y), (w, y)], fill=NAVY + (int(225 * (y / (h - top)) ** 1.3),))
    return shade, top


class LowerThird:
    """Navy fade at the bottom of the frame with an animated 'HEADLINE | subline'."""

    def __init__(self, text, size, font_path):
        w, h = size
        self.shade, self.shade_top = _lower_third_shade(size)
        self.block = TextBlock(text, size, font_path, x=int(w * 0.06), y_bottom=int(h * 0.9), max_w=int(w * 0.8))

    def draw(self, frame, t):
        _paste(frame, self.shade, 0, self.shade_top, ease_out(progress(t, 0, 0.4)))
        self.block.draw(frame, t)


def _supersampled(size, painter, scale=4):
    """Draw at 4x and shrink, for smooth edges on shapes."""
    from PIL import Image, ImageDraw
    w, h = size
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    painter(ImageDraw.Draw(big), scale)
    return big.resize((w, h), Image.LANCZOS)


class SubscribeAnim:
    """Pop-up channel badge + SUBSCRIBE button: a cursor clicks it (-> SUBSCRIBED), then rings the bell."""

    DURATION = 4.6

    def __init__(self, size, font_path, start=0.6, high=False, speed=1.0):
        from PIL import Image, ImageDraw
        w, h = size
        s = h / 1080 * 1.35
        self.w, self.h, self.s, self.start, self.speed = w, h, s, start, speed
        bh = int(78 * s)
        font = _font(font_path, int(32 * s))

        def pill(label, color, text_color):
            d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            tw = d.textlength(label, font=font)
            bw = int(tw + 70 * s)

            def paint(dr, k):
                dr.rounded_rectangle([(0, 0), (bw * k - 1, bh * k - 1)], radius=bh * k // 2, fill=color)
            img = _supersampled((bw, bh), paint)
            ascent, descent = _metrics(font, int(32 * s))
            ImageDraw.Draw(img).text(((bw - tw) / 2, (bh - ascent - descent) / 2 + 2 * s), label,
                                     font=font, fill=text_color)
            return img

        self.red = pill("SUBSCRIBE", (204, 0, 0), WHITE)
        self.gray = pill("SUBSCRIBED", (56, 60, 70), (225, 228, 235))

        av = int(bh * 1.05)

        def paint_avatar(dr, k):
            dr.ellipse([(0, 0), (av * k - 1, av * k - 1)], fill=CYAN)
            r = int(5 * s * k)
            dr.ellipse([(r, r), (av * k - 1 - r, av * k - 1 - r)], fill=NAVY)
        self.avatar = _supersampled((av, av), paint_avatar)
        af = _font(font_path, int(av * 0.38))
        ascent, descent = _metrics(af, int(av * 0.38))
        ad = ImageDraw.Draw(self.avatar)
        aw = ad.textlength("WR", font=af)
        ad.text(((av - aw) / 2, (av - ascent - descent) / 2), "WR", font=af, fill=WHITE)

        bs = int(bh * 0.95)

        def paint_bell(dr, k):
            u = bs * k / 100
            dr.ellipse([(44 * u, 6 * u), (56 * u, 18 * u)], fill=WHITE)  # top knob
            dr.chord([(22 * u, 12 * u), (78 * u, 70 * u)], 180, 360, fill=WHITE)  # dome
            dr.polygon([(22 * u, 41 * u), (78 * u, 41 * u), (88 * u, 74 * u), (12 * u, 74 * u)], fill=WHITE)
            dr.rounded_rectangle([(8 * u, 70 * u), (92 * u, 80 * u)], radius=5 * u, fill=WHITE)  # rim
            dr.ellipse([(41 * u, 80 * u), (59 * u, 96 * u)], fill=WHITE)  # clapper
        self.bell = _supersampled((bs, bs), paint_bell)

        cs = int(46 * s)

        def paint_cursor(dr, k):
            u = cs * k / 24
            pts = [(2, 1), (2, 19), (7, 15), (10.5, 22.5), (13.5, 21), (10, 14), (17, 14)]
            dr.polygon([(px * u, py * u) for px, py in pts], fill=WHITE, outline=(0, 0, 0), width=max(1, int(1.6 * u)))
        self.cursor = _supersampled((cs, cs), paint_cursor)

        gap = int(22 * s)
        self.group_w = av + gap + self.gray.width + gap + bs
        self.group_h = max(av, bh, bs)
        self.gx = (w - self.group_w) / 2
        self.gy = (h * 0.13 if high else h * 0.80) - self.group_h / 2
        self.av_x, self.btn_x = 0, av + gap
        self.bell_x = self.btn_x + self.gray.width + gap
        self.btn_center = (self.gx + self.btn_x + self.red.width / 2, self.gy + self.group_h / 2)
        self.bell_center = (self.gx + self.bell_x + bs / 2, self.gy + self.group_h / 2)

    def _group(self, t):
        from PIL import Image
        g = Image.new("RGBA", (self.group_w, self.group_h), (0, 0, 0, 0))
        g.alpha_composite(self.avatar, (self.av_x, (self.group_h - self.avatar.height) // 2))
        btn = self.gray if t >= 1.5 else self.red
        squish = 1 - 0.08 * max(0.0, 1 - abs(t - 1.5) / 0.12)
        if squish < 0.999:
            btn = btn.resize((max(1, int(btn.width * squish)), max(1, int(btn.height * squish))), Image.BILINEAR)
        bx = self.btn_x + (self.red.width - btn.width) // 2 if btn.width <= self.red.width else self.btn_x
        g.alpha_composite(btn, (int(bx), (self.group_h - btn.height) // 2))
        bell = self.bell
        if 2.5 <= t <= 3.5:  # ring: swing that dies down
            angle = 24 * math.sin((t - 2.5) * 26) * (1 - (t - 2.5))
            bell = bell.rotate(angle, resample=Image.BICUBIC, center=(bell.width / 2, bell.height * 0.1))
        g.alpha_composite(bell, (self.bell_x, (self.group_h - bell.height) // 2))
        return g

    def draw(self, frame, t):
        from PIL import Image, ImageDraw
        t = (t - self.start) * self.speed
        if t < 0 or t > self.DURATION:
            return
        appear = ease_back(progress(t, 0, 0.45))
        leave = ease_in_out(progress(t, self.DURATION - 0.45, 0.45))
        k = progress(t, 0, 0.15) * (1 - leave)
        scale = max(0.05, 0.6 + 0.4 * appear)
        g = self._group(t)
        if abs(scale - 1) > 0.002:
            g = g.resize((max(1, int(g.width * scale)), max(1, int(g.height * scale))), Image.BILINEAR)
        cx, cy = self.gx + self.group_w / 2, self.gy + self.group_h / 2 + leave * 30 * self.s
        _paste(frame, g, cx - g.width / 2, cy - g.height / 2, k)

        # Click ripples on the button and the bell.
        for at, (px, py) in ((1.5, self.btn_center), (2.5, self.bell_center)):
            p = progress(t, at, 0.45)
            if 0 < p < 1:
                r = (20 + 70 * ease_out(p)) * self.s
                ring = Image.new("RGBA", (int(2 * r) + 4, int(2 * r) + 4), (0, 0, 0, 0))
                ImageDraw.Draw(ring).ellipse([(2, 2), (2 * r + 1, 2 * r + 1)], outline=WHITE + (int(200 * (1 - p)),),
                                             width=max(2, int(4 * self.s)))
                _paste(frame, ring, px - r - 2, py - r - 2, k)

        # The cursor glides in, clicks SUBSCRIBE, then the bell, then drifts off.
        start_pt = (self.w * 0.78, self.h * 1.05)
        bx, by = self.btn_center[0] + 10 * self.s, self.btn_center[1] + 8 * self.s
        lx, ly = self.bell_center[0] + 6 * self.s, self.bell_center[1] + 10 * self.s
        if t < 1.4:
            p = ease_in_out(progress(t, 0.55, 0.85))
            x, y = start_pt[0] + (bx - start_pt[0]) * p, start_pt[1] + (by - start_pt[1]) * p
        elif t < 2.45:
            p = ease_in_out(progress(t, 1.85, 0.55))
            x, y = bx + (lx - bx) * p, by + (ly - by) * p
        else:
            p = ease_in_out(progress(t, 3.1, 0.9))
            x, y = lx + (self.w * 0.9 - lx) * p, ly + (self.h * 1.1 - ly) * p
        press = 0.85 if (1.45 <= t <= 1.58 or 2.45 <= t <= 2.58) else 1.0
        cur = self.cursor if press == 1 else self.cursor.resize(
            (int(self.cursor.width * press), int(self.cursor.height * press)), Image.BILINEAR)
        _paste(frame, cur, x, y, progress(t, 0.5, 0.2) * (1 - leave))


@functools.lru_cache(maxsize=4)
def _glow_background(size):
    """Navy background, 20% larger than the frame, with two soft glows - drifted slowly on text cards."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    big = (int(w * 1.2), int(h * 1.2))
    small = (big[0] // 8, big[1] // 8)
    glow = Image.new("RGB", small, (0, 0, 0))
    d = ImageDraw.Draw(glow)
    sw, sh = small
    d.ellipse([(-0.1 * sw, -0.3 * sh), (0.55 * sw, 0.55 * sh)], fill=(14, 60, 110))
    d.ellipse([(0.55 * sw, 0.5 * sh), (1.15 * sw, 1.3 * sh)], fill=(10, 50, 95))
    glow = glow.filter(ImageFilter.GaussianBlur(sw / 10)).resize(big, Image.BILINEAR)
    from PIL import ImageChops
    return ImageChops.lighter(_navy_background(big), glow)


def prepare_canvas(path, fit, size):
    """Turn an image file into a full frame. fit: contain | card | cover | person.
    'person' leaves the right half free for the animated name label."""
    from PIL import Image, ImageDraw
    w, h = size
    src = Image.open(path).convert("RGB")
    if fit == "cover":
        scale = max(w / src.width, h / src.height)
        im = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
        left, top = (im.width - w) // 2, (im.height - h) // 2
        return im.crop((left, top, left + w, top + h))
    if fit == "person":
        canvas = _navy_background(size)
        bw, bh = int(w * 0.34), int(h * 0.78)
        scale = max(bw / src.width, bh / src.height)
        im = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
        left = (im.width - bw) // 2
        top = int(max(0, (im.height - bh) * 0.25))  # keep faces, which sit high in portraits
        im = im.crop((left, top, left + bw, top + bh))
        x, y = int(w * 0.08), (h - bh) // 2
        ImageDraw.Draw(canvas).rectangle([(x + 12, y + 12), (x + bw + 12, y + bh + 12)], fill=(3, 12, 28))
        canvas.paste(im, (x, y))
        return canvas
    canvas = _navy_background(size) if fit == "card" else Image.new("RGB", (w, h), NAVY)
    box_w, box_h = (int(w * 0.86), int(h * 0.82)) if fit == "card" else (w, h)
    scale = min(box_w / src.width, box_h / src.height)
    im = src.resize((max(1, round(src.width * scale)), max(1, round(src.height * scale))), Image.LANCZOS)
    x, y = (w - im.width) // 2, (h - im.height) // 2
    if fit == "card":
        ImageDraw.Draw(canvas).rectangle([(x + 12, y + 12), (x + im.width + 12, y + im.height + 12)], fill=(3, 12, 28))
    canvas.paste(im, (x, y))
    return canvas


# ---------------------------------------------------------------- stock footage & photos

def stock_path(query, occurrence, cache_dir, ext=".mp4"):
    """Where a stock clip/photo for this query lives, e.g. stock/empty-train-station-0.mp4.

    You can also save a file here by hand (downloaded from pexels.com, pixabay.com…)
    and it will be used without any API key.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40]
    return Path(cache_dir) / f"{slug}-{occurrence}{ext}"


def _best(files, target_w=1920):
    """Pick the file closest to 1080p width, preferring HD."""
    files = [f for f in files if f.get("url") and f.get("width")]
    if not files:
        return None
    return min(files, key=lambda f: (f["width"] < 1280, abs(f["width"] - target_w)))["url"]


USER_AGENT = "WorkRewiredVideoTool/1.0 (https://github.com/Gabriel-Bjay/Learn-C)"


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def pick_pexels_file(video):
    return _best([{"url": f.get("link"), "width": f.get("width")}
                  for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"])


def pexels_links(query, api_key):
    data = _get_json("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "per_page": 15}), {"Authorization": api_key})
    return [pick_pexels_file(v) for v in data.get("videos", [])]


def pick_pixabay_file(hit):
    return _best([v for v in (hit.get("videos") or {}).values() if isinstance(v, dict)])


def pixabay_links(query, api_key):
    data = _get_json("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": api_key, "q": query[:100], "per_page": 20, "safesearch": "true"}))
    return [pick_pixabay_file(h) for h in data.get("hits", [])]


def pixabay_photo_links(query, api_key):
    data = _get_json("https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": api_key, "q": query[:100], "image_type": "photo", "orientation": "horizontal",
         "per_page": 20, "safesearch": "true"}))
    return [h.get("largeImageURL") for h in data.get("hits", [])]


def pexels_photo_links(query, api_key):
    data = _get_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "per_page": 15}), {"Authorization": api_key})
    return [(p.get("src") or {}).get("large2x") for p in data.get("photos", [])]


STOCK_PROVIDERS = {"pixabay": pixabay_links, "pexels": pexels_links}
PHOTO_PROVIDERS = {"pixabay": pixabay_photo_links, "pexels": pexels_photo_links}


def fetch_stock(query, occurrence, cache_dir, keys, providers=None, download=None, ext=".mp4"):
    """Return a local file for `query`: one you saved by hand, or one downloaded
    from the first provider with a key. Repeated queries get different results."""
    path = stock_path(query, occurrence, cache_dir, ext)
    if path.exists():
        return path
    for name, find_links in (providers or STOCK_PROVIDERS).items():
        if not keys.get(name):
            continue
        try:
            links = [link for link in find_links(query, keys[name]) if link]
        except (urllib.error.URLError, ValueError, OSError) as err:
            print(f"  {name} search failed for '{query}': {err}", file=sys.stderr)
            continue
        if links:
            path.parent.mkdir(parents=True, exist_ok=True)
            (download or _download)(links[occurrence % len(links)], path)
            return path
    return None


def fetch_asset(query, occurrence, cache_dir, keys, kind="stock"):
    if kind in PHOTO_TYPES:
        return fetch_stock(query, occurrence, cache_dir, keys, PHOTO_PROVIDERS, ext=".jpg")
    return fetch_stock(query, occurrence, cache_dir, keys, STOCK_PROVIDERS)


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as fh:
        shutil.copyfileobj(resp, fh)


# ---------------------------------------------------------------- people (Wikimedia Commons)

FREE_LICENSE = re.compile(r"^\s*(cc0|cc[ -]by|public domain|pd\b|no restrictions)", re.I)


def _strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def wikipedia_photo(name):
    """Lead photo of a Wikipedia article, only if it is freely licensed on Commons.

    Returns {"url", "license", "artist"} or raises LookupError with the reason.
    """
    api = "https://en.wikipedia.org/w/api.php?"
    data = _get_json(api + urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "pageimages", "piprop": "thumbnail|name",
        "pithumbsize": 1600, "redirects": 1, "titles": name}))
    pages = list((data.get("query") or {}).get("pages", {}).values())
    page = pages[0] if pages else {}
    thumb, file_name = (page.get("thumbnail") or {}).get("source"), page.get("pageimage")
    if not thumb or not file_name:
        raise LookupError("no photo on its Wikipedia page")
    meta = _get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "extmetadata",
        "titles": "File:" + file_name}))
    cpages = list((meta.get("query") or {}).get("pages", {}).values())
    cpage = cpages[0] if cpages else {}
    if "missing" in cpage or not cpage.get("imageinfo"):
        raise LookupError("its Wikipedia photo isn't freely licensed")
    ext = cpage["imageinfo"][0].get("extmetadata", {})
    license_name = _strip_html((ext.get("LicenseShortName") or {}).get("value"))
    if not FREE_LICENSE.match(license_name):
        raise LookupError(f"its photo's licence ({license_name or 'unknown'}) doesn't allow reuse")
    artist = _strip_html((ext.get("Artist") or {}).get("value")) or "unknown author"
    return {"url": thumb, "license": license_name, "artist": artist}


def fetch_person(name, cache_dir, lookup=wikipedia_photo, download=None):
    """Return (path, credit) for a person's photo, cached in people/. A photo you
    save by hand as people/<name>.jpg is used as-is (credit it yourself)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    path, info_path = Path(cache_dir) / f"{slug}.jpg", Path(cache_dir) / f"{slug}.json"
    if path.exists():
        info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
        return path, info.get("credit")
    info = lookup(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    (download or _download)(info["url"], path)
    credit = f"Photo of {name}: {info['artist']}, {info['license']}, via Wikimedia Commons"
    info_path.write_text(json.dumps({"credit": credit, **info}, indent=1), encoding="utf-8")
    return path, credit


# ---------------------------------------------------------------- automatic screenshots

DISMISS_JS = r"""
() => {
  const h1 = document.querySelector('article h1, main h1, h1');
  const keep = el => el === document.body || el === document.documentElement || (h1 && el.contains(h1));
  // Only real buttons - never links, which could navigate away from the article.
  const words = /^(accept( all)?( cookies)?|i accept|agree|i agree|allow( all)?|got it|ok|okay|no,? thanks|maybe later|not now|close|dismiss|reject all|[×✕])$/i;
  for (const el of document.querySelectorAll('button, [role=button]')) {
    if (el.closest('a[href]')) continue;
    const t = (el.innerText || '').trim();
    const label = el.getAttribute('aria-label') || '';
    if ((t.length < 25 && words.test(t)) || /^(close|dismiss)/i.test(label)) { try { el.click(); } catch (e) {} }
  }
  const sel = 'dialog, [role=dialog], [role=alertdialog], [aria-modal=true], [class*=modal i], [class*=popup i], ' +
              '[class*=newsletter i], [class*=paywall i], [class*=overlay i], [id*=modal i], [id*=popup i], ' +
              '[class*=consent i], [id*=consent i], [class*=cookie i], [id*=cookie i]';
  for (const el of document.querySelectorAll(sel)) { if (!keep(el)) el.remove(); }
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if ((s.position === 'fixed' || s.position === 'sticky') && !keep(el)) {
      const r = el.getBoundingClientRect();
      if (r.width * r.height > vw * vh * 0.1 || parseInt(s.zIndex || 0) > 999) el.remove();
    }
  }
  const style = document.createElement('style');
  style.textContent = '*{filter:none!important;backdrop-filter:none!important}html,body{overflow:auto!important;position:static!important}';
  document.head.appendChild(style);
}
"""

FIND_PHRASE_JS = r"""
(phrase) => {
  // Case-, quote- and dash-insensitive search across tags (a phrase may span <a>, <em>...).
  const fold = c => {
    if ('‘’‛′`'.includes(c)) return "'";
    if ('“”″'.includes(c)) return '"';
    if ('‐‑‒–—−'.includes(c)) return '-';
    if (/\s/.test(c)) return ' ';
    const l = c.toLowerCase();
    return l.length === 1 ? l : c;
  };
  const target = Array.from(phrase.trim()).map(fold).join('').replace(/ +/g, ' ');
  if (!target) return false;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {acceptNode: n =>
    (n.parentElement && !/^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA)$/.test(n.parentElement.tagName))
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
  let flat = '', map = [], node;
  while ((node = walker.nextNode())) {
    const v = node.nodeValue;
    for (let i = 0; i < v.length; i++) {
      const c = fold(v[i]);
      if (c === ' ' && (flat === '' || flat.endsWith(' '))) continue;
      flat += c; map.push([node, i]);
    }
  }
  for (let from = 0; ; ) {
    const idx = flat.indexOf(target, from);
    if (idx < 0) return false;
    const [sn, so] = map[idx], [en, eo] = map[idx + target.length - 1];
    const range = document.createRange();
    range.setStart(sn, so); range.setEnd(en, eo + 1);
    const r = range.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && getComputedStyle(sn.parentElement).visibility !== 'hidden') {
      window.__wrTarget = range;
      window.scrollBy(0, r.top - innerHeight * 0.42);
      return true;
    }
    from = idx + 1;
  }
}
"""

HEADLINE_JS = r"""
() => {
  const h = document.querySelector('article h1, main h1, h1');
  if (!h) return false;
  h.scrollIntoView({block: 'start'});
  window.scrollBy(0, -120);
  window.__wrTarget = h;
  return true;
}
"""

# Where the target is right now (call just before the screenshot: late images can shift the page).
TARGET_BOXES_JS = r"""
() => {
  const t = window.__wrTarget;
  if (!t) return [];
  let r = t.getBoundingClientRect();
  if (r.top < innerHeight * 0.1 || r.bottom > innerHeight * 0.85) {
    window.scrollBy(0, r.top - innerHeight * 0.42);
  }
  return Array.from(t.getClientRects()).filter(q => q.width > 1 && q.height > 1)
              .map(q => [q.left, q.top, q.right, q.bottom]);
}
"""

SHOT_SCALE = 2  # screenshot pixels per CSS pixel: sharp enough for the camera to zoom in on a phrase


def merge_line_boxes(rects):
    """Join the boxes of one text line (a phrase split over <a>/<em> tags) into one box per line."""
    out = []
    for x0, y0, x1, y1 in sorted(rects, key=lambda r: (r[1], r[0])):
        if out:
            px0, py0, px1, py1 = out[-1]
            if abs(py0 - y0) < (y1 - y0) * 0.5 and abs(py1 - y1) < (y1 - y0) * 0.5:
                out[-1] = (min(px0, x0), min(py0, y0), max(px1, x1), max(py1, y1))
                continue
        out.append((x0, y0, x1, y1))
    return out


BLOCKED_TITLE = re.compile(r"just a moment|access denied|attention required|are you a robot|captcha|403 forbidden", re.I)


def shot_cache_path(url, phrase, cache_dir):
    host = re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc) or "page"
    digest = hashlib.sha1(f"v2|{url}|{phrase}".encode("utf-8")).hexdigest()[:8]
    return Path(cache_dir) / f"{re.sub(r'[^a-z0-9.-]+', '-', host.lower())}-{digest}.png"


class _BrowserGrabber:
    """Captures news-article screenshots in a hidden Chromium browser (Playwright)."""

    def __init__(self):
        self._pw = self._browser = None

    def _page(self):
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as err:
                raise RuntimeError("automatic screenshots need: pip install playwright && "
                                   "python -m playwright install chromium") from err
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                executable_path=os.environ.get("WR_CHROMIUM") or None,
                args=["--disable-blink-features=AutomationControlled"])
        page = self._browser.new_page(
            viewport={"width": 1280, "height": 800}, device_scale_factor=SHOT_SCALE, locale="en-US",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.set_default_timeout(15000)
        return page

    def capture(self, url, phrase, out_path):
        """Save a screenshot plus <name>.json with where the phrase (or headline) is on it.
        Returns a note (e.g. 'phrase not found') or raises RuntimeError."""
        page = self._page()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as err:  # timeouts, DNS errors…
                raise RuntimeError(f"page didn't load ({type(err).__name__})") from err
            page.wait_for_timeout(2500)
            if BLOCKED_TITLE.search(page.title() or ""):
                page.wait_for_timeout(6000)  # some bot checks pass on their own after a few seconds
                if BLOCKED_TITLE.search(page.title() or ""):
                    raise RuntimeError("the site blocked the automatic browser")
            self._dismiss(page, url)
            page.wait_for_timeout(1500)
            self._dismiss(page, url)  # pop-ups that appear late
            note, found = None, False
            if phrase:
                found = page.evaluate(FIND_PHRASE_JS, phrase)
                if not found:
                    note = f"phrase '{phrase}' not found, focused on the headline"
            if not found and not page.evaluate(HEADLINE_JS):
                note = (note or "no headline found") + ", used the top of the page"
            page.wait_for_timeout(800)
            self._dismiss(page, url)
            boxes = page.evaluate(TARGET_BOXES_JS)
            page.wait_for_timeout(150)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path), timeout=20000)
            info = {"boxes": [[round(v * SHOT_SCALE) for v in b] for b in merge_line_boxes(boxes)],
                    "mark": bool(found)}
            Path(out_path).with_suffix(".json").write_text(json.dumps(info), encoding="utf-8")
            return note
        finally:
            page.close()

    @staticmethod
    def _dismiss(page, url):
        try:
            page.evaluate(DISMISS_JS)
        except Exception:
            pass
        page.wait_for_timeout(300)
        if urllib.parse.urlparse(page.url).netloc != urllib.parse.urlparse(url).netloc:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)  # a click left the article
            page.wait_for_timeout(2000)
        # Consent banners inside iframes (e.g. Sourcepoint, OneTrust): click their accept button.
        for frame in page.frames[1:8]:
            if re.search(r"consent|cmp|privacy|sp_message|cookie", frame.url or "", re.I):
                try:
                    frame.locator("button").filter(
                        has_text=re.compile(r"accept|agree|allow|ok|continue", re.I)).first.click(timeout=1500)
                except Exception:
                    pass

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


class Grabber:
    """Runs each capture in its own process with a time limit, so one stuck page
    can never freeze the whole video build."""

    def __init__(self, time_limit=90):
        self.time_limit = time_limit

    def capture(self, url, phrase, out_path):
        cmd = [sys.executable, os.path.abspath(__file__), "--grab", url, phrase or "", str(out_path)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.time_limit)
        except subprocess.TimeoutExpired as err:
            raise RuntimeError(f"page took longer than {self.time_limit}s") from err
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        if not lines:
            raise RuntimeError("screenshot helper crashed: " + (proc.stderr.strip().splitlines() or ["?"])[-1])
        result = json.loads(lines[-1])
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result.get("note")

    def close(self):
        pass


def _grab_main(url, phrase, out_path):
    grabber = _BrowserGrabber()
    try:
        note = grabber.capture(url, phrase, out_path)
        print(json.dumps({"note": note}))
    except Exception as err:
        print(json.dumps({"error": str(err)}))
    finally:
        try:
            grabber.close()
        except Exception:
            pass


# ---------------------------------------------------------------- rendering

def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(cmd) + "\n" + proc.stderr[-1500:])


def encode_args(preset):
    return ["-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]


NAVY_HEX = "0x{:02x}{:02x}{:02x}".format(*NAVY)
MARKER = (255, 226, 77)


def fade_filter(frames, fade):
    """Dip-to-navy transition at both ends of a shot (skipped for very short shots)."""
    dur = frames / FPS
    d = min(fade, dur / 4)
    if d < 0.08:
        return "null"
    return (f"fade=t=in:st=0:d={d:.3f}:color={NAVY_HEX},"
            f"fade=t=out:st={dur - d:.3f}:d={d:.3f}:color={NAVY_HEX}")


MOTIONS = {"cover": ("in", "right", "out", "left"), "person": ("in", "out"),
           "card": ("in", "out"), "contain": ("in", "out")}


def camera_box(motion, p, w, h, amount=0.05):
    """The part of a w x h canvas to show at progress p (0..1) for a Ken Burns move."""
    z = {"in": 1 + amount * p, "out": 1 + amount * (1 - p)}.get(motion, 1 + amount if motion != "none" else 1)
    bw, bh = w / z, h / z
    x0 = {"left": (w - bw) * (1 - p), "right": (w - bw) * p}.get(motion, (w - bw) / 2)
    return (x0, (h - bh) / 2, x0 + bw, (h - bh) / 2 + bh)


class ImageScene:
    """A still image with a slow camera move (push in, pull out or pan)."""

    def __init__(self, canvas, n, size, motion):
        self.canvas, self.n, self.size, self.motion = canvas, n, size, motion

    def frame(self, i, t):
        from PIL import Image
        w, h = self.size
        if self.motion == "none":
            return self.canvas.copy()
        box = camera_box(self.motion, i / max(self.n - 1, 1), w, h)
        return self.canvas.resize((w, h), Image.BILINEAR, box=box)


class ChartScene(ImageScene):
    """A chart that draws itself in from left to right, then slowly pushes in."""

    def __init__(self, canvas, n, size, motion, animate=True):
        super().__init__(canvas, n, size, motion)
        from PIL import Image
        self.animate = animate
        self.bg = Image.new("RGB", size, canvas.getpixel((2, 2)))
        w, h = size
        self.ramp_w = max(2, int(w * 0.08))
        self.ramp = Image.linear_gradient("L").rotate(90, expand=True).resize((self.ramp_w, h))

    def frame(self, i, t):
        from PIL import Image
        img = super().frame(i, t)
        p = ease_in_out(progress(t, 0.0, 1.0)) if self.animate else 1
        if p >= 1:
            return img
        w, h = self.size
        edge = int(-self.ramp_w + (w + self.ramp_w) * p)
        mask = Image.new("L", (w, h), 0)
        if edge > 0:
            mask.paste(255, (0, 0, edge, h))
        mask.paste(self.ramp.transpose(Image.FLIP_LEFT_RIGHT), (edge, 0))
        return Image.composite(img, self.bg, mask)


def highlighted(region):
    """The region as if run over with a highlighter pen: yellow background, dark text.
    Works on any page colour (dark text on white, white text on a coloured header...)."""
    from PIL import Image, ImageChops
    gray = region.convert("L")
    hist = gray.histogram()
    half, seen, bg = sum(hist) / 2, 0, 0
    for level, count in enumerate(hist):  # median brightness = the background
        seen += count
        if seen >= half:
            bg = level
            break
    diff = ImageChops.difference(gray, Image.new("L", gray.size, bg))
    top = max(diff.getextrema()[1], 60)
    ink = diff.point(lambda v: min(255, int(v * 255 / top * 1.15)))
    return Image.composite(Image.new("RGB", region.size, (22, 22, 28)), Image.new("RGB", region.size, MARKER), ink)


class FocusScene:
    """A web-page screenshot: the camera glides from the whole page to the key phrase,
    then a yellow highlighter sweeps across it, line by line."""

    def __init__(self, path, info, n, size, animate=True):
        from PIL import Image, ImageDraw
        w, h = size
        self.size, self.n, self.animate = size, n, animate
        W, H = 2 * w, 2 * h  # work at 2x so the zoomed-in text stays sharp
        src = Image.open(path).convert("RGB")
        canvas = _navy_background((W, H))
        s = min(W * 0.86 / src.width, H * 0.82 / src.height)
        im = src.resize((max(1, round(src.width * s)), max(1, round(src.height * s))), Image.LANCZOS)
        ox, oy = (W - im.width) // 2, (H - im.height) // 2
        ImageDraw.Draw(canvas).rectangle([(ox + 24, oy + 24), (ox + im.width + 24, oy + im.height + 24)],
                                         fill=(3, 12, 28))
        canvas.paste(im, (ox, oy))
        boxes = []
        for x0, y0, x1, y1 in info.get("boxes", []):
            x0, x1 = max(0, x0), min(src.width, x1)
            y0, y1 = max(0, y0), min(src.height, y1)
            if x1 - x0 > 2 and y1 - y0 > 2:
                pad_x, pad_y = (y1 - y0) * 0.12, (y1 - y0) * 0.06
                boxes.append((round(ox + (x0 - pad_x) * s), round(oy + (y0 - pad_y) * s),
                              round(ox + (x1 + pad_x) * s), round(oy + (y1 + pad_y) * s)))
        self.work, self.full = canvas, (0, 0, W, H)
        self.mark = bool(info.get("mark")) and bool(boxes)
        self.boxes, self.done = boxes, [0] * len(boxes)
        if self.mark:
            marked = canvas.copy()
            for b in boxes:
                marked.paste(highlighted(canvas.crop(b)), b[:2])
            self.marked = marked
        page = (ox, oy, ox + im.width, oy + im.height)
        self.target = self._target(boxes, page, W, H) if boxes else None

    @staticmethod
    def _target(boxes, page, W, H):
        """A 16:9 view around the phrase, wide enough to read its whole line, inside the page if possible."""
        ux0, uy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        ux1, uy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        bw = min(W, max((ux1 - ux0) * 1.4, W * 0.62, (uy1 - uy0) * 2.4 * W / H))
        bh = bw * H / W
        cx, cy = (ux0 + ux1) / 2, (uy0 + uy1) / 2 + bh * 0.05
        px0, py0, px1, py1 = page
        lo_x, hi_x = (px0, px1 - bw) if px1 - px0 >= bw else (0, W - bw)
        lo_y, hi_y = (py0, py1 - bh) if py1 - py0 >= bh else (0, H - bh)
        x0, y0 = _clamp(cx - bw / 2, lo_x, hi_x), _clamp(cy - bh / 2, lo_y, hi_y)
        return (x0, y0, x0 + bw, y0 + bh)

    def frame(self, i, t):
        from PIL import Image
        w, h = self.size
        tt = t if self.animate else 99
        if self.mark:  # sweep the highlighter across each line in turn (monotonic, drawn into self.work)
            widths = [b[2] - b[0] for b in self.boxes]
            total, sweep = sum(widths), ease_in_out(progress(tt, 1.0, 0.35 + 0.25 * len(self.boxes)))
            reach = sweep * total
            for k, b in enumerate(self.boxes):
                upto = int(_clamp(reach, 0, widths[k]))
                reach -= widths[k]
                if upto > self.done[k]:
                    piece = (b[0] + self.done[k], b[1], b[0] + upto, b[3])
                    self.work.paste(self.marked.crop(piece), piece[:2])
                    self.done[k] = upto
        if self.target:
            p = ease_in_out(progress(tt, 0.2, 1.0))
            box = tuple(f + (g - f) * p for f, g in zip(self.full, self.target))
            drift = 1 - 0.03 * progress(t, 1.2, max(self.n / FPS - 1.2, 0.1))  # keep moving gently
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            bw, bh = (box[2] - box[0]) * drift, (box[3] - box[1]) * drift
            box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        else:
            W, H = self.full[2], self.full[3]
            box = camera_box("in", i / max(self.n - 1, 1), W, H)
        return self.work.resize((w, h), Image.BILINEAR, box=box)


class TextScene:
    """Navy text card: slowly drifting glow background, headline and subline animate in."""

    def __init__(self, value, n, size, font_path, start=0.15):
        w, h = size
        self.size, self.n = size, n
        self.bg = _glow_background(size)
        self.block = TextBlock(value, size, font_path, x=w / 2, y_center=h / 2, max_w=int(w * 0.82),
                               align="center", head=0.11, sub=0.045, max_lines=3, start=start)

    def frame(self, i, t):
        from PIL import Image
        w, h = self.size
        p = i / max(self.n - 1, 1)
        W, H = self.bg.size
        x0, y0 = (W - w) * (0.15 + 0.7 * p), (H - h) * (0.6 - 0.2 * p)
        img = self.bg.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))
        self.block.draw(img, t)
        return img


class VideoScene:
    """Frames of a (looped) video clip, decoded by ffmpeg so animated layers can be drawn on top."""

    def __init__(self, clip, n, size):
        w, h = size
        self.size, self.nbytes, self.last = size, w * h * 3, None
        cmd = ["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-i", str(clip), "-vf",
               f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1",
               "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def frame(self, i, t):
        from PIL import Image
        data = self.proc.stdout.read(self.nbytes)
        if len(data) == self.nbytes:
            self.last = data
        elif self.last is None:
            return Image.new("RGB", self.size, NAVY)
        return Image.frombytes("RGB", self.size, self.last)

    def close(self):
        self.proc.stdout.close()
        self.proc.wait()


def encode_frames(scene, layers, frames, out, size, preset, fade=0.25):
    """Render each frame in Python (scene + animated layers) and pipe it into ffmpeg."""
    w, h = size
    cmd = (["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
            "-r", str(FPS), "-i", "-", "-vf", fade_filter(frames, fade), "-frames:v", str(frames)]
           + encode_args(preset) + [str(out)])
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / FPS
            img = scene.frame(i, t)
            for layer in layers:
                layer.draw(img, t)
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        if hasattr(scene, "close"):
            scene.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding a shot:\n" + err[-1500:])


def render_video_job(clip, frames, out, size, preset, fade=0.25):
    """A clip with nothing drawn on top: let ffmpeg do it all (fastest)."""
    w, h = size
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1,"
          + fade_filter(frames, fade))
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(clip), "-vf", vf,
         "-frames:v", str(frames)] + encode_args(preset) + [str(out)])


def render_job(job, index, frames, out, size, preset, font_path, zoom=True, animate=True, fade=0.25):
    """Build the scene + layers for one shot and encode it."""
    w, h = size
    still = (lambda layer: layer) if animate else _Finished  # --no-animations: text shows at once
    layers = []
    if job.get("overlay"):
        layers.append(still(LowerThird(job["overlay"], size, font_path)))
    if job.get("subscribe") is not None:  # the call to action always plays, sped up to fit a short shot
        start = min(job["subscribe"], max(0.3, frames / FPS - SubscribeAnim.DURATION - 0.2))
        speed = max(1.0, SubscribeAnim.DURATION / max(frames / FPS - start - 0.15, 1.5))
        layers.append(SubscribeAnim(size, font_path, start=start, high=bool(job.get("overlay")), speed=speed))

    mode = job["mode"]
    if mode == "video":
        if not layers:
            render_video_job(job["path"], frames, out, size, preset, fade)
            return
        scene = VideoScene(job["path"], frames, size)
    elif mode == "text":
        scene = TextScene(job["value"], frames, size, font_path, start=0.15 if animate else -99)
    elif mode == "focus":
        scene = FocusScene(job["path"], job["info"], frames, size, animate)
    else:
        fit = job["fit"]
        motions = MOTIONS.get(fit, ("in",))
        motion = motions[index % len(motions)] if zoom else "none"
        canvas = prepare_canvas(job["path"], fit, size)
        if fit == "contain" and job.get("chart"):
            scene = ChartScene(canvas, frames, size, motion, animate)
        else:
            scene = ImageScene(canvas, frames, size, motion)
        if fit == "person":
            layers.insert(0, still(TextBlock(job.get("label") or "", size, font_path, x=int(w * 0.48),
                                             y_bottom=int(h * 0.62), max_w=int(w * 0.45), start=0.3)))
    encode_frames(scene, layers, frames, out, size, preset, fade)


class _Finished:
    """Draws a text layer in its finished state from the first frame."""

    def __init__(self, layer):
        self.layer = layer

    def draw(self, frame, t):
        self.layer.draw(frame, 99)


def resolve(value, base_dir):
    return (Path(base_dir) / value) if not Path(value).is_absolute() else Path(value)


def _is_url(value):
    return bool(re.match(r"https?://", value.strip(), re.I))


def split_extras(kind, value):
    """'stock: money >> $1B | raised >> @subscribe' -> ('money', '$1B | raised', True)."""
    parts = [part.strip() for part in value.split(">>")]
    value, rest = parts[0], parts[1:]
    subscribe = any(part.lower() == "@subscribe" for part in rest)
    texts = [part for part in rest if part.lower() != "@subscribe"]
    return value, (texts[0] if texts and kind != "text" else None), subscribe


def subscribe_moment(timings, timeline):
    """Where the voiceover first says 'subscribe': (shot index, seconds into that shot)."""
    paras = timings["paragraphs"]
    for k, para in enumerate(paras):
        m = re.search(r"\bsubscribe\b", para.get("text", ""), re.I)
        if not m:
            continue
        start = 0.0 if k == 0 else para["start"]
        end = paras[k + 1]["start"] if k + 1 < len(paras) else timings["duration"]
        said = para["start"] + (para["end"] - para["start"]) * m.start() / max(len(para["text"]), 1)
        at = min(max(said - 0.4, start), end - 0.1)
        for i, (s0, s1, *_) in enumerate(timeline):
            if s0 <= at < s1:
                return i, max(0.3, at - s0)
    return None


def make_video(audio, shots_path, out, size=(1920, 1080), preset="veryfast", music=None,
               music_volume=0.12, zoom=True, font=None, stock_keys=None, stock_dir="stock",
               fetch=fetch_asset, person_lookup=wikipedia_photo, grabber_factory=Grabber,
               fade=0.25, workers=None, animate=True, subscribe=True):
    audio = Path(audio)
    timings_path = audio.with_suffix(".timings.json")
    if not timings_path.exists():
        sys.exit(f"Can't find {timings_path.name}. Re-run voiceover.py — it writes this file next to the .wav.")
    timings = json.loads(timings_path.read_text(encoding="utf-8"))
    shots_path = Path(shots_path)
    shots = parse_shots(shots_path.read_text(encoding="utf-8"))
    base = shots_path.parent

    known = {p["n"] for p in timings["paragraphs"]}
    extra = sorted(set(shots) - known)
    if extra:
        print(f"Note: shot list mentions paragraphs {extra} that aren't in the voiceover — ignored.",
              file=sys.stderr)

    timeline = build_timeline(timings, shots)
    frames = frame_counts(timeline)
    font_path = find_font(font)
    warnings, notes, credits, seen = [], [], [], {}
    asked_subscribe = set()
    stock_keys = stock_keys or {}
    grabber = None

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        jobs = []

        # Pass 1: fetch/capture every asset and turn each shot into a render job.
        for i, (start, end, kind, value) in enumerate(timeline):
            print(f"  preparing shot {i + 1}/{len(timeline)} ({kind})", file=sys.stderr)
            value, overlay, wants_subscribe = split_extras(kind, value)
            if wants_subscribe:
                asked_subscribe.add(i)
            job = None
            try:
                if kind in STOCK_TYPES | PHOTO_TYPES:
                    occurrence = seen.get((kind, value), 0)
                    seen[(kind, value)] = occurrence + 1
                    got = fetch(value, occurrence, base / stock_dir, stock_keys, kind)
                    if got:
                        if kind in PHOTO_TYPES:
                            job = {"mode": "image", "path": got, "fit": "cover"}
                        else:
                            job = {"mode": "video", "path": got}
                        if stock_keys.get("pixabay"):
                            credits.append("Stock footage and photos: Pixabay")
                    else:
                        ext = ".jpg" if kind in PHOTO_TYPES else ".mp4"
                        wanted = stock_path(value, occurrence, Path(stock_dir), ext).as_posix()
                        warnings.append(f"{'photo' if ext == '.jpg' else 'stock clip'} '{value}' -> save one as {wanted}")
                elif kind in PERSON_TYPES:
                    try:
                        path, credit = fetch_person(value, base / "people", lookup=person_lookup)
                        job = {"mode": "image", "path": path, "fit": "person", "label": overlay or value}
                        overlay = None
                        if credit:
                            credits.append(credit)
                    except (LookupError, urllib.error.URLError, OSError, ValueError) as err:
                        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
                        warnings.append(f"no photo of {value} ({err}) -> save one as people/{slug}.jpg")
                elif kind in IMAGE_TYPES and _is_url(value):
                    url, _, phrase = (part.strip() for part in value.partition("|"))
                    target = shot_cache_path(url, phrase, base / "screenshots" / "auto")
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            grabber = grabber or grabber_factory()
                            note = grabber.capture(url, phrase, target)
                            if note:
                                notes.append(f"{url}: {note}")
                        except Exception as err:
                            rel = target.relative_to(base).as_posix()
                            warnings.append(f"screenshot of {url} failed ({err}) -> save one by hand as {rel}")
                    if target.exists():
                        info_path = target.with_suffix(".json")
                        info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
                        job = {"mode": "focus", "path": target, "info": info}
                elif kind in IMAGE_TYPES | VIDEO_TYPES:
                    path = resolve(value, base)
                    if path.exists():
                        if kind in VIDEO_TYPES:
                            job = {"mode": "video", "path": path}
                        elif path.with_suffix(".json").exists():  # a capture that knows where its phrase is
                            info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
                            job = {"mode": "focus", "path": path, "info": info}
                        else:
                            job = {"mode": "image", "path": path, "fit": "contain" if kind == "chart" else "card",
                                   "chart": kind == "chart"}
                    else:
                        warnings.append(f"missing file {value}")
            except RuntimeError as err:
                warnings.append(str(err))
            if job is None:
                job = {"mode": "text", "value": value if kind == "text" else f"MISSING | {value}"}
                overlay = None
            job["overlay"] = overlay
            jobs.append(job)
        if grabber:
            grabber.close()

        # The animated subscribe button: where the shot list asks for it (">> @subscribe"),
        # otherwise when the voiceover first says "subscribe".
        if asked_subscribe:
            for i in asked_subscribe:
                jobs[i]["subscribe"] = 0.6
        elif subscribe:
            moment = subscribe_moment(timings, timeline)
            if moment:
                jobs[moment[0]]["subscribe"] = moment[1]

        # Pass 2: render all shots in parallel.
        seg_paths = [tmp / f"seg{i:04d}.mp4" for i in range(len(jobs))]

        def render(i):
            render_job(jobs[i], i, frames[i], seg_paths[i], size, preset, font_path, zoom, animate, fade)
            return i

        workers = workers or max(1, min(4, os.cpu_count() or 1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for done, _ in enumerate(pool.map(render, range(len(jobs))), 1):
                print(f"  rendered {done}/{len(jobs)}", file=sys.stderr)

        concat = tmp / "list.txt"
        concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_paths), encoding="utf-8")
        silent = tmp / "silent.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
             "-c", "copy", str(silent)])

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio)]
        if music:
            cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                    f"[2:a]volume={music_volume}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]"]
        else:
            cmd += ["-map", "0:v", "-map", "1:a"]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        run(cmd)

    credits = list(dict.fromkeys(credits))
    if credits:
        (base / "credits.txt").write_text(
            "Paste these into the video description:\n\n" + "\n".join(credits) + "\n", encoding="utf-8")
    return timeline, warnings + [f"note: {n}" for n in notes]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--grab"] and len(argv) == 4:  # internal: one screenshot per process
        _grab_main(argv[1], argv[2], argv[3])
        return
    p = argparse.ArgumentParser(description="Auto-edit a video from a voiceover and a shot list.")
    p.add_argument("audio", help="voiceover .wav from voiceover.py (its .timings.json must be next to it)")
    p.add_argument("shots", help="shot list .txt (see SHOTS.md)")
    p.add_argument("--out", help="output .mp4 (default: <audio name>.mp4)")
    p.add_argument("--preview", action="store_true", help="fast 960x540 draft to check timing")
    p.add_argument("--music", help="optional background music file (looped, quiet)")
    p.add_argument("--music-volume", type=float, default=0.12, help="music level, 0–1 (default 0.12)")
    p.add_argument("--no-zoom", action="store_true", help="no slow camera moves on images")
    p.add_argument("--no-animations", action="store_true",
                   help="text appears at once, no highlighter sweep or chart reveal")
    p.add_argument("--no-subscribe", action="store_true",
                   help="don't add the subscribe animation where the voiceover says 'subscribe'")
    p.add_argument("--fade", type=float, default=0.25, help="transition length in seconds (0 = hard cuts)")
    p.add_argument("--workers", type=int, help="shots rendered at once (default: up to 4)")
    p.add_argument("--font", help="path to a .ttf font for text cards")
    args = p.parse_args(argv)

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg isn't installed or not on PATH. Windows: winget install Gyan.FFmpeg "
                 "(then reopen PowerShell). Mac: brew install ffmpeg.")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow isn't installed. Run:  pip install pillow")

    size, preset = ((960, 540), "ultrafast") if args.preview else ((1920, 1080), "veryfast")
    audio = Path(args.audio)
    out = Path(args.out) if args.out else audio.with_name(audio.stem + ("_preview" if args.preview else "") + ".mp4")
    print(f"Building {out} ...", file=sys.stderr)
    timeline, warnings = make_video(audio, args.shots, out, size=size, preset=preset, music=args.music,
                                    music_volume=args.music_volume, zoom=not args.no_zoom, font=args.font,
                                    stock_keys={"pixabay": os.environ.get("PIXABAY_API_KEY"),
                                                "pexels": os.environ.get("PEXELS_API_KEY")},
                                    fade=args.fade, workers=args.workers, animate=not args.no_animations,
                                    subscribe=not args.no_subscribe)
    print(f"Done: {out} ({len(timeline)} shots)")
    real = [w for w in warnings if not w.startswith("note: ")]
    notes = [w[6:] for w in warnings if w.startswith("note: ")]
    if notes:
        print("\nNotes:")
        for n in dict.fromkeys(notes):
            print(f"  - {n}")
    if real:
        print("\nPlaceholders were used for:")
        for w in dict.fromkeys(real):
            print(f"  - {w}")
        print("Add those files (or set PIXABAY_API_KEY for automatic stock clips) and run again.")
    credits = Path(args.shots).parent / "credits.txt"
    if credits.exists():
        print(f"\nPhoto/stock credits for your description: {credits}")


if __name__ == "__main__":
    main()
