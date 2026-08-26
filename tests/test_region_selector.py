from __future__ import annotations

import unittest

from reading_assistant.models import Rect
from reading_assistant.region_selector import _geometry, intersection, left_half
from reading_assistant.window_control import WindowsWindowController


class FakeUser32:
    def __init__(self, iconic: bool) -> None:
        self.iconic = iconic
        self.show_calls: list[tuple[int, int]] = []

    def IsWindow(self, handle: int) -> bool:
        return True

    def IsIconic(self, handle: int) -> bool:
        return self.iconic

    def ShowWindow(self, handle: int, mode: int) -> bool:
        self.show_calls.append((handle, mode))
        return True

    def SetForegroundWindow(self, handle: int) -> bool:
        return True


class RegionSelectorTests(unittest.TestCase):
    def test_negative_monitor_geometry_uses_valid_tk_syntax(self) -> None:
        self.assertEqual(_geometry(Rect(-1920, -120, 0, 960)), "1920x1080-1920-120")
        self.assertEqual(_geometry(Rect(0, 0, 1920, 1080)), "1920x1080+0+0")

    def test_selector_uses_left_monitor_half_clipped_to_target(self) -> None:
        monitor = Rect(0, 0, 1920, 1080)
        target = Rect(100, 40, 1800, 1000)
        self.assertEqual(left_half(monitor), Rect(0, 0, 960, 1080))
        self.assertEqual(
            intersection(target, left_half(monitor)),
            Rect(100, 40, 960, 1000),
        )

    def test_target_on_right_has_no_left_selection_area(self) -> None:
        monitor = Rect(0, 0, 1920, 1080)
        target = Rect(1000, 0, 1920, 1080)
        self.assertIsNone(intersection(target, left_half(monitor)))

    def test_left_snapped_reader_can_use_its_whole_visible_area(self) -> None:
        monitor = Rect(0, 0, 1920, 1080)
        target = Rect(0, 0, 948, 1065)
        self.assertEqual(
            intersection(target, left_half(monitor)),
            target,
        )

    def test_activation_does_not_unmaximize_normal_window(self) -> None:
        controller = WindowsWindowController()
        fake = FakeUser32(iconic=False)
        controller.user32 = fake
        controller.activate(123)
        self.assertEqual(fake.show_calls, [])

    def test_activation_restores_only_minimized_window(self) -> None:
        controller = WindowsWindowController()
        fake = FakeUser32(iconic=True)
        controller.user32 = fake
        controller.activate(123)
        self.assertEqual(fake.show_calls, [(123, 9)])


if __name__ == "__main__":
    unittest.main()
