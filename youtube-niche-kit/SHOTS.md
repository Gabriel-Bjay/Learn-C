# Auto-editing with make_video.py

`make_video.py` builds a finished 1080p video from:
1. your voiceover (`.wav`) and its `.timings.json`, which `voiceover.py` writes automatically, and
2. a **shot list** (`shots.txt`) that says what's on screen for each paragraph.

It handles the timing, camera moves, animated text and charts, the highlighter on article screenshots, the subscribe animation, stock footage, background music, and the final export. Your manual work is collecting screenshots, plus a quick watch-through at the end.

---

## One-time setup (Windows)

In the same PowerShell window, with the `venv` active (see VOICEOVER.md):

```powershell
winget install Gyan.FFmpeg      # video engine. Close and reopen PowerShell afterwards
pip install pillow              # draws the text cards
ffmpeg -version                 # check: prints a version number
```

### Free stock footage: pick one way

**A. Automatic, with a free Pixabay key (recommended).**
1. Create a free account at **pixabay.com**, then open **pixabay.com/api/docs/**. Your key is shown on that page once you're logged in.
2. Save the key once (PowerShell), then close and reopen PowerShell:
   ```powershell
   setx PIXABAY_API_KEY "paste-your-key-here"
   ```
Pixabay content is free to use, including in monetized videos. Pixabay asks that you mention it as a source, so add "Stock footage: Pixabay" to your video description.
*(Pexels keys also work via `PEXELS_API_KEY`, but Pexels has paused issuing new keys.)*

**B. By hand, with no key.** Run a `--preview` first. At the end it lists the exact file names it wants, for example:
```
stock clip 'empty train station' -> save one as stock/empty-train-station-0.mp4
```
Search that phrase on pexels.com or pixabay.com, download the clip, and save it into the `stock` folder (next to `shots.txt`) with that exact name. The next run uses it automatically.

Downloaded and hand-saved clips are reused on every re-render.

---

## Every video

```powershell
python voiceover.py quibi_voiceover.txt --voice am_michael         # makes .wav, .srt, .timings.json
python make_video.py quibi_voiceover.wav shots.txt --preview        # fast low-res draft (minutes)
python make_video.py quibi_voiceover.wav shots.txt --music music.mp3  # final 1080p
```

- **Start with `--preview`.** Missing screenshots and charts show as labelled placeholder cards, and the end of the run lists exactly what's missing. Add those files, then run again.
- **Final render:** a 13-minute video takes about 10–20 minutes on a normal laptop. Add `--no-zoom` to make it about 3x faster, with still images instead of the slow zoom.
- **Music:** download a track from the **YouTube Audio Library** (Studio → Audio Library) and pass it with `--music`. It loops quietly under the voice. Use `--music-volume 0.08` to make it quieter.
- **Output:** an `.mp4` ready to upload. Then upload the `.srt` as subtitles.

---

## Shot list format

One visual per line: `paragraph: type: value`

```text
# comments start with #
1: screenshot: screenshots/01_roku_headline.png
1: text: 75+ SHOWS | sold to Roku for well under $100 million
2: chart: charts/chart1_funding.png
3-4: stock: person watching phone on train
5: video: clips/my_own_clip.mp4
```

| Type | What it does |
|---|---|
| `screenshot: https://link \| phrase` | **Captured automatically**: opens the article and closes pop-ups. In the video the camera glides in to the phrase and a yellow highlighter sweeps across it. Without a phrase it focuses on the headline. Some sites block it; then you're told the exact file name to save by hand |
| `screenshot`, `chart`, `image` + file | Your own picture, with a smooth slow zoom |
| `stock: search words` | Free stock **video** clip (Pixabay key, or saved by hand) |
| `photo: search words` | Free stock **photo** (Pixabay key, or saved by hand) |
| `person: Full Name` | The person's photo from Wikipedia, **only if freely licensed**. The credit line is written to `credits.txt` for your description |
| `text: Headline \| smaller line` | A navy text card with a slowly drifting background; the text animates in. Use sparingly |
| `video`, `clip` | Your own video file |

**Overlays:** add `>> HEADLINE | smaller line` after any stock, photo, person, screenshot or chart line to put text on top of it, for example `stock: stack of money cash >> $1.75 BILLION | raised`.

### Animations (automatic)
- **Numbers count up:** when a headline starts with one number (`$1.75 BILLION`, `75+ SHOWS`, `≈ $2,800`) it ticks up from 0. So put the key number first.
- **Text** slides up and fades in, line by line, with the cyan bar growing in.
- **Charts** draw themselves in from left to right.
- **Photos and footage** get slow camera moves that alternate: push in, pull out, pan.
- **Subscribe button:** where the voiceover first says "subscribe", a SUBSCRIBE button pops up, a cursor clicks it (it turns to SUBSCRIBED) and rings the bell. To put it somewhere else, add `>> @subscribe` to that line, e.g. `21: stock: person smiling at phone >> @subscribe`. `--no-subscribe` turns it off.
- `--no-animations` makes text appear at once and skips the highlighter sweep and the chart reveal.

**Transitions:** each shot fades softly through navy (`--fade 0` turns this off).

Rules:
- **Several lines for one paragraph** split that paragraph's time evenly, in order.
- **`3-4:`** means one visual across paragraphs 3 to 4.
- **A paragraph with no line** keeps showing the previous visual.
- Paragraph numbers match the voiceover file: blank-line-separated paragraphs, counted from 1.
- File paths are relative to the shot-list file's folder.

### Screenshots
Press **Win + Shift + S**, select the headline or paragraph, then paste into Paint and save as `.png` using the file name from the shot list. Save them in a `screenshots/` folder next to `shots.txt`.

### Getting shot lists from Claude
In your Work Rewired Claude Project, type **`SHOTS`** after a script is final. It replies with a shot list in this exact format. Save it as `shots.txt`.
