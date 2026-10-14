import importlib.util
import os
import unittest

KIT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("build_app", os.path.join(KIT, "windows-app", "build_app.py"))
build_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_app)


class ManifestTests(unittest.TestCase):
    def test_manifest_is_up_to_date(self):
        # If this fails, run: python windows-app/build_app.py  (then commit manifest.txt + WorkRewired.zip)
        self.assertEqual(build_app.MANIFEST.read_text(), build_app.manifest_text())

    def test_user_settings_and_keys_are_never_shipped(self):
        dests = {dest for _, _, dest in build_app.FILES}
        self.assertFalse({"keys.txt", "settings.txt"} & dests)
        for mode, _, dest in build_app.FILES:
            if dest.startswith("videos/"):
                self.assertEqual(mode, "user", dest)

    def test_bat_files_run_from_one_block(self):
        # cmd reads a bracketed block in one go, so the updater can replace a running .bat safely.
        for _, src, _ in build_app.FILES:
            if src.endswith(".bat"):
                text = (build_app.KIT / src).read_bytes().decode("ascii")
                self.assertIn("\r\n", text)
                body = text.split("(\r\n", 1)[1]
                self.assertTrue(body.rstrip().endswith("exit /b\r\n)"), src)


if __name__ == "__main__":
    unittest.main()
