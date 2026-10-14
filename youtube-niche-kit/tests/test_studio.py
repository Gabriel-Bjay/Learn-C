import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import studio  # noqa: E402

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "videos" / "01-quibi").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_video_path_only_real_folders(self):
        self.assertIsNotNone(studio.video_path(self.root, "01-quibi"))
        for bad in ["..", "../videos", "02-nope", "", "01-quibi/../..", "a\\b"]:
            self.assertIsNone(studio.video_path(self.root, bad), bad)

    def test_upload_targets(self):
        folder = self.root / "videos" / "01-quibi"
        ok = ["stock/clip-0.mp4", "screenshots/auto/x.png", "people/jane-doe.jpg", "music.mp3", "logos/uber.png"]
        bad = ["../x.mp3", "stock/../../x.mp4", "/etc/passwd", "C:/x.png", "script.txt", "notes/x.png",
               "stock/run.exe", "cover.png", "stock//x.mp4"]
        for rel in ok:
            self.assertIsNotNone(studio.upload_target(folder, rel), rel)
        for rel in bad:
            self.assertIsNone(studio.upload_target(folder, rel), rel)

    def test_missing_from_output(self):
        lines = [
            "Placeholders were used for:",
            "  - stock clip 'empty train station' -> save one as stock/empty-train-station-0.mp4",
            "  - screenshot of https://x.com/a failed (blocked) -> save one by hand as screenshots/auto/x.com-1234abcd.png",
            "  - no photo of Meg Whitman (no free photo) -> save one as people/meg-whitman.jpg",
            "  - missing file charts/chart9.png",
            "  - stock clip 'empty train station' -> save one as stock/empty-train-station-0.mp4",
        ]
        paths = [m["path"] for m in studio.missing_from_output(lines)]
        self.assertEqual(paths, ["stock/empty-train-station-0.mp4", "screenshots/auto/x.com-1234abcd.png",
                                 "people/meg-whitman.jpg", "charts/chart9.png"])

    def test_thumbnail_run_keeps_the_videos_missing_list(self):
        folder = self.root / "videos" / "01-quibi"
        studio.save_studio_state(folder, missing_video=[{"path": "stock/a-0.mp4", "text": "a"}],
                                 missing_thumbs=[{"path": "stock/b-0.jpg", "text": "b"}])
        self.assertEqual([m["path"] for m in studio.missing_items(folder)], ["stock/a-0.mp4", "stock/b-0.jpg"])
        studio.save_studio_state(folder, missing_thumbs=[])  # what a clean thumbnails-only run stores
        self.assertEqual([m["path"] for m in studio.missing_items(folder)], ["stock/a-0.mp4"])
        studio.forget_missing(folder, "stock/a-0.mp4")
        self.assertEqual(studio.missing_items(folder), [])

    def test_create_video_numbers_and_starter_files(self):
        name = studio.create_video(self.root, "Uber: one ride!")
        self.assertEqual(name, "02-uber-one-ride")
        folder = self.root / "videos" / name
        for f in ("script.txt", "shots.txt", "thumbnail.txt"):
            self.assertTrue((folder / f).exists(), f)
        self.assertIsNone(studio.check_text("shots", (folder / "shots.txt").read_text()))
        self.assertIsNone(studio.check_text("thumbnail", (folder / "thumbnail.txt").read_text()))

    def test_settings_files_keep_other_lines(self):
        path = self.root / "settings.txt"
        path.write_text("# my notes\nVOICE=am_michael\nOTHER=1\n")
        studio.write_kv(path, {"VOICE": "bm_george"})
        self.assertEqual(path.read_text(), "# my notes\nVOICE=bm_george\nOTHER=1\n")
        self.assertEqual(studio.read_kv(path)["VOICE"], "bm_george")

    def test_build_steps_skip_voiceover_when_up_to_date(self):
        folder = self.root / "videos" / "01-quibi"
        (folder / "script.txt").write_text("hello")
        (folder / "shots.txt").write_text("1: text: hi")
        steps = studio.build_steps(self.root, folder, "preview", "am_michael")
        self.assertEqual([s[0] for s in steps], ["Voiceover (am_michael)", "Preview video"])
        (folder / "script.wav").write_bytes(b"x")
        os.utime(folder / "script.txt", (time.time() - 60, time.time() - 60))
        (folder / "thumbnail.txt").write_text("text: HI")
        (folder / "bg.mp3").write_bytes(b"x")
        steps = studio.build_steps(self.root, folder, "final", "am_michael")
        self.assertEqual([s[0] for s in steps], ["Final 1080p video", "Thumbnails"])
        self.assertIn("--music", steps[0][1])
        self.assertNotIn("--preview", steps[0][1])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        folder = cls.root / "videos" / "01-quibi"
        folder.mkdir(parents=True)
        (folder / "script.txt").write_text("one\n\ntwo\n")
        (folder / "shots.txt").write_text("1: text: hi\n")
        (folder / "thumbnail.txt").write_text("text: 700 HOMES\ntrend: up\n")
        (folder / "clip.mp4").write_bytes(bytes(range(256)) * 4)
        cls.server = studio.make_server(cls.root, 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or f"localhost:{self.port}"}
        if method in ("POST", "PUT"):
            h["X-Studio"] = "1"
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, data, res

    def test_page_and_state(self):
        status, page, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Work Rewired Studio", page)
        status, data, _ = self.request("GET", "/api/state")
        state = json.loads(data)
        self.assertEqual([v["name"] for v in state["videos"]], ["01-quibi"])
        self.assertEqual(state["job"]["state"], "idle")

    def test_rejects_other_sites(self):
        status, _, _ = self.request("GET", "/api/state", host="evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/videos", body=b'{"title":"x"}', headers={"X-Studio": ""})
        self.assertEqual(status, 403)

    def test_save_text_reports_problems(self):
        status, data, _ = self.request("PUT", "/api/videos/01-quibi/text/shots", body="1: gif: x\r\n".encode())
        self.assertEqual(status, 200)
        self.assertIn("unknown type 'gif'", json.loads(data)["problem"])
        self.assertEqual((self.root / "videos/01-quibi/shots.txt").read_text(), "1: gif: x\n")
        status, data, _ = self.request("POST", "/api/videos/01-quibi/run", body=b'{"kind":"preview"}')
        self.assertEqual(status, 400)  # won't build with a broken shot list
        self.request("PUT", "/api/videos/01-quibi/text/shots", body=b"1: text: hi\n")

    def test_upload_and_traversal(self):
        status, data, _ = self.request("PUT", "/api/videos/01-quibi/upload?path=stock/x-0.mp4", body=b"abc")
        self.assertEqual((status, json.loads(data)["path"]), (200, "stock/x-0.mp4"))
        self.assertEqual((self.root / "videos/01-quibi/stock/x-0.mp4").read_bytes(), b"abc")
        status, _, _ = self.request("PUT", "/api/videos/01-quibi/upload?path=../../x.mp3", body=b"abc")
        self.assertEqual(status, 400)
        status, _, _ = self.request("GET", "/media/01-quibi/..%2F..%2Fsettings.txt")
        self.assertEqual(status, 404)

    def test_video_range_requests(self):
        status, data, res = self.request("GET", "/media/01-quibi/clip.mp4", headers={"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(data, bytes(range(10, 20)))
        self.assertEqual(res.getheader("Content-Range"), "bytes 10-19/1024")

    @unittest.skipUnless(HAVE_PIL, "needs Pillow")
    def test_thumbnail_job_runs_to_done(self):
        status, _, _ = self.request("POST", "/api/videos/01-quibi/run", body=b'{"kind":"thumbs"}')
        self.assertEqual(status, 200)
        deadline = time.time() + 60
        while time.time() < deadline:
            job = json.loads(self.request("GET", "/api/job")[1])
            if job["state"] != "running":
                break
            time.sleep(0.3)
        self.assertEqual(job["state"], "done", "\n".join(job["lines"]))
        self.assertTrue((self.root / "videos/01-quibi/thumbnail-1.jpg").exists())
        video = json.loads(self.request("GET", "/api/videos/01-quibi")[1])
        self.assertEqual(video["thumbs"], ["thumbnail-1.jpg"])


if __name__ == "__main__":
    unittest.main()
