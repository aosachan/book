from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean


@dataclass
class CalibrationSample:
    seconds: float
    success: bool
    confidence: float = 0.0
    json_failed: bool = False
    retries: int = 0


@dataclass
class CalibrationTracker:
    target_pages: int = 10
    samples: list[CalibrationSample] = field(default_factory=list)

    def add(self, sample: CalibrationSample) -> None:
        if not self.complete:
            self.samples.append(sample)

    @property
    def complete(self) -> bool:
        return len(self.samples) >= self.target_pages

    def metrics(self, configured_total_pages: int) -> dict:
        durations = [sample.seconds for sample in self.samples]
        successes = [sample for sample in self.samples if sample.success]
        average = fmean(durations) if durations else 0.0
        count = len(self.samples)
        return {
            "sample_pages": count,
            "target_pages": self.target_pages,
            "complete": self.complete,
            "average_seconds_per_page": average,
            "fastest_seconds": min(durations) if durations else 0.0,
            "slowest_seconds": max(durations) if durations else 0.0,
            "success_rate": len(successes) / count if count else 0.0,
            "average_confidence": fmean([s.confidence for s in successes]) if successes else 0.0,
            "json_failure_rate": sum(s.json_failed for s in self.samples) / count if count else 0.0,
            "retry_rate": sum(s.retries > 0 for s in self.samples) / count if count else 0.0,
            "estimates_seconds": {
                "100_pages": average * 100,
                "200_pages": average * 200,
                "300_pages": average * 300,
                "configured_total": average * max(0, configured_total_pages),
            },
        }

