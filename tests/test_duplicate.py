from __future__ import annotations

import unittest

from reading_assistant.config import CaptureSettings
from reading_assistant.duplicate import PageImageInspector, SpreadSplitter, difference_hash, hamming_distance
from tests.fakes import sample_image


class DuplicateTests(unittest.TestCase):
    def test_same_image_is_duplicate(self) -> None:
        image = sample_image(1)
        try:
            inspector = PageImageInspector(CaptureSettings())
            first = inspector.assess(image, None)
            second = inspector.assess(image.copy(), first.page_hash)
            self.assertTrue(second.duplicate)
            self.assertEqual(second.hamming_from_previous, 0)
        finally:
            image.close()

    def test_black_screen_is_rejected(self) -> None:
        from PIL import Image

        image = Image.new("RGB", (500, 700), "black")
        try:
            self.assertTrue(PageImageInspector(CaptureSettings()).assess(image, None).black_or_flat)
        finally:
            image.close()

    def test_spread_order(self) -> None:
        image = sample_image(3, (1200, 800))
        try:
            parts = SpreadSplitter().split(image, "2ページ見開き", "右→左")
            self.assertEqual([part.name for part in parts], ["right", "left"])
            for part in parts:
                part.image.close()
        finally:
            image.close()


if __name__ == "__main__":
    unittest.main()

