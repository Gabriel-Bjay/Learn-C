import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import voiceover as vo  # noqa: E402

try:
    import numpy as np
except ImportError:  # numpy comes with kokoro; skip synthesis tests without it
    np = None


def tok(text, start, end, ws=" "):
    return SimpleNamespace(text=text, whitespace=ws, start_ts=start, end_ts=end)


class FakeTensor:
    def __init__(self, arr):
        self.arr = arr

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.arr


class FakePipeline:
    """Yields one 1-second chunk per sentence, with word timings."""

    def __call__(self, text, voice, speed, split_pattern):
        for sentence in [s.strip() + "." for s in text.split(".") if s.strip()]:
            words = sentence.split()
            step = 1.0 / len(words)
            tokens = [tok(w, i * step, (i + 1) * step) for i, w in enumerate(words)]
            audio = FakeTensor(np.zeros(vo.SAMPLE_RATE, dtype=np.float32))
            yield SimpleNamespace(graphemes=sentence, tokens=tokens, audio=audio)


class VoiceoverTests(unittest.TestCase):
    def test_clean_script_strips_markdown_and_directions(self):
        raw = (
            "# Title\n\n"
            "**In 2020**, a start-up raised $1.75 billion. [B-roll: logo]\n"
            "Six months later, it was gone.\n\n"
            "[Cut to chart]\n"
            "---\n"
            "- Here's *why*.\n"
        )
        self.assertEqual(vo.clean_script(raw), [
            "In 2020, a start-up raised $1.75 billion. Six months later, it was gone.",
            "Here's why.",
        ])

    def test_fmt_time(self):
        self.assertEqual(vo.fmt_time(0), "00:00:00,000")
        self.assertEqual(vo.fmt_time(3723.456), "01:02:03,456")

    def test_caption_cues_split_long_chunks(self):
        words = "Six months later the company that raised almost two billion dollars was completely gone".split()
        tokens = [tok(w, i * 0.4, (i + 1) * 0.4) for i, w in enumerate(words)]
        cues = vo.caption_cues(" ".join(words), tokens, 10.0, 6.0)
        self.assertGreater(len(cues), 1)
        self.assertTrue(all(len(text) <= 42 for _, _, text in cues))
        self.assertAlmostEqual(cues[0][0], 10.0)
        self.assertEqual(" ".join(c[2] for c in cues), " ".join(words))
        self.assertTrue(all(cues[i][1] <= cues[i + 1][0] + 1e-9 for i in range(len(cues) - 1)))

    def test_caption_cues_fallback_without_timings(self):
        tokens = [SimpleNamespace(text="Hi", whitespace="", start_ts=None, end_ts=None)]
        self.assertEqual(vo.caption_cues("Hi.", tokens, 2.0, 1.5), [(2.0, 3.5, "Hi.")])

    @unittest.skipIf(np is None, "numpy not installed")
    def test_synthesize_timeline_and_srt(self):
        paragraphs = ["First sentence here. Second one.", "New paragraph."]
        timings = []
        audio, cues = vo.synthesize(paragraphs, FakePipeline(), "am_michael", 1.0, pause=0.5, chunk_gap=0.1,
                                    timings=timings)
        # 3 one-second chunks + one 0.1s chunk gap + one 0.5s paragraph pause
        self.assertAlmostEqual(len(audio) / vo.SAMPLE_RATE, 3.6, places=2)
        self.assertEqual(timings, [(0.0, 2.1), (2.6, 3.6)])
        self.assertAlmostEqual(cues[-1][0], 2.6, places=2)  # last paragraph starts after the pause
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.srt")
            vo.write_srt(cues, path)
            with open(path, encoding="utf-8") as fh:
                srt = fh.read()
        self.assertIn("00:00:00,000 --> ", srt)
        self.assertIn("New paragraph.", srt)

    def test_list_voices_runs_without_kokoro(self):
        vo.main(["--list-voices"])


if __name__ == "__main__":
    unittest.main()
