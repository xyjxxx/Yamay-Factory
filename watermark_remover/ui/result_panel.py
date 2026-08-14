"""Repair result preview for a single frame or a playable processed video."""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from watermark_remover.core.video_io import VideoReader, get_video_info
from watermark_remover.ui.image_utils import ndarray_to_pixmap, pixmap_is_valid


class ResultPanel(QFrame):
    """Show the repaired current frame or the completed output video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        self._preview_pixmap: QPixmap | None = None
        self._video_path: str | None = None
        self._video_reader: VideoReader | None = None
        self._video_info = None
        self._video_frame_no = 0
        self._playing = False
        self._playback_timer = QTimer(self)
        self._playback_timer.timeout.connect(self._on_playback_tick)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("修复预览")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.canvas = _ResultCanvas(self)
        self.canvas.setMinimumHeight(200)
        layout.addWidget(self.canvas, stretch=1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.setObjectName("compactBtn")
        self.play_btn.setFixedWidth(64)
        self.play_btn.setEnabled(False)
        self.play_btn.setToolTip("播放 / 暂停处理完成的视频")
        self.play_btn.clicked.connect(self._toggle_playback)
        controls.addWidget(self.play_btn)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 0)
        self.time_slider.setEnabled(False)
        self.time_slider.setToolTip("定位处理完成的视频")
        self.time_slider.sliderReleased.connect(self._seek_video)
        controls.addWidget(self.time_slider, stretch=1)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setObjectName("infoLabel")
        self.time_label.setFixedWidth(100)
        self.time_label.setAlignment(Qt.AlignCenter)
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        self.hint = QLabel("点击“预览修复效果”后显示当前帧的修复结果")
        self.hint.setObjectName("infoLabel")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

    def set_before(self, pixmap: QPixmap):
        """Compatibility hook; the result panel intentionally shows repaired output only."""
        if self._video_path is None and self._preview_pixmap is None:
            self.canvas.set_pixmap(pixmap)

    def set_after(self, pixmap: QPixmap):
        """Show the repaired version of the frame currently displayed above."""
        self._stop_video()
        self._video_path = None
        self._video_info = None
        self._preview_pixmap = pixmap if pixmap_is_valid(pixmap) else None
        self.canvas.set_pixmap(self._preview_pixmap)
        self.play_btn.setEnabled(False)
        self.time_slider.setRange(0, 0)
        self.time_slider.setEnabled(False)
        self.time_label.setText("--:-- / --:--")
        if self._preview_pixmap is not None:
            self.hint.setText("当前帧修复效果")

    def set_video(self, path: str):
        """Load a completed output video and make it playable in the result area."""
        self._stop_video()
        self._preview_pixmap = None
        self._video_path = path
        try:
            self._video_info = get_video_info(path)
            total_frames = max(0, int(self._video_info.total_frames))
            self.time_slider.setRange(0, max(0, total_frames - 1))
            self.time_slider.setEnabled(total_frames > 0)
            self.play_btn.setEnabled(total_frames > 0)
            self._video_frame_no = 0
            self._read_video_frame(0)
            self.hint.setText("处理完成的视频（可播放）")
        except Exception:
            self._video_path = None
            self._video_info = None
            self.canvas.set_pixmap(None)
            self.play_btn.setEnabled(False)
            self.time_slider.setRange(0, 0)
            self.time_slider.setEnabled(False)
            self.hint.setText("处理完成后将在这里显示视频")

    def _toggle_playback(self):
        if not self._video_path or not self._video_info:
            return
        if self._playing:
            self._stop_video()
            return

        self._video_reader = VideoReader(self._video_path)
        fps = self._video_info.fps if self._video_info.fps > 0 else 30.0
        self._video_reader.open(seek_seconds=self._video_frame_no / fps)
        self._playing = True
        self.play_btn.setText("暂停")
        self._playback_timer.start(max(16, int(1000 / fps)))

    def _stop_video(self):
        self._playing = False
        self._playback_timer.stop()
        if self._video_reader is not None:
            try:
                self._video_reader.close()
            except Exception:
                pass
            self._video_reader = None
        self.play_btn.setText("播放")

    def _on_playback_tick(self):
        if not self._video_reader:
            return
        frame = self._video_reader.read_frame()
        if frame is None:
            self._stop_video()
            self._video_frame_no = max(0, int(self._video_info.total_frames) - 1)
            self._read_video_frame(self._video_frame_no)
            return
        self._video_frame_no = min(
            self._video_frame_no + 1,
            max(0, int(self._video_info.total_frames) - 1),
        )
        self.canvas.set_pixmap(ndarray_to_pixmap(frame))
        self._update_video_controls()

    def _read_video_frame(self, frame_no: int):
        if not self._video_path:
            return
        reader = VideoReader(self._video_path)
        try:
            fps = self._video_info.fps if self._video_info and self._video_info.fps > 0 else 30.0
            reader.open(seek_seconds=max(0, frame_no) / fps)
            frame = reader.read_frame()
            if frame is not None:
                self._video_frame_no = max(0, frame_no)
                self.canvas.set_pixmap(ndarray_to_pixmap(frame))
                self._update_video_controls()
        finally:
            reader.close()

    def _seek_video(self):
        if not self._video_path:
            return
        was_playing = self._playing
        self._stop_video()
        self._read_video_frame(self.time_slider.value())
        if was_playing:
            self._toggle_playback()

    def _update_video_controls(self):
        total = int(self._video_info.total_frames) if self._video_info else 0
        fps = self._video_info.fps if self._video_info and self._video_info.fps > 0 else 30.0
        self.time_slider.blockSignals(True)
        self.time_slider.setValue(self._video_frame_no)
        self.time_slider.blockSignals(False)
        self.time_label.setText(
            f"{self._fmt_time(self._video_frame_no / fps)} / {self._fmt_time(total / fps)}"
        )

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        minutes, seconds = divmod(int(seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def clear_images(self):
        """Clear the preview and stop any output-video playback."""
        self._stop_video()
        self._preview_pixmap = None
        self._video_path = None
        self._video_info = None
        self.canvas.set_pixmap(None)
        self.time_slider.setRange(0, 0)
        self.time_slider.setEnabled(False)
        self.play_btn.setEnabled(False)
        self.time_label.setText("--:-- / --:--")
        self.hint.setText("点击“预览修复效果”后显示当前帧的修复结果")


class _ResultCanvas(QLabel):
    """Display one repaired frame without an interactive comparison divider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 180)
        self.setObjectName("resultCanvas")
        self.setAlignment(Qt.AlignCenter)

        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._offset = QPoint()

    def set_pixmap(self, pixmap: QPixmap | None):
        self._source = pixmap if pixmap_is_valid(pixmap) else None
        self._schedule_scale_update()

    def _schedule_scale_update(self):
        QTimer.singleShot(0, self._update_scaled)

    def _update_scaled(self):
        if not pixmap_is_valid(self._source):
            self._scaled = None
            self.update()
            return
        avail = self.size()
        if avail.width() <= 0 or avail.height() <= 0:
            return
        scale = min(avail.width() / self._source.width(), avail.height() / self._source.height())
        new_w = max(1, int(self._source.width() * scale))
        new_h = max(1, int(self._source.height() * scale))
        self._scaled = self._source.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._offset = QPoint((avail.width() - new_w) // 2, (avail.height() - new_h) // 2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not pixmap_is_valid(self._scaled):
            painter.setPen(QColor("#555"))
            painter.drawText(self.rect(), Qt.AlignCenter, "点击“预览修复效果”或完成处理后查看结果")
            painter.end()
            return
        painter.drawPixmap(self._offset, self._scaled)
        painter.end()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._update_scaled()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_scaled()