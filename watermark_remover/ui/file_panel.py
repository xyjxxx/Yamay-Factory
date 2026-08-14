"""File picker panel with drag-and-drop support."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from watermark_remover.core.image_processor import image_dimensions, is_image_file
from watermark_remover.core.video_io import VideoInfo, get_video_info


class _DropZone(QFrame):
    """Drag-and-drop target; click to open file dialog."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setMinimumHeight(156)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点击选择，或把视频/图片拖到这里")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class FilePanel(QFrame):
    """Left-side panel: drag-drop zone + video file info."""

    video_loaded = Signal(str, VideoInfo)  # file_path, video_info
    image_loaded = Signal(str)  # file_path
    batch_queue_changed = Signal(int)  # queue size

    VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv")
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")
    SUPPORTED_EXTS = VIDEO_EXTS + IMAGE_EXTS

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAcceptDrops(True)
        self._current_path: str | None = None
        self._batch_queue: list[str] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # -- Title --
        title = QLabel("视频 / 图片文件")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # -- Drop zone --
        self.drop_zone = _DropZone()
        self.drop_zone.clicked.connect(self._on_browse)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setAlignment(Qt.AlignCenter)

        self.drop_icon = QLabel("VIDEO")
        self.drop_icon.setObjectName("dropIcon")
        self.drop_icon.setAlignment(Qt.AlignCenter)
        self.drop_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        self.drop_icon.setFont(font)
        drop_layout.addWidget(self.drop_icon)

        self.drop_label = QLabel("点击选择，或把视频/图片拖到这里")
        self.drop_label.setObjectName("dropLabel")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setWordWrap(True)
        self.drop_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        drop_layout.addWidget(self.drop_label)

        layout.addWidget(self.drop_zone)

        # -- Browse button --
        btn_layout = QHBoxLayout()
        self.browse_btn = QPushButton("选择视频 / 图片")
        self.browse_btn.clicked.connect(self._on_browse)
        btn_layout.addWidget(self.browse_btn)
        layout.addLayout(btn_layout)

        # -- File info area --
        self.info_frame = QFrame()
        self.info_frame.setObjectName("panel")
        self.info_frame.setVisible(False)
        info_layout = QVBoxLayout(self.info_frame)
        info_layout.setSpacing(4)

        info_title = QLabel("文件信息")
        info_title.setObjectName("sectionTitle")
        info_layout.addWidget(info_title)

        self.lbl_name = QLabel("")
        self.lbl_name.setObjectName("valueLabel")
        self.lbl_name.setWordWrap(True)
        info_layout.addWidget(self.lbl_name)

        self.lbl_res = QLabel("")
        self.lbl_res.setObjectName("valueLabel")
        info_layout.addWidget(self.lbl_res)

        self.lbl_fps = QLabel("")
        self.lbl_fps.setObjectName("valueLabel")
        info_layout.addWidget(self.lbl_fps)

        self.lbl_dur = QLabel("")
        self.lbl_dur.setObjectName("valueLabel")
        info_layout.addWidget(self.lbl_dur)

        self.lbl_frames = QLabel("")
        self.lbl_frames.setObjectName("valueLabel")
        info_layout.addWidget(self.lbl_frames)

        layout.addWidget(self.info_frame)

        # -- Batch queue --
        batch_title = QLabel("批量队列")
        batch_title.setObjectName("sectionTitle")
        layout.addWidget(batch_title)

        self.batch_list = QListWidget()
        self.batch_list.setMaximumHeight(120)
        self.batch_list.itemDoubleClicked.connect(self._on_batch_item_activated)
        layout.addWidget(self.batch_list)

        batch_btn_row = QHBoxLayout()
        self.add_batch_btn = QPushButton("添加到队列")
        self.add_batch_btn.clicked.connect(self._on_add_batch)
        batch_btn_row.addWidget(self.add_batch_btn)

        self.clear_batch_btn = QPushButton("清空队列")
        self.clear_batch_btn.setObjectName("secondaryBtn")
        self.clear_batch_btn.clicked.connect(self._clear_batch)
        batch_btn_row.addWidget(self.clear_batch_btn)
        layout.addLayout(batch_btn_row)

        self.batch_hint = QLabel("队列: 0 个待处理")
        self.batch_hint.setObjectName("infoLabel")
        layout.addWidget(self.batch_hint)

        # Spacer
        layout.addStretch()

    # ------------------------------------------------------------------
    # Drag & Drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for u in urls:
                path = u.toLocalFile()
                if self._is_supported(path):
                    event.acceptProposedAction()
                    self.drop_zone.setStyleSheet(
                        "QFrame#dropZone{border:2px solid #3a5af0;"
                        "background-color:#1a1a36;border-radius:12px;}"
                    )
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.drop_zone.setStyleSheet("")
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self.drop_zone.setStyleSheet("")
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if self._is_supported(u.toLocalFile())
        ]
        if not paths:
            return

        self._load_file(paths[0])
        if len(paths) > 1:
            self.add_to_batch(paths[1:])
        event.acceptProposedAction()

    @staticmethod
    def _is_supported(path: str) -> bool:
        return path.lower().endswith(FilePanel.SUPPORTED_EXTS)

    def add_to_batch(self, paths: list[str]) -> int:
        """Add unique video paths to the batch queue. Returns count added."""
        added = 0
        for path in paths:
            if not self._is_supported(path):
                continue
            if path == self._current_path or path in self._batch_queue:
                continue
            self._batch_queue.append(path)
            added += 1
        if added:
            self._refresh_batch_list()
        return added

    def get_all_paths_for_batch(self) -> list[str]:
        """Return current video plus queued paths for sequential batch processing."""
        paths: list[str] = []
        if self._current_path:
            paths.append(self._current_path)
        for path in self._batch_queue:
            if path not in paths:
                paths.append(path)
        return paths

    def remove_from_batch(self, path: str):
        if path in self._batch_queue:
            self._batch_queue.remove(path)
            self._refresh_batch_list()

    def clear_batch(self):
        self._clear_batch()

    def clear_current_video(self):
        """Clear the selected video and its displayed metadata."""
        self._current_path = None
        for label in (self.lbl_name, self.lbl_res, self.lbl_fps, self.lbl_dur, self.lbl_frames):
            label.clear()
        self.info_frame.setVisible(False)

    def _refresh_batch_list(self):
        self.batch_list.clear()
        for path in self._batch_queue:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.batch_list.addItem(item)
        count = len(self._batch_queue)
        self.batch_hint.setText(f"队列: {count} 个待处理")
        self.batch_queue_changed.emit(count)

    def _clear_batch(self):
        self._batch_queue.clear()
        self._refresh_batch_list()

    def _on_add_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加批量视频 / 图片",
            "",
            "视频 / 图片 (*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.png *.jpg *.jpeg *.bmp *.webp);;全部文件 (*.*)",
        )
        if paths:
            self.add_to_batch(paths)

    def _on_batch_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path:
            self._load_file(path)
            self.remove_from_batch(path)

    # ------------------------------------------------------------------
    # File browsing
    # ------------------------------------------------------------------

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频 / 图片",
            "",
            "视频 / 图片 (*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.png *.jpg *.jpeg *.bmp *.webp);;全部文件 (*.*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        """Route a file to the video or image loader."""
        if is_image_file(path):
            self._load_image(path)
        else:
            self._load_video(path)

    def _load_video(self, path: str):
        """Parse video metadata and emit signal."""
        try:
            info = get_video_info(path)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "打开失败", f"无法读取视频文件:\n{e}")
            return

        self._current_path = path

        # Update info labels
        fname = os.path.basename(path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        self.lbl_name.setText(f"{fname}  ({size_mb:.1f} MB)")
        self.lbl_res.setText(f"分辨率: {info.width} × {info.height}")
        self.lbl_fps.setText(f"帧率: {info.fps:.2f} fps")
        self.lbl_dur.setText(f"时长: {info.duration_str}")
        self.lbl_frames.setText(f"总帧数: {info.total_frames}")
        self.info_frame.setVisible(True)

        self.video_loaded.emit(path, info)

    def _load_image(self, path: str):
        """Show image metadata and emit the image_loaded signal."""
        try:
            width, height = image_dimensions(path)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "打开失败", f"无法读取图片文件:\n{e}")
            return

        self._current_path = path
        size_mb = os.path.getsize(path) / (1024 * 1024)
        self.lbl_name.setText(f"{os.path.basename(path)}  ({size_mb:.2f} MB)")
        self.lbl_res.setText(f"分辨率: {width} ? {height}")
        self.lbl_fps.setText("类型: 图片")
        self.lbl_dur.setText("")
        self.lbl_frames.setText("")
        self.info_frame.setVisible(True)

        self.image_loaded.emit(path)
