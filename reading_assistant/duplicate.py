from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean

from PIL import Image, ImageStat

from .config import CaptureSettings
from .models import CaptureAssessment


def difference_hash(image: Image.Image, hash_size: int = 16) -> str:
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    getter = getattr(gray, "get_flattened_data", gray.getdata)
    values = list(getter())
    bits = []
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits.append(values[offset + col] > values[offset + col + 1])
    number = 0
    for bit in bits:
        number = (number << 1) | int(bit)
    return f"{number:0{hash_size * hash_size // 4}x}"


def hamming_distance(first: str, second: str) -> int:
    if not first or not second or len(first) != len(second):
        return 10_000
    return (int(first, 16) ^ int(second, 16)).bit_count()


class PageImageInspector:
    def __init__(self, settings: CaptureSettings) -> None:
        self.settings = settings

    def assess(self, image: Image.Image, previous_hash: str | None) -> CaptureAssessment:
        sample = image.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
        stats = ImageStat.Stat(sample)
        mean = float(stats.mean[0])
        stddev = float(stats.stddev[0])
        page_hash = difference_hash(sample)
        distance = hamming_distance(page_hash, previous_hash) if previous_hash else None
        duplicate = distance is not None and distance <= self.settings.duplicate_hamming_threshold
        suspicious = (
            distance is not None
            and not duplicate
            and distance <= self.settings.suspicious_hamming_threshold
        )
        black_or_flat = (
            mean <= self.settings.black_mean_threshold
            or (stddev <= self.settings.flat_stddev_threshold and mean < 245.0)
        )
        warning = ""
        if black_or_flat:
            warning = "黒画面または単色画面です。キャプチャ保護を回避せず停止します。"
        elif duplicate:
            warning = "前ページと同じ画面です。新しいページとして記録しません。"
        elif suspicious:
            warning = "前ページと異常に似ています。UI重なりや未切替を確認してください。"
        return CaptureAssessment(
            page_hash=page_hash,
            mean_brightness=mean,
            stddev=stddev,
            hamming_from_previous=distance,
            duplicate=duplicate,
            suspiciously_similar=suspicious,
            black_or_flat=black_or_flat,
            warning=warning,
        )


@dataclass
class SpreadPart:
    name: str
    image: Image.Image


class SpreadSplitter:
    def split(self, image: Image.Image, mode: str, direction: str) -> list[SpreadPart]:
        double = mode == "2ページ見開き" or (mode == "自動判定" and self._looks_like_spread(image))
        if not double:
            return [SpreadPart("single", image.copy())]
        midpoint = self._find_gutter(image)
        left = image.crop((0, 0, midpoint, image.height))
        right = image.crop((midpoint, 0, image.width, image.height))
        resolved = direction
        if direction == "自動":
            resolved = self._guess_direction(image)
        if resolved == "右→左":
            return [SpreadPart("right", right), SpreadPart("left", left)]
        return [SpreadPart("left", left), SpreadPart("right", right)]

    @staticmethod
    def _looks_like_spread(image: Image.Image) -> bool:
        return image.width / max(1, image.height) >= 1.28

    @staticmethod
    def _find_gutter(image: Image.Image) -> int:
        gray = image.convert("L").resize((max(40, image.width // 8), max(40, image.height // 8)))
        start = int(gray.width * 0.42)
        end = int(gray.width * 0.58)
        candidates: list[tuple[float, int]] = []
        pixels = gray.load()
        for x in range(start, max(start + 1, end)):
            column = [pixels[x, y] for y in range(gray.height)]
            # Gutter tends to be bright/flat; center proximity is a tie-breaker.
            score = fmean(column) - math.sqrt(fmean([(p - fmean(column)) ** 2 for p in column]))
            score -= abs(x - gray.width / 2) * 0.05
            candidates.append((score, x))
        scaled = max(candidates)[1] if candidates else gray.width // 2
        return min(image.width - 1, max(1, round(scaled * image.width / gray.width)))

    @staticmethod
    def _guess_direction(image: Image.Image) -> str:
        # Vertical Japanese books are commonly right-to-left. This conservative
        # heuristic only selects that order for portrait-like halves.
        half_aspect = (image.width / 2) / max(1, image.height)
        return "右→左" if half_aspect < 0.82 else "左→右"
