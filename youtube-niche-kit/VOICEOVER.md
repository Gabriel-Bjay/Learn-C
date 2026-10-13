# Free AI voiceover (no recording needed)

`voiceover.py` turns your script into:
- **`script.wav`**, the narration, ready to drop into DaVinci Resolve or CapCut
- **`script.srt`**, word-timed captions. Upload them to YouTube or import them into your editor

It uses **Kokoro-82M**, a free, open-source voice model that runs on your own computer. The model weights are licensed **Apache 2.0**, so you can use the audio in monetized videos. There are no credits, no subscription and no watermark.

> Why not ElevenLabs' free plan? Its free tier doesn't include a commercial license, so you couldn't use it on a monetized channel.

---

## One-time setup (about 20–30 minutes, mostly downloads)

### 1. Install Python 3.12
Kokoro supports **Python 3.10–3.12 only**; 3.13 won't work.
- **Windows:** python.org → Downloads → Python **3.12.x** installer. Tick **"Add Python to PATH"** during install.
- **Mac:** `brew install python@3.12`

Check it: `python --version` (Windows) or `python3.12 --version` (Mac).

### 2. Install espeak-ng (helps pronounce unusual words)
- **Windows:** download the `.msi` from <https://github.com/espeak-ng/espeak-ng/releases> and install it.
- **Mac:** `brew install espeak-ng`
- **Linux:** `sudo apt install espeak-ng`

### 3. Install Kokoro
Open a terminal in the `youtube-niche-kit` folder:

```bash
# Windows
py -3.12 -m venv venv
venv\Scripts\activate

# Mac / Linux
python3.12 -m venv venv
source venv/bin/activate

# both
pip install "kokoro>=0.9.4" soundfile
```

This pulls in PyTorch, which is a large download (a few GB). It only happens once.

### 4. Pick a voice
```bash
python voiceover.py --samples
```
This makes a short clip for each suggested voice in a `voice_samples/` folder. The first run also downloads the voice model from Hugging Face (a few hundred MB). Listen and pick one:

| Voice | Sound |
|---|---|
| `am_michael` | American male, calm (default) |
| `am_fenrir` | American male, deeper |
| `af_heart` | American female, warm |
| `af_bella` | American female, energetic |
| `bm_george` | British male, documentary feel |
| `bm_fable` | British male, storyteller |
| `bf_emma` | British female, clear |

More voices are listed in `VOICES.md` at huggingface.co/hexgrad/Kokoro-82M.

---

## Every video

1. Copy the **voiceover script** (part B of Claude's `SCRIPT:` output) into a text file, e.g. `quibi.txt`. Leave a blank line between paragraphs; each one becomes a natural pause.
2. Run:
   ```bash
   python voiceover.py quibi.txt --voice am_michael
   ```
3. You get `quibi.wav` and `quibi.srt`. Put the `.wav` on your editor's timeline and build the visuals on top.

Options:
- `--speed 0.95` slows it down a little. Calmer often sounds more human.
- `--pause 0.8` gives longer gaps between paragraphs.
- `--out final_take` sets a different output file name.

Markdown, headings and `[stage directions]` are stripped automatically, so only the spoken words are read.

### Fixing pronunciation
If a word comes out wrong, spell it the way it sounds **in the script file only** (not in your video description):
- `Quibi` → `Kwibby`
- `SaaS` → `sass`
- `$1.75B` → `1.75 billion dollars`
- Write years and big numbers the way you'd say them if they sound odd.

### Speed
On an average laptop CPU, expect a few minutes for a 15-minute script. An NVIDIA GPU is used automatically if you have one, and it's much faster.

---

## Using an AI voice on YouTube
- AI narration is allowed and can be monetized. What YouTube penalizes is **low-effort, mass-produced** content, so the research and visuals are what protect the channel.
- Switch on YouTube's **"altered or synthetic content"** setting when uploading if your video shows anything realistic that's AI-generated. Never use an AI voice that imitates a real person.
- Use the **same voice on every video**. It becomes your channel's recognizable "host."
