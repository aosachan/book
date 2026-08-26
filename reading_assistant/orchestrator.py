from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from PIL import Image

from .analyzer import PageAnalyzer
from .calibration import CalibrationSample, CalibrationTracker
from .chapter import ChapterIntegrator, write_chapter_markdown
from .capture.base import FrameSource
from .config import AppConfig
from .duplicate import PageImageInspector, SpreadSplitter, hamming_distance
from .errors import (
    DuplicatePageError,
    PageChangeTimeout,
    ProtectedCaptureError,
    ReadingAssistantError,
)
from .integrator import ChunkIntegrator
from .memory import ReadingMemory
from .models import PageRecord, Rect, WindowInfo
from .reports import ReportGenerator
from .window_control import WindowsWindowController


class ReaderState(str, Enum):
    IDLE = "未開始"
    READY = "待機中"
    READING = "読解中"
    PAUSED = "一時停止"
    ERROR = "要確認"
    STOPPED = "停止"
    FINALIZING = "最終分析中"
    FINISHED = "読書終了"


@dataclass
class ReaderCallbacks:
    status: Callable[[str], None] = lambda _: None
    warning: Callable[[str], None] = lambda _: None
    preview: Callable[[Image.Image | None], None] = lambda image: image.close() if image is not None else None
    page: Callable[[PageRecord], None] = lambda _: None
    chunk: Callable[[dict], None] = lambda _: None
    metrics: Callable[[dict], None] = lambda _: None
    understanding: Callable[[dict], None] = lambda _: None
    calibration: Callable[[dict], None] = lambda _: None


class ReadingOrchestrator:
    def __init__(
        self,
        config: AppConfig,
        memory: ReadingMemory,
        frame_source: FrameSource,
        analyzer: PageAnalyzer,
        integrator: ChunkIntegrator,
        report_generator: ReportGenerator,
        controller: WindowsWindowController,
        reports_root: Path,
        callbacks: ReaderCallbacks | None = None,
        chapter_integrator: ChapterIntegrator | None = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.frame_source = frame_source
        self.analyzer = analyzer
        self.integrator = integrator
        self.report_generator = report_generator
        self.chapter_integrator = chapter_integrator or ChapterIntegrator(
            integrator.client, config.quality
        )
        self.controller = controller
        self.reports_root = reports_root
        self.callbacks = callbacks or ReaderCallbacks()
        self.inspector = PageImageInspector(config.capture)
        self.splitter = SpreadSplitter()
        self.session_id: int | None = None
        self.window: WindowInfo | None = None
        self.capture_rect: Rect | None = None
        self.state = ReaderState.IDLE
        self._operation_lock = threading.Lock()
        self._pause_requested = False
        self._stop_requested = False
        self.calibration_tracker: CalibrationTracker | None = None

    def new_session(self, title: str, total_pages: int) -> int:
        settings = {
            "base_url": self.config.llm.base_url,
            "model": self.config.llm.model,
            "quality": self.config.quality,
            "spread_mode": self.config.spread_mode,
            "reading_direction": self.config.reading_direction,
            "reading_mode": self.config.reading_mode,
        }
        self.session_id = self.memory.create_session(
            title,
            total_pages,
            self.config.quality,
            self.config.chunk_size,
            settings,
        )
        self.state = ReaderState.READY
        self._emit_status("新しい読書セッションを作成しました。対象ウィンドウと本文領域を設定してください。")
        return self.session_id

    def resume_session(self, session_id: int, window_lookup: Callable[[int], WindowInfo | None] | None = None) -> None:
        session = self.memory.get_session(session_id)
        self.session_id = session_id
        capture = session.get("capture", {})
        if capture.get("capture_rect"):
            self.capture_rect = Rect.from_dict(capture["capture_rect"])
        if window_lookup and capture.get("window_handle"):
            self.window = window_lookup(int(capture["window_handle"]))
        self.state = ReaderState.READY
        self.memory.update_status(session_id, "ready")
        context = self.memory.recent_context(session_id, self.config.recent_chunks_on_resume)
        self.callbacks.understanding(context)
        self._emit_status(
            f"「{session['title']}」を {session['read_pages']}ページ読了地点から再開しました。"
        )
        self._emit_metrics()

    def set_capture_target(self, window: WindowInfo, rect: Rect) -> None:
        self._require_session()
        rect.validate()
        if not _rect_inside(rect, window.rect):
            raise ValueError("本文領域は対象ウィンドウの内側を選択してください。")
        self.window = window
        self.capture_rect = rect
        self.memory.set_capture(self.session_id, window, rect)  # type: ignore[arg-type]
        self._emit_status(f"本文領域を設定しました: {rect.width}x{rect.height}")

    def start(self) -> None:
        self._require_ready_target()
        self._pause_requested = False
        self._stop_requested = False
        self.state = ReaderState.READY
        self.memory.update_status(self.session_id, "ready")  # type: ignore[arg-type]
        self._emit_status("読書準備完了。「次のページ」または「このページを読む」を押してください。")

    def pause(self) -> None:
        self._pause_requested = True
        if self.state != ReaderState.READING:
            self.state = ReaderState.PAUSED
            self.memory.update_status(self.session_id, "paused")  # type: ignore[arg-type]
        self._emit_status("一時停止を予約しました。処理中なら現在ページの保存後に停止します。")

    def resume(self) -> None:
        self._pause_requested = False
        self._stop_requested = False
        self.state = ReaderState.READY
        self.memory.update_status(self.session_id, "ready")  # type: ignore[arg-type]
        self._emit_status("読書を再開しました。")

    def stop(self) -> None:
        self._stop_requested = True
        if self.state != ReaderState.READING:
            self.state = ReaderState.STOPPED
            self.memory.update_status(self.session_id, "stopped")  # type: ignore[arg-type]
        self._emit_status("停止しました。読書メモはSQLiteへ保存済みです。")

    def start_calibration(self) -> None:
        self.calibration_tracker = CalibrationTracker(10)
        self._emit_status("10ページ・キャリブレーションを開始しました。通常どおり10ページ読ませてください。")
        self.callbacks.calibration(self.calibration_tracker.metrics(self.config.total_pages))

    def read_current_page(self, user_note: str = "", user_important: bool = False) -> list[PageRecord]:
        return self._process_capture(user_note, user_important, turn_after=False)

    def read_and_turn(self, user_note: str = "", user_important: bool = False) -> list[PageRecord]:
        return self._process_capture(user_note, user_important, turn_after=True)

    def skip_current_page(self, turn_after: bool = False) -> None:
        self._require_ready_target()
        self.memory.record_failure(self.session_id)  # type: ignore[arg-type]
        self.callbacks.warning("このページを読書メモなしでスキップしました。")
        if turn_after:
            previous = self._capture_hash_only()
            self.controller.send_page_key(self.window.handle, self.config.capture.turn_key)  # type: ignore[union-attr]
            self._wait_for_change(previous)
        self._emit_metrics()

    def finalize(self) -> Path:
        self._require_session()
        if not self._operation_lock.acquire(blocking=False):
            raise ReadingAssistantError("別の処理が進行中です。")
        try:
            self.state = ReaderState.FINALIZING
            self._close_chapter_locked(finalizing=True, allow_empty=True)
            material = self.memory.all_semantic_material(self.session_id)  # type: ignore[arg-type]
            output_dir = self.report_generator.generate(material, self.reports_root, self._emit_status)
            self.memory.update_status(self.session_id, "finished")  # type: ignore[arg-type]
            self.state = ReaderState.FINISHED
            self._emit_status(f"読書終了。7つのMarkdownレポートを生成しました: {output_dir}")
            return output_dir
        finally:
            self._operation_lock.release()

    def close_chapter(self) -> Path:
        self._require_session()
        if not self._operation_lock.acquire(blocking=False):
            raise ReadingAssistantError("別の処理が進行中です。")
        try:
            return self._close_chapter_locked(finalizing=False, allow_empty=False)
        except Exception as exc:
            self.state = ReaderState.ERROR
            if self.session_id:
                self.memory.update_status(self.session_id, "error")
            self.callbacks.warning(str(exc))
            raise
        finally:
            self._operation_lock.release()

    def _close_chapter_locked(self, finalizing: bool, allow_empty: bool) -> Path:
        session_id = self.session_id
        self._require_session()
        chapters = self.memory.chapter_summaries(session_id)  # type: ignore[arg-type]
        previous_end = int(chapters[-1]["end_page"]) if chapters else 0
        session = self.memory.get_session(session_id)  # type: ignore[arg-type]
        end_page = int(session["read_pages"])
        if end_page <= previous_end:
            if allow_empty:
                return Path()
            raise ReadingAssistantError("前回の章区切り以降に読んだページがありません。")

        pending = self.memory.pages_since_last_integration(session_id)  # type: ignore[arg-type]
        if pending:
            self._integrate_notes(pending)
        chunk_records = self.memory.chunks_since_last_chapter(session_id)  # type: ignore[arg-type]
        if not chunk_records:
            raise ReadingAssistantError("章へまとめるチャンク読書メモがありません。")

        chapter_index = len(chapters) + 1
        start_page = previous_end + 1
        prior_carryover = chapters[-1].get("carryover", {}) if chapters else {}
        self._emit_status(
            f"第{chapter_index}章（page {start_page}〜{end_page}）の感想と引き継ぎを作成中…"
        )
        chapter = self.chapter_integrator.integrate(
            chapter_index,
            start_page,
            end_page,
            chunk_records,
            prior_carryover,
        )
        path = write_chapter_markdown(
            chapter,
            str(session["title"]),
            int(session_id),  # type: ignore[arg-type]
            self.reports_root,
        )
        self.memory.save_chapter(session_id, chapter, str(path))  # type: ignore[arg-type]
        context = self.memory.recent_context(
            session_id, self.config.recent_chunks_on_resume  # type: ignore[arg-type]
        )
        self.callbacks.understanding(context)
        self._emit_metrics()
        if finalizing:
            self.state = ReaderState.FINALIZING
        else:
            self.state = ReaderState.READY
            self.memory.update_status(session_id, "ready")  # type: ignore[arg-type]
            self._emit_status(
                f"第{chapter_index}章を保存しました。次章用の最小記憶へ切り替えました: {path}"
            )
        return path

    def _process_capture(self, user_note: str, user_important: bool, turn_after: bool) -> list[PageRecord]:
        self._require_ready_target()
        if self._pause_requested or self.state == ReaderState.PAUSED:
            raise ReadingAssistantError("一時停止中です。先に再開してください。")
        if not self._operation_lock.acquire(blocking=False):
            raise ReadingAssistantError("すでにページ処理中です。")
        image: Image.Image | None = None
        parts = []
        started = time.perf_counter()
        failure_recorded = False
        duplicate_recorded = False
        try:
            self.state = ReaderState.READING
            self.memory.update_status(self.session_id, "reading")  # type: ignore[arg-type]
            self._emit_status("現在ページを画面から取得しています…")
            image = self.frame_source.capture(self.capture_rect)  # type: ignore[arg-type]
            self.callbacks.preview(image.copy())
            previous_hash = self.memory.last_page_hash(self.session_id)  # type: ignore[arg-type]
            assessment = self.inspector.assess(image, previous_hash)
            if assessment.black_or_flat:
                self.memory.record_failure(self.session_id)  # type: ignore[arg-type]
                failure_recorded = True
                raise ProtectedCaptureError(assessment.warning)
            if assessment.duplicate:
                self.memory.record_duplicate(self.session_id)  # type: ignore[arg-type]
                duplicate_recorded = True
                raise DuplicatePageError(assessment.warning)
            if assessment.suspiciously_similar:
                self.callbacks.warning(assessment.warning)

            parts = self.splitter.split(image, self.config.spread_mode, self.config.reading_direction)
            records: list[PageRecord] = []
            capture_index = self.memory.next_capture_index(self.session_id)  # type: ignore[arg-type]
            for part_number, part in enumerate(parts):
                if self._stop_requested:
                    break
                page_index = self.memory.next_page_index(self.session_id)  # type: ignore[arg-type]
                self._emit_status(f"論理ページ {page_index} をVision LLMで読解中…")
                context = self.memory.recent_context(
                    self.session_id, self.config.recent_chunks_on_resume  # type: ignore[arg-type]
                )
                page_started = time.perf_counter()
                analysis, call = self.analyzer.analyze(part.image, page_index, context)
                elapsed = time.perf_counter() - page_started
                record = PageRecord(
                    analysis=analysis,
                    page_hash=assessment.page_hash,
                    capture_index=capture_index,
                    source_part=part.name,
                    processing_seconds=elapsed,
                    retry_count=call.retry_count,
                    json_failed_once=call.json_failed_once,
                    user_important=user_important,
                )
                note_for_page = user_note if part_number == 0 else f"[同じ見開きへのメモ] {user_note}" if user_note else ""
                self.memory.record_page(self.session_id, record, note_for_page)  # type: ignore[arg-type]
                records.append(record)
                self.callbacks.page(record)
                if analysis.reading_status == "UNREADABLE":
                    self.callbacks.warning(
                        f"論理ページ {page_index} は推測で補完せず、内容判定不能として保存しました。"
                    )
                elif analysis.reading_status == "PARTIAL":
                    self.callbacks.warning(
                        f"論理ページ {page_index} は情報不足として、確認できた事実だけを保存しました。"
                    )
                self._record_calibration(record, True)
            self._integrate_ready_chunks()
            self.callbacks.understanding(
                self.memory.recent_context(self.session_id, self.config.recent_chunks_on_resume)  # type: ignore[arg-type]
            )
            if turn_after and records and not self._pause_requested and not self._stop_requested:
                self._emit_status("通常のページ送りキーを送信し、画面変化を確認しています…")
                self.controller.send_page_key(self.window.handle, self.config.capture.turn_key)  # type: ignore[union-attr]
                self._wait_for_change(assessment.page_hash)
            if self._pause_requested:
                self.state = ReaderState.PAUSED
                self.memory.update_status(self.session_id, "paused")  # type: ignore[arg-type]
            elif self._stop_requested:
                self.state = ReaderState.STOPPED
                self.memory.update_status(self.session_id, "stopped")  # type: ignore[arg-type]
            else:
                self.state = ReaderState.READY
                self.memory.update_status(self.session_id, "ready")  # type: ignore[arg-type]
                self._emit_status("保存完了。次ページ待機中です。")
            self._emit_metrics()
            return records
        except Exception as exc:
            if self.session_id and not failure_recorded and not duplicate_recorded:
                self.memory.record_failure(self.session_id)
            self._record_calibration_failure(time.perf_counter() - started)
            self.state = ReaderState.ERROR
            if self.session_id:
                self.memory.update_status(self.session_id, "error")
            self.callbacks.warning(str(exc))
            self._emit_metrics()
            raise
        finally:
            for part in parts:
                try:
                    part.image.close()
                except Exception:
                    pass
            if image is not None:
                image.close()
            self.callbacks.preview(None)
            self._operation_lock.release()

    def _integrate_ready_chunks(self) -> None:
        pending = self.memory.pages_since_last_integration(self.session_id)  # type: ignore[arg-type]
        while len(pending) >= self.config.chunk_size:
            self._integrate_notes(pending[: self.config.chunk_size])
            pending = self.memory.pages_since_last_integration(self.session_id)  # type: ignore[arg-type]

    def _integrate_notes(self, notes: list[dict]) -> None:
        metrics = self.memory.metrics(self.session_id)  # type: ignore[arg-type]
        chunk_index = int(metrics["chunks"]) + 1
        prior = self.memory.recent_context(self.session_id, self.config.recent_chunks_on_resume)  # type: ignore[arg-type]
        self._emit_status(f"チャンク {chunk_index} を深く統合中（Thinking優先）…")
        chunk, _ = self.integrator.integrate(chunk_index, notes, prior)
        self.memory.save_chunk(self.session_id, chunk)  # type: ignore[arg-type]
        self.callbacks.chunk(chunk.summary)

    def _capture_hash_only(self) -> str:
        image = self.frame_source.capture(self.capture_rect)  # type: ignore[arg-type]
        try:
            assessment = self.inspector.assess(image, None)
            if assessment.black_or_flat:
                raise ProtectedCaptureError(assessment.warning)
            return assessment.page_hash
        finally:
            image.close()

    def _wait_for_change(self, previous_hash: str) -> None:
        deadline = time.monotonic() + self.config.capture.change_timeout_seconds
        candidate_hash: str | None = None
        stable = 0
        while time.monotonic() < deadline:
            time.sleep(self.config.capture.change_poll_seconds)
            image = self.frame_source.capture(self.capture_rect)  # type: ignore[arg-type]
            try:
                assessment = self.inspector.assess(image, previous_hash)
                if assessment.black_or_flat:
                    raise ProtectedCaptureError(assessment.warning)
                distance = assessment.hamming_from_previous or 0
                if distance <= self.config.capture.suspicious_hamming_threshold:
                    candidate_hash, stable = None, 0
                    continue
                if candidate_hash and hamming_distance(candidate_hash, assessment.page_hash) <= 3:
                    stable += 1
                else:
                    candidate_hash, stable = assessment.page_hash, 1
                if stable >= self.config.capture.stable_checks:
                    self._emit_status("ページ切替を確認しました。次ページ待機中です。")
                    return
            finally:
                image.close()
        raise PageChangeTimeout(
            "ページが変わりませんでした。キー設定、対象ウィンドウ、ローディング状態を確認してください。"
        )

    def _record_calibration(self, record: PageRecord, success: bool) -> None:
        tracker = self.calibration_tracker
        if tracker is None or tracker.complete:
            return
        tracker.add(
            CalibrationSample(
                seconds=record.processing_seconds,
                success=success,
                confidence=record.analysis.confidence,
                json_failed=record.json_failed_once,
                retries=record.retry_count,
            )
        )
        metrics = tracker.metrics(self.config.total_pages)
        self.callbacks.calibration(metrics)
        if tracker.complete:
            self.memory.save_calibration(self.session_id, metrics)
            self._emit_status("10ページ・キャリブレーションが完了しました。推定時間を確認できます。")

    def _record_calibration_failure(self, elapsed_seconds: float) -> None:
        tracker = self.calibration_tracker
        if tracker is None or tracker.complete:
            return
        tracker.add(CalibrationSample(seconds=elapsed_seconds, success=False))
        metrics = tracker.metrics(self.config.total_pages)
        self.callbacks.calibration(metrics)
        if tracker.complete:
            self.memory.save_calibration(self.session_id, metrics)

    def _emit_metrics(self) -> None:
        if self.session_id:
            self.callbacks.metrics(self.memory.metrics(self.session_id))

    def _emit_status(self, message: str) -> None:
        self.callbacks.status(message)

    def _require_session(self) -> None:
        if self.session_id is None:
            raise ReadingAssistantError("先に新規セッションまたは前回の続きからを選んでください。")

    def _require_ready_target(self) -> None:
        self._require_session()
        if self.window is None or self.capture_rect is None:
            raise ReadingAssistantError("対象ウィンドウと本文領域を設定してください。")
        self.capture_rect.validate()


def _rect_inside(inner: Rect, outer: Rect, tolerance: int = 8) -> bool:
    return (
        inner.left >= outer.left - tolerance
        and inner.top >= outer.top - tolerance
        and inner.right <= outer.right + tolerance
        and inner.bottom <= outer.bottom + tolerance
    )
