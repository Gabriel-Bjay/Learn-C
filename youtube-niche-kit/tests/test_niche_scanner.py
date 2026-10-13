import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import niche_scanner as ns  # noqa: E402

NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


VIDEOS = {
    # small channel, huge breakout, long-form
    "v1": ("chA", "The Economics of Owning a Software Company", "PT24M53S", 148000, 10),
    # big channel, normal performance
    "v2": ("chB", "How Netflix Makes Money", "PT15M", 500000, 30),
    # a Short — must be ignored
    "v3": ("chA", "Quick fact", "PT45S", 900000, 5),
    # small channel, average performance
    "v4": ("chC", "Why Rivian Struggled", "PT1H2M3S", 3000, 20),
}
CHANNELS = {
    "chA": {"subscriberCount": "4500", "viewCount": "540000", "videoCount": "1000", "created": iso(200)},
    "chB": {"subscriberCount": "2000000", "viewCount": "900000000", "videoCount": "900", "created": iso(3000)},
    "chC": {"subscriberCount": "1200", "viewCount": "60000", "videoCount": "20", "created": iso(100)},
}


def fake_fetch(endpoint, params, api_key):
    if endpoint == "search":
        return {"items": [{"id": {"videoId": vid}} for vid in VIDEOS]}
    if endpoint == "videos":
        items = []
        for vid in params["id"].split(","):
            ch, title, dur, views, age = VIDEOS[vid]
            items.append({
                "id": vid,
                "snippet": {"channelId": ch, "channelTitle": ch, "title": title, "publishedAt": iso(age)},
                "statistics": {"viewCount": str(views)},
                "contentDetails": {"duration": dur},
            })
        return {"items": items}
    if endpoint == "channels":
        items = []
        for cid in params["id"].split(","):
            c = CHANNELS[cid]
            items.append({"id": cid, "snippet": {"publishedAt": c["created"]},
                          "statistics": {k: c[k] for k in ("subscriberCount", "viewCount", "videoCount")}})
        return {"items": items}
    raise AssertionError(endpoint)


ARGS = SimpleNamespace(days=90, region="US", lang="en", min_minutes=4, small_subs=50000)


class ScannerTests(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(ns.parse_duration("PT1H2M3S"), 3723)
        self.assertEqual(ns.parse_duration("PT45S"), 45)
        self.assertEqual(ns.parse_duration("P1DT1M"), 86460)
        self.assertEqual(ns.parse_duration(""), 0)

    def test_parse_niche(self):
        self.assertEqual(ns.parse_niche("economics of owning:business"), ("economics of owning", "business", 8.0))
        self.assertEqual(ns.parse_niche("car news:autos:6.5"), ("car news", "autos", 6.5))
        self.assertEqual(ns.parse_niche("space facts"), ("space facts", "education", 6.0))
        self.assertEqual(ns.parse_niche("x:unknowncat"), ("x", "unknowncat", 4.0))

    def test_scan_skips_shorts_and_finds_breakout(self):
        r = ns.scan("economics of owning", "business", 8.0, ARGS, "key", fetch=fake_fetch)
        self.assertEqual(r["videos"], 3)  # the 45-second Short is excluded
        self.assertEqual(r["small_channel_breakouts"], 1)
        top = r["top_outliers"][0]
        self.assertEqual(top["title"], "The Economics of Owning a Software Company")
        self.assertAlmostEqual(top["outlier"], 274.1, places=1)  # 148000 / (540000/1000)
        self.assertEqual(r["new_channels_in_results"], 2)
        self.assertEqual(r["pay_pts"], 20.0)
        self.assertGreater(r["score"], 0)
        self.assertLessEqual(r["score"], 100)

    def test_reports_written(self):
        r = ns.scan("economics of owning", "business", 8.0, ARGS, "key", fetch=fake_fetch)
        with tempfile.TemporaryDirectory() as d:
            prefix = os.path.join(d, "rep")
            ns.write_reports([r], prefix)
            with open(prefix + ".md", encoding="utf-8") as fh:
                self.assertIn("Economics of Owning a Software Company", fh.read())
            with open(prefix + ".csv", encoding="utf-8") as fh:
                self.assertIn("score", fh.readline())

    def test_empty_niche(self):
        r = ns.analyse_niche("nothing", "business", 8.0, [], {}, NOW, 240, 50000)
        self.assertEqual(r["videos"], 0)
        self.assertEqual(r["score"], 0)


if __name__ == "__main__":
    unittest.main()
