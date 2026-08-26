from __future__ import annotations

import json
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

from PIL import Image, ImageTk

from .analyzer import PageAnalyzer
from .capture.windows import WindowsScreenCapture, WindowsWindowProvider
from .chapter_export import chapter_note_paths, combine_chapter_notes
from .config import (
    AppConfig,
    QualityPreset,
    ReadingDirection,
    ReadingMode,
    SpreadMode,
    default_config_path,
    default_database_path,
    default_reports_dir,
)
from .hotkeys import GlobalReadHotkey
from .integrator import ChunkIntegrator
from .llm_client import LocalLLMClient
from .memory import ReadingMemory
from .models import PageRecord, WindowInfo
from .orchestrator import ReaderCallbacks, ReadingOrchestrator
from .region_selector import RegionSelector, intersection, left_half
from .reports import ReportGenerator
from .window_control import WindowsWindowController


BG = "#0b1220"
PANEL = "#111b2e"
PANEL_2 = "#152238"
TEXT = "#e8eef8"
MUTED = "#91a1b9"
ACCENT = "#43d9ad"
ACCENT_2 = "#55a7ff"
WARN = "#ffb454"
ERROR = "#ff6b7a"
BORDER = "#253552"


class ReadingAssistantApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Local Reading Assistant — 画面だけを読むローカルAI")
        self.root.geometry("1540x920")
        # A common reading layout puts the book on the left half and this app
        # on the right half of a 1920px monitor.
        self.root.minsize(900, 720)
        self.root.configure(bg=BG)

        self.config_path = default_config_path()
        try:
            self.config = AppConfig.load(self.config_path)
        except Exception:
            self.config = AppConfig()
        self.memory = ReadingMemory(default_database_path())
        self.window_provider = WindowsWindowProvider()
        self.frame_source = WindowsScreenCapture()
        self.controller = WindowsWindowController()
        self.client = LocalLLMClient(self.config.llm)
        self.analyzer = PageAnalyzer(self.client, self.config.quality)
        self.integrator = ChunkIntegrator(self.client, self.config.quality)
        self.report_generator = ReportGenerator(self.client, self.config.quality)
        self._windows: dict[str, WindowInfo] = {}
        self._sessions: dict[str, int] = {}
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._busy = False
        self._last_action: Callable[[], None] | None = None
        self._last_report_dir: Path | None = None
        self._started_at = time.monotonic()

        callbacks = ReaderCallbacks(
            status=lambda text: self._ui(self._set_status, text),
            warning=lambda text: self._ui(self._show_warning, text),
            preview=lambda image: self._ui(self._set_preview, image),
            page=lambda record: self._ui(self._on_page_record, record),
            chunk=lambda summary: self._ui(self._on_chunk, summary),
            metrics=lambda metrics: self._ui(self._update_metrics, metrics),
            understanding=lambda context: self._ui(self._update_understanding, context),
            calibration=lambda metrics: self._ui(self._update_calibration, metrics),
        )
        self.orchestrator = ReadingOrchestrator(
            self.config,
            self.memory,
            self.frame_source,
            self.analyzer,
            self.integrator,
            self.report_generator,
            self.controller,
            default_reports_dir(),
            callbacks,
        )

        self._configure_styles()
        self._build_ui()
        self._load_values()
        self._refresh_windows()
        self._refresh_sessions()
        self.hotkey = GlobalReadHotkey(self.root, self._on_hotkey)
        if self.config.hotkey_enabled and not self.hotkey.register():
            self._set_status("Ctrl+Shift+R ホットキーは他アプリで使用中のため登録できませんでした。")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Yu Gothic UI", 10))
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Yu Gothic UI", 17, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Yu Gothic UI", 9))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Value.TLabel", background=PANEL, foreground=ACCENT, font=("Yu Gothic UI", 12, "bold"))
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=("Yu Gothic UI", 11, "bold"))
        style.configure("Status.TLabel", background="#07101c", foreground=MUTED, padding=7)
        style.configure("Warning.TLabel", background="#3a291b", foreground="#ffd8a8", padding=8)
        style.configure("TButton", background=PANEL_2, foreground=TEXT, padding=(10, 6), borderwidth=0)
        style.map("TButton", background=[("active", "#20334f"), ("disabled", "#172033")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#07111f", font=("Yu Gothic UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#6ce8c4")])
        style.configure("Danger.TButton", background="#6e2632", foreground="#fff0f2")
        style.configure("TCombobox", fieldbackground="#0d1728", background=PANEL_2, foreground=TEXT, arrowcolor=TEXT)
        style.configure("TEntry", fieldbackground="#0d1728", foreground=TEXT, insertcolor=TEXT)
        style.configure("TSpinbox", fieldbackground="#0d1728", foreground=TEXT, arrowcolor=TEXT)
        style.configure("Horizontal.TProgressbar", troughcolor="#17233a", background=ACCENT, bordercolor="#17233a")
        style.configure("TLabelframe", background=PANEL, foreground=MUTED, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(16, 10, 16, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title_box = ttk.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="Local Reading Assistant", style="Header.TLabel").pack(side="left")
        ttk.Label(
            title_box,
            text="  画面表示だけを読み、原文・画像を保存しません",
            style="Sub.TLabel",
        ).pack(side="left", pady=(7, 0))
        self.connection_var = tk.StringVar(value="● 未接続")
        self.connection_label = tk.Label(
            header,
            textvariable=self.connection_var,
            bg=BG,
            fg=WARN,
            font=("Yu Gothic UI", 10, "bold"),
        )
        self.connection_label.grid(row=0, column=1, sticky="e")

        controls = ttk.Frame(self.root, style="Panel.TFrame", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=12)
        controls.columnconfigure(0, weight=1)

        target_row = ttk.Frame(controls, style="Panel.TFrame")
        target_row.grid(row=0, column=0, sticky="ew")
        target_row.columnconfigure(1, weight=1)
        ttk.Label(target_row, text="対象ウィンドウ", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(target_row, textvariable=self.window_var, state="readonly", width=44)
        self.window_combo.grid(row=0, column=1, sticky="ew", padx=(6, 5))
        ttk.Button(target_row, text="更新", command=self._refresh_windows).grid(row=0, column=2, padx=3)
        ttk.Button(target_row, text="本文領域を選択", command=self._select_region).grid(row=0, column=3, padx=(3, 0))

        llm_row = ttk.Frame(controls, style="Panel.TFrame")
        llm_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        llm_row.columnconfigure(1, weight=3)
        llm_row.columnconfigure(3, weight=2)
        ttk.Label(llm_row, text="Base URL", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.base_url_var = tk.StringVar()
        ttk.Entry(llm_row, textvariable=self.base_url_var, width=27).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Label(llm_row, text="Model", style="Muted.TLabel").grid(row=0, column=2)
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(llm_row, textvariable=self.model_var, width=19)
        self.model_combo.grid(row=0, column=3, sticky="ew", padx=5)
        ttk.Button(llm_row, text="接続確認", command=self._check_connection).grid(row=0, column=4, padx=3)
        ttk.Button(llm_row, text="localhost自動検出", command=self._detect_servers).grid(row=0, column=5, padx=(3, 0))

        session_row = ttk.Frame(controls, style="Panel.TFrame")
        session_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        session_row.columnconfigure(1, weight=2)
        session_row.columnconfigure(5, weight=3)
        ttk.Label(session_row, text="本の名前", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.book_title_var = tk.StringVar(value="無題の本")
        ttk.Entry(session_row, textvariable=self.book_title_var, width=24).grid(row=0, column=1, sticky="ew", padx=(6, 5))
        ttk.Label(session_row, text="総ページ", style="Muted.TLabel").grid(row=0, column=2)
        self.total_pages_var = tk.IntVar(value=300)
        ttk.Spinbox(session_row, from_=1, to=10000, textvariable=self.total_pages_var, width=7).grid(row=0, column=3, sticky="w", padx=5)
        ttk.Button(session_row, text="新規セッション", style="Accent.TButton", command=self._new_session).grid(row=0, column=4, padx=5)
        self.session_var = tk.StringVar()
        self.session_combo = ttk.Combobox(session_row, textvariable=self.session_var, state="readonly", width=25)
        self.session_combo.grid(row=0, column=5, sticky="ew", padx=5)
        ttk.Button(session_row, text="前回の続きから", command=self._resume_session).grid(row=0, column=6, padx=(3, 0))

        action_row = ttk.Frame(controls, style="Panel.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        action_row.columnconfigure(9, weight=1)
        ttk.Label(action_row, text="読書モード", style="Muted.TLabel").grid(row=0, column=0)
        self.mode_var = tk.StringVar()
        ttk.Combobox(
            action_row,
            textvariable=self.mode_var,
            values=[item.value for item in ReadingMode],
            state="readonly",
            width=9,
        ).grid(row=0, column=1, padx=5)
        ttk.Label(action_row, text="品質", style="Muted.TLabel").grid(row=0, column=2)
        self.quality_var = tk.StringVar()
        ttk.Combobox(
            action_row,
            textvariable=self.quality_var,
            values=[item.value for item in QualityPreset],
            state="readonly",
            width=10,
        ).grid(row=0, column=3, padx=5)
        ttk.Button(action_row, text="開始", style="Accent.TButton", command=self._start).grid(row=0, column=4, padx=3)
        ttk.Button(action_row, text="一時停止", command=self.orchestrator.pause).grid(row=0, column=5, padx=3)
        ttk.Button(action_row, text="再開", command=self.orchestrator.resume).grid(row=0, column=6, padx=3)
        ttk.Button(action_row, text="停止", command=self.orchestrator.stop).grid(row=0, column=7, padx=3)
        ttk.Button(action_row, text="保存", command=self._save_settings).grid(row=0, column=8, padx=3)
        ttk.Button(action_row, text="読書終了", style="Danger.TButton", command=self._finalize).grid(row=0, column=10, padx=(3, 0))

        chapter_row = ttk.Frame(controls, style="Panel.TFrame")
        chapter_row.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        chapter_row.columnconfigure(0, weight=1)
        ttk.Label(
            chapter_row,
            text="章区切り: 感想を保存し、次章用の最小記憶へ切替",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="e")
        ttk.Button(
            chapter_row,
            text="ここで章のおわり",
            style="Accent.TButton",
            command=self._close_chapter,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            chapter_row,
            text="章メモのフォルダーを開く",
            command=self._open_chapter_notes,
        ).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(
            chapter_row,
            text="ChatGPT用に1ファイルへまとめる",
            command=self._export_chapter_notes_for_chatgpt,
        ).grid(row=0, column=3, padx=(6, 0))

        self.warning_frame = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 5))
        self.warning_frame.grid(row=2, column=0, sticky="ew", padx=12)
        self.warning_frame.columnconfigure(0, weight=1)
        self.warning_var = tk.StringVar(value="")
        self.warning_label = ttk.Label(self.warning_frame, textvariable=self.warning_var, style="Warning.TLabel")
        self.warning_label.grid(row=0, column=0, sticky="ew")
        self.retry_button = ttk.Button(self.warning_frame, text="再試行", command=self._retry_last)
        self.retry_button.grid(row=0, column=1, padx=3)
        self.skip_button = ttk.Button(self.warning_frame, text="このページをスキップ", command=self._skip_page)
        self.skip_button.grid(row=0, column=2, padx=3)
        self.manual_button = ttk.Button(self.warning_frame, text="手動確認", command=self._manual_confirm)
        self.manual_button.grid(row=0, column=3, padx=3)
        self.warning_frame.grid_remove()

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=3, column=0, sticky="nsew", padx=12, pady=8)
        self.root.rowconfigure(3, weight=1)
        self.root.columnconfigure(0, weight=1)
        left = ttk.Frame(body, style="Panel.TFrame", padding=12, width=360)
        center = ttk.Frame(body, style="Panel.TFrame", padding=12, width=240)
        right = ttk.Frame(body, style="Panel.TFrame", padding=12, width=330)
        body.add(left, weight=4)
        body.add(center, weight=3)
        body.add(right, weight=5)
        self._build_left(left)
        self._build_center(center)
        self._build_right(right)

        self.status_var = tk.StringVar(value="準備中…")
        ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel").grid(row=4, column=0, sticky="ew")

    def _build_left(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        ttk.Label(parent, text="現在のページ", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.preview_label = tk.Label(
            parent,
            text="本文領域を選択すると\n処理中だけプレビューします",
            bg="#07101c",
            fg=MUTED,
            font=("Yu Gothic UI", 12),
            relief="flat",
        )
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(8, 10))

        info = ttk.Frame(parent, style="Panel2.TFrame", padding=8)
        info.grid(row=2, column=0, sticky="ew")
        for col in range(4):
            info.columnconfigure(col, weight=1)
        self.page_index_var = tk.StringVar(value="—")
        self.page_state_var = tk.StringVar(value="未処理")
        self.page_confidence_var = tk.StringVar(value="—")
        self.duplicate_var = tk.StringVar(value="0")
        for col, (label, variable) in enumerate(
            [
                ("読書番号", self.page_index_var),
                ("処理状態", self.page_state_var),
                ("認識確信度", self.page_confidence_var),
                ("重複", self.duplicate_var),
            ]
        ):
            tk.Label(info, text=label, bg=PANEL_2, fg=MUTED, font=("Yu Gothic UI", 8)).grid(row=0, column=col)
            tk.Label(info, textvariable=variable, bg=PANEL_2, fg=TEXT, font=("Yu Gothic UI", 11, "bold")).grid(row=1, column=col)

        options = ttk.Frame(parent, style="Panel.TFrame")
        options.grid(row=3, column=0, sticky="ew", pady=(10, 5))
        ttk.Label(options, text="見開き", style="Muted.TLabel").pack(side="left")
        self.spread_var = tk.StringVar()
        ttk.Combobox(options, textvariable=self.spread_var, values=[i.value for i in SpreadMode], state="readonly", width=12).pack(side="left", padx=5)
        ttk.Label(options, text="順序", style="Muted.TLabel").pack(side="left", padx=(10, 0))
        self.direction_var = tk.StringVar()
        ttk.Combobox(options, textvariable=self.direction_var, values=[i.value for i in ReadingDirection], state="readonly", width=9).pack(side="left", padx=5)
        self.important_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="このページ重要", variable=self.important_var).pack(side="right")

        ttk.Label(parent, text="ユーザーメモ（AIメモとは別に保存）", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(6, 3))
        self.user_note = tk.Text(
            parent,
            height=3,
            bg="#0d1728",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Yu Gothic UI", 10),
        )
        self.user_note.grid(row=5, column=0, sticky="ew")

        actions = ttk.Frame(parent, style="Panel.TFrame")
        actions.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="このページを読む  Ctrl+Shift+R", command=self._read_current).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text="次のページ", style="Accent.TButton", command=self._read_and_turn).grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _build_center(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text="進行状況", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(parent, variable=self.progress_var, maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 14))

        self.metric_vars: dict[str, tk.StringVar] = {}
        metrics = [
            ("read_pages", "読了ページ数"),
            ("elapsed", "経過時間"),
            ("average", "平均秒 / page"),
            ("remaining", "推定残り時間"),
            ("success", "読み取り成功率"),
            ("duplicates", "重複ページ数"),
            ("failures", "読み取り失敗数"),
            ("chunk", "現在のチャンク"),
            ("integrated", "最後の統合位置"),
        ]
        grid = ttk.Frame(parent, style="Panel.TFrame")
        grid.grid(row=2, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(metrics):
            var = tk.StringVar(value="—")
            self.metric_vars[key] = var
            ttk.Label(grid, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            ttk.Label(grid, textvariable=var, style="Value.TLabel").grid(row=row, column=1, sticky="e", pady=4)

        calibration = ttk.LabelFrame(parent, text="10ページ・キャリブレーション", padding=9)
        calibration.grid(row=3, column=0, sticky="ew", pady=(16, 10))
        calibration.columnconfigure(0, weight=1)
        self.calibration_var = tk.StringVar(value="本番前に速度と認識品質を測れます。")
        ttk.Label(calibration, textvariable=self.calibration_var, style="Muted.TLabel", wraplength=300, justify="left").grid(row=0, column=0, sticky="ew")
        ttk.Button(calibration, text="10ページ校正を開始", command=self._start_calibration).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        settings = ttk.LabelFrame(parent, text="品質・接続設定", padding=9)
        settings.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        for col in (1, 3):
            settings.columnconfigure(col, weight=1)
        self.chunk_size_var = tk.IntVar(value=20)
        self.temp_var = tk.DoubleVar(value=0.2)
        self.page_tokens_var = tk.IntVar(value=900)
        self.deep_tokens_var = tk.IntVar(value=3500)
        self.timeout_var = tk.DoubleVar(value=180.0)
        self.turn_key_var = tk.StringVar(value="Right")
        self.api_key_var = tk.StringVar(value="")
        fields = [
            ("チャンク", self.chunk_size_var),
            ("temperature", self.temp_var),
            ("Page tokens", self.page_tokens_var),
            ("Deep tokens", self.deep_tokens_var),
            ("timeout秒", self.timeout_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(settings, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(settings, textvariable=variable, width=10).grid(row=row, column=1, sticky="ew", padx=(5, 10), pady=2)
        ttk.Label(settings, text="送りキー", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Combobox(settings, textvariable=self.turn_key_var, values=["Right", "Left", "PageDown", "PageUp", "Space"], state="readonly", width=10).grid(row=0, column=3, sticky="ew")
        ttk.Label(settings, text="API key", style="Muted.TLabel").grid(row=1, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.api_key_var, show="•", width=12).grid(row=1, column=3, sticky="ew")
        ttk.Label(settings, text="API keyは保存しません", style="Muted.TLabel").grid(row=2, column=2, columnspan=2, sticky="w")
        ttk.Button(settings, text="設定を保存", command=self._save_settings).grid(row=4, column=2, columnspan=2, sticky="ew", pady=(5, 0))

        self.open_reports_button = ttk.Button(parent, text="生成レポートを開く", command=self._open_reports)
        self.open_reports_button.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.open_reports_button.state(["disabled"])

    def _build_right(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        ttk.Label(parent, text="AIの現在の理解", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.understanding = scrolledtext.ScrolledText(
            parent,
            bg="#0b1525",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            padx=14,
            pady=12,
            font=("Yu Gothic UI", 10),
        )
        self.understanding.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.understanding.tag_configure("heading", foreground=ACCENT_2, font=("Yu Gothic UI", 11, "bold"), spacing1=10, spacing3=4)
        self.understanding.tag_configure("fact", foreground="#b7e4d7")
        self.understanding.tag_configure("uncertain", foreground="#ffd6a5")
        self.understanding.tag_configure("body", foreground=TEXT, lmargin1=8, lmargin2=16, spacing3=3)
        self.understanding.insert("end", "ページを読むと、要約だけがここに表示されます。\n")
        self.understanding.configure(state="disabled")

    def _load_values(self) -> None:
        self.base_url_var.set(self.config.llm.base_url)
        self.model_var.set(self.config.llm.model)
        self.mode_var.set(self.config.reading_mode)
        self.quality_var.set(self.config.quality)
        self.spread_var.set(self.config.spread_mode)
        self.direction_var.set(self.config.reading_direction)
        self.total_pages_var.set(self.config.total_pages)
        self.chunk_size_var.set(self.config.chunk_size)
        self.temp_var.set(self.config.llm.temperature)
        self.page_tokens_var.set(self.config.llm.page_max_tokens)
        self.deep_tokens_var.set(self.config.llm.deep_max_tokens)
        self.timeout_var.set(self.config.llm.timeout_seconds)
        self.turn_key_var.set(self.config.capture.turn_key)

    def _sync_config(self) -> None:
        self.config.llm.base_url = self.base_url_var.get().strip()
        self.config.llm.model = self.model_var.get().strip()
        self.config.llm.api_key = self.api_key_var.get()
        self.config.llm.temperature = min(2.0, max(0.0, float(self.temp_var.get())))
        self.config.llm.page_max_tokens = max(1200, int(self.page_tokens_var.get()))
        self.config.llm.deep_max_tokens = max(800, int(self.deep_tokens_var.get()))
        self.config.llm.timeout_seconds = max(5.0, float(self.timeout_var.get()))
        self.config.quality = self.quality_var.get()
        self.config.reading_mode = self.mode_var.get()
        self.config.spread_mode = self.spread_var.get()
        self.config.reading_direction = self.direction_var.get()
        self.config.total_pages = max(1, int(self.total_pages_var.get()))
        self.config.chunk_size = min(100, max(2, int(self.chunk_size_var.get())))
        self.config.capture.turn_key = self.turn_key_var.get()
        self.client.update_settings(self.config.llm)
        self.analyzer.quality = self.config.quality
        self.integrator.quality = self.config.quality
        self.report_generator.quality = self.config.quality

    def _save_settings(self) -> None:
        try:
            self._sync_config()
            self.config.save(self.config_path)
            self._set_status("設定を保存しました（API keyは保存対象外）。")
        except Exception as exc:
            self._show_warning(f"設定を保存できません: {exc}")

    def _refresh_windows(self) -> None:
        selected_handle = self._selected_window().handle if self._selected_window() else None
        windows = [w for w in self.window_provider.list_windows() if "Local Reading Assistant" not in w.title]
        self._windows = {w.display_name(): w for w in windows}
        values = list(self._windows)
        self.window_combo["values"] = values
        for name, window in self._windows.items():
            if selected_handle and window.handle == selected_handle:
                self.window_var.set(name)
                break
        else:
            if values:
                self.window_var.set(values[0])

    def _refresh_sessions(self) -> None:
        self._sessions.clear()
        for session in self.memory.list_resumable_sessions():
            label = f"{session['title']} — {session['read_pages']}/{session['total_pages']}p — {session['updated_at'][:16]}"
            self._sessions[label] = int(session["id"])
        values = list(self._sessions)
        self.session_combo["values"] = values
        if values:
            self.session_var.set(values[0])

    def _new_session(self) -> None:
        try:
            self._sync_config()
            session_id = self.orchestrator.new_session(self.book_title_var.get(), self.config.total_pages)
            self._refresh_sessions()
            self._set_status(f"新規セッション #{session_id} を作成しました。")
        except Exception as exc:
            self._show_warning(str(exc))

    def _resume_session(self) -> None:
        session_id = self._sessions.get(self.session_var.get())
        if not session_id:
            self._show_warning("再開するセッションを選んでください。")
            return
        try:
            self._sync_config()
            by_handle = {window.handle: window for window in self._windows.values()}
            self.orchestrator.resume_session(session_id, by_handle.get)
            session = self.memory.get_session(session_id)
            self.book_title_var.set(session["title"])
            self.total_pages_var.set(session["total_pages"])
            if self.orchestrator.window:
                for name, window in self._windows.items():
                    if window.handle == self.orchestrator.window.handle:
                        self.window_var.set(name)
                        break
            if self.orchestrator.capture_rect:
                rect = self.orchestrator.capture_rect
                self._set_status(f"前回の本文領域 {rect.width}x{rect.height} を復元しました。ウィンドウ位置が変わった場合は再選択してください。")
        except Exception as exc:
            self._show_warning(str(exc))

    def _selected_window(self) -> WindowInfo | None:
        return self._windows.get(self.window_var.get())

    def _select_region(self) -> None:
        window = self._selected_window()
        if not window:
            self._show_warning("対象ウィンドウを選択してください。")
            return
        if self.orchestrator.session_id is None:
            self._show_warning("先に新規セッションまたは前回の続きからを選んでください。")
            return
        try:
            self.controller.activate(window.handle)
            # Activation can restore a minimized window and change its bounds.
            # Read the final rectangle only after Windows has completed that move.
            self.root.after(220, lambda: self._show_region_selector(window))
        except Exception as exc:
            self._show_warning(str(exc))

    def _show_region_selector(self, window: WindowInfo) -> None:
        try:
            current_rect = self.window_provider.get_window_rect(window.handle)
            current_window = WindowInfo(
                window.handle, window.title, current_rect, window.process_id
            )
            monitor_rect = self.window_provider.get_monitor_rect(window.handle)
            selector_bounds = left_half(monitor_rect)
            allowed_bounds = intersection(current_rect, selector_bounds)
            if allowed_bounds is None or allowed_bounds.width < 80 or allowed_bounds.height < 80:
                raise ValueError(
                    "対象ウィンドウがモニター左半分と重なっていません。"
                    "対象を左側へ移動するか最大化してください。"
                )
            rect = RegionSelector(
                self.root,
                selector_bounds,
                allowed_bounds=allowed_bounds,
            ).select()
            if rect:
                self.orchestrator.set_capture_target(current_window, rect)
                self._set_status(
                    f"モニター左半分から本文領域を選択しました: "
                    f"({rect.left}, {rect.top}) {rect.width}x{rect.height}"
                )
        except Exception as exc:
            self._show_warning(str(exc))

    def _check_connection(self) -> None:
        try:
            self._sync_config()
        except Exception as exc:
            self._show_warning(str(exc))
            return

        def action() -> tuple[bool, str, list[str]]:
            return self.client.check_connection()

        def complete(result: tuple[bool, str, list[str]]) -> None:
            ok, kind, models = result
            if ok:
                self.connection_var.set(f"● 接続済み ({kind})")
                self.connection_label.configure(fg=ACCENT)
                if models:
                    self.model_combo["values"] = models
                    if self.model_var.get() not in models:
                        self.model_var.set(models[0])
                self._set_status(f"ローカルLLMへ接続しました。モデル数: {len(models)}")
            else:
                self.connection_var.set("● 接続失敗")
                self.connection_label.configure(fg=ERROR)
                self._show_warning(kind)

        self._run_background("LLM接続確認中…", action, complete)

    def _detect_servers(self) -> None:
        def complete(found: list[tuple[str, list[str]]]) -> None:
            if not found:
                self._show_warning("一般的なlocalhostポートにOpenAI互換/Ollamaサーバーが見つかりませんでした。")
                return
            base_url, models = found[0]
            self.base_url_var.set(base_url)
            self.model_combo["values"] = models
            if models:
                preferred = next((model for model in models if "qwen3.5" in model.casefold()), models[0])
                self.model_var.set(preferred)
            self._set_status(f"ローカルLLMを検出しました: {base_url}")

        self._run_background(
            "localhost上のLLMサーバーを検出中…",
            LocalLLMClient.detect_local_servers,
            complete,
        )

    def _start(self) -> None:
        try:
            self._sync_config()
            self.orchestrator.start()
        except Exception as exc:
            self._show_warning(str(exc))

    def _read_current(self) -> None:
        self._read(turn=False)

    def _read_and_turn(self) -> None:
        if self.mode_var.get() == ReadingMode.MANUAL.value:
            self._show_warning("手動モードではユーザーが対象アプリ側でページを送り、「このページを読む」を押してください。")
            return
        self._read(turn=True)

    def _read(self, turn: bool) -> None:
        try:
            self._sync_config()
        except Exception as exc:
            self._show_warning(str(exc))
            return
        note = self.user_note.get("1.0", "end").strip()
        important = self.important_var.get()
        action = (lambda: self.orchestrator.read_and_turn(note, important)) if turn else (lambda: self.orchestrator.read_current_page(note, important))
        self._last_action = lambda: self._read(turn)

        def complete(_: list[PageRecord]) -> None:
            self.user_note.delete("1.0", "end")
            self.important_var.set(False)
            self.warning_frame.grid_remove()
            self._refresh_sessions()

        self._run_background("ページ処理を開始します…", action, complete)

    def _retry_last(self) -> None:
        self.warning_frame.grid_remove()
        if self._last_action:
            self._last_action()

    def _skip_page(self) -> None:
        turn = self.mode_var.get() == ReadingMode.SEMI_AUTO.value
        self._run_background("ページをスキップしています…", lambda: self.orchestrator.skip_current_page(turn), lambda _: self.warning_frame.grid_remove())

    def _manual_confirm(self) -> None:
        self.warning_frame.grid_remove()
        self._set_status("手動確認中です。対象画面を直し、再試行またはスキップを選んでください。勝手には進みません。")

    def _start_calibration(self) -> None:
        try:
            self._sync_config()
            self.orchestrator.start_calibration()
        except Exception as exc:
            self._show_warning(str(exc))

    def _finalize(self) -> None:
        if not messagebox.askyesno("読書終了", "未統合ページを統合し、4段階の最終検証と7レポート生成を開始しますか？"):
            return

        def complete(path: Path) -> None:
            self._last_report_dir = path
            self.open_reports_button.state(["!disabled"])
            self._refresh_sessions()

        self._run_background("最終分析を開始します…", self.orchestrator.finalize, complete)

    def _close_chapter(self) -> None:
        if not messagebox.askyesno(
            "章の終わり",
            "現在までの章感想を生成して保存し、次章用の最小記憶へ切り替えますか？\n"
            "ページメモと既存チャンクは削除されません。",
        ):
            return

        def complete(path: Path) -> None:
            self.warning_frame.grid_remove()
            self._set_status(f"章の読書記録を保存しました: {path}")

        self._run_background(
            "章の読書記録を生成しています…",
            self.orchestrator.close_chapter,
            complete,
        )

    def _current_chapters(self) -> list[dict[str, Any]]:
        session_id = self.orchestrator.session_id
        if session_id is None:
            raise ValueError("先に『前回の続きから』で対象セッションを開いてください。")
        return self.memory.chapter_summaries(session_id)

    def _open_chapter_notes(self) -> None:
        try:
            paths = chapter_note_paths(self._current_chapters())
            os.startfile(paths[0].parent)
            self._set_status(f"章メモのフォルダーを開きました: {paths[0].parent}")
        except Exception as exc:
            self._show_warning(str(exc))

    def _export_chapter_notes_for_chatgpt(self) -> None:
        try:
            path = combine_chapter_notes(self._current_chapters())
            os.startfile(path)
            self._set_status(
                "各章メモを内容変更なしで読書順に結合しました。"
                f"ChatGPTへ添付できます: {path}"
            )
        except Exception as exc:
            self._show_warning(str(exc))

    def _run_background(self, label: str, action: Callable[[], Any], complete: Callable[[Any], None] | None = None) -> None:
        if self._busy:
            self._show_warning("別の処理が進行中です。完了するまでお待ちください。")
            return
        self._busy = True
        self._set_status(label)

        def worker() -> None:
            try:
                result = action()
            except Exception as exc:
                self._ui(self._background_failed, str(exc))
            else:
                self._ui(self._background_complete, complete, result)

        threading.Thread(target=worker, daemon=True, name="reading-worker").start()

    def _background_complete(self, complete: Callable[[Any], None] | None, result: Any) -> None:
        self._busy = False
        if complete:
            complete(result)

    def _background_failed(self, message: str) -> None:
        self._busy = False
        self._show_warning(message)

    def _set_preview(self, image: Image.Image | None) -> None:
        if image is None:
            self._preview_photo = None
            self.preview_label.configure(image="", text="画像データは処理完了後に破棄しました")
            return
        try:
            image.thumbnail((520, 390), Image.Resampling.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self._preview_photo, text="")
        finally:
            image.close()

    def _on_page_record(self, record: PageRecord) -> None:
        self.page_index_var.set(str(record.analysis.page_index))
        state = {
            "UNREADABLE": "保存済み（内容判定不能）",
            "PARTIAL": "保存済み（情報不足）",
        }.get(record.analysis.reading_status, "保存済み")
        self.page_state_var.set(state)
        self.page_confidence_var.set(f"{record.analysis.confidence:.0%}")

    def _on_chunk(self, summary: dict) -> None:
        self._set_status("チャンク統合を保存しました。途中予想と解釈更新を長期記憶へ反映済みです。")

    def _update_metrics(self, metrics: dict) -> None:
        read = int(metrics.get("read_pages", 0))
        total = max(1, int(metrics.get("total_pages", self.total_pages_var.get())))
        average = float(metrics.get("average_seconds_per_page", 0.0))
        remaining = max(0, total - read) * average
        self.progress_var.set(min(100.0, read / total * 100))
        self.metric_vars["read_pages"].set(f"{read} / {total}")
        self.metric_vars["elapsed"].set(_duration(float(metrics.get("total_processing_seconds", 0))))
        self.metric_vars["average"].set(f"{average:.1f} 秒")
        self.metric_vars["remaining"].set(_duration(remaining))
        self.metric_vars["success"].set(f"{float(metrics.get('success_rate', 0)):.1%}")
        self.metric_vars["duplicates"].set(str(metrics.get("duplicate_pages", 0)))
        self.metric_vars["failures"].set(str(metrics.get("failed_pages", 0)))
        chunk = int(metrics.get("chunks", 0)) + 1
        self.metric_vars["chunk"].set(f"{chunk}  ({read % max(1, int(metrics.get('chunk_size', 20)))}/ {metrics.get('chunk_size', 20)})")
        self.metric_vars["integrated"].set(f"page {metrics.get('last_integrated_page', 0)}")
        self.duplicate_var.set(str(metrics.get("duplicate_pages", 0)))

    def _update_calibration(self, metrics: dict) -> None:
        count = metrics.get("sample_pages", 0)
        estimates = metrics.get("estimates_seconds", {})
        self.calibration_var.set(
            f"{count}/10ページ  平均 {metrics.get('average_seconds_per_page', 0):.1f}秒\n"
            f"最速 {metrics.get('fastest_seconds', 0):.1f} / 最遅 {metrics.get('slowest_seconds', 0):.1f}秒\n"
            f"成功率 {metrics.get('success_rate', 0):.1%}  confidence {metrics.get('average_confidence', 0):.1%}\n"
            f"JSON失敗 {metrics.get('json_failure_rate', 0):.1%}  再試行 {metrics.get('retry_rate', 0):.1%}\n"
            f"100p {_duration(estimates.get('100_pages', 0))} / 200p {_duration(estimates.get('200_pages', 0))}\n"
            f"300p {_duration(estimates.get('300_pages', 0))} / 設定総数 {_duration(estimates.get('configured_total', 0))}"
        )

    def _update_understanding(self, context: dict) -> None:
        pages = context.get("recent_pages", [])
        latest = pages[-1] if pages else {}
        chunks = context.get("recent_chunks", [])
        chunk_summary = chunks[-1].get("summary", {}) if chunks else {}
        chapter = context.get("last_chapter_checkpoint") or {}
        chapter_summary = chapter.get("summary", {}) if isinstance(chapter, dict) else {}
        carryover = chapter.get("carryover", {}) if isinstance(chapter, dict) else {}
        if not isinstance(chapter_summary, dict):
            chapter_summary = {}
        if not isinstance(carryover, dict):
            carryover = {}
        sections = [
            ("現在起きていること", [latest.get("short_summary") or carryover.get("immediate_situation") or carryover.get("continuity_bridge") or chapter_summary.get("detailed_summary") or "まだ読書メモがありません。"]),
            ("登場人物", [_character_line(item) for item in latest.get("characters", [])] or _to_lines(carryover.get("active_characters")) or _to_lines(chapter_summary.get("character_actions_and_emotions")) or _to_lines(chapter_summary.get("character_end_states"))),
            ("人物心理", _psychology_lines(latest.get("characters", [])) or _to_lines(chapter_summary.get("character_actions_and_emotions")) or _to_lines(chapter_summary.get("character_end_states"))),
            ("関係性の変化", [_relation_line(item) for item in latest.get("relationship_updates", [])] or _to_lines(chunk_summary.get("relationship_changes")) or _to_lines(carryover.get("active_relationships"))),
            ("気になる伏線", _statement_lines(latest.get("foreshadowing_or_suspicious_points")) or _to_lines(chunk_summary.get("new_clues")) or _to_lines(chunk_summary.get("important_foreshadowing")) or _to_lines(carryover.get("unresolved_clues"))),
            ("未解決の疑問", _statement_lines(latest.get("unresolved_questions")) or _to_lines(chunk_summary.get("new_questions")) or _to_lines(chunk_summary.get("continuing_questions")) or _to_lines(chunk_summary.get("unresolved_items")) or _to_lines(carryover.get("open_questions"))),
            ("現在の予想", _to_lines(chunk_summary.get("predictions_at_this_point")) or [p.get("prediction_text", "") for p in context.get("prediction_history_tail", [])[-5:]] or _to_lines(carryover.get("active_predictions"))),
            ("AIが特に重要だと思った部分", _statement_lines(latest.get("new_facts")) or _statement_lines(latest.get("important_details")) or _to_lines(chunk_summary.get("memorable_scenes")) or _to_lines(chunk_summary.get("new_facts")) or _to_lines(chunk_summary.get("especially_important")) or _to_lines(carryover.get("critical_facts"))),
        ]
        self.understanding.configure(state="normal")
        self.understanding.delete("1.0", "end")
        for heading, lines in sections:
            self.understanding.insert("end", heading + "\n", "heading")
            valid = [line for line in lines if str(line).strip()]
            if not valid:
                valid = ["—"]
            for line in valid[:12]:
                tag = "uncertain" if "UNCERTAIN" in line or "SPECULATION" in line else "body"
                self.understanding.insert("end", f"• {line}\n", tag)
        self.understanding.configure(state="disabled")

    def _show_warning(self, message: str) -> None:
        self.warning_var.set(message)
        self.warning_frame.grid()
        self._set_status("確認が必要です。勝手には次へ進みません。")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _on_hotkey(self) -> None:
        if not self._busy:
            self._read_current()

    def _open_reports(self) -> None:
        if self._last_report_dir and self._last_report_dir.exists():
            os.startfile(self._last_report_dir)

    def _ui(self, func: Callable, *args: Any) -> None:
        try:
            self.root.after(0, func, *args)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self._busy and not messagebox.askyesno("処理中", "処理中です。アプリを閉じますか？保存済みページは再開できます。"): 
            return
        self.hotkey.unregister()
        try:
            self._sync_config()
            self.config.save(self.config_path)
        except Exception:
            pass
        self.memory.close()
        self.root.destroy()


def _statement_lines(items: Any) -> list[str]:
    lines = []
    for item in items or []:
        if isinstance(item, dict):
            text = item.get("text", "")
            level = item.get("evidence_level", "UNCERTAIN")
            confidence = item.get("confidence", 0.5)
            try:
                lines.append(f"[{level} {float(confidence):.0%}] {text}")
            except (TypeError, ValueError):
                lines.append(f"[{level}] {text}")
        else:
            lines.append(str(item))
    return lines


def _to_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value else []
    results = []
    for item in value:
        if isinstance(item, dict):
            text = (
                item.get("text")
                or item.get("action")
                or item.get("meaning")
                or item.get("change")
                or item.get("answer")
                or item.get("event")
                or item.get("prediction")
                or item.get("summary")
            )
            results.append(str(text if text is not None else json.dumps(item, ensure_ascii=False)))
        else:
            results.append(str(item))
    return results


def _character_line(item: Any) -> str:
    if isinstance(item, dict):
        action = item.get("role_or_action") or item.get("action") or item.get("actions") or ""
        return f"{item.get('name', '不明')}: {action}"
    return str(item)


def _psychology_lines(items: Any) -> list[str]:
    results = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "不明")
        psychology = _statement_lines(item.get("psychology", []))
        if not psychology and item.get("emotion"):
            psychology = [
                f"{item.get('emotion')}（根拠: {item.get('evidence_scene') or '不明'}）"
            ]
        for line in psychology:
            results.append(f"{name}: {line}")
    return results


def _relation_line(item: Any) -> str:
    if isinstance(item, dict):
        return f"{item.get('source', '不明')} → {item.get('target', '不明')}: {item.get('change', '')} [{item.get('evidence_level', 'UNCERTAIN')}]"
    return str(item)


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}時間{minutes:02d}分"
    if minutes:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"


def run_app() -> None:
    root = tk.Tk()
    ReadingAssistantApp(root)
    root.mainloop()
