"""Preview panel: shows first frame with interactive watermark selection."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from watermark_remover.core.detector import DetectionRegion
from watermark_remover.ui.image_utils import pixmap_is_valid


class PreviewPanel(QFrame):
    """Central preview area — shows frame with draggable watermark selection."""

    mask_confirmed = Signal(list)          # list[DetectionRegion]
    play_pause_clicked = Signal()          # toggle play / pause
    seek_frame = Signal(int)               # jump to frame number
    clear_workspace_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        self._pixmap: QPixmap | None = None
        self._display_rect = QRect()
        self._image_offset = QPoint()

        # Selection state
        self._selecting = False
        self._selection_start = QPoint()
        self._selection_end = QPoint()
        self._confirmed_regions: list[DetectionRegion] = []
        self._candidate_regions: list[DetectionRegion] = []

        # Selection box color (user-configurable in settings)
        self._box_color = QColor("#00ff88")

        # Playback state
        self._playing = False
        self._total_frames = 0
        self._fps = 0.0
        self._image_mode = False

        self._setup_ui()

    def set_box_color(self, color: QColor):
        """Set the color used to draw watermark selection boxes."""
        self._box_color = QColor(color)
        self.canvas._box_color = QColor(color)
        self.canvas.update()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # -- Title bar --
        title_bar = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("sectionTitle")
        title_bar.addWidget(self.title_label)
        title_bar.addStretch()

        self.clear_video_btn = QPushButton("清除当前视频")
        self.clear_video_btn.setObjectName("secondaryBtn")
        self.clear_video_btn.setEnabled(False)
        self.clear_video_btn.clicked.connect(self.clear_workspace_requested.emit)
        title_bar.addWidget(self.clear_video_btn)

        self.auto_detect_btn = QPushButton("检测当前帧")
        self.auto_detect_btn.setObjectName("secondaryBtn")
        self.auto_detect_btn.setEnabled(False)
        title_bar.addWidget(self.auto_detect_btn)

        self.clear_btn = QPushButton("清除选区")
        self.clear_btn.setObjectName("secondaryBtn")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear_selection)
        title_bar.addWidget(self.clear_btn)

        layout.addLayout(title_bar)

        # -- Canvas --
        self.canvas = _Canvas(self)
        self.canvas.setMinimumHeight(300)
        self.canvas.setSizePolicy(
            self.canvas.sizePolicy().horizontalPolicy(),
            self.canvas.sizePolicy().verticalPolicy(),
        )
        self.canvas.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self.canvas, stretch=1)

        # -- Playback controls --
        pb_layout = QHBoxLayout()
        pb_layout.setSpacing(6)

        self.play_btn = QPushButton("播放")
        self.play_btn.setObjectName("compactBtn")
        self.play_btn.setFixedWidth(64)
        self.play_btn.setEnabled(False)
        self.play_btn.setToolTip("播放 / 暂停")
        self.play_btn.clicked.connect(self._on_play_btn)
        pb_layout.addWidget(self.play_btn)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setEnabled(False)
        self.time_slider.setToolTip("拖动定位帧")
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        self.time_slider.valueChanged.connect(self._on_slider_value_changed)
        pb_layout.addWidget(self.time_slider, stretch=1)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setObjectName("infoLabel")
        self.time_label.setFixedWidth(100)
        self.time_label.setAlignment(Qt.AlignCenter)
        pb_layout.addWidget(self.time_label)

        self.frame_label = QLabel("")
        self.frame_label.setObjectName("infoLabel")
        self.frame_label.setFixedWidth(80)
        self.frame_label.setAlignment(Qt.AlignRight)
        pb_layout.addWidget(self.frame_label)
        self._playback_widgets = [self.play_btn, self.time_slider, self.time_label, self.frame_label]

        layout.addLayout(pb_layout)

        # -- Hint --
        self.hint = QLabel("")
        self.hint.setObjectName("infoLabel")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def set_image_mode(self, enabled: bool):
        """Switch the preview between video and still-image mode."""
        self._image_mode = enabled
        self.title_label.setText("图片预览" if enabled else "视频预览")
        self.clear_video_btn.setText("清除当前图片" if enabled else "清除当前视频")
        self.auto_detect_btn.setText("检测水印" if enabled else "检测当前帧")
        for widget in self._playback_widgets:
            widget.setVisible(not enabled)
        self.set_playback_enabled(False)

    # ------------------------------------------------------------------
    # Playback slots
    # ------------------------------------------------------------------

    def _on_play_btn(self):
        self.play_pause_clicked.emit()

    def _on_slider_pressed(self):
        """User starts dragging — pause tracking updates."""
        self.time_slider.blockSignals(False)

    def _on_slider_released(self):
        """User finished dragging — seek to selected frame."""
        frame_no = self.time_slider.value()
        self.seek_frame.emit(frame_no)

    def _on_slider_value_changed(self, value: int):
        """Update time label while dragging or playing."""
        if self._fps > 0:
            secs = value / self._fps
            total = self._total_frames / self._fps if self._fps > 0 else 0
            self.time_label.setText(
                f"{self._fmt_time(secs)} / {self._fmt_time(total)}"
            )
        self.frame_label.setText(f"帧 {value}/{self._total_frames}")

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_playback_enabled(self, enabled: bool, total_frames: int = 0, fps: float = 0.0):
        """Enable playback controls and set video metadata."""
        self._total_frames = max(0, total_frames)
        self._fps = fps
        self.play_btn.setEnabled(enabled)
        self.time_slider.setEnabled(enabled)
        if enabled and total_frames > 0:
            self.time_slider.setRange(0, total_frames - 1)
            self.time_slider.setValue(0)
        else:
            self.time_slider.setRange(0, 0)

    def set_playback_state(self, playing: bool, frame_no: int):
        """Update UI for playback state (called from main thread)."""
        self._playing = playing
        self.play_btn.setText("暂停" if playing else "播放")
        if not self.time_slider.isSliderDown():
            self.time_slider.blockSignals(True)
            self.time_slider.setValue(frame_no)
            self.time_slider.blockSignals(False)
            self._on_slider_value_changed(frame_no)

    def show_frame(self, pixmap: QPixmap):
        """Display a frame (usually the first frame of the video)."""
        self._pixmap = pixmap if pixmap_is_valid(pixmap) else None
        self.canvas.set_pixmap(pixmap)
        self.clear_video_btn.setEnabled(self._pixmap is not None)

    def clear_frame(self):
        """Clear the preview canvas."""
        self._pixmap = None
        self._confirmed_regions.clear()
        self._candidate_regions.clear()
        self.canvas.clear_all()
        self.clear_btn.setEnabled(False)
        self.clear_video_btn.setEnabled(False)
        self.auto_detect_btn.setEnabled(False)
        self.hint.setText("加载图片后在画面上拖拽鼠标框选水印区域" if self._image_mode else "加载视频后在画面上拖拽鼠标框选水印区域")
        self.set_playback_enabled(False)
        self.mask_confirmed.emit([])

    def show_candidates(self, regions: list[DetectionRegion]):
        """Show OCR/morphology-detected candidates on the canvas."""
        self._candidate_regions = list(regions)
        self.canvas.set_candidates(self._candidate_regions)

    def set_detector_enabled(self, enabled: bool):
        """Enable/disable the auto-detect button."""
        self.auto_detect_btn.setEnabled(enabled)

    def get_confirmed_regions(self) -> list[DetectionRegion]:
        return list(self._confirmed_regions)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_selection_changed(self, rect: QRect | None):
        if rect is None or rect.isEmpty():
            self.hint.setText("在画面上拖拽鼠标框选水印区域")
            self.clear_btn.setEnabled(bool(self._confirmed_regions))
            return

        self.hint.setText(
            f"已选择区域: ({rect.x()}, {rect.y()}) → "
            f"({rect.x() + rect.width()}, {rect.y() + rect.height()})"
        )
        self.clear_btn.setEnabled(True)

    def _clear_selection(self):
        self._confirmed_regions.clear()
        self._candidate_regions.clear()
        self.canvas.clear_selection()
        self.hint.setText("在画面上拖拽鼠标框选水印区域")
        self.clear_btn.setEnabled(False)
        self.mask_confirmed.emit([])

    def confirm_current_region(self, region: DetectionRegion):
        """Add a confirmed region from the manual selection."""
        # Avoid duplicates
        for existing in self._confirmed_regions:
            if (abs(existing.x - region.x) < 10 and
                    abs(existing.y - region.y) < 10 and
                    abs(existing.width - region.width) < 20):
                return
        self._confirmed_regions.append(region)
        self.canvas.add_confirmed_region(region)
        self.clear_btn.setEnabled(True)
        self.mask_confirmed.emit(list(self._confirmed_regions))

    def remove_last_region(self):
        if self._confirmed_regions:
            self._confirmed_regions.pop()
            self.canvas.set_confirmed_regions(self._confirmed_regions)
        self.clear_btn.setEnabled(bool(self._confirmed_regions))
        self.mask_confirmed.emit(list(self._confirmed_regions))


class _Canvas(QLabel):
    """Paintable label that displays the frame and overlay graphics."""

    selection_changed = Signal(object)  # QRect or None
    video_dropped = Signal(str)  # file path

    SUPPORTED_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv",
                     ".png", ".jpg", ".jpeg", ".bmp", ".webp")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(400, 250)
        self.setObjectName("previewCanvas")

        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._candidates: list[DetectionRegion] = []

        # Manual selection
        self._selecting = False
        self._sel_start = QPoint()
        self._sel_end = QPoint()
        self._confirmed_regions: list[DetectionRegion] = []
        self._display_rect = QRect()
        self._scale = 1.0
        self._offset = QPoint()
        self._box_color = QColor("#00ff88")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_pixmap(self, pixmap: QPixmap):
        if pixmap_is_valid(pixmap):
            self._source = pixmap
        else:
            self._source = None
        # Timeline seeking changes only the source frame; keep confirmed boxes
        # so manual selection remains available across frame navigation.
        self._schedule_scale_update()

    def clear_all(self):
        """Clear image and all overlays."""
        self._source = None
        self._scaled = None
        self.clear()
        self._candidates = []
        self._confirmed_regions = []
        self._sel_start = QPoint()
        self._sel_end = QPoint()
        self._selecting = False
        self.selection_changed.emit(None)
        self.update()

    def _schedule_scale_update(self):
        """Re-scale after layout; handles pixmap set before widget is visible."""
        QTimer.singleShot(0, self._update_scaled)

    def set_candidates(self, regions: list[DetectionRegion]):
        self._candidates = regions
        self.update()

    def add_confirmed_region(self, region: DetectionRegion):
        """Add a confirmed region overlay in image coordinates."""
        self._confirmed_regions.append(region)
        self.update()

    def set_confirmed_regions(self, regions: list[DetectionRegion]):
        """Replace confirmed region overlays in image coordinates."""
        self._confirmed_regions = list(regions)
        self.update()

    def clear_selection(self):
        self._confirmed_regions = []
        self._candidates = []
        self._sel_start = QPoint()
        self._sel_end = QPoint()
        self._selecting = False
        self.selection_changed.emit(None)
        self.update()

    # ------------------------------------------------------------------
    # Scaling
    # ------------------------------------------------------------------

    def _update_scaled(self):
        if not pixmap_is_valid(self._source):
            self._scaled = None
            self.clear()
            self.update()
            return

        avail = self.size()
        if avail.width() <= 0 or avail.height() <= 0:
            return

        src_w = self._source.width()
        src_h = self._source.height()
        if src_w <= 0 or src_h <= 0:
            return

        scale = min(avail.width() / src_w, avail.height() / src_h)
        self._scale = scale

        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))
        self._scaled = self._source.scaled(
            new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # Compute display rect (centered)
        dx = (avail.width() - new_w) // 2
        dy = (avail.height() - new_h) // 2
        self._offset = QPoint(dx, dy)
        self._display_rect = QRect(dx, dy, new_w, new_h)
        self.update()

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def _to_image_coords(self, point: QPoint) -> QPoint:
        """Convert a canvas point to image pixel coordinates."""
        return QPoint(
            int((point.x() - self._offset.x()) / self._scale),
            int((point.y() - self._offset.y()) / self._scale),
        )

    def _to_canvas_rect(self, region: DetectionRegion) -> QRect:
        """Convert a DetectionRegion to canvas coordinates."""
        return QRect(
            int(region.x * self._scale) + self._offset.x(),
            int(region.y * self._scale) + self._offset.y(),
            int(region.width * self._scale),
            int(region.height * self._scale),
        )

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        # Lazy scale: catch any timing issue where source is set but scaled not
        if (self._source is not None and pixmap_is_valid(self._source)
                and (self._scaled is None or not pixmap_is_valid(self._scaled))):
            self._update_scaled()

        painter = QPainter(self)

        if not pixmap_is_valid(self._scaled):
            painter.setPen(QColor("#555"))
            font = QFont()
            font.setPointSize(14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "加载视频/图片后在此预览")
            painter.end()
            return

        painter.drawPixmap(self._offset, self._scaled)

        # Draw candidate regions (OCR / morphology)
        dash_pen = QPen(QColor("#ffcc00"), 2, Qt.DashLine)
        painter.setPen(dash_pen)
        for region in self._candidates:
            r = self._to_canvas_rect(region)
            painter.drawRect(r)

        # Draw confirmed regions
        solid_pen = QPen(self._box_color, 2, Qt.SolidLine)
        painter.setPen(solid_pen)
        for region in self._confirmed_regions:
            painter.drawRect(self._to_canvas_rect(region))

        # Draw current manual selection
        if self._selecting and not self._sel_start.isNull():
            sel_pen = QPen(self._box_color, 2, Qt.SolidLine)
            painter.setPen(sel_pen)
            r = QRect(self._sel_start, self._sel_end).normalized()
            # Draw semi-transparent fill
            fill = QColor(self._box_color)
            fill.setAlpha(40)
            painter.fillRect(r, fill)
            painter.drawRect(r)

        painter.end()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if not pixmap_is_valid(self._source):
                # Click empty canvas → browse for video
                self._browse_video()
                return
            pt = event.position().toPoint()
            if self._display_rect.contains(pt):
                self._selecting = True
                self._sel_start = pt
                self._sel_end = pt

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._selecting:
            self._sel_end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._sel_end = event.position().toPoint()

            r = QRect(self._sel_start, self._sel_end).normalized()
            if r.width() > 10 and r.height() > 10:
                self.selection_changed.emit(r)

                # Emit the region in image coordinates via parent
                img_p1 = self._to_image_coords(r.topLeft())
                img_p2 = self._to_image_coords(r.bottomRight())
                img_rect = QRect(img_p1, img_p2).normalized()

                if self.parent() and isinstance(self.parent(), PreviewPanel):
                    self.parent().confirm_current_region(DetectionRegion(
                        x=img_rect.x(),
                        y=img_rect.y(),
                        width=img_rect.width(),
                        height=img_rect.height(),
                        confidence=1.0,
                        method="manual",
                    ))

            self.update()

    # ------------------------------------------------------------------
    # Drag & drop (video files)
    # ------------------------------------------------------------------

    def _browse_video(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频 / 图片",
            "",
            "视频 / 图片 (*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.png *.jpg *.jpeg *.bmp *.webp);;全部文件 (*.*)",
        )
        if path:
            self.video_dropped.emit(path)

    def _is_supported(self, path: str) -> bool:
        return path.lower().endswith(self.SUPPORTED_EXTS)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for u in event.mimeData().urls():
                if self._is_supported(u.toLocalFile()):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event: QDropEvent):
        for u in event.mimeData().urls():
            path = u.toLocalFile()
            if self._is_supported(path):
                self.video_dropped.emit(path)
                event.acceptProposedAction()
                return

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._update_scaled()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_scaled()