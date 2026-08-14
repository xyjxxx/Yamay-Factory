"""Settings panel: detection method, inpainting method, output options."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class SettingsPanel(QFrame):
    """Right-side panel with all processing settings."""

    mask_padding_changed = Signal(int)
    analyze_temporal_requested = Signal()
    open_preferences_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumWidth(292)
        self.setMaximumWidth(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("处理设置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # -- Detection method --
        detect_group = QGroupBox("水印检测")
        detect_layout = QVBoxLayout(detect_group)

        self.detect_group = QButtonGroup(self)
        self.radio_ocr = QRadioButton("OCR 文字检测")
        self.radio_ocr.setChecked(True)
        self.radio_morph = QRadioButton("形态学边缘检测")
        self.radio_manual = QRadioButton("手动框选")
        self.radio_temporal = QRadioButton("时序追踪（四角扫描）")
        self.radio_temporal.setToolTip("自动分析水印在视频不同时间段的角落位置，适合豆包等跳动水印")
        self.detect_group.addButton(self.radio_ocr, 0)
        self.detect_group.addButton(self.radio_morph, 1)
        self.detect_group.addButton(self.radio_manual, 2)
        self.detect_group.addButton(self.radio_temporal, 3)

        detect_layout.addWidget(self.radio_ocr)
        detect_layout.addWidget(self.radio_morph)
        detect_layout.addWidget(self.radio_manual)
        detect_layout.addWidget(self.radio_temporal)
        layout.addWidget(detect_group)

        # -- Periodic re-detection --
        redetect_layout = QHBoxLayout()
        redetect_layout.addWidget(QLabel("重检测"))
        self.redetect_combo = QComboBox()
        self.redetect_combo.addItems([
            "关闭",
            "每 30 帧",
            "每 60 帧",
            "每 120 帧",
            "每 5 秒",
        ])
        self.redetect_combo.setCurrentIndex(0)
        self.redetect_combo.setToolTip("处理过程中周期性重新检测水印位置，应对水印漂移")
        redetect_layout.addWidget(self.redetect_combo)
        redetect_layout.addStretch()
        layout.addLayout(redetect_layout)

        self.detect_group.idClicked.connect(self._on_detect_method_changed)
        self._on_detect_method_changed(self.detect_group.checkedId())

        # -- Inpainting method --
        inpaint_group = QGroupBox("修复方法")
        inpaint_layout = QVBoxLayout(inpaint_group)

        self.inpaint_group = QButtonGroup(self)
        self.radio_cv = QRadioButton("OpenCV（快速，纯CPU）")
        self.radio_cv.setChecked(True)
        self.radio_lama = QRadioButton("LaMa（高质量，需下载模型）")
        self.inpaint_group.addButton(self.radio_lama, 0)
        self.inpaint_group.addButton(self.radio_cv, 1)

        inpaint_layout.addWidget(self.radio_lama)
        inpaint_layout.addWidget(self.radio_cv)
        layout.addWidget(inpaint_group)

        # -- Mask padding + fine mask --
        pad_layout = QHBoxLayout()
        pad_layout.addWidget(QLabel("边缘扩展"))
        self.pad_spin = QSpinBox()
        self.pad_spin.setRange(0, 50)
        self.pad_spin.setValue(8)
        self.pad_spin.setSuffix(" px")
        self.pad_spin.valueChanged.connect(self.mask_padding_changed.emit)
        pad_layout.addWidget(self.pad_spin)
        pad_layout.addStretch()
        layout.addLayout(pad_layout)

        self.fine_mask_check = QCheckBox("精细文字掩码（Canny）")
        self.fine_mask_check.setToolTip("只修复文字笔画，不破坏纯色背景")
        layout.addWidget(self.fine_mask_check)

        # -- Temporal region table --
        self.temporal_group = QGroupBox("时序水印区域")
        temporal_layout = QVBoxLayout(self.temporal_group)
        btn_row = QHBoxLayout()
        self.analyze_temporal_btn = QPushButton("自动分析")
        self.analyze_temporal_btn.setObjectName("compactBtn")
        self.analyze_temporal_btn.clicked.connect(self.analyze_temporal_requested.emit)
        btn_row.addWidget(self.analyze_temporal_btn)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("compactBtn")
        add_btn.clicked.connect(self.add_empty_row)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(self.remove_selected_row)
        btn_row.addWidget(del_btn)
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.clicked.connect(self.clear_temporal_regions)
        btn_row.addWidget(clear_btn)
        temporal_layout.addLayout(btn_row)

        self.temporal_table = QTableWidget(0, 7)
        self.temporal_table.setHorizontalHeaderLabels([
            "开始(s)", "结束(s)", "X", "Y", "宽", "高", "角落",
        ])
        self.temporal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.temporal_table.verticalHeader().setVisible(False)
        self.temporal_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.temporal_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.temporal_table.setMinimumHeight(120)
        temporal_layout.addWidget(self.temporal_table)
        layout.addWidget(self.temporal_group)

        # -- Output & quality (configured in the preferences dialog) --
        out_group = QGroupBox("输出与画质")
        out_layout = QVBoxLayout(out_group)
        hint = QLabel("输出位置、视频质量、画质增强等设置已移至左上角「设置」中统一调整。")
        hint.setWordWrap(True)
        hint.setObjectName("infoLabel")
        out_layout.addWidget(hint)
        open_prefs_btn = QPushButton("打开设置")
        open_prefs_btn.setObjectName("compactBtn")
        open_prefs_btn.clicked.connect(self.open_preferences_requested.emit)
        out_layout.addWidget(open_prefs_btn)
        layout.addWidget(out_group)

        # -- Action buttons --
        self.preview_btn = QPushButton("预览修复效果")
        self.preview_btn.setObjectName("secondaryBtn")
        layout.addWidget(self.preview_btn)

        self.process_btn = QPushButton("开始处理")
        layout.addWidget(self.process_btn)

        self.cancel_btn = QPushButton("取消处理")
        self.cancel_btn.setObjectName("dangerBtn")
        self.cancel_btn.setEnabled(False)
        layout.addWidget(self.cancel_btn)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_available_methods(self, ocr: bool, lama: bool, cuda: bool = False):
        """Enable/disable method radios based on what's actually installed."""
        if not ocr:
            self.radio_ocr.setEnabled(False)
            self.radio_ocr.setText("OCR 文字检测（不可用）")
            if self.radio_ocr.isChecked():
                self.radio_morph.setChecked(True)
        if not lama:
            self.radio_lama.setEnabled(False)
            self.radio_lama.setText("LaMa（未安装 torch）")
            if self.radio_lama.isChecked():
                self.radio_cv.setChecked(True)
        elif cuda:
            self.radio_lama.setText("LaMa（GPU 加速）")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def detection_method(self) -> str:
        mid = self.detect_group.checkedId()
        return {0: "ocr", 1: "morphology", 2: "manual", 3: "temporal"}.get(mid, "ocr")

    @property
    def inpainting_method(self) -> str:
        mid = self.inpaint_group.checkedId()
        return {0: "lama", 1: "opencv"}.get(mid, "lama")

    @property
    def mask_padding(self) -> int:
        return self.pad_spin.value()

    @property
    def fine_mask_enabled(self) -> bool:
        return self.fine_mask_check.isChecked()

    def redetect_interval_frames(self, fps: float = 30.0) -> int:
        """Return re-detection interval in frames (0 = disabled)."""
        idx = self.redetect_combo.currentIndex()
        if idx == 0:
            return 0
        if idx == 1:
            return 30
        if idx == 2:
            return 60
        if idx == 3:
            return 120
        return max(1, int(fps * 5))

    def set_processing_mode(self, processing: bool):
        """Toggle UI state during processing."""
        self.preview_btn.setEnabled(not processing)
        self.process_btn.setEnabled(not processing)
        self.cancel_btn.setEnabled(processing)
        self.analyze_temporal_btn.setEnabled(not processing)

    # ------------------------------------------------------------------
    # Temporal region table
    # ------------------------------------------------------------------

    def set_temporal_regions(self, regions: list[dict]):
        self.temporal_table.setRowCount(len(regions))
        for row, region in enumerate(regions):
            values = [
                f"{region.get('start_sec', 0):.2f}",
                f"{region.get('end_sec', 0):.2f}",
                str(region.get("x", 0)),
                str(region.get("y", 0)),
                str(region.get("w", 0)),
                str(region.get("h", 0)),
                str(region.get("corner", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                self.temporal_table.setItem(row, col, item)

    def temporal_regions(self) -> list[dict]:
        regions = []
        for row in range(self.temporal_table.rowCount()):
            try:
                start = float(self.temporal_table.item(row, 0).text())
                end = float(self.temporal_table.item(row, 1).text())
                x = int(self.temporal_table.item(row, 2).text())
                y = int(self.temporal_table.item(row, 3).text())
                w = int(self.temporal_table.item(row, 4).text())
                h = int(self.temporal_table.item(row, 5).text())
            except (AttributeError, ValueError):
                continue
            corner_item = self.temporal_table.item(row, 6)
            regions.append({
                "start_sec": start,
                "end_sec": end,
                "x": x,
                "y": y,
                "w": max(w, 1),
                "h": max(h, 1),
                "corner": corner_item.text() if corner_item else "",
            })
        return regions

    def add_empty_row(self):
        row = self.temporal_table.rowCount()
        self.temporal_table.insertRow(row)
        defaults = ["0.00", "1.00", "0", "0", "100", "60", "右下"]
        for col, value in enumerate(defaults):
            self.temporal_table.setItem(row, col, QTableWidgetItem(value))

    def remove_selected_row(self):
        row = self.temporal_table.currentRow()
        if row >= 0:
            self.temporal_table.removeRow(row)

    def clear_temporal_regions(self):
        self.temporal_table.setRowCount(0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_detect_method_changed(self, button_id: int):
        no_redetect = button_id in (2, 3)
        self.redetect_combo.setEnabled(not no_redetect)
        if no_redetect:
            self.redetect_combo.setCurrentIndex(0)

