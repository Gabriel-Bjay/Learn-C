#!/usr/bin/env python3
"""
YouTube niche scanner — free, standard-library only.

Uses the YouTube Data API v3 (free quota: 10,000 units/day) to compare niches:
  * demand        — how many views/day recent videos in the niche are getting
  * newcomer odds — how often SMALL channels break out (views >> channel average)
  * pay           — your RPM assumption for the niche's ad category

Usage:
  export YT_API_KEY="your-key"
  python3 niche_scanner.py niches.txt
  python3 niche_scanner.py --niche "economics of owning:business" --niche "car industry explained:autos"

Each niche costs about 102 quota units (1 search + 2 batch lookups), so the free
quota covers roughly 95 niches per day.
"""

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API_BASE = "https://www.googleapis.com/youtube/v3/"

# Estimated creator RPM (USD per 1,000 long-form views, US audience).
# business/education/technology/autos/news come from vidIQ's earnings model
# (100k monthly views, Oct 2026). The rest are rough placeholders — edit freely.
DEFAULT_RPM = {
    "business": 8.0,
    "finance": 8.0,
    "education": 6.0,
    "technology": 5.0,
    "autos": 5.0,
    "news": 5.0,
    "health": 5.0,
    "entertainment": 3.0,
    "gaming": 2.0,
}


# ---------------------------------------------------------------- API layer

class QuotaError(RuntimeError):
    pass


def fetch_json(endpoint, params, api_key):
    """GET an API endpoint and return parsed JSON. Replaced in tests."""
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = f"{API_BASE}{endpoint}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        if err.code == 403 and "quota" in body.lower():
            raise QuotaError("Daily YouTube API quota used up — try again tomorrow.") from err
        try:
            message = json.loads(body)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = body[:300]
        raise RuntimeError(f"YouTube API error {err.code}: {message}") from err


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def search_videos(keyword, days, region, lang, api_key, fetch=fetch_json):
    """Top 50 videos for a keyword published in the last `days` (100 units)."""
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = fetch("search", {
        "part": "id",
        "q": keyword,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": after,
        "regionCode": region,
        "relevanceLanguage": lang,
        "maxResults": 50,
    }, api_key)
    return [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]


def video_details(video_ids, api_key, fetch=fetch_json):
    """Stats, duration and channel for each video (1 unit per 50 videos)."""
    out = []
    for batch in chunks(video_ids, 50):
        data = fetch("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
        }, api_key)
        out.extend(data.get("items", []))
    return out


def channel_details(channel_ids, api_key, fetch=fetch_json):
    """Subscriber/view/video counts for each channel (1 unit per 50 channels)."""
    out = {}
    for batch in chunks(sorted(set(channel_ids)), 50):
        data = fetch("channels", {
            "part": "snippet,statistics",
            "id": ",".join(batch),
        }, api_key)
        for item in data.get("items", []):
            out[item["id"]] = item
    return out


# ---------------------------------------------------------------- analysis

_DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(iso):
    """'PT1H2M3S' -> 3723 seconds."""
    m = _DURATION_RE.fullmatch(iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def analyse_niche(keyword, category, rpm, videos, channels, now, min_duration, small_subs):
    rows = []
    for v in videos:
        seconds = parse_duration(v.get("contentDetails", {}).get("duration"))
        if seconds < min_duration:
            continue  # skip Shorts / very short clips
        stats = v.get("statistics", {})
        views = int(stats.get("viewCount", 0))
        published = parse_time(v["snippet"]["publishedAt"])
        age_days = max((now - published).total_seconds() / 86400, 1)
        ch = channels.get(v["snippet"]["channelId"], {})
        ch_stats = ch.get("statistics", {})
        hidden = ch_stats.get("hiddenSubscriberCount", False)
        subs = None if hidden else int(ch_stats.get("subscriberCount", 0))
        ch_views = int(ch_stats.get("viewCount", 0))
        ch_videos = max(int(ch_stats.get("videoCount", 1)), 1)
        ch_avg = ch_views / ch_videos if ch_views else 0
        ch_created = ch.get("snippet", {}).get("publishedAt")
        rows.append({
            "title": v["snippet"]["title"],
            "channel": v["snippet"]["channelTitle"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "views": views,
            "views_per_day": views / age_days,
            "minutes": round(seconds / 60, 1),
            "subs": subs,
            "outlier": round(views / ch_avg, 1) if ch_avg else 0.0,
            "new_channel": bool(ch_created) and (now - parse_time(ch_created)).days <= 548,
        })

    if not rows:
        return {"keyword": keyword, "category": category, "rpm": rpm, "videos": 0,
                "score": 0, "top_outliers": []}

    small = [r for r in rows if r["subs"] is not None and r["subs"] < small_subs]
    small_breakouts = [r for r in small if r["outlier"] >= 3]
    median_vpd = statistics.median(r["views_per_day"] for r in rows)

    # Heuristic 0–100 score: demand (40) + newcomer odds (40) + pay (20).
    demand = min(40.0, 10 * math.log10(median_vpd + 1))
    newcomer = min(40.0, 100 * len(small_breakouts) / len(rows))
    pay = min(20.0, 20 * rpm / 8)

    return {
        "keyword": keyword,
        "category": category,
        "rpm": rpm,
        "videos": len(rows),
        "median_views_per_day": round(median_vpd),
        "small_channel_share": round(len(small) / len(rows), 2),
        "small_channel_breakouts": len(small_breakouts),
        "new_channels_in_results": sum(r["new_channel"] for r in rows),
        "avg_minutes": round(statistics.mean(r["minutes"] for r in rows), 1),
        "est_monthly_usd_per_100k_views": round(rpm * 100),
        "demand_pts": round(demand, 1),
        "newcomer_pts": round(newcomer, 1),
        "pay_pts": round(pay, 1),
        "score": round(demand + newcomer + pay, 1),
        "top_outliers": sorted(small_breakouts, key=lambda r: r["outlier"], reverse=True)[:5],
    }


def scan(keyword, category, rpm, args, api_key, fetch=fetch_json):
    ids = search_videos(keyword, args.days, args.region, args.lang, api_key, fetch)
    videos = video_details(ids, api_key, fetch)
    channels = channel_details([v["snippet"]["channelId"] for v in videos], api_key, fetch)
    return analyse_niche(keyword, category, rpm, videos, channels,
                         datetime.now(timezone.utc), args.min_minutes * 60, args.small_subs)


# ---------------------------------------------------------------- I/O

def parse_niche(spec):
    """'keyword:category' or 'keyword:category:rpm' -> (keyword, category, rpm)."""
    parts = [p.strip() for p in spec.rsplit(":", 2)] if ":" in spec else [spec.strip()]
    keyword = parts[0]
    category = parts[1].lower() if len(parts) > 1 and parts[1] else "education"
    if len(parts) > 2 and parts[2]:
        rpm = float(parts[2])
    else:
        rpm = DEFAULT_RPM.get(category, 4.0)
    return keyword, category, rpm


def load_niches(path):
    with open(path, encoding="utf-8") as fh:
        return [parse_niche(line) for line in fh
                if line.strip() and not line.lstrip().startswith("#")]


def write_reports(results, out_prefix):
    results = sorted(results, key=lambda r: r["score"], reverse=True)
    fields = ["score", "keyword", "category", "rpm", "videos", "median_views_per_day",
              "small_channel_share", "small_channel_breakouts", "new_channels_in_results",
              "avg_minutes", "est_monthly_usd_per_100k_views",
              "demand_pts", "newcomer_pts", "pay_pts"]
    with open(f"{out_prefix}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    lines = [f"# Niche scan — {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             "| Rank | Score | Niche | Median views/day | Small-channel breakouts | RPM |",
             "|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r['score']} | {r['keyword']} | {r.get('median_views_per_day', 0):,} "
                     f"| {r.get('small_channel_breakouts', 0)}/{r['videos']} | ${r['rpm']:.0f} |")
    for r in results:
        if not r["top_outliers"]:
            continue
        lines += ["", f"## Breakouts on small channels — {r['keyword']}", ""]
        for o in r["top_outliers"]:
            lines.append(f"- **{o['outlier']}x** — [{o['title']}]({o['url']}) "
                         f"({o['channel']}, {o['subs']:,} subs, {o['views']:,} views, {o['minutes']} min)")
    with open(f"{out_prefix}.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Compare YouTube niches with the free YouTube Data API.")
    p.add_argument("niches_file", nargs="?", help="text file: one 'keyword:category[:rpm]' per line")
    p.add_argument("--niche", action="append", default=[], help="'keyword:category[:rpm]' (repeatable)")
    p.add_argument("--days", type=int, default=90, help="only videos from the last N days (default 90)")
    p.add_argument("--region", default="US", help="region code (default US)")
    p.add_argument("--lang", default="en", help="language code (default en)")
    p.add_argument("--min-minutes", type=float, default=4, help="ignore videos shorter than this (default 4)")
    p.add_argument("--small-subs", type=int, default=50000, help="'small channel' threshold (default 50,000)")
    p.add_argument("--out", default="niche_report", help="output file prefix (default niche_report)")
    args = p.parse_args(argv)

    api_key = os.environ.get("YT_API_KEY")
    if not api_key:
        sys.exit("Set your key first:  export YT_API_KEY='...'   (see README.md)")

    niches = [parse_niche(n) for n in args.niche]
    if args.niches_file:
        niches += load_niches(args.niches_file)
    if not niches:
        sys.exit("Give a niches file or at least one --niche.")

    results = []
    for keyword, category, rpm in niches:
        print(f"Scanning: {keyword} ...", file=sys.stderr)
        try:
            results.append(scan(keyword, category, rpm, args, api_key))
        except (QuotaError, RuntimeError, urllib.error.URLError) as err:
            print(f"Stopped: {err}", file=sys.stderr)
            break

    if not results:
        sys.exit("Nothing scanned.")
    ranked = write_reports(results, args.out)
    print(f"\n{'Score':>6}  {'Views/day':>9}  {'Breakouts':>9}  {'RPM':>4}  Niche")
    for r in ranked:
        print(f"{r['score']:>6}  {r.get('median_views_per_day', 0):>9,}  "
              f"{r.get('small_channel_breakouts', 0):>4}/{r['videos']:<4}  ${r['rpm']:>3.0f}  {r['keyword']}")
    print(f"\nSaved {args.out}.csv and {args.out}.md")


if __name__ == "__main__":
    main()
