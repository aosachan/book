from __future__ import annotations

import unittest

from reading_assistant.calibration import CalibrationSample, CalibrationTracker


class CalibrationTests(unittest.TestCase):
    def test_ten_page_metrics_and_estimates(self) -> None:
        tracker = CalibrationTracker()
        for index in range(10):
            tracker.add(CalibrationSample(2.0 + index, True, 0.8, index == 2, 1 if index == 2 else 0))
        metrics = tracker.metrics(250)
        self.assertTrue(metrics["complete"])
        self.assertEqual(metrics["sample_pages"], 10)
        self.assertAlmostEqual(metrics["success_rate"], 1.0)
        self.assertAlmostEqual(metrics["estimates_seconds"]["configured_total"], 6.5 * 250)


if __name__ == "__main__":
    unittest.main()

