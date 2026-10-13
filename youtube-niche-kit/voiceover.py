#!/usr/bin/env python3
"""
Turn a video script into an AI voiceover + captions, for free, on your own computer.

Uses Kokoro-82M (open-weight text-to-speech, Apache-2.0 licence — OK for monetized videos).

  python voiceover.py script.txt                    -> script.wav + script.srt
  python voiceover.py script.txt --voice bm_george  -> British male voice
  python voiceover.py --samples                     -> short sample of each suggested voice

Setup (once): Python 3.10–3.12, espeak-ng, then  pip install "kokoro>=0.9.4" soundfile
See VOICEOVER.md for step-by-step instructions.
"""

import argparse
import re
import sys
from pathlib import Path

SAMPLE_RATE = 24000
REPO_ID = "hexgrad/Kokoro-82M"

# A short list to start with. The full list (50+ voices) is in VOICES.md on
# huggingface.co/hexgrad/Kokoro-82M. First letter: a = American, b = British.
# Second letter: f = female, m = male.
SUGGESTED_VOICES = {
    "am_michael": "American male, calm — good default for business explainers",
    "am_fenrir": "American male, deeper",
    "af_heart": "American female, warm",
    "af_bella": "American female, energetic",
    "bm_george": "British male, documentary feel",
    "bm_fable": "British male, storyteller",
    "bf_emma": "British female, clear",
}

SAMPLE_TEXT = (
    "In 2020, a start-up raised one point seven five billion dollars. "
    "Six months later, it was gone. Here's how the money disappeared."
)


# ---------------------------------------------------------------- text prep

def clean_script(raw):
    """Strip markdown and stage directions so only spoken words remain.

    Returns a list of paragraphs (blank lines in the script = paragraph breaks).
    """
    paragraphs, current = [], []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if s.startswith("#") or re.fullmatch(r"[-*_=]{3,}", s):
            continue                                   # headings, horizontal rules
        if re.fullmatch(r"[\[(].*[\])]", s):
            continue                                   # whole-line [B-roll ...] / (pause)
        s = re.sub(r"\[[^\]]*\]", "", s)               # inline [stage directions]
        s = re.sub(r"\*\*|__|\*|`", "", s)             # bold / italics / code marks
        s = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", s)  # list bullets
        s = re.sub(r"\s{2,}", " ", s).strip()
        if s:
            current.append(s)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


# ---------------------------------------------------------------- captions

def fmt_time(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def caption_cues(chunk_text, tokens, chunk_start, chunk_len, max_chars=42):
    """Split one spoken chunk into short caption cues using word timestamps.

    tokens: objects with .text, .whitespace, .start_ts, .end_ts (seconds, relative
    to the chunk). Falls back to one cue for the whole chunk if timings are missing.
    """
    words = [t for t in (tokens or []) if getattr(t, "text", "").strip()]
    if not words or any(getattr(t, "start_ts", None) is None or getattr(t, "end_ts", None) is None
                        for t in words):
        return [(chunk_start, chunk_start + chunk_len, chunk_text.strip())]

    cues, line, line_start = [], "", None
    for t in words:
        piece = t.text + (t.whitespace or "")
        if line and len((line + piece).strip()) > max_chars:
            cues.append((line_start, prev_end, line.strip()))
            line, line_start = "", None
        if line_start is None:
            line_start = chunk_start + t.start_ts
        line += piece
        prev_end = chunk_start + t.end_ts
    if line.strip():
        cues.append((line_start, prev_end, line.strip()))
    return cues


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as fh:
        for i, (start, end, text) in enumerate(cues, 1):
            fh.write(f"{i}\n{fmt_time(start)} --> {fmt_time(max(end, start + 0.3))}\n{text}\n\n")


# ---------------------------------------------------------------- synthesis

def load_pipeline(voice):
    try:
        from kokoro import KPipeline
    except ImportError:
        sys.exit('Kokoro isn\'t installed. Run:  pip install "kokoro>=0.9.4" soundfile\n'
                 "(needs Python 3.10–3.12 — see VOICEOVER.md)")
    lang = voice[0]
    if lang not in "ab":
        sys.exit(f"'{voice}' isn't an English voice. Use one starting with a (American) or b (British).")
    return KPipeline(lang_code=lang, repo_id=REPO_ID)


def synthesize(paragraphs, pipeline, voice, speed, pause, chunk_gap=0.12):
    """Return (audio as float32 numpy array, list of caption cues)."""
    import numpy as np

    pieces, cues, cursor = [], [], 0.0
    para_silence = np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32)
    chunk_silence = np.zeros(int(chunk_gap * SAMPLE_RATE), dtype=np.float32)

    for p_index, paragraph in enumerate(paragraphs):
        print(f"  paragraph {p_index + 1}/{len(paragraphs)}", file=sys.stderr)
        first = True
        for result in pipeline(paragraph, voice=voice, speed=speed, split_pattern=None):
            if result.audio is None:
                continue
            if not first:
                pieces.append(chunk_silence)
                cursor += chunk_gap
            audio = result.audio.detach().cpu().numpy().astype(np.float32)
            length = len(audio) / SAMPLE_RATE
            cues.extend(caption_cues(result.graphemes, result.tokens, cursor, length))
            pieces.append(audio)
            cursor += length
            first = False
        if p_index < len(paragraphs) - 1:
            pieces.append(para_silence)
            cursor += pause

    if not pieces:
        sys.exit("No speech was generated — is the script empty?")
    return np.concatenate(pieces), cues


def main(argv=None):
    p = argparse.ArgumentParser(description="Free AI voiceover + captions from a script (Kokoro TTS).")
    p.add_argument("script", nargs="?", help="script file (.txt or .md)")
    p.add_argument("--voice", default="am_michael", help="voice name (default am_michael)")
    p.add_argument("--speed", type=float, default=1.0, help="0.8 = slower, 1.2 = faster (default 1.0)")
    p.add_argument("--pause", type=float, default=0.6, help="seconds of silence between paragraphs (default 0.6)")
    p.add_argument("--out", help="output name without extension (default: same as the script)")
    p.add_argument("--samples", action="store_true", help="make a short sample of each suggested voice")
    p.add_argument("--list-voices", action="store_true", help="show suggested voices")
    args = p.parse_args(argv)

    if args.list_voices:
        for name, desc in SUGGESTED_VOICES.items():
            print(f"{name:12} {desc}")
        return

    import soundfile as sf

    if args.samples:
        out_dir = Path("voice_samples")
        out_dir.mkdir(exist_ok=True)
        pipelines = {}
        for voice in SUGGESTED_VOICES:
            pipe = pipelines.setdefault(voice[0], load_pipeline(voice))
            audio, _ = synthesize([SAMPLE_TEXT], pipe, voice, args.speed, args.pause)
            sf.write(out_dir / f"{voice}.wav", audio, SAMPLE_RATE)
            print(f"Saved {out_dir / (voice + '.wav')}")
        return

    if not args.script:
        p.error("give a script file, or use --samples / --list-voices")
    script_path = Path(args.script)
    paragraphs = clean_script(script_path.read_text(encoding="utf-8"))
    if not paragraphs:
        sys.exit("The script has no speakable text.")

    out = Path(args.out) if args.out else script_path.with_suffix("")
    print(f"Generating voiceover with '{args.voice}' ...", file=sys.stderr)
    pipeline = load_pipeline(args.voice)
    audio, cues = synthesize(paragraphs, pipeline, args.voice, args.speed, args.pause)

    sf.write(f"{out}.wav", audio, SAMPLE_RATE)
    write_srt(cues, f"{out}.srt")
    minutes = len(audio) / SAMPLE_RATE / 60
    print(f"Done: {out}.wav ({minutes:.1f} min) and {out}.srt (captions)")


if __name__ == "__main__":
    main()
