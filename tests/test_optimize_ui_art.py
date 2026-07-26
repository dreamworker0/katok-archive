from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from PIL import Image

from scripts import build_hosting, build_site
from scripts.optimize_ui_art import optimize_image


class OptimizeUiArtTests(unittest.TestCase):
    def test_resizes_to_max_width_and_writes_webp(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "nested" / "result.webp"
            Image.new("RGB", (1200, 800), "#ca7154").save(source)

            optimize_image(source, output, max_width=480, quality=76)

            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual("WEBP", image.format)
                self.assertEqual((480, 320), image.size)

    def test_does_not_upscale_small_sources(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "result.webp"
            Image.new("RGBA", (320, 240), (135, 157, 120, 180)).save(source)

            optimize_image(source, output, max_width=480, quality=76)

            with Image.open(output) as image:
                self.assertEqual((320, 240), image.size)

    def test_art_is_copied_to_local_and_hosting_builds(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            hosting = root / "hosting"
            with (
                mock.patch.object(build_site, "SITE", site),
                mock.patch.object(build_site, "ASSETS_IMAGES", root / "no-private-images"),
            ):
                build_site.write_site({})
            with mock.patch.object(build_hosting, "HOSTING", hosting):
                build_hosting.main()

            self.assertTrue((site / "art" / "archive-hero.webp").is_file())
            self.assertTrue((hosting / "art" / "archive-hero.webp").is_file())


if __name__ == "__main__":
    unittest.main()
