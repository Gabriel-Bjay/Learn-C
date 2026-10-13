# YouTube Niche Kit

Everything for starting a faceless business & tech breakdowns channel on a $0 budget (plus a Claude subscription).

| File | What it is |
|---|---|
| `PROJECT_INSTRUCTIONS.md` | Paste into a Claude Project. It turns Claude into your researcher and scriptwriter |
| `VIDEO_IDEAS.md` | 20 starter ideas, each backed by a format that's breaking out right now |
| `niche_scanner.py` | Free tool that compares niches using YouTube's own data |
| `niches.txt` | Example niche list for the scanner |

---

## niche_scanner.py

For each niche it searches YouTube for the top 50 videos from the last 90 days, skips Shorts, and measures:

- **Demand**: median views per day of those videos
- **Newcomer odds**: how many videos are on **small channels (<50k subs)** that got **3x or more** their channel's average views. This is the best sign that a new channel can still win
- **Pay**: the estimated RPM for the niche's ad category

These combine into a **0–100 score** (40 demand + 40 newcomer odds + 20 pay). The score is a rough guide, not a guarantee. The report also lists the **top breakout videos on small channels** for each niche, which are useful as video ideas.

### 1. Get a free YouTube API key (about 5 minutes)

1. Go to <https://console.cloud.google.com/> and sign in with a Google account.
2. Create a new project (top bar → **New Project**). Any name works.
3. Open **APIs & Services → Library**, search **YouTube Data API v3**, and click **Enable**.
4. Open **APIs & Services → Credentials → Create credentials → API key**. Copy the key.
5. Recommended: click the key → **API restrictions → Restrict key → YouTube Data API v3**.

It's free and doesn't need a card. The daily quota is **10,000 units**, and each niche scan uses about **102**, so you can scan about 95 niches a day.

### 2. Run it (Python 3.8+, nothing to install)

```bash
export YT_API_KEY="paste-your-key-here"     # Windows PowerShell: $env:YT_API_KEY="..."

python3 niche_scanner.py niches.txt          # scan every niche in the file
python3 niche_scanner.py --niche "economics of owning:business" --niche "car industry explained:autos"
```

Output: a ranked table in the terminal, plus `niche_report.csv` (opens in Excel or Google Sheets) and `niche_report.md` (includes links to the breakout videos).

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--days` | 90 | Only count videos published in the last N days |
| `--region` | US | Which country's results to search |
| `--lang` | en | Language |
| `--min-minutes` | 4 | Ignore videos shorter than this (filters out Shorts) |
| `--small-subs` | 50000 | Subscriber count that counts as a "small channel" |
| `--out` | niche_report | Prefix for the output file names |

### Niche format

`keyword:category[:rpm]`, for example `economics of owning:business` or `drone reviews:technology:6.5`.

Built-in RPMs (USD per 1,000 long-form views, US audience): business 8, finance 8, education 6, technology 5, autos 5, news 5, health 5, entertainment 3, gaming 2. Business, education, technology, autos and news come from vidIQ's earnings model (Oct 2026). The others are rough guesses. Override any of them with your own numbers once you have real RPM data from YouTube Studio.

### Tests

```bash
python3 -m unittest discover -s tests
```
