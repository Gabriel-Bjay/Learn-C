import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import make_video as mv  # noqa: E402

TIMINGS = {"duration": 9.0, "paragraphs": [
    {"n": 1, "start": 0.2, "end": 2.4, "text": "a"},
    {"n": 2, "start": 3.0, "end": 5.0, "text": "b"},
    {"n": 3, "start": 5.6, "end": 7.0, "text": "c"},
    {"n": 4, "start": 7.6, "end": 9.0, "text": "d"},
]}

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class ShotListTests(unittest.TestCase):
    def test_parse(self):
        shots = mv.parse_shots("""
            # comment
            1: image: a.png
            1: text: Big | small
            3-4: pexels: phone on train
            5: Chart: charts/c1.png
        """)
        self.assertEqual(shots[1], [("image", "a.png"), ("text", "Big | small")])
        self.assertEqual(shots[3], [("pexels", "phone on train")])
        self.assertEqual(shots[4], [])
        self.assertEqual(shots[5], [("chart", "charts/c1.png")])

    def test_parse_errors(self):
        with self.assertRaises(ValueError):
            mv.parse_shots("1 image a.png")
        with self.assertRaises(ValueError):
            mv.parse_shots("1: gif: a.gif")
        with self.assertRaises(ValueError):
            mv.parse_shots("4-2: text: backwards")

    def test_timeline_covers_audio_and_splits(self):
        shots = mv.parse_shots("1: image: a.png\n1: text: b\n3: video: c.mp4")
        tl = mv.build_timeline(TIMINGS, shots)
        # p1 split in two from 0.0 to 3.0; p2 has no shot -> extends p1's last visual; p3-4 video
        self.assertEqual(tl[0][:3], (0.0, 1.5, "image"))
        self.assertEqual(tl[1][:3], (1.5, 5.6, "text"))
        self.assertEqual(tl[2][:3], (5.6, 9.0, "video"))
        self.assertEqual(sum(mv.frame_counts(tl)), 9 * mv.FPS)

    def test_timeline_title_card_when_first_paragraph_has_no_shot(self):
        tl = mv.build_timeline(TIMINGS, mv.parse_shots("2: text: hi"))
        self.assertEqual(tl[0][2:], ("text", "WORK REWIRED"))
        self.assertEqual(tl[0][1], 3.0)

    def test_frame_counts_no_drift(self):
        tl = [(i / 3, (i + 1) / 3, "text", "x") for i in range(300)]  # 100 s in thirds
        self.assertEqual(sum(mv.frame_counts(tl)), 100 * mv.FPS)


class StockTests(unittest.TestCase):
    def test_pick_pexels_file_prefers_hd_near_1920(self):
        video = {"video_files": [
            {"file_type": "video/mp4", "width": 640, "link": "sd"},
            {"file_type": "video/mp4", "width": 1920, "link": "hd"},
            {"file_type": "video/mp4", "width": 3840, "link": "4k"},
        ]}
        self.assertEqual(mv.pick_pexels_file(video), "hd")

    def test_pick_pixabay_file_skips_empty_sizes(self):
        hit = {"videos": {
            "large": {"url": "", "width": 0},
            "medium": {"url": "m", "width": 1920},
            "small": {"url": "s", "width": 1280},
            "tiny": {"url": "t", "width": 640},
        }}
        self.assertEqual(mv.pick_pixabay_file(hit), "m")
        self.assertIsNone(mv.pick_pixabay_file({"videos": {}}))

    def test_fetch_uses_cache_rotates_and_falls_back(self):
        calls = []

        def broken(query, key):
            raise mv.urllib.error.URLError("down")

        def working(query, key):
            return [f"clip{i}" for i in range(3)]

        def fake_download(url, path):
            calls.append(url)
            Path(path).write_bytes(b"x")

        providers = {"pixabay": broken, "pexels": working}
        keys = {"pixabay": "k1", "pexels": "k2"}
        with tempfile.TemporaryDirectory() as d:
            a = mv.fetch_stock("phone on train", 0, d, keys, providers, fake_download)
            b = mv.fetch_stock("phone on train", 1, d, keys, providers, fake_download)
            again = mv.fetch_stock("phone on train", 0, d, keys, providers, fake_download)
            self.assertNotEqual(a, b)
            self.assertEqual(a, again)
            self.assertEqual(calls, ["clip0", "clip1"])  # third call came from the cache
            self.assertIsNone(mv.fetch_stock("new query", 0, d, {}, providers, fake_download))

    def test_manually_saved_clip_needs_no_key(self):
        with tempfile.TemporaryDirectory() as d:
            manual = mv.stock_path("Empty train station!", 0, d)
            self.assertEqual(manual.name, "empty-train-station-0.mp4")
            manual.write_bytes(b"x")
            self.assertEqual(mv.fetch_stock("Empty train station!", 0, d, {}), manual)


@unittest.skipUnless(HAVE_FFMPEG and HAVE_PIL, "needs ffmpeg and Pillow")
class RenderTests(unittest.TestCase):
    def test_end_to_end_preview(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=9",
                            "-ar", "24000", str(d / "voice.wav")], check=True)
            (d / "voice.timings.json").write_text(json.dumps(TIMINGS))
            Image.new("RGB", (800, 600), "white").save(d / "shot.png")
            (d / "shots.txt").write_text("1: screenshot: shot.png\n2: text: $1.75B | raised\n"
                                         "3: stock: office\n4: image: missing.png\n")
            out = d / "out.mp4"
            fake_fetch = lambda *a: None  # noqa: E731  (no network in tests)
            tl, warnings = mv.make_video(d / "voice.wav", d / "shots.txt", out, size=(480, 270),
                                         preset="ultrafast", fetch=fake_fetch)
            self.assertEqual(len(tl), 4)
            self.assertEqual(len(warnings), 2)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
            self.assertAlmostEqual(float(probe.stdout), 9.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_FFMPEG and HAVE_PIL, "needs ffmpeg and Pillow")
class VisualsV2Tests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=9",
                        "-ar", "24000", str(d / "voice.wav")], check=True)
        (d / "voice.timings.json").write_text(json.dumps(TIMINGS))
        (d / "people").mkdir()
        Image.new("RGB", (400, 600), "gray").save(d / "people" / "jane-doe.jpg")
        Image.new("RGB", (900, 500), "white").save(d / "page.png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_people_photos_overlays_and_auto_screenshots(self):
        captured = []

        class FakeGrabber:
            def capture(self, url, phrase, out):
                from PIL import Image
                captured.append((url, phrase))
                Image.new("RGB", (1280, 800), "white").save(out)
                return None

            def close(self):
                pass

        def fake_fetch(query, occurrence, cache_dir, keys, kind="stock"):
            return None  # no stock available -> placeholder + exact file name

        (self.d / "shots.txt").write_text(
            "1: person: Jane Doe >> Jane Doe | Founder\n"
            "1: person: Unknown Person\n"
            "2: screenshot: https://example.com/story | key phrase\n"
            "3: photo: city skyline >> BIG NUMBER | detail\n"
            "4: image: page.png >> Overlay | on an image\n")

        def no_wiki(name):
            raise LookupError("no photo on its Wikipedia page")

        tl, warnings = mv.make_video(self.d / "voice.wav", self.d / "shots.txt", self.d / "out.mp4",
                                     size=(480, 270), preset="ultrafast", fetch=fake_fetch,
                                     person_lookup=no_wiki, grabber_factory=FakeGrabber)
        self.assertEqual(captured, [("https://example.com/story", "key phrase")])
        auto = list((self.d / "screenshots" / "auto").glob("example.com-*.png"))
        self.assertEqual(len(auto), 1)
        joined = "\n".join(warnings)
        self.assertIn("no photo of Unknown Person", joined)
        self.assertIn("people/unknown-person.jpg", joined)
        self.assertIn("photo 'city skyline' -> save one as stock/city-skyline-0.jpg", joined)
        self.assertNotIn("Jane Doe", joined)  # hand-saved photo was used

        # A second run reuses the cached screenshot instead of capturing again.
        mv.make_video(self.d / "voice.wav", self.d / "shots.txt", self.d / "out2.mp4",
                      size=(480, 270), preset="ultrafast", fetch=fake_fetch,
                      person_lookup=no_wiki, grabber_factory=FakeGrabber)
        self.assertEqual(len(captured), 1)

    def test_person_credit_written(self):
        from PIL import Image

        def fake_wiki(name):
            return {"url": "http://x/photo.jpg", "license": "CC BY-SA 4.0", "artist": "A. Photographer"}

        def fake_download(url, path):
            Image.new("RGB", (300, 400), "gray").save(path, "JPEG")

        path, credit = mv.fetch_person("John Smith", self.d / "people", lookup=fake_wiki, download=fake_download)
        self.assertTrue(path.exists())
        self.assertEqual(credit, "Photo of John Smith: A. Photographer, CC BY-SA 4.0, via Wikimedia Commons")
        # cached: no lookup needed the second time
        again = mv.fetch_person("John Smith", self.d / "people", lookup=None)
        self.assertEqual(again, (path, credit))

    def test_free_licence_check(self):
        for ok in ["CC BY-SA 4.0", "CC0", "Public domain", "CC BY 2.0"]:
            self.assertTrue(mv.FREE_LICENSE.match(ok), ok)
        for bad in ["Fair use", "Non-free", "All rights reserved", ""]:
            self.assertFalse(mv.FREE_LICENSE.match(bad), bad)

    def test_fade_filter(self):
        self.assertEqual(mv.fade_filter(3, 0.25), "null")          # too short to fade
        self.assertIn("fade=t=in", mv.fade_filter(90, 0.25))
        self.assertIn("st=2.750", mv.fade_filter(90, 0.25))
