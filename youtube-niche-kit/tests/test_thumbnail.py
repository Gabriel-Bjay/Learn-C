import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import thumbnail as th  # noqa: E402

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class SpecTests(unittest.TestCase):
    def test_parse(self):
        spec = th.parse_spec("""
            # comment
            text: $17 MISSING
            text: PROBLEM #2   # trailing note
            logo: UBER
            strike: $31.40 -> $14.12
        """)
        self.assertEqual(spec["text"], ["$17 MISSING", "PROBLEM #2"])
        self.assertEqual((spec["trend"], spec["bar"], spec["logo"]), ("down", "cyan", "UBER"))
        self.assertEqual(spec["strike"], "$31.40 -> $14.12")

    def test_errors(self):
        for bad in ["logo: X", "text: A\ntrend: sideways", "text: A\nbar: pink", "text: A\ncolour: red"]:
            with self.assertRaises(ValueError):
                th.parse_spec(bad)

    def test_trend_direction(self):
        down, up = th.trend_points("down", 1), th.trend_points("up", 1)
        self.assertGreater(down[-1][1], down[0][1])  # y grows downwards
        self.assertLess(up[-1][1], up[0][1])
        self.assertLess(max(x for x, _ in down), th.SIZE[0] * 0.9)


@unittest.skipUnless(HAVE_PIL, "needs Pillow")
class RenderTests(unittest.TestCase):
    def test_three_versions_and_empty_corner(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            Image.new("RGB", (1600, 900), (90, 120, 160)).save(d / "bg.png")
            (d / "thumbnail.txt").write_text(
                "text: $1.75B FLOP\ntext: 6 MONTHS\ntext: A MUCH LONGER BAR TEXT THAT MUST SHRINK\n"
                "background: bg.png\nlogo: logos/missing.png\nkicker: What went wrong\n"
                "strike: RAISED $1.75B -> SOLD FOR <$100M\n", encoding="utf-8")
            outs, notes = th.make_thumbnails(d / "thumbnail.txt", fetch=lambda *a: None)
            self.assertEqual([o.name for o in outs], ["thumbnail-1.jpg", "thumbnail-2.jpg", "thumbnail-3.jpg"])
            self.assertIn("logo file logos/missing.png not found", notes)  # falls back to a text badge
            for out in outs:
                img = Image.open(out)
                self.assertEqual(img.size, (1280, 720))
                self.assertLess(out.stat().st_size, 2_000_000)
                # the bottom-right corner (video length) has no bright bar in it
                corner = img.crop((1050, 620, 1280, 720)).convert("L")
                self.assertLess(max(corner.getdata()), 200)

    def test_missing_stock_photo_tells_you_the_file_name(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "thumbnail.txt").write_text("text: 700 HOMES\nbackground: photo: new houses street\n")
            _, notes = th.make_thumbnails(d / "thumbnail.txt", fetch=lambda *a: None)
            self.assertEqual(notes, ["background photo 'new houses street' -> save one as stock/new-houses-street-0.jpg"])


if __name__ == "__main__":
    unittest.main()
