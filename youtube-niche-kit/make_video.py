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
">>" puts a text overlay (headline | smaller line) on top of any visual.
Several lines for the same paragraph split its time evenly, in order.
Paragraphs with no line keep showing the previous visual.
"""

import argparse
import concurrent.futures
import hashlib
import html
import json
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


def render_text_card(value, out_path, size, font_path):
    """Navy card with a big headline and optional '| subline'."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    img = Image.new("RGB", (w, h), NAVY)
    draw = ImageDraw.Draw(img)
    for y in range(h):  # soft vertical gradient
        t = 1 - abs(y - h / 2) / (h / 2)
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t * 0.6) for a, b in zip(NAVY, NAVY_2)))

    headline, _, sub = (part.strip() for part in value.partition("|"))

    def load(px):
        if font_path:
            return ImageFont.truetype(font_path, px)
        try:
            return ImageFont.load_default(size=px)
        except TypeError:  # Pillow < 10.1
            return ImageFont.load_default()

    def wrap(text, font, max_w):
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        return lines + ([line] if line else [])

    max_w = int(w * 0.82)
    head_px = int(h * 0.11)
    while True:
        head_font = load(head_px)
        head_lines = wrap(headline, head_font, max_w)
        if len(head_lines) <= 3 or head_px <= int(h * 0.05):
            break
        head_px = int(head_px * 0.88)
    sub_font = load(int(h * 0.045))
    sub_lines = wrap(sub, sub_font, max_w) if sub else []

    # Lay out with real font metrics so descenders (g, p, y) never touch the accent bar.
    try:
        ascent, descent = head_font.getmetrics()
    except AttributeError:
        ascent, descent = head_px, int(head_px * 0.25)
    head_text_h = ascent + descent
    line_h = int(head_text_h * 1.02)
    sub_h = int(h * 0.045 * 1.35)
    bar_w, bar_h = int(w * 0.07), max(4, int(h * 0.006))
    space = int(h * 0.03)  # gap above and below the accent bar
    head_block = (len(head_lines) - 1) * line_h + head_text_h
    sub_block = (2 * space + bar_h + len(sub_lines) * sub_h) if sub_lines else 0
    y = (h - head_block - sub_block) // 2
    for line in head_lines:
        lw = draw.textlength(line, font=head_font)
        draw.text(((w - lw) / 2, y), line, font=head_font, fill=WHITE)
        y += line_h
    if sub_lines:
        y += head_text_h - line_h + space  # bottom of the last headline line, plus space
        draw.rounded_rectangle([((w - bar_w) / 2, y), ((w + bar_w) / 2, y + bar_h)],
                               radius=bar_h // 2, fill=CYAN)
        y += bar_h + space
        for line in sub_lines:
            lw = draw.textlength(line, font=sub_font)
            draw.text(((w - lw) / 2, y), line, font=sub_font, fill=MUTED)
            y += sub_h
    img.save(out_path)




# ---------------------------------------------------------------- layouts

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


def _navy_background(size):
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGB", (w, h), NAVY)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = 1 - abs(y - h / 2) / (h / 2)
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t * 0.6) for a, b in zip(NAVY, NAVY_2)))
    return img


def _draw_text_block(draw, x, y_bottom, text, size, font_path, max_w):
    """Left-aligned 'Headline | subline' block whose bottom sits at y_bottom."""
    w, h = size
    headline, _, sub = (part.strip() for part in text.partition("|"))
    head_px = int(h * 0.07)
    while True:
        head_font = _font(font_path, head_px)
        head_lines = _wrap(draw, headline, head_font, max_w)
        if len(head_lines) <= 2 or head_px <= int(h * 0.04):
            break
        head_px = int(head_px * 0.88)
    sub_font = _font(font_path, int(h * 0.036))
    sub_lines = _wrap(draw, sub, sub_font, max_w) if sub else []
    try:
        ascent, descent = head_font.getmetrics()
    except AttributeError:
        ascent, descent = head_px, int(head_px * 0.25)
    line_h, sub_h = ascent + descent, int(h * 0.036 * 1.35)
    bar_h, space = max(4, int(h * 0.007)), int(h * 0.018)
    block = bar_h + space + len(head_lines) * line_h + (space + len(sub_lines) * sub_h if sub_lines else 0)
    y = y_bottom - block
    draw.rounded_rectangle([(x, y), (x + int(w * 0.06), y + bar_h)], radius=bar_h // 2, fill=CYAN)
    y += bar_h + space
    for line in head_lines:
        draw.text((x, y), line, font=head_font, fill=WHITE)
        y += line_h
    if sub_lines:
        y += space
        for line in sub_lines:
            draw.text((x, y), line, font=sub_font, fill=MUTED)
            y += sub_h


def render_overlay(text, size, font_path):
    """Transparent lower-third: navy fade at the bottom with a headline and optional subline."""
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    top = int(h * 0.42)
    for y in range(top, h):
        a = int(225 * ((y - top) / (h - top)) ** 1.3)
        sd.line([(0, y), (w, y)], fill=NAVY + (a,))
    img = Image.alpha_composite(img, shade)
    _draw_text_block(ImageDraw.Draw(img), int(w * 0.06), int(h * 0.9), text, size, font_path, int(w * 0.8))
    return img


def prepare_canvas(path, fit, size, font_path, label=None):
    """Turn an image file into a full frame. fit: contain | card | cover | person."""
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
        _draw_text_block(ImageDraw.Draw(canvas), int(w * 0.48), int(h * 0.62), label or "", size, font_path,
                         int(w * 0.45))
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

HIGHLIGHT_JS = r"""
(phrase) => {
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(phrase.trim().split(/\s+/).map(esc).join('\\s+'), 'i');
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const m = re.exec(node.nodeValue);
    if (!m || !node.parentElement || node.parentElement.offsetParent === null) continue;
    const range = document.createRange();
    range.setStart(node, m.index);
    range.setEnd(node, m.index + m[0].length);
    const mark = document.createElement('mark');
    mark.style.cssText = 'background:#ffe14d;color:#000;padding:0 3px;border-radius:3px;box-shadow:0 0 0 3px #ffe14d';
    range.surroundContents(mark);
    mark.scrollIntoView({block: 'center'});
    return true;
  }
  return false;
}
"""

HEADLINE_JS = r"""
() => {
  const h = document.querySelector('article h1, main h1, h1');
  if (!h) return false;
  h.scrollIntoView({block: 'start'});
  window.scrollBy(0, -120);
  return true;
}
"""

BLOCKED_TITLE = re.compile(r"just a moment|access denied|attention required|are you a robot|captcha|403 forbidden", re.I)


def shot_cache_path(url, phrase, cache_dir):
    host = re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc) or "page"
    digest = hashlib.sha1(f"{url}|{phrase}".encode("utf-8")).hexdigest()[:8]
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
            viewport={"width": 1280, "height": 800}, device_scale_factor=1.5, locale="en-US",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.set_default_timeout(15000)
        return page

    def capture(self, url, phrase, out_path):
        """Save a screenshot; returns a note (e.g. 'phrase not found') or raises RuntimeError."""
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
            note = None
            if phrase:
                if not page.evaluate(HIGHLIGHT_JS, phrase):
                    note = f"phrase '{phrase}' not found, used the headline"
                    page.evaluate(HEADLINE_JS)
            elif not page.evaluate(HEADLINE_JS):
                note = "no headline found, used the top of the page"
            page.wait_for_timeout(800)
            self._dismiss(page, url)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path), timeout=20000)
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


def fade_filter(frames, fade):
    """Dip-to-navy transition at both ends of a shot (skipped for very short shots)."""
    dur = frames / FPS
    d = min(fade, dur / 4)
    if d < 0.08:
        return "null"
    return (f"fade=t=in:st=0:d={d:.3f}:color={NAVY_HEX},"
            f"fade=t=out:st={dur - d:.3f}:d={d:.3f}:color={NAVY_HEX}")


def render_image_job(canvas, frames, out, size, preset, zoom=True, fade=0.25):
    """Encode a still frame, with a smooth sub-pixel 4% push-in when zoom is on."""
    from PIL import Image
    w, h = size
    vf = fade_filter(frames, fade)
    if not zoom:
        still = Path(out).with_suffix(".png")
        canvas.save(still)
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(still), "-vf", vf,
             "-frames:v", str(frames)] + encode_args(preset) + [str(out)])
        return
    cmd = (["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
            "-r", str(FPS), "-i", "-", "-vf", vf, "-frames:v", str(frames)] + encode_args(preset) + [str(out)])
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            z = 1 + 0.04 * i / max(frames - 1, 1)
            bw, bh = w / z, h / z
            x0, y0 = (w - bw) / 2, (h - bh) / 2
            proc.stdin.write(canvas.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + bw, y0 + bh)).tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding a zoomed image:\n" + err[-1500:])


def render_video_job(clip, frames, out, size, preset, overlay_png=None, fade=0.25):
    w, h = size
    graph = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[b];"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(clip)]
    if overlay_png:
        cmd += ["-loop", "1", "-i", str(overlay_png)]
        graph += "[b][1:v]overlay=0:0[c];"
    else:
        graph += "[b]null[c];"
    graph += f"[c]{fade_filter(frames, fade)}[v]"
    run(cmd + ["-filter_complex", graph, "-map", "[v]", "-frames:v", str(frames)]
        + encode_args(preset) + [str(out)])


def resolve(value, base_dir):
    return (Path(base_dir) / value) if not Path(value).is_absolute() else Path(value)


def _is_url(value):
    return bool(re.match(r"https?://", value.strip(), re.I))


def make_video(audio, shots_path, out, size=(1920, 1080), preset="veryfast", music=None,
               music_volume=0.12, zoom=True, font=None, stock_keys=None, stock_dir="stock",
               fetch=fetch_asset, person_lookup=wikipedia_photo, grabber_factory=Grabber,
               fade=0.25, workers=None):
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
    stock_keys = stock_keys or {}
    grabber = None

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        jobs = []

        # Pass 1: fetch/capture every asset and turn each shot into a render job.
        for i, (start, end, kind, value) in enumerate(timeline):
            print(f"  preparing shot {i + 1}/{len(timeline)} ({kind})", file=sys.stderr)
            overlay = None
            if kind != "text" and ">>" in value:
                value, _, overlay = (part.strip() for part in value.partition(">>"))
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
                        job = {"mode": "image", "path": target, "fit": "card"}
                elif kind in IMAGE_TYPES | VIDEO_TYPES:
                    path = resolve(value, base)
                    if path.exists():
                        if kind in VIDEO_TYPES:
                            job = {"mode": "video", "path": path}
                        else:
                            job = {"mode": "image", "path": path, "fit": "contain" if kind == "chart" else "card"}
                    else:
                        warnings.append(f"missing file {value}")
            except RuntimeError as err:
                warnings.append(str(err))
            if job is None:
                label = value if kind == "text" else f"MISSING | {value}"
                card = tmp / f"card{i:04d}.png"
                render_text_card(label, card, size, font_path)
                job = {"mode": "image", "path": card, "fit": "contain"}
                if kind == "text":
                    overlay = None
            job["overlay"] = overlay
            jobs.append(job)
        if grabber:
            grabber.close()

        # Pass 2: render all shots in parallel.
        seg_paths = [tmp / f"seg{i:04d}.mp4" for i in range(len(jobs))]

        def render(i):
            job, n = jobs[i], frames[i]
            if job["mode"] == "video":
                overlay_png = None
                if job["overlay"]:
                    overlay_png = tmp / f"overlay{i:04d}.png"
                    render_overlay(job["overlay"], size, font_path).save(overlay_png)
                render_video_job(job["path"], n, seg_paths[i], size, preset, overlay_png, fade)
            else:
                canvas = prepare_canvas(job["path"], job["fit"], size, font_path, job.get("label"))
                if job["overlay"]:
                    canvas = canvas.convert("RGBA")
                    canvas.alpha_composite(render_overlay(job["overlay"], size, font_path))
                    canvas = canvas.convert("RGB")
                render_image_job(canvas, n, seg_paths[i], size, preset, zoom, fade)
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
    p.add_argument("--no-zoom", action="store_true", help="static images instead of slow zoom (faster)")
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
                                    fade=args.fade, workers=args.workers)
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
