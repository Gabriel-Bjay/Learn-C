#!/usr/bin/env python3
"""Build the 8 Quibi charts as 1920x1080 SVG pages (render to PNG with render.js).

Data comes from the script package's "D. Charts to build" section.
Palette validated with the dataviz validator (dark, surface #08204a, all pairs pass).
"""
from pathlib import Path

W, H = 1920, 1080
SURFACE = "#08204a"
INK = "#ffffff"        # values, titles
INK_2 = "#b9c8e6"      # labels, subtitles
INK_3 = "#8fa3c8"      # sources, axis
GRID = "#1d3a6e"
CYAN = "#14a3c4"       # Quibi / money in
ORANGE = "#e0682a"     # costs / losses
VIOLET = "#8b7cf0"     # comparisons
OUT = Path(__file__).parent

FONT = "'Inter Display','Inter',sans-serif"


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=32, fill=INK, weight=500, anchor="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def hbar(x, y, w, h, fill, round_end=True, r=6):
    """Horizontal bar anchored at x; only the data end is rounded."""
    w = max(w, 4)
    if not round_end or w <= r:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>'
    return (f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z" fill="{fill}"/>')


def vbar(x, y_base, w, h, fill, round_end=True, r=6):
    """Vertical bar standing on y_base; only the top is rounded."""
    h = max(h, 4)
    top = y_base - h
    if not round_end or h <= r:
        return f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>'
    return (f'<path d="M{x:.1f},{y_base:.1f} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} '
            f'H{x + w - r:.1f} Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f} V{y_base:.1f} Z" fill="{fill}"/>')


def badge(label, color=ORANGE):
    w = 26 * len(label) * 0.62 + 56
    x = W - 120 - w
    return (f'<rect x="{x:.1f}" y="92" width="{w:.1f}" height="54" rx="27" fill="none" stroke="{color}" stroke-width="3"/>'
            + text(x + w / 2, 128, label, 26, INK, 700, "middle", 'letter-spacing="2"'))


def frame(title, subtitle, source, body, badge_label=None):
    defs = (f'<defs><pattern id="hatchO" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="18" height="18" fill="{SURFACE}"/><rect width="8" height="18" fill="{ORANGE}"/></pattern>'
            f'<pattern id="hatchMix" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="18" height="18" fill="{CYAN}"/><rect width="9" height="18" fill="{ORANGE}"/></pattern></defs>')
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
        defs,
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        f'<rect x="120" y="60" width="90" height="8" rx="4" fill="{CYAN}"/>',
        text(120, 150, title, 64, INK, 800),
        text(120, 212, subtitle, 34, INK_2, 500),
        body,
        text(120, 1030, source, 24, INK_3, 500),
        text(W - 120, 1030, "WORK REWIRED", 24, INK_3, 800, "end", 'letter-spacing="3"'),
    ]
    if badge_label:
        parts.append(badge(badge_label))
    parts.append("</svg>")
    return "".join(parts)


def page(svg):
    return ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;padding:0;"
            f"background:{SURFACE}}}</style></head><body>{svg}</body></html>")


# ---------------------------------------------------------------- charts

def chart1():
    x0, total_w, y, h = 120, 1680, 430, 190
    s = total_w / 1.75
    w1, w2 = 1.00 * s, 0.75 * s
    b = [
        hbar(x0, y, w1 - 2, h, CYAN, round_end=False),
        hbar(x0 + w1 + 2, y, w2 - 2, h, VIOLET),
        text(x0 + 40, y + 88, "$1.00B", 64, INK, 800),
        text(x0 + 40, y + 145, "2018 · when it was still called NewTV", 32, INK, 500),
        text(x0 + w1 + 42, y + 88, "$0.75B", 64, INK, 800),
        text(x0 + w1 + 42, y + 145, "March 2020 · one month before launch", 32, INK, 500),
        # total bracket
        f'<path d="M{x0},{y - 40} V{y - 60} H{x0 + total_w} V{y - 40}" fill="none" stroke="{INK_2}" stroke-width="3"/>',
        text(x0 + total_w / 2, y - 80, "$1.75 billion raised before a single customer paid", 40, INK, 700, "middle"),
        text(x0, y + h + 70, "Backers included the major Hollywood studios, Goldman Sachs and Alibaba.", 32, INK_2),
    ]
    return frame("Quibi's funding", "Two rounds, $ billions", "Source: Variety via Tubefilter, March 2020", "".join(b))


def chart2():
    base, top = 900, 330
    s = (base - top) / 1500
    bw = 340
    xi, xo = 520, 1040
    b = [f'<line x1="300" y1="{base}" x2="1700" y2="{base}" stroke="{INK_3}" stroke-width="2"/>']
    for v in (500, 1000, 1500):
        y = base - v * s
        b.append(f'<line x1="300" y1="{y:.1f}" x2="1700" y2="{y:.1f}" stroke="{GRID}" stroke-width="2"/>')
        b.append(text(280, y + 10, f"${v:,}M", 26, INK_3, 500, "end"))
    # money in: subscriptions 250 + ads 150
    b += [vbar(xi, base, bw, 250 * s - 2, CYAN, round_end=False),
          vbar(xi, base - 250 * s, bw, 150 * s - 2, CYAN),
          text(xi + bw / 2, base - 125 * s + 10, "Subscriptions $250M", 28, INK, 600, "middle"),
          text(xi + bw / 2, base - 325 * s + 10, "Ads ~$150M", 28, INK, 600, "middle"),
          text(xi + bw / 2, base - 400 * s - 24, "$400M", 48, INK, 800, "middle"),
          text(xi + bw / 2, base + 52, "MONEY IN", 30, INK_2, 700, "middle", 'letter-spacing="2"')]
    # money out: content 1000 + marketing 470
    b += [vbar(xo, base, bw, 1000 * s - 2, ORANGE, round_end=False),
          vbar(xo, base - 1000 * s, bw, 470 * s - 2, ORANGE),
          text(xo + bw / 2, base - 500 * s + 10, "Shows $1,000M", 30, INK, 600, "middle"),
          text(xo + bw / 2, base - 1235 * s + 10, "Marketing $470M", 30, INK, 600, "middle"),
          text(xo + bw / 2, base - 1470 * s - 24, "$1,470M", 48, INK, 800, "middle"),
          text(xo + bw / 2, base + 52, "MONEY OUT", 30, INK_2, 700, "middle", 'letter-spacing="2"')]
    # gap bracket
    y400, y1470, bx = base - 400 * s, base - 1470 * s, xo + bw + 60
    b += [f'<line x1="{xi + bw}" y1="{y400:.1f}" x2="{bx}" y2="{y400:.1f}" stroke="{INK_2}" stroke-width="2" stroke-dasharray="10 8"/>',
          f'<path d="M{bx - 18},{y1470:.1f} H{bx} V{y400:.1f} H{bx - 18}" fill="none" stroke="{INK}" stroke-width="3"/>',
          text(bx + 30, (y400 + y1470) / 2 - 6, "Gap ≈ $1.07B", 48, INK, 800),
          text(bx + 30, (y400 + y1470) / 2 + 40, "before salaries, tech", 28, INK_2),
          text(bx + 30, (y400 + y1470) / 2 + 76, "and offices", 28, INK_2)]
    return frame("Year one, best case: ~$1 billion short", "Quibi's own year-one plans, if everything had gone right",
                 "Sources: Playback (Jun 2019), NextTV (Mar 2020), TechCrunch (May 2020). Combines plans from different dates.",
                 "".join(b), "ROUGH ESTIMATE")


def chart3():
    x0, maxw = 560, 1180
    s = maxw / 100000
    rows = [("High-end YouTube video", 2000, VIOLET, "~$2,000"), ("Quibi's top originals", 100000, ORANGE, "up to $100,000")]
    b = []
    for i, (label, v, color, vl) in enumerate(rows):
        y = 400 + i * 230
        b += [text(x0 - 30, y + 72, label, 36, INK_2, 600, "end"),
              hbar(x0, y, v * s, 110, color),
              text(x0 + v * s + 24, y + 72, vl, 44, INK, 800)]
    # the big bar's value sits inside its end so it stays on-canvas
    b[5] = text(x0 + maxw - 24, 630 + 72, "up to $100,000", 44, INK, 800, "end")
    b += [text(x0, 860, "Quibi's best shows cost up to 50× more per minute.", 40, INK, 700),
          text(x0, 912, "That's $6 million an hour — prime-time TV money.", 32, INK_2)]
    return frame("Cost per minute of video", "Quibi vs a high-end YouTube video (Jeffrey Katzenberg's figures)",
                 "Source: Tubefilter, June 2019", "".join(b))


def chart4():
    x0, maxw = 600, 1060
    s = maxw / 10_000_000
    rows = [
        ("Disney+  ·  signed up", 9_500_000, VIOLET, "9.5M"),
        ("Disney+  ·  became paying", 1_050_000, VIOLET, "~1.05M  (≈11%)"),
        ("Quibi  ·  signed up", 910_000, CYAN, "~910K"),
        ("Quibi  ·  became paying", 72_000, CYAN, "~72K  (≈8%)"),
    ]
    b = []
    for i, (label, v, color, vl) in enumerate(rows):
        y = 320 + i * 140 + (40 if i >= 2 else 0)
        b += [text(x0 - 30, y + 58, label, 34, INK_2, 600, "end"),
              hbar(x0, y, v * s, 88, color)]
        vx = x0 + max(v * s, 8) + 24
        if v * s > maxw - 300:
            b.append(text(x0 + v * s - 24, y + 60, vl, 40, INK, 800, "end"))
        else:
            b.append(text(vx, y + 60, vl, 40, INK, 800))
    b += [f'<line x1="{x0}" y1="300" x2="{x0}" y2="910" stroke="{INK_3}" stroke-width="2"/>',
          text(x0, 935, "Quibi kept people about as well as Disney+.", 32, INK, 700),
          text(x0, 975, "It just had over 10× fewer people at the top.", 32, INK_2, 600)]
    return frame("The funnel was 10× smaller", "First 3 days of sign-ups, and how many paid after the free trial (US & Canada)",
                 "Source: Sensor Tower via The Verge and MobileSyrup, July 2020. All figures are estimates.",
                 "".join(b), "ESTIMATES")


def chart5():
    base, top = 880, 300
    s = (base - top) / 1000
    bw = 380
    xa, xb = 220, 680
    b = [f'<line x1="{xa - 120}" y1="{base}" x2="{xb + bw + 120}" y2="{base}" stroke="{INK_3}" stroke-width="2"/>',
         vbar(xa, base, bw, 1000 * s, ORANGE),
         text(xa + bw / 2, base - 1000 * s - 26, "~$1,000M", 52, INK, 800, "middle"),
         text(xa + bw / 2, base + 52, "Planned content spend, year one", 30, INK_2, 600, "middle"),
         vbar(xb, base, bw, 100 * s, VIOLET),
         f'<line x1="{xb}" y1="{base - 100 * s - 2:.1f}" x2="{xb + bw}" y2="{base - 100 * s - 2:.1f}" stroke="{INK}" stroke-width="3" stroke-dasharray="12 8"/>',
         text(xb + bw / 2, base - 100 * s - 30, "under $100M", 52, INK, 800, "middle"),
         text(xb + bw / 2, base + 52, "What Roku paid for the library", 30, INK_2, 600, "middle"),
         f'<rect x="1230" y="470" width="8" height="190" rx="4" fill="{CYAN}"/>',
         text(1270, 540, "Less than 10¢ back", 52, INK, 800),
         text(1270, 598, "for every $1 Quibi", 36, INK_2, 600),
         text(1270, 644, "planned to spend on shows", 36, INK_2, 600)]
    return frame("Spent on shows vs what they sold for", "$ millions",
                 "Sources: Playback (Jun 2019); WSJ via Tubefilter (Jan 2021). $1B was planned spend, not audited actual.",
                 "".join(b), "ROUGH ESTIMATE")


def chart6():
    x0, total_w, y, h = 120, 1680, 440, 190
    s = total_w / 1.75
    b = [hbar(x0, y, 1.40 * s - 2, h, ORANGE, round_end=False),
         f'<rect x="{x0 + 1.40 * s:.1f}" y="{y}" width="{0.05 * s:.1f}" height="{h}" fill="url(#hatchMix)"/>',
         hbar(x0 + 1.45 * s + 2, y, 0.30 * s - 2, h, CYAN),
         text(x0 + 40, y + 90, "≈ $1.40–1.45B", 64, INK, 800),
         text(x0 + 40, y + 146, "not returned — spent on shows, marketing, staff and tech", 32, INK, 500),
         text(x0 + total_w - 20, y + 90, "$300–350M", 40, INK, 800, "end"),
         text(x0 + total_w - 24, y + 146, "returned", 32, INK, 500, "end"),
         f'<path d="M{x0},{y - 40} V{y - 60} H{x0 + total_w} V{y - 40}" fill="none" stroke="{INK_2}" stroke-width="3"/>',
         text(x0 + total_w / 2, y - 80, "$1.75 billion raised", 40, INK, 700, "middle"),
         f'<rect x="{x0}" y="{y + h + 60}" width="40" height="40" fill="url(#hatchMix)"/>',
         text(x0 + 60, y + h + 92, "Uncertain: Bloomberg reported about $300M returned; other reports said $350M.", 30, INK_2)]
    return frame("Where the $1.75 billion went", "Investors' money, $ billions",
                 "Sources: Bloomberg via Infobae; VideoNuze (Jan 2021).", "".join(b), "ESTIMATE")


def chart7():
    x0, maxw = 640, 1100
    s = maxw / 500
    b = [text(x0 - 30, 440, "Planned 2020 marketing", 36, INK_2, 600, "end"),
         text(x0 - 30, 482, "(all kinds, per media executives)", 28, INK_3, 500, "end"),
         hbar(x0, 380, 400 * s - 2, 120, ORANGE, round_end=False),
         f'<rect x="{x0 + 400 * s:.1f}" y="380" width="{100 * s:.1f}" height="120" fill="url(#hatchO)" rx="6"/>',
         text(x0 + 30, 458, "$400–500M", 48, INK, 800),
         text(x0 - 30, 660, "Tracked TV, digital & print ads", 36, INK_2, 600, "end"),
         text(x0 - 30, 702, "(measured ad buys only)", 28, INK_3, 500, "end"),
         hbar(x0, 600, 63 * s, 120, VIOLET),
         text(x0 + 63 * s + 24, 678, "$63M", 48, INK, 800),
         f'<rect x="{x0}" y="800" width="40" height="40" fill="url(#hatchO)"/>',
         text(x0 + 60, 832, "Range of the estimate", 30, INK_2),
         text(x0, 905, "Not the same measure — so the gap can't be settled.", 36, INK, 700)]
    return frame("Marketing: planned vs tracked", "2020, $ millions",
                 "Sources: Digiday (Feb 2020); MediaRadar via MediaPost (Oct 2020).", "".join(b))


def chart8():
    events = [("Aug 2018", "Founded, $1B raised"), ("Feb 2, 2020", "Super Bowl ad"),
              ("Mar 2020", "$750M round"), ("Apr 6, 2020", "LAUNCH"), ("May 2020", "NYT interview"),
              ("Jul 2020", "Sensor Tower report"), ("Sep 17, 2020", "Two Emmy wins"),
              ("Oct 21, 2020", "Shutdown announced"), ("Dec 1, 2020", "App goes dark"),
              ("Jan 8, 2021", "Roku buys the shows")]
    x0, x1, y = 190, 1730, 600
    step = (x1 - x0) / (len(events) - 1)
    xs = [x0 + i * step for i in range(len(events))]
    b = [f'<line x1="{x0 - 40}" y1="{y}" x2="{x1 + 40}" y2="{y}" stroke="{INK_3}" stroke-width="4"/>',
         f'<rect x="{xs[3]:.1f}" y="{y - 10}" width="{xs[8] - xs[3]:.1f}" height="20" rx="10" fill="{CYAN}"/>',
         text((xs[3] + xs[8]) / 2, y + 260, "The app was live for about 8 months", 34, INK, 700, "middle")]
    for i, ((date, label), x) in enumerate(zip(events, xs)):
        up = i % 2 == 0
        key = i in (3, 7, 8)
        color = CYAN if 3 <= i <= 8 else INK_2
        b.append(f'<circle cx="{x:.1f}" cy="{y}" r="{16 if key else 12}" fill="{color}" stroke="{SURFACE}" stroke-width="4"/>')
        ly = y - 60 if up else y + 80
        b.append(f'<line x1="{x:.1f}" y1="{y + (-18 if up else 18)}" x2="{x:.1f}" y2="{ly + (10 if up else -40)}" stroke="{GRID}" stroke-width="2"/>')
        if up:
            b += [text(x, ly - 40, date, 28, INK_2, 600, "middle"), text(x, ly, label, 30, INK, 800 if key else 600, "middle")]
        else:
            b += [text(x, ly, date, 28, INK_2, 600, "middle"), text(x, ly + 40, label, 30, INK, 800 if key else 600, "middle")]
    return frame("Quibi, start to finish", "Key dates (spacing not to scale)",
                 "Sources: Variety, Adweek, Deadline, CNN, Television Academy, WSJ.", "".join(b))


CHARTS = {
    "chart1_funding": chart1, "chart2_year_one": chart2, "chart3_cost_per_minute": chart3,
    "chart4_funnel": chart4, "chart5_spend_vs_salvage": chart5, "chart6_where_money_went": chart6,
    "chart7_marketing": chart7, "chart8_timeline": chart8,
}

if __name__ == "__main__":
    for name, fn in CHARTS.items():
        (OUT / f"{name}.html").write_text(page(fn()), encoding="utf-8")
    print("wrote", len(CHARTS), "chart pages")
