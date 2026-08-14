"""Main window — ties all panels together with signal/slot connections."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

import numpy as np
from PySide6.QtCore import QRect, QSettings, Qt, Signal, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from watermark_remover import __version__
from watermark_remover.core.detector import WatermarkDetector
from watermark_remover.core.inpainter import Inpainter
from watermark_remover.core.pipeline import WatermarkPipeline
from watermark_remover.core.video_io import (
    extract_first_frame,
    extract_frame_at,
    VideoReader,
)
from watermark_remover.core.temporal_tracker import TemporalWatermarkTracker
from watermark_remover.core.image_processor import (
    is_image_file,
    load_image,
    process_image,
    save_image,
)

from watermark_remover.ui.file_panel import FilePanel
from watermark_remover.ui.preview_panel import PreviewPanel
from watermark_remover.ui.result_panel import ResultPanel
from watermark_remover.ui.settings_panel import SettingsPanel
from watermark_remover.ui.progress_panel import ProgressPanel
from watermark_remover.ui.preferences_dialog import PreferencesDialog
from watermark_remover.ui.styles import DARK_STYLE
from watermark_remover.ui.image_utils import ndarray_to_pixmap


class _BackgroundVideoWidget(QWidget):
    """Painted video layer that stays behind the interactive UI."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._frame: QImage | None = None
        self.setObjectName("backgroundVideo")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

    def set_frame(self, image: QImage):
        self._frame = image.copy()
        self.update()

    def clear_frame(self):
        self._frame = None
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt override
        if self._frame is None or self._frame.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        frame_size = self._frame.size()
        widget_size = self.size()
        if frame_size.isEmpty() or widget_size.isEmpty():
            return

        scale = max(
            widget_size.width() / frame_size.width(),
            widget_size.height() / frame_size.height(),
        )
        target_width = int(frame_size.width() * scale)
        target_height = int(frame_size.height() * scale)
        target = QRect(
            (widget_size.width() - target_width) // 2,
            (widget_size.height() - target_height) // 2,
            target_width,
            target_height,
        )
        painter.drawImage(target, self._frame)


class MainWindow(QMainWindow):
    """羊咩的工厂 — main application window."""

    def __init__(self, deps: dict[str, bool] | None = None):
        super().__init__()
        self.setWindowTitle(f"羊咩的工厂 v{__version__}")
        self.setMinimumSize(1200, 750)
        self.resize(1400, 820)

        # Optional-dependency availability
        deps = deps or {}
        self._has_ocr = deps.get("easyocr", False)
        self._has_lama = deps.get("lama", False)
        self._has_cuda = deps.get("cuda", False)

        # App preferences
        self._settings = QSettings("YangmieFactory", "WatermarkRemover")
        self._name_template = self._migrate_name_template(
            str(self._settings.value("output/name_template", ""))
        )
        self._conflict_rule = self._settings.value("output/conflict_rule", "auto_rename")
        self._output_directory = str(self._settings.value("output/directory", ""))
        self._quality_index = int(self._settings.value("output/quality_index", 1))
        self._enhance_enabled = self._setting_bool("output/enhance_enabled", False)
        self._enhance_scale_index = int(self._settings.value("output/enhance_scale_index", 0))
        self._enhance_sharpen = self._setting_bool("output/enhance_sharpen", True)
        self._enhance_saturation = self._setting_bool("output/enhance_saturation", False)
        self._auto_crf = self._setting_bool("output/auto_crf", False)
        self._box_color = str(self._settings.value("ui/box_color", "#00ff88"))
        self._background_enabled = self._setting_bool("background/enabled", True)
        self._background_image_path = self._settings.value("background/image_path", "")
        self._gpu_enabled = self._has_cuda and self._setting_bool("performance/gpu_enabled", True)

        # State
        self._current_video_path: str | None = None
        self._current_info = None
        self._current_image_path: str | None = None
        self._current_image: np.ndarray | None = None
        self._image_worker: QThread | None = None
        self._first_frame: np.ndarray | None = None       # fallback / compatibility
        self._display_frame: np.ndarray | None = None     # currently shown frame
        self._mask: np.ndarray | None = None
        self._pipeline: WatermarkPipeline | None = None
        self._load_worker: QThread | None = None
        self._seek_worker: QThread | None = None
        self._detect_worker: QThread | None = None
        self._temporal_worker: QThread | None = None
        self._temporal_pending: tuple[str, str | None] | None = None
        self._temporal_table_video: str | None = None
        self._detector = WatermarkDetector(
            use_ocr=self._has_ocr,
            use_morphology=True,
            gpu=self._effective_cuda(),
        )
        self._batch_mode = False
        self._batch_paths: list[str] = []
        self._batch_index = 0
        self._batch_completed: list[str] = []

        # Playback state
        self._playback_timer = QTimer(self)
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._bg_player = None
        self._bg_video = None
        self._bg_sink = None
        self._video_reader: VideoReader | None = None
        self._current_frame_no: int = 0
        self._is_playing: bool = False
        self._seeking: bool = False  # suppress slider updates during seek

        self._setup_ui()
        self._apply_saved_preferences_to_panels()
        self._setup_background_video()
        self._setup_menu()
        self._connect_signals()
        self._apply_style()

        # Reflect actual availability in settings panel
        self.settings_panel.set_available_methods(
            ocr=self._has_ocr,
            lama=self._has_lama,
            cuda=self._effective_cuda(),
        )

    # ==================================================================
    # App preferences
    # ==================================================================

    def _setting_bool(self, key: str, default: bool) -> bool:
        value = self._settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _effective_cuda(self) -> bool:
        return self._has_cuda and self._gpu_enabled

    def _apply_saved_preferences_to_panels(self):
        self.preview_panel.set_box_color(QColor(self._box_color))

    def _current_preferences(self) -> dict:
        return {
            "output_directory": self._output_directory,
            "name_template": self._name_template,
            "conflict_rule": self._conflict_rule,
            "quality_index": self._quality_index,
            "enhance_enabled": self._enhance_enabled,
            "enhance_scale_index": self._enhance_scale_index,
            "enhance_sharpen": self._enhance_sharpen,
            "enhance_saturation": self._enhance_saturation,
            "auto_crf": self._auto_crf,
            "background_enabled": self._background_enabled,
            "background_image_path": self._background_image_path,
            "box_color": self._box_color,
            "gpu_enabled": self._gpu_enabled,
            "has_cuda": self._has_cuda,
        }

    def _save_preferences(self):
        self._settings.setValue("output/directory", self._output_directory)
        self._settings.setValue("output/quality_index", self._quality_index)
        self._settings.setValue("output/name_template", self._name_template)
        self._settings.setValue("output/conflict_rule", self._conflict_rule)
        self._settings.setValue("output/enhance_enabled", self._enhance_enabled)
        self._settings.setValue("output/enhance_scale_index", self._enhance_scale_index)
        self._settings.setValue("output/enhance_sharpen", self._enhance_sharpen)
        self._settings.setValue("output/enhance_saturation", self._enhance_saturation)
        self._settings.setValue("output/auto_crf", self._auto_crf)
        self._settings.setValue("ui/box_color", self._box_color)
        self._settings.setValue("background/enabled", self._background_enabled)
        self._settings.setValue("background/image_path", self._background_image_path)
        self._settings.setValue("performance/gpu_enabled", self._gpu_enabled)

    def _apply_preferences(self, values: dict, save: bool = True):
        self._output_directory = str(values.get("output_directory", ""))
        self._name_template = str(values.get("name_template", "")).strip() or "{name}_\u65e0\u6c34\u5370.{ext}"
        self._conflict_rule = values.get("conflict_rule", "auto_rename")
        self._quality_index = int(values.get("quality_index", 1))
        self._enhance_enabled = bool(values.get("enhance_enabled", False))
        self._enhance_scale_index = int(values.get("enhance_scale_index", 0))
        self._enhance_sharpen = bool(values.get("enhance_sharpen", True))
        self._enhance_saturation = bool(values.get("enhance_saturation", False))
        self._auto_crf = bool(values.get("auto_crf", False))
        self._box_color = str(values.get("box_color", "#00ff88"))
        self.preview_panel.set_box_color(QColor(self._box_color))
        self._background_enabled = bool(values.get("background_enabled", True))
        self._background_image_path = values.get("background_image_path", "")
        self._gpu_enabled = self._has_cuda and bool(values.get("gpu_enabled", True))
        if save:
            self._save_preferences()
        self._setup_background_video()

    def _open_preferences(self):
        dialog = PreferencesDialog(self._current_preferences(), self)
        if dialog.exec():
            self._apply_preferences(dialog.values(), save=True)
            self.progress_panel.set_status("设置已保存")

    # ==================================================================
    # UI Setup
    # ==================================================================

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(12)

        # --- Top: file panel | preview | settings ---
        top_splitter = QSplitter(Qt.Horizontal)

        self.file_panel = FilePanel()
        top_splitter.addWidget(self.file_panel)

        # Center: preview + result (tab-like, stacked vertically)
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)

        self.preview_panel = PreviewPanel()
        center_layout.addWidget(self.preview_panel, stretch=3)

        self.result_panel = ResultPanel()
        center_layout.addWidget(self.result_panel, stretch=2)

        top_splitter.addWidget(center_widget)

        self.settings_panel = SettingsPanel()
        top_splitter.addWidget(self.settings_panel)

        # Set splitter proportions
        top_splitter.setHandleWidth(10)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setStretchFactor(0, 1)  # file panel
        top_splitter.setStretchFactor(1, 4)  # preview / result workspace
        top_splitter.setStretchFactor(2, 1)  # settings
        top_splitter.setSizes([320, 940, 320])

        root.addWidget(top_splitter, stretch=1)

        # --- Bottom: progress ---
        self.progress_panel = ProgressPanel()
        root.addWidget(self.progress_panel)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("文件(&F)")

        open_action = QAction("打开视频(&O)", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.file_panel._on_browse)
        file_menu.addAction(open_action)

        add_batch_action = QAction("添加批量视频(&B)", self)
        add_batch_action.setShortcut("Ctrl+Shift+O")
        add_batch_action.triggered.connect(self.file_panel._on_add_batch)
        file_menu.addAction(add_batch_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Settings menu
        settings_menu = menubar.addMenu("设置(&S)")
        preferences_action = QAction("偏好设置(&P)", self)
        preferences_action.setShortcut("Ctrl+,")
        preferences_action.triggered.connect(self._open_preferences)
        settings_menu.addAction(preferences_action)

        # Help menu
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _apply_style(self):
        self.setStyleSheet(DARK_STYLE)

    def _setup_background_video(self):
        """Apply the selected background without covering interactive widgets."""
        if not self._background_enabled:
            self._stop_background_player()
            if self._bg_video is not None:
                self._bg_video.hide()
            return

        background = self._ensure_background_widget()
        background.show()
        background.lower()

        image_path = self._background_image_path
        if image_path and os.path.isfile(image_path):
            image = QImage(image_path)
            if not image.isNull():
                self._stop_background_player()
                background.set_frame(image)
                background.lower()
                return

        path = self._resolve_background_video_path()
        if path is None:
            self._stop_background_player()
            background.clear_frame()
            background.hide()
            return

        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except ImportError:
            return

        self._stop_background_player()
        self._bg_sink = QVideoSink(self)
        self._bg_sink.videoFrameChanged.connect(self._on_background_frame)

        # No QAudioOutput is attached, so the background plays silently.
        self._bg_player = QMediaPlayer(self)
        self._bg_player.setVideoOutput(self._bg_sink)
        self._bg_player.setSource(QUrl.fromLocalFile(path))
        self._bg_player.setLoops(-1)  # loop forever
        self._bg_player.play()

    def _ensure_background_widget(self) -> _BackgroundVideoWidget:
        central = self.centralWidget()
        if self._bg_video is None:
            self._bg_video = _BackgroundVideoWidget(central)
        self._bg_video.setGeometry(central.rect())
        return self._bg_video

    def _stop_background_player(self):
        if self._bg_player is not None:
            self._bg_player.stop()
            self._bg_player = None
        self._bg_sink = None

    def _on_background_frame(self, frame):
        """Receive decoded frames and repaint the bottom background widget."""
        if self._bg_video is None or frame is None or not frame.isValid():
            return

        image = frame.toImage()
        if image.isNull():
            return

        self._bg_video.set_frame(image)
        self._bg_video.lower()

    def _resolve_background_video_path(self) -> str | None:
        """Locate the background video file, or return None when missing."""
        candidates = []

        # PyInstaller bundle: sys._MEIPASS is the temp extraction directory
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(sys._MEIPASS, "icons", "sheep1.mp4"))

        # Development: relative to this file's location (ui/ -> watermark_remover/ -> root)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(base_dir))
        candidates.append(os.path.join(root, "icons", "sheep1.mp4"))

        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    # ==================================================================
    # Signal connections
    # ==================================================================

    def _connect_signals(self):
        # File loaded → extract first frame, enable auto-detect
        self.file_panel.video_loaded.connect(self._on_video_loaded)
        self.file_panel.image_loaded.connect(self._on_image_loaded)

        # Auto-detect button
        self.preview_panel.auto_detect_btn.clicked.connect(self._on_auto_detect)

        # Mask confirmed (user selected region on preview)
        self.preview_panel.mask_confirmed.connect(self._on_mask_confirmed)

        # Settings buttons
        self.settings_panel.preview_btn.clicked.connect(self._on_preview_inpaint)
        self.settings_panel.process_btn.clicked.connect(self._on_start_processing)
        self.settings_panel.cancel_btn.clicked.connect(self._on_cancel_processing)
        self.settings_panel.open_preferences_requested.connect(self._open_preferences)
        self.settings_panel.analyze_temporal_requested.connect(self._on_manual_temporal_analyze)

        # Mask padding spinbox — auto-recalculate mask on change
        self.settings_panel.mask_padding_changed.connect(self._on_padding_changed)

        # Preview canvas — drag video or click empty to browse
        self.preview_panel.canvas.video_dropped.connect(self._on_preview_video_dropped)

        # Playback controls
        self.preview_panel.play_pause_clicked.connect(self._on_play_pause)
        self.preview_panel.seek_frame.connect(self._on_seek_frame)
        self.preview_panel.clear_workspace_requested.connect(self._clear_current_workspace_video)

    # ==================================================================
    # Slots: video loading
    # ==================================================================

    def _on_preview_video_dropped(self, path: str):
        """Video or image dropped or clicked on the preview canvas."""
        self.file_panel._load_file(path)

    def _clear_current_workspace_video(self):
        """Return the workbench to an empty state without touching source files."""
        self._stop_playback()
        self._cancel_load_worker()
        self._current_video_path = None
        self._current_info = None
        self._current_image_path = None
        self._current_image = None
        self._first_frame = None
        self._display_frame = None
        self._mask = None
        self._current_frame_no = 0
        self.file_panel.clear_current_video()
        self.preview_panel.clear_frame()
        self.result_panel.clear_images()
        self.progress_panel.reset()

    def _on_video_loaded(self, path: str, info):
        """Handle video file loaded: extract first frame + detect in background."""
        # Stop playback & cancel in-flight worker
        self._stop_playback()
        self._cancel_load_worker()

        self._current_video_path = path
        self._current_info = info
        self._current_image_path = None
        self._current_image = None
        self._mask = None
        self._first_frame = None
        self._display_frame = None
        self._current_frame_no = 0

        # Reset UI
        self.preview_panel.set_image_mode(False)
        self.preview_panel.clear_frame()
        self.result_panel.clear_images()
        self.progress_panel.reset()

        # Enable playback controls
        self.preview_panel.set_playback_enabled(
            True, info.total_frames, info.fps
        )
        self.preview_panel.set_playback_state(False, 0)

        # Offload heavy work to background thread
        self.progress_panel.set_status("正在提取首帧…")
        method = self.settings_panel.detection_method

        self._load_worker = _VideoLoadWorker(path, self._has_ocr, self._effective_cuda(), method, self)
        self._load_worker.frame_ready.connect(self._on_first_frame_ready)
        self._load_worker.detection_done.connect(self._on_detection_ready)
        self._load_worker.load_error.connect(self._on_load_error)
        worker = self._load_worker
        worker.finished.connect(self._on_load_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_image_loaded(self, path: str):
        """Handle an image file loaded: decode, preview, auto-detect."""
        self._stop_playback()
        self._cancel_load_worker()

        self._current_video_path = None
        self._current_info = None
        self._current_image_path = path
        self._current_image = None
        self._mask = None
        self._first_frame = None
        self._display_frame = None
        self._current_frame_no = 0

        # Reset UI
        self.preview_panel.set_image_mode(True)
        self.preview_panel.clear_frame()
        self.result_panel.clear_images()
        self.progress_panel.reset()

        self.progress_panel.set_status("\u6b63\u5728\u52a0\u8f7d\u56fe\u7247\u2026")
        try:
            image = load_image(path)
        except Exception as e:
            QMessageBox.warning(self, "\u52a0\u8f7d\u5931\u8d25", f"{"\u52a0\u8f7d\u56fe\u7247\u51fa\u9519:"}\n{e}")
            return

        self._current_image = image
        self._display_frame = image
        pixmap = ndarray_to_pixmap(image)
        self.preview_panel.show_frame(pixmap)
        self.result_panel.set_before(pixmap)
        self.preview_panel.set_detector_enabled(True)

        method = self.settings_panel.detection_method
        if method == "manual":
            self.progress_panel.set_status("\u624b\u52a8\u6a21\u5f0f\uff1a\u8bf7\u5728\u9884\u89c8\u753b\u9762\u4e0a\u62d6\u62fd\u6846\u9009\u6c34\u5370\u533a\u57df")
            return

        self.progress_panel.set_status("\u6b63\u5728\u81ea\u52a8\u68c0\u6d4b\u6c34\u5370\u2026")
        self._detect_worker = _DetectWorker(
            image, self._has_ocr, self._effective_cuda(), method, self
        )
        self._detect_worker.detection_done.connect(self._on_detection_ready)
        self._detect_worker.load_error.connect(self._on_load_error)
        worker = self._detect_worker
        worker.finished.connect(self._on_detect_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_load_worker_finished(self):
        """Drop the Python reference before Qt destroys the worker object."""
        worker = self.sender()
        if worker is self._load_worker:
            self._load_worker = None

    def _cancel_load_worker(self):
        """Stop and detach the loader without touching an already-deleted Qt object."""
        worker = self._load_worker
        self._load_worker = None
        if worker is None:
            return
        try:
            if worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                worker.wait(2000)
        except RuntimeError:
            # The finished signal may already have scheduled deleteLater().
            pass

    # ==================================================================
    # Slots: background-load callbacks
    # ==================================================================

    def _on_first_frame_ready(self, frame):
        """Called from background thread when first frame is extracted."""
        if self.sender() is not self._load_worker or not self._current_video_path:
            return
        self._first_frame = frame
        self._display_frame = frame
        pixmap = ndarray_to_pixmap(frame)
        self.preview_panel.show_frame(pixmap)
        self.result_panel.set_before(pixmap)
        self.preview_panel.set_detector_enabled(True)
        self.preview_panel.set_playback_state(False, 0)
        self.progress_panel.set_status("正在自动检测水印…")

    def _on_detection_ready(self, regions):
        """Called from background thread when detection is complete."""
        if self.sender() is not self._load_worker and self.sender() is not self._detect_worker:
            return
        if not self._current_video_path and not self._current_image_path:
            return
        if regions:
            self.preview_panel.show_candidates(regions)
            best = max(regions, key=lambda r: r.confidence)
            self.preview_panel.confirm_current_region(best)
            self.progress_panel.set_status(
                f"检测到 {len(regions)} 个候选水印区域，已自动选择最佳匹配"
            )
        else:
            self.progress_panel.set_status(
                "未检测到水印区域，请在预览画面上手动框选"
            )

    def _on_load_error(self, msg: str):
        QMessageBox.warning(self, "加载失败", f"加载视频出错:\n{msg}")

    # ==================================================================
    # Slots: playback
    # ==================================================================

    def _on_play_pause(self):
        """Toggle play / pause."""
        if self._is_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        """Begin sequential playback from the current frame."""
        if not self._current_video_path:
            return

        # Close any existing reader
        if self._video_reader is not None:
            try:
                self._video_reader.close()
            except Exception:
                pass
            self._video_reader = None

        # Open reader at current position
        info = self._current_info
        fps = info.fps if info and info.fps > 0 else 30.0
        seek_sec = self._current_frame_no / fps if fps > 0 else 0.0

        try:
            self._video_reader = VideoReader(self._current_video_path)
            self._video_reader.open(seek_seconds=seek_sec)
        except Exception as e:
            self.progress_panel.set_status(f"播放失败: {e}")
            return

        self._is_playing = True
        self.preview_panel.set_playback_state(True, self._current_frame_no)
        self.progress_panel.set_status("播放中…")

        # Drive playback at video FPS
        interval_ms = max(16, int(1000.0 / fps))
        self._playback_timer.start(interval_ms)

    def _stop_playback(self):
        """Pause or stop playback."""
        self._is_playing = False
        self._playback_timer.stop()
        self.preview_panel.set_playback_state(False, self._current_frame_no)

        if self._video_reader is not None:
            try:
                self._video_reader.close()
            except Exception:
                pass
            self._video_reader = None

        if self._current_video_path:
            self.progress_panel.set_status("已暂停 — 可拖拽进度条定位")

    def _on_playback_tick(self):
        """Read next frame and display it."""
        if not self._video_reader or not self._is_playing:
            return

        try:
            frame = self._video_reader.read_frame()
        except Exception:
            self._stop_playback()
            return

        if frame is None:
            # End of video
            self._stop_playback()
            self._current_frame_no = max(0, (self._current_info.total_frames or 1) - 1)
            self.preview_panel.set_playback_state(False, self._current_frame_no)
            self.progress_panel.set_status("播放完毕")
            return

        self._display_frame = frame
        self._current_frame_no = min(
            self._current_frame_no + 1,
            max(0, (self._current_info.total_frames or 1) - 1),
        )

        # Update canvas (lazy — only set the source pixmap)
        pixmap = ndarray_to_pixmap(frame)
        self.preview_panel.show_frame(pixmap)
        self.preview_panel.set_playback_state(True, self._current_frame_no)
        # Also mirror in before panel
        self.result_panel.set_before(pixmap)

    def _on_seek_frame(self, frame_no: int):
        """User dragged the timeline slider — seek to frame."""
        if self._seeking:
            return
        self._seeking = True

        was_playing = self._is_playing
        if was_playing:
            self._stop_playback()

        self._seek_to_frame(frame_no)

        if was_playing:
            self._start_playback()

        self._seeking = False

    def _seek_to_frame(self, frame_no: int):
        """Extract and display a specific frame (background)."""
        if not self._current_video_path:
            return

        self._current_frame_no = frame_no
        self.progress_panel.set_status(f"跳转到第 {frame_no} 帧…")

        # Run in background to avoid UI freeze
        self._seek_worker = _SeekWorker(self._current_video_path, frame_no, self)
        self._seek_worker.frame_ready.connect(self._on_seek_frame_ready)
        self._seek_worker.load_error.connect(self._on_load_error)
        worker = self._seek_worker
        worker.finished.connect(self._on_seek_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_seek_worker_finished(self):
        """Drop the seek worker reference before Qt disposes its C++ object."""
        worker = self.sender()
        if worker is self._seek_worker:
            self._seek_worker = None

    def _on_seek_frame_ready(self, frame):
        """Called when seek completes."""
        if self.sender() is not self._seek_worker or not self._current_video_path:
            return
        self._display_frame = frame
        pixmap = ndarray_to_pixmap(frame)
        self.preview_panel.show_frame(pixmap)
        self.result_panel.set_before(pixmap)
        self.preview_panel.set_playback_state(False, self._current_frame_no)
        # Clear old detection — user should re-detect on new frame
        self.preview_panel.show_candidates([])
        regions = self.preview_panel.get_confirmed_regions()
        if regions:
            self._mask = WatermarkDetector.generate_mask(
                frame.shape, regions, dilate_px=self.settings_panel.mask_padding
            )
            status = f"第 {self._current_frame_no} 帧 — 已保留框选区域，可继续调整或预览"
        else:
            self._mask = None
            status = f"第 {self._current_frame_no} 帧 — 点击「检测当前帧」或手动框选水印"
        self.progress_panel.set_status(status)

    # ==================================================================
    # Slots: detection
    # ==================================================================

    def _on_auto_detect(self):
        if self._display_frame is None:
            return
        self._auto_detect_and_show()

    def _auto_detect_and_show(self):
        if self._display_frame is None:
            return

        method = self.settings_panel.detection_method
        if method == "manual":
            self.progress_panel.set_status("手动模式：请在预览画面上拖拽框选水印区域")
            return

        # Detection can be slow (EasyOCR) — run in background
        self.progress_panel.set_status("正在自动检测水印…")
        self._detect_worker = _DetectWorker(
            self._display_frame, self._has_ocr, self._effective_cuda(), method, self
        )
        self._detect_worker.detection_done.connect(self._on_detection_ready)
        self._detect_worker.load_error.connect(self._on_load_error)
        worker = self._detect_worker
        worker.finished.connect(self._on_detect_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_detect_worker_finished(self):
        """Drop the detector worker reference before Qt disposes its C++ object."""
        worker = self.sender()
        if worker is self._detect_worker:
            self._detect_worker = None

    def _on_mask_confirmed(self, regions: list):
        """User confirmed/updated the watermark regions."""
        if not regions or self._display_frame is None:
            self._mask = None
            return

        self._mask = WatermarkDetector.generate_mask(
            self._display_frame.shape,
            regions,
            dilate_px=self.settings_panel.mask_padding,
        )
        self.progress_panel.set_status(
            f"水印区域已确认 ({len(regions)} 处)，可预览修复效果"
        )

    def _on_padding_changed(self, value: int):
        """Mask padding spinbox changed — re-generate mask in-place."""
        regions = self.preview_panel.get_confirmed_regions()
        if not regions or self._display_frame is None:
            return

        self._mask = WatermarkDetector.generate_mask(
            self._display_frame.shape,
            regions,
            dilate_px=value,
        )
        self.progress_panel.set_status(
            f"Mask 扩展已更新 ({value} px)，共 {len(regions)} 处水印区域"
        )

    # ==================================================================
    # Slots: preview inpainting on current frame
    # ==================================================================

    def _on_preview_inpaint(self):
        if self._display_frame is None:
            QMessageBox.information(self, "\u63d0\u793a", "\u8bf7\u5148\u52a0\u8f7d\u89c6\u9891\u6216\u56fe\u7247\u3002")
            return

        mask = self._mask
        if mask is None and self.settings_panel.detection_method == "temporal":
            regions = self.settings_panel.temporal_regions()
            if not regions:
                QMessageBox.information(
                    self,
                    "\u63d0\u793a",
                    "\u8bf7\u5148\u5728\u300c\u65f6\u5e8f\u6c34\u5370\u533a\u57df\u300d\u4e2d\u81ea\u52a8\u5206\u6790\u6216\u6dfb\u52a0\u533a\u57df\uff0c\u518d\u9884\u89c8\u4fee\u590d\u6548\u679c\u3002",
                )
                return
            fps = self._current_info.fps if self._current_info and self._current_info.fps > 0 else 30.0
            current_time = self._current_frame_no / fps
            active = next(
                (r for r in regions if r["start_sec"] <= current_time <= r["end_sec"]),
                None,
            )
            if active is None:
                QMessageBox.information(
                    self,
                    "\u63d0\u793a",
                    f"\u5f53\u524d\u64ad\u653e\u65f6\u95f4 ({current_time:.1f} \u79d2) \u6ca1\u6709\u6c34\u5370\u533a\u57df\uff0c"
                    "\u8bf7\u62d6\u52a8\u8fdb\u5ea6\u6761\u5230\u6c34\u5370\u51fa\u73b0\u7684\u65f6\u95f4\u6bb5\u518d\u9884\u89c8\u3002",
                )
                return
            from watermark_remover.core.detector import DetectionRegion
            det = DetectionRegion(
                x=active["x"],
                y=active["y"],
                width=active["w"],
                height=active["h"],
                method="temporal",
            ).expanded(padding=self.settings_panel.mask_padding)
            mask = WatermarkDetector.generate_mask(
                self._display_frame.shape,
                [det],
                dilate_px=self.settings_panel.mask_padding,
            )
        if mask is None:
            QMessageBox.information(self, "\u63d0\u793a", "\u8bf7\u5148\u9009\u62e9\u6c34\u5370\u533a\u57df\u3002")
            return

        self.progress_panel.set_status("\u6b63\u5728\u9884\u89c8\u4fee\u590d\u6548\u679c\u2026")
        self.settings_panel.preview_btn.setEnabled(False)

        try:
            inpainter = Inpainter(
                method=self.settings_panel.inpainting_method,
                device="cuda" if self._effective_cuda() else "cpu",
            )
            result = inpainter.inpaint(self._display_frame, mask)
            after_pix = ndarray_to_pixmap(result)
            self.result_panel.set_after(after_pix)
            self.progress_panel.set_status("修复预览完成 — 拖拽滑块对比效果")
        except Exception as e:
            QMessageBox.warning(self, "预览失败", f"{e}")
        finally:
            self.settings_panel.preview_btn.setEnabled(True)

    # ==================================================================
    # Slots: full processing
    # ==================================================================

    def _on_start_processing(self):
        batch_paths = self.file_panel.get_all_paths_for_batch()
        if not batch_paths:
            QMessageBox.information(self, "提示", "请先加载视频。")
            return

        if len(batch_paths) == 1:
            single_path = batch_paths[0]
            if is_image_file(single_path):
                if self._current_image is None or self._mask is None:
                    QMessageBox.information(self, "提示", "请先加载图片并确认水印区域。")
                    return
                output = self._resolve_output_path(single_path)
                if output is None:
                    return
                self._batch_mode = False
                self._process_image(single_path, output, self._mask)
                return
            if self._current_video_path is None or self._mask is None:
                if self.settings_panel.detection_method != "temporal":
                    QMessageBox.information(self, "\u63d0\u793a", "\u8bf7\u5148\u52a0\u8f7d\u89c6\u9891\u5e76\u786e\u8ba4\u6c34\u5370\u533a\u57df\u3002")
                    return
            output = self._resolve_output_path(self._current_video_path)
            if output is None:
                return
            self._batch_mode = False
            if self.settings_panel.detection_method == "temporal":
                regions = self.settings_panel.temporal_regions()
                if regions and self._temporal_table_video == self._current_video_path:
                    self._start_pipeline(
                        self._current_video_path, output, None, temporal_regions=regions
                    )
                else:
                    self._start_temporal_analysis(self._current_video_path, output)
            else:
                self._start_pipeline(self._current_video_path, output, self._mask)
            return

        # Batch mode
        if self.settings_panel.detection_method == "manual" and self._mask is None:
            QMessageBox.information(
                self,
                "提示",
                "批量处理在手动模式下需要为当前视频框选水印区域。\n"
                "其他视频将尝试自动检测；若失败则跳过。",
            )

        if self._conflict_rule != "auto_rename":
            outputs = [self._default_output_path(p) for p in batch_paths]
            existing = [out for out in outputs if os.path.exists(out)]
            if existing:
                reply = QMessageBox.question(
                    self,
                    "\u786e\u8ba4\u8986\u76d6",
                    f"\u6709 {len(existing)} \u4e2a\u8f93\u51fa\u6587\u4ef6\u5df2\u5b58\u5728\uff0c\u662f\u5426\u5168\u90e8\u8986\u76d6\uff1f",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        self._batch_mode = True
        self._batch_paths = batch_paths
        self._batch_index = 0
        self._batch_completed = []
        self._process_next_batch_item()

    def _output_directory(self, input_path: str) -> str:
        """Return one shared output folder, creating it when necessary."""
        selected = self._output_directory
        folder_name = "去水印图片" if is_image_file(input_path) else "去水印视频"
        directory = selected or os.path.join(os.path.dirname(input_path), folder_name)
        os.makedirs(directory, exist_ok=True)
        return os.path.abspath(directory)

    def _default_output_path(self, input_path: str) -> str:
        directory = self._output_directory(input_path)
        stem, ext = os.path.splitext(os.path.basename(input_path))
        rendered = self._render_name_template(stem, ext)
        if os.path.splitext(rendered)[1].lower() not in {
            ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
            ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv",
        }:
            rendered = f"{rendered}{ext}"
        return os.path.join(directory, rendered)

    def _render_name_template(self, stem: str, ext: str) -> str:
        """Fill the user's filename template with placeholder values."""
        now = datetime.now()
        return (
            self._name_template
            .replace("{name}", stem)
            .replace("{date}", now.strftime("%Y%m%d"))
            .replace("{time}", now.strftime("%H%M%S"))
            .replace("{ext}", ext.lstrip("."))
        )

    @staticmethod
    def _migrate_name_template(value: str) -> str:
        """Convert old fixed rules to the editable template format."""
        if value in ("suffix_cn", "suffix_clean", "date_prefix"):
            return {
                "suffix_cn": "{name}_\u65e0\u6c34\u5370.{ext}",
                "suffix_clean": "{name}_clean.{ext}",
                "date_prefix": "{date}_{name}.{ext}",
            }[value]
        return value or "{name}_\u65e0\u6c34\u5370.{ext}"

    def _dedupe_output_path(self, output_path: str) -> str:
        if not os.path.exists(output_path):
            return output_path
        stem, ext = os.path.splitext(output_path)
        counter = 1
        while True:
            candidate = f"{stem}_{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _resolve_output_path(self, input_path: str) -> str | None:
        output = self._default_output_path(input_path)
        if not os.path.exists(output):
            return output

        if self._conflict_rule == "auto_rename":
            return self._dedupe_output_path(output)
        if self._conflict_rule == "overwrite":
            return output

        reply = QMessageBox.question(
            self,
            "\u786e\u8ba4\u8986\u76d6",
            f"\u8f93\u51fa\u6587\u4ef6\u5df2\u5b58\u5728\n{output}\n\n\u662f\u5426\u8986\u76d6\uff1f",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return None
        return output

    def _resolve_batch_output_path(self, input_path: str) -> str:
        output = self._default_output_path(input_path)
        if os.path.exists(output) and self._conflict_rule == "auto_rename":
            return self._dedupe_output_path(output)
        return output

    def _prepare_mask_for_path(self, path: str) -> np.ndarray | None:
        """Build a watermark mask for the given video path."""
        method = self.settings_panel.detection_method

        if path == self._current_video_path and self._mask is not None:
            return self._mask

        if method == "manual":
            return self._mask if path == self._current_video_path else None

        try:
            frame = extract_first_frame(path)
        except Exception:
            return None

        # Fresh detector — never share across threads
        detector = WatermarkDetector(
            use_ocr=self._has_ocr,
            use_morphology=True,
            gpu=self._effective_cuda(),
        )
        regions = detector.detect_with_method(frame, method)
        best = WatermarkDetector.pick_best_region(regions)
        if best is None:
            return None

        return WatermarkDetector.generate_mask(
            frame.shape,
            [best],
            dilate_px=self.settings_panel.mask_padding,
        )

    def _build_inpainter(self) -> Inpainter | None:
        method = self.settings_panel.inpainting_method
        inpainter = Inpainter(
            method=method,
            device="cuda" if self._effective_cuda() else "cpu",
        )

        if method == "lama":
            if not inpainter.is_lama_available():
                # torch not even installed
                reply = QMessageBox.question(
                    self,
                    "LaMa 不可用",
                    "未检测到 PyTorch。是否降级为 OpenCV 修复？\n\n"
                    "LaMa 需要:\n  pip install torch\n\n"
                    "OpenCV 修复无需额外安装。",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    inpainter.method = "opencv"
                else:
                    return None
            else:
                # torch is installed — try to actually load the model
                # (must happen in main thread; torch models are not thread-safe)
                self.progress_panel.set_status("正在加载 LaMa 模型（首次需下载约 200MB）…")
                ok = inpainter.try_init_lama()
                if not ok:
                    reply = QMessageBox.question(
                        self,
                        "LaMa 模型加载失败",
                        "无法加载 LaMa 模型（网络问题或模型下载失败）。\n"
                        "是否降级为 OpenCV 修复？\n\n"
                        "提示：在中国大陆访问 GitHub 可能受限，\n"
                        "建议使用 OpenCV 模式。",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if reply == QMessageBox.Yes:
                        inpainter.method = "opencv"
                        # Also switch the radio button in the UI
                        self.settings_panel.radio_cv.setChecked(True)
                    else:
                        return None
        return inpainter

    def _on_manual_temporal_analyze(self):
        """User clicked 自动分析 in the temporal table: analyze the loaded
        video and fill the table for editing (no processing yet)."""
        if self._temporal_worker is not None and self._temporal_worker.isRunning():
            return
        if self._current_video_path is None:
            QMessageBox.information(self, "提示", "请先加载视频，再自动分析水印位置。")
            return
        self._start_temporal_analysis(self._current_video_path, None)

    def _start_temporal_analysis(self, input_path: str, output_path: str | None):
        """Analyze the video to learn where and when the watermark appears.
        When output_path is None the result is only filled into the editable table."""
        self._temporal_pending = (input_path, output_path)
        self.progress_panel.set_status("\u6b63\u5728\u5206\u6790\u6c34\u5370\u6eda\u52a8\u4f4d\u7f6e\u2026")
        self.settings_panel.set_processing_mode(True)
        worker = _TemporalAnalyzeWorker(input_path, self)
        worker.regions_ready.connect(self._on_temporal_analysis_done)
        worker.load_error.connect(self._on_temporal_analysis_error)
        self._temporal_worker = worker
        worker.start()

    def _on_temporal_analysis_done(self, regions: list):
        self._temporal_worker = None
        pending = self._temporal_pending
        self._temporal_pending = None
        if pending is None:
            self.settings_panel.set_processing_mode(False)
            return
        if not regions:
            self.settings_panel.set_processing_mode(False)
            QMessageBox.warning(
                self,
                "\u672a\u68c0\u6d4b\u5230\u6c34\u5370",
                "\u672a\u80fd\u81ea\u52a8\u8bc6\u522b\u6c34\u5370\u7684\u6eda\u52a8\u4f4d\u7f6e\uff0c\u8bf7\u6539\u7528\u81ea\u52a8\u68c0\u6d4b\u6216\u624b\u52a8\u6846\u9009\u3002",
            )
            return
        input_path, output_path = pending
        if output_path is None:
            self.settings_panel.set_processing_mode(False)
            self._temporal_table_video = input_path
            self.settings_panel.set_temporal_regions([r.to_dict() for r in regions])
            self.progress_panel.set_status(
                f"已识别 {len(regions)} 段水印位置，可编辑后点击开始处理。"
            )
            return
        self._start_pipeline(
            input_path,
            output_path,
            None,
            temporal_regions=[r.to_dict() for r in regions],
        )

    def _on_temporal_analysis_error(self, message: str):
        self._temporal_worker = None
        self._temporal_pending = None
        self.settings_panel.set_processing_mode(False)
        QMessageBox.warning(self, "\u5206\u6790\u5931\u8d25", f"{message}")

    def _start_pipeline(
        self,
        input_path: str,
        output_path: str,
        mask: np.ndarray | None,
        temporal_regions: list[dict] | None = None,
    ):
        inpainter = self._build_inpainter()
        if inpainter is None:
            return

        # Create a *fresh* detector for the pipeline thread.
        # EasyOCR / torch models are NOT thread-safe, so we cannot share
        # self._detector across threads.
        pipeline_detector = WatermarkDetector(
            use_ocr=self._has_ocr,
            use_morphology=True,
            gpu=self._effective_cuda(),
        )

        fps = self._current_info.fps if self._current_info and input_path == self._current_video_path else 30.0
        if input_path != self._current_video_path:
            try:
                from watermark_remover.core.video_io import get_video_info
                fps = get_video_info(input_path).fps
            except Exception:
                fps = 30.0

        self._pipeline = WatermarkPipeline(
            input_path=input_path,
            output_path=output_path,
            mask=mask,
            inpainter=inpainter,
            crf={0: 18, 1: 23, 2: 28}[self._quality_index],
            detector=pipeline_detector,
            detection_method=self.settings_panel.detection_method,
            mask_padding=self.settings_panel.mask_padding,
            redetect_interval=self.settings_panel.redetect_interval_frames(fps),
            temporal_regions=temporal_regions,
            fine_mask=self.settings_panel.fine_mask_enabled,
            enhance=self._enhance_enabled,
            enhance_scale={0: 1.0, 1: 1.25, 2: 1.5}[self._enhance_scale_index],
            enhance_sharpen=self._enhance_sharpen,
            enhance_saturation=self._enhance_saturation,
            auto_crf=self._auto_crf,
        )
        self._pipeline.progress.connect(self._on_pipeline_progress)
        self._pipeline.finished.connect(self._on_pipeline_finished)
        self._pipeline.error.connect(self._on_pipeline_error)

        self.settings_panel.set_processing_mode(True)
        self.progress_panel.set_status("处理中…")
        self._pipeline.start()

    # ------------------------------------------------------------------
    # Slots: image processing
    # ------------------------------------------------------------------

    def _process_image(self, input_path: str, output_path: str, mask: np.ndarray):
        """Process a still image in a background worker."""
        inpainter = self._build_inpainter()
        if inpainter is None:
            return
        self.settings_panel.set_processing_mode(True)
        self.progress_panel.set_status("\u6b63\u5728\u5904\u7406\u56fe\u7247\u2026")
        worker = _ImageProcessWorker(
            input_path=input_path,
            output_path=output_path,
            mask=mask,
            inpainter=inpainter,
            fine_mask=self.settings_panel.fine_mask_enabled,
            enhance=self._enhance_enabled,
            enhance_scale={0: 1.0, 1: 1.25, 2: 1.5}[self._enhance_scale_index],
            enhance_sharpen=self._enhance_sharpen,
            enhance_saturation=self._enhance_saturation,
            parent=self,
        )
        worker.finished.connect(self._on_image_processed)
        worker.error.connect(self._on_image_process_error)
        self._image_worker = worker
        worker.start()

    def _prepare_image_mask(self, path: str) -> np.ndarray | None:
        """Build a watermark mask for an image (used by batch mode)."""
        method = self.settings_panel.detection_method
        if path == self._current_image_path and self._mask is not None:
            return self._mask
        if method == "manual":
            return self._mask if path == self._current_image_path else None
        try:
            image = load_image(path)
        except Exception:
            return None
        detector = WatermarkDetector(
            use_ocr=self._has_ocr,
            use_morphology=True,
            gpu=self._effective_cuda(),
        )
        regions = detector.detect_with_method(image, method)
        best = WatermarkDetector.pick_best_region(regions)
        if best is None:
            return None
        return WatermarkDetector.generate_mask(
            image.shape, [best], dilate_px=self.settings_panel.mask_padding
        )

    def _on_image_processed(self, output_path: str):
        self._image_worker = None
        self.settings_panel.set_processing_mode(False)
        self.progress_panel.set_finished(output_path)

        if self._batch_mode:
            self._batch_completed.append(output_path)
            processed = self._batch_paths[self._batch_index]
            try:
                after = load_image(output_path)
                self.result_panel.set_after(ndarray_to_pixmap(after))
            except Exception:
                pass
            self.file_panel.remove_from_batch(processed)
            self._batch_index += 1
            if self._batch_index < len(self._batch_paths):
                self._process_next_batch_item()
            else:
                self._finish_batch()
            return

        try:
            after = load_image(output_path)
            self.result_panel.set_after(ndarray_to_pixmap(after))
        except Exception:
            pass

        reply = QMessageBox.information(
            self,
            "图片处理完成",
            f"去水印图片已保存到:\n{output_path}\n\n是否打开所在文件夹？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", output_path])
            else:
                subprocess.Popen(["open", os.path.dirname(output_path)])

    def _on_image_process_error(self, message: str):
        self._image_worker = None
        self.settings_panel.set_processing_mode(False)
        self.progress_panel.set_error(message)

        if self._batch_mode:
            failed = self._batch_paths[self._batch_index]
            QMessageBox.warning(self, "图片处理失败", f"处理失败，已跳过:\n{os.path.basename(failed)}\n\n{message}")
            self.file_panel.remove_from_batch(failed)
            self._batch_index += 1
            if self._batch_index < len(self._batch_paths):
                self._process_next_batch_item()
            else:
                self._finish_batch()
            return

        QMessageBox.critical(self, "图片处理失败", message)

    def _process_next_batch_item(self):
        while self._batch_index < len(self._batch_paths):
            path = self._batch_paths[self._batch_index]
            output = self._resolve_batch_output_path(path)

            if is_image_file(path):
                mask = self._prepare_image_mask(path)
                if mask is None:
                    QMessageBox.warning(self, "跳过", f"无法为以下图片生成水印区域，已跳过:\n{os.path.basename(path)}")
                    self.file_panel.remove_from_batch(path)
                    self._batch_index += 1
                    continue
                total = len(self._batch_paths)
                self.progress_panel.set_status(
                    f"\u6b63\u5728\u5904\u7406\u56fe\u7247 {self._batch_index + 1}/{total}: {os.path.basename(path)}"
                )
                self._process_image(path, output, mask)
                return

            if self.settings_panel.detection_method == "temporal":
                regions = self.settings_panel.temporal_regions()
                if regions:
                    total = len(self._batch_paths)
                    self.progress_panel.set_status(
                        f"批量处理 {self._batch_index + 1}/{total}: {os.path.basename(path)}"
                    )
                    self._start_pipeline(path, output, None, temporal_regions=regions)
                    return
                self._start_temporal_analysis(path, output)
                return

            mask = self._prepare_mask_for_path(path)

            if mask is None:
                QMessageBox.warning(
                    self,
                    "跳过",
                    f"无法为以下视频生成水印区域，已跳过:\n{os.path.basename(path)}",
                )
                self.file_panel.remove_from_batch(path)
                self._batch_index += 1
                continue

            total = len(self._batch_paths)
            self.progress_panel.set_status(
                f"批量处理 {self._batch_index + 1}/{total}: {os.path.basename(path)}"
            )
            self._start_pipeline(path, output, mask)
            return

        self._finish_batch()

    def _finish_batch(self):
        self._batch_mode = False
        count = len(self._batch_completed)
        self.settings_panel.set_processing_mode(False)

        if count == 0:
            QMessageBox.information(self, "批量处理", "没有成功处理的视频。")
            return

        preview = "\n".join(self._batch_completed[:5])
        if count > 5:
            preview += f"\n…等共 {count} 个文件"
        QMessageBox.information(
            self,
            "批量处理完成",
            f"已成功处理 {count} 个视频:\n{preview}",
        )
        self._batch_completed = []

    def _on_cancel_processing(self):
        if self._image_worker is not None and self._image_worker.isRunning():
            self._image_worker.requestInterruption()
            self._image_worker.wait(5000)
            self._image_worker = None
            self.settings_panel.set_processing_mode(False)
            self.progress_panel.set_status("已取消图片处理")
            return
        if self._temporal_worker is not None and self._temporal_worker.isRunning():
            self._temporal_worker.cancel()
            self._temporal_worker.wait(3000)
            self._temporal_worker = None
            self._temporal_pending = None
            self.settings_panel.set_processing_mode(False)
            self.progress_panel.set_status("已取消分析")
            return
        if self._pipeline and self._pipeline.isRunning():
            self._pipeline.cancel()
            self._batch_mode = False
            self.progress_panel.set_status("正在取消…")

    def _on_pipeline_progress(self, pct: int, message: str):
        self.progress_panel.set_progress(pct, message)

    def _on_pipeline_finished(self, output_path: str):
        self._pipeline = None

        if self._batch_mode:
            self._batch_completed.append(output_path)
            processed = self._batch_paths[self._batch_index]
            self.result_panel.set_video(output_path)
            self.file_panel.remove_from_batch(processed)
            self._batch_index += 1
            self.progress_panel.set_finished(output_path)
            if self._batch_index < len(self._batch_paths):
                self._process_next_batch_item()
                return
            self._finish_batch()
            return

        self.progress_panel.set_finished(output_path)
        self.settings_panel.set_processing_mode(False)
        self.result_panel.set_video(output_path)

        reply = QMessageBox.information(
            self,
            "处理完成",
            f"去水印视频已保存到:\n{output_path}\n\n是否打开所在文件夹？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", output_path])
            else:
                subprocess.Popen(["open", os.path.dirname(output_path)])

    def _on_pipeline_error(self, message: str):
        self.progress_panel.set_error(message)
        self.settings_panel.set_processing_mode(False)
        self._pipeline = None

        if self._batch_mode:
            failed = self._batch_paths[self._batch_index]
            QMessageBox.warning(
                self,
                "批量处理错误",
                f"处理失败，已跳过:\n{os.path.basename(failed)}\n\n{message}",
            )
            self.file_panel.remove_from_batch(failed)
            self._batch_index += 1
            if self._batch_index < len(self._batch_paths):
                self._process_next_batch_item()
            else:
                self._finish_batch()
            return

        QMessageBox.critical(self, "处理失败", message)

    # ==================================================================
    # About & lifecycle
    # ==================================================================

    def _show_about(self):
        QMessageBox.about(
            self,
            "关于 羊咩的工厂",
            f"<h3>羊咩的工厂 v{__version__}</h3>"
            "<p>视频水印移除工具。</p>"
            "<p><b>技术栈:</b> EasyOCR + LaMa / OpenCV Inpainting</p>"
            "<p><b>框架:</b> PySide6 (Qt for Python)</p>"
            "<hr>"
            "<p>羊咩的工厂 | 仅用于个人研究</p>",
        )

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def resizeEvent(self, event):
        """Keep the painted background filling the window on resize."""
        super().resizeEvent(event)
        bg = self._bg_video
        if bg is not None:
            bg.setGeometry(self.centralWidget().rect())
            bg.lower()

    def closeEvent(self, event):
        if self._pipeline and self._pipeline.isRunning():
            reply = QMessageBox.question(
                self,
                "确认退出",
                "视频处理尚未完成，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._pipeline.cancel()
                self._pipeline.wait(3000)
                self._stop_background_player()
                event.accept()
            else:
                event.ignore()
        else:
            self._stop_playback()
            self._cancel_load_worker()
            self._seek_worker = None
            self._detect_worker = None
            if self._image_worker is not None and self._image_worker.isRunning():
                self._image_worker.wait(5000)
            self._image_worker = None
            if self._temporal_worker is not None and self._temporal_worker.isRunning():
                self._temporal_worker.cancel()
                self._temporal_worker.wait(3000)
            self._temporal_worker = None
            self._temporal_pending = None
            self._stop_background_player()
            event.accept()


# ==================================================================
# Background workers — keep the UI responsive during heavy I/O
# ==================================================================

class _TemporalAnalyzeWorker(QThread):
    """Analyze a video to learn the watermark positions over time."""

    regions_ready = Signal(object)  # list[TemporalRegion]
    load_error = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            tracker = TemporalWatermarkTracker()
            regions = tracker.analyze(self._path)
            if not self._cancelled:
                self.regions_ready.emit(regions)
        except Exception as e:
            self.load_error.emit(str(e))


class _VideoLoadWorker(QThread):
    """Extract first frame + run watermark detection on a background thread.

    Creates its own detector instance — NEVER shares EasyOCR across threads.
    """

    frame_ready = Signal(object)        # np.ndarray
    detection_done = Signal(list)       # list[DetectionRegion]
    load_error = Signal(str)

    def __init__(self, path: str, has_ocr: bool, has_cuda: bool, method: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._has_ocr = has_ocr
        self._has_cuda = has_cuda
        self._method = method

    def run(self):
        try:
            # Stage 1: extract first frame (ffmpeg subprocess call)
            frame = extract_first_frame(self._path)
            self.frame_ready.emit(frame)

            # Stage 2: detect watermarks
            # Use a FRESH detector — never share EasyOCR/PyTorch across threads
            if self._method != "manual":
                detector = WatermarkDetector(
                    use_ocr=self._has_ocr,
                    use_morphology=True,
                    gpu=self._has_cuda,
                )
                regions = detector.detect_with_method(frame, self._method)
                self.detection_done.emit(regions)
        except Exception as e:
            self.load_error.emit(str(e))


class _DetectWorker(QThread):
    """Run watermark detection on a background thread (for manual re-detect).

    Creates its own detector instance — NEVER shares EasyOCR across threads.
    """

    detection_done = Signal(list)       # list[DetectionRegion]
    load_error = Signal(str)

    def __init__(self, frame, has_ocr: bool, has_cuda: bool, method: str, parent=None):
        super().__init__(parent)
        self._frame = frame
        self._has_ocr = has_ocr
        self._has_cuda = has_cuda
        self._method = method

    def run(self):
        try:
            detector = WatermarkDetector(
                use_ocr=self._has_ocr,
                use_morphology=True,
                gpu=self._has_cuda,
            )
            regions = detector.detect_with_method(self._frame, self._method)
            self.detection_done.emit(regions)
        except Exception as e:
            self.load_error.emit(str(e))


class _SeekWorker(QThread):
    """Extract a specific frame in the background (for timeline scrubbing)."""

    frame_ready = Signal(object)    # np.ndarray
    load_error = Signal(str)

    def __init__(self, path: str, frame_no: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._frame_no = frame_no

    def run(self):
        try:
            frame = extract_frame_at(self._path, self._frame_no)
            self.frame_ready.emit(frame)
        except Exception as e:
            self.load_error.emit(str(e))


class _ImageProcessWorker(QThread):
    """Inpaint a still image in the background and save the result."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        mask,
        inpainter,
        fine_mask: bool = False,
        enhance: bool = False,
        enhance_scale: float = 1.0,
        enhance_sharpen: bool = False,
        enhance_saturation: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._input_path = input_path
        self._output_path = output_path
        self._mask = mask
        self._inpainter = inpainter
        self._fine_mask = fine_mask
        self._enhance = enhance
        self._enhance_scale = enhance_scale
        self._enhance_sharpen = enhance_sharpen
        self._enhance_saturation = enhance_saturation

    def run(self):
        try:
            image = load_image(self._input_path)
            result = process_image(
                image,
                self._mask,
                self._inpainter,
                fine_mask=self._fine_mask,
                enhance=self._enhance,
                enhance_scale=self._enhance_scale,
                enhance_sharpen=self._enhance_sharpen,
                enhance_saturation=self._enhance_saturation,
            )
            save_image(result, self._output_path)
            self.finished.emit(self._output_path)
        except Exception as e:
            self.error.emit(str(e))
