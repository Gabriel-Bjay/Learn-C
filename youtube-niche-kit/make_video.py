#!/usr/bin/env python3
"""
Auto-edit a Work Rewired video: voiceover + shot list -> finished 1080p MP4.

  python make_video.py quibi_voiceover.wav shots.txt
  python make_video.py quibi_voiceover.wav shots.txt --preview      # fast, low-res check
  python make_video.py quibi_voiceover.wav shots.txt --music bg.mp3

Needs: ffmpeg on PATH, Pillow (pip install pillow), and the .timings.json that
voiceover.py writes next to the .wav. Stock footage ("pexels:" lines) needs a free
Pexels API key in the PEXELS_API_KEY environment variable.

Shot list format (one visual per line; see SHOTS.md):
  1: image: screenshots/roku_headline.png
  2: text: $1.75 BILLION | raised before a single customer paid
  3-4: pexels: person watching phone on train
  5: video: clips/my_clip.mp4
Several lines for the same paragraph split its time evenly, in order.
Paragraphs with no line keep showing the previous visual.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
ALL_TYPES = IMAGE_TYPES | VIDEO_TYPES | {"text", "pexels"}

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
                             f"(use image, chart, screenshot, video, text or pexels)")
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


def pexels_search(query, api_key):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "per_page": 15})
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": "make_video/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def pick_pexels_file(video, target_w=1920):
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
    if not files:
        return None
    return min(files, key=lambda f: (f["width"] < 1280, abs(f["width"] - target_w)))["link"]


def fetch_pexels(query, occurrence, cache_dir, api_key, search=pexels_search, download=None):
    """Download (or reuse) a stock clip. Repeated queries get different clips."""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40]
    path = Path(cache_dir) / f"{slug}-{occurrence}.mp4"
    if path.exists():
        return path
    if not api_key:
        return None
    videos = search(query, api_key).get("videos", [])
    if not videos:
        return None
    link = pick_pexels_file(videos[occurrence % len(videos)])
    if not link:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    (download or _download)(link, path)
    return path


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "make_video/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as fh:
        shutil.copyfileobj(resp, fh)


# ---------------------------------------------------------------- rendering

def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(cmd) + "\n" + proc.stderr[-1500:])


def encode_args(preset):
    return ["-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]


def render_image_segment(image, frames, out, size, preset, zoom=True):
    w, h = size
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x{NAVY[0]:02x}{NAVY[1]:02x}{NAVY[2]:02x},setsar=1")
    if zoom:
        # Slow 4% push-in (Ken Burns). Upscale first so the motion is smooth.
        vf = (f"{fit},scale={w * 2}:{h * 2},"
              f"zoompan=z='1+0.04*on/{max(frames, 1)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={w}x{h}:fps={FPS}")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(image), "-vf", vf, "-frames:v", str(frames)]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image), "-vf", fit,
               "-frames:v", str(frames)]
    run(cmd + encode_args(preset) + [str(out)])


def render_video_segment(clip, frames, out, size, preset):
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1"
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(clip), "-vf", vf,
         "-frames:v", str(frames)] + encode_args(preset) + [str(out)])


def resolve(kind, value, base_dir):
    return (Path(base_dir) / value) if not Path(value).is_absolute() else Path(value)


def make_video(audio, shots_path, out, size=(1920, 1080), preset="veryfast", music=None,
               music_volume=0.12, zoom=True, font=None, pexels_key=None, stock_dir="stock",
               fetch=fetch_pexels):
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
    warnings, pexels_seen = [], {}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        seg_paths = []
        for i, ((start, end, kind, value), n_frames) in enumerate(zip(timeline, frames)):
            print(f"  segment {i + 1}/{len(timeline)} ({kind}, {end - start:.1f}s)", file=sys.stderr)
            seg = tmp / f"seg{i:04d}.mp4"
            if kind == "pexels":
                occurrence = pexels_seen.get(value, 0)
                pexels_seen[value] = occurrence + 1
                clip = fetch(value, occurrence, base / stock_dir, pexels_key)
                if clip:
                    kind, value = "video", str(clip)
                else:
                    warnings.append(f"no stock clip for '{value}' "
                                    f"({'set PEXELS_API_KEY' if not pexels_key else 'no results'})")
                    kind, value = "text", f"STOCK: {value}"
            if kind in IMAGE_TYPES | VIDEO_TYPES:
                path = resolve(kind, value, base)
                if not path.exists():
                    warnings.append(f"missing file {value}")
                    kind, value = "text", f"MISSING | {value}"
                else:
                    value = str(path)
            if kind == "text":
                card = tmp / f"card{i:04d}.png"
                render_text_card(value, card, size, font_path)
                render_image_segment(card, n_frames, seg, size, preset, zoom)
            elif kind in IMAGE_TYPES:
                render_image_segment(value, n_frames, seg, size, preset, zoom)
            else:
                render_video_segment(value, n_frames, seg, size, preset)
            seg_paths.append(seg)

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

    return timeline, warnings


def main(argv=None):
    p = argparse.ArgumentParser(description="Auto-edit a video from a voiceover and a shot list.")
    p.add_argument("audio", help="voiceover .wav from voiceover.py (its .timings.json must be next to it)")
    p.add_argument("shots", help="shot list .txt (see SHOTS.md)")
    p.add_argument("--out", help="output .mp4 (default: <audio name>.mp4)")
    p.add_argument("--preview", action="store_true", help="fast 960x540 draft to check timing")
    p.add_argument("--music", help="optional background music file (looped, quiet)")
    p.add_argument("--music-volume", type=float, default=0.12, help="music level, 0–1 (default 0.12)")
    p.add_argument("--no-zoom", action="store_true", help="static images instead of slow zoom (faster)")
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
                                    pexels_key=os.environ.get("PEXELS_API_KEY"))
    print(f"Done: {out} ({len(timeline)} shots)")
    if warnings:
        print("\nPlaceholders were used for:")
        for w in dict.fromkeys(warnings):
            print(f"  - {w}")
        print("Add those files (or a Pexels key) and run again for the final version.")


if __name__ == "__main__":
    main()
