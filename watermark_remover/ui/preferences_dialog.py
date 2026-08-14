"""Application preferences dialog."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


NAME_TEMPLATE_PRESETS = [
    "{name}_无水印.{ext}",
    "{name}_clean.{ext}",
    "{date}_{name}.{ext}",
    "{name}_{date}.{ext}",
]

CONFLICT_RULES = [
    ("自动重命名", "auto_rename"),
    ("覆盖原文件", "overwrite"),
    ("每次询问", "ask"),
]

QUALITY_ITEMS = ["高 (CRF 18)", "标准 (CRF 23)", "小文件 (CRF 28)"]


class PreferencesDialog(QDialog):
    """Small settings window for default output, quality, GPU, and background."""

    def __init__(self, values: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(600)
        self._box_color = str(values.get("box_color", "#00ff88"))
        self._setup_ui(values)

    def _setup_ui(self, values: dict):
        root = QVBoxLayout(self)
        root.setSpacing(14)

        output_group = QGroupBox("输出设置")
        output_form = QFormLayout(output_group)

        self.output_path = QLineEdit(values.get("output_directory", ""))
        self.output_path.setReadOnly(True)
        self.output_path.setPlaceholderText("未选择时，自动保存到原文件旁边的“去水印视频/图片”文件夹")
        output_form.addRow("默认保存地址", self._path_row(
            self.output_path,
            "选择",
            self._browse_output_directory,
            "清空",
            self._clear_output_directory,
        ))

        # Editable filename template: presets + free typing.
        self.name_template_combo = QComboBox()
        self.name_template_combo.setEditable(True)
        self.name_template_combo.setInsertPolicy(QComboBox.NoInsert)
        for preset in NAME_TEMPLATE_PRESETS:
            self.name_template_combo.addItem(preset)
        current = values.get("name_template", "")
        if current:
            self.name_template_combo.setCurrentText(current)
        else:
            self.name_template_combo.setCurrentText(NAME_TEMPLATE_PRESETS[0])
        output_form.addRow("文件命名模板", self.name_template_combo)
        name_hint = QLabel(
            "可自由编辑，支持占位符："
            "{name} 原文件名、{date} 日期、{time} 时间、{ext} 扩展名"
        )
        name_hint.setWordWrap(True)
        name_hint.setObjectName("infoLabel")
        output_form.addRow("", name_hint)

        self.conflict_combo = QComboBox()
        for label, value in CONFLICT_RULES:
            self.conflict_combo.addItem(label, value)
        self._set_combo_by_data(self.conflict_combo, values.get("conflict_rule", "auto_rename"))
        output_form.addRow("文件已存在时", self.conflict_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITY_ITEMS)
        self.quality_combo.setCurrentIndex(int(values.get("quality_index", 1)))
        output_form.addRow("默认输出质量", self.quality_combo)
        root.addWidget(output_group)

        # -- Quality enhancement (moved from the right-hand processing panel) --
        enhance_group = QGroupBox("画质增强")
        enhance_layout = QVBoxLayout(enhance_group)
        self.enhance_check = QCheckBox("启用画质增强（超分/锐化/饱和度）")
        self.enhance_check.setChecked(bool(values.get("enhance_enabled", False)))
        enhance_layout.addWidget(self.enhance_check)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("超分倍率"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["1.0x（原分辨率）", "1.25x", "1.5x"])
        self.scale_combo.setCurrentIndex(int(values.get("enhance_scale_index", 0)))
        scale_layout.addWidget(self.scale_combo)
        scale_layout.addStretch()
        enhance_layout.addLayout(scale_layout)

        self.sharpen_check = QCheckBox("内容自适应锐化")
        self.sharpen_check.setChecked(bool(values.get("enhance_sharpen", True)))
        enhance_layout.addWidget(self.sharpen_check)

        self.saturation_check = QCheckBox("饱和度增强 (+10%)")
        self.saturation_check.setChecked(bool(values.get("enhance_saturation", False)))
        enhance_layout.addWidget(self.saturation_check)

        self.auto_crf_check = QCheckBox("自动 CRF（按分辨率）")
        self.auto_crf_check.setChecked(bool(values.get("auto_crf", False)))
        enhance_layout.addWidget(self.auto_crf_check)

        self.enhance_check.toggled.connect(self._sync_enhance_controls)
        self._sync_enhance_controls(self.enhance_check.isChecked())
        root.addWidget(enhance_group)

        performance_group = QGroupBox("性能设置")
        performance_layout = QVBoxLayout(performance_group)
        self.gpu_check = QCheckBox("启用 GPU 加速")
        self.gpu_check.setChecked(bool(values.get("gpu_enabled", False)))
        if not values.get("has_cuda", False):
            self.gpu_check.setChecked(False)
            self.gpu_check.setEnabled(False)
            self.gpu_check.setText("启用 GPU 加速（当前设备未检测到 CUDA）")
        performance_layout.addWidget(self.gpu_check)
        root.addWidget(performance_group)

        background_group = QGroupBox("背景设置")
        background_layout = QVBoxLayout(background_group)
        self.background_check = QCheckBox("启用动态/图片背景")
        self.background_check.setChecked(bool(values.get("background_enabled", True)))
        self.background_check.toggled.connect(self._sync_background_controls)
        background_layout.addWidget(self.background_check)

        self.background_path = QLineEdit(values.get("background_image_path", ""))
        self.background_path.setReadOnly(True)
        self.background_path.setPlaceholderText("未选择图片时，使用默认动态背景")
        background_layout.addWidget(QLabel("自定义背景图"))
        background_layout.addLayout(self._path_row(
            self.background_path,
            "选择图片",
            self._browse_background_image,
            "使用默认动态背景",
            self._clear_background_image,
        ))

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("选区方框颜色"))
        self.box_color_btn = QPushButton()
        self.box_color_btn.setObjectName("compactBtn")
        self.box_color_btn.setFixedWidth(96)
        self.box_color_btn.clicked.connect(self._pick_box_color)
        self._update_box_color_btn()
        color_row.addWidget(self.box_color_btn)
        color_row.addStretch()
        background_layout.addLayout(color_row)
        root.addWidget(background_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._sync_background_controls(self.background_check.isChecked())

    def values(self) -> dict:
        return {
            "output_directory": self.output_path.text().strip(),
            "name_template": self.name_template_combo.currentText().strip() or NAME_TEMPLATE_PRESETS[0],
            "conflict_rule": self.conflict_combo.currentData(),
            "quality_index": self.quality_combo.currentIndex(),
            "enhance_enabled": self.enhance_check.isChecked(),
            "enhance_scale_index": self.scale_combo.currentIndex(),
            "enhance_sharpen": self.sharpen_check.isChecked(),
            "enhance_saturation": self.saturation_check.isChecked(),
            "auto_crf": self.auto_crf_check.isChecked(),
            "background_enabled": self.background_check.isChecked(),
            "background_image_path": self.background_path.text().strip(),
            "box_color": self._box_color,
            "gpu_enabled": self.gpu_check.isChecked(),
        }

    def _path_row(self, line_edit: QLineEdit, browse_text: str, browse_slot, clear_text: str, clear_slot):
        row = QHBoxLayout()
        row.addWidget(line_edit, 1)
        browse_btn = QPushButton(browse_text)
        browse_btn.setObjectName("compactBtn")
        browse_btn.clicked.connect(browse_slot)
        row.addWidget(browse_btn)
        clear_btn = QPushButton(clear_text)
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.clicked.connect(clear_slot)
        row.addWidget(clear_btn)
        return row

    def _browse_output_directory(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "选择默认保存文件夹",
            self.output_path.text() or "",
        )
        if path:
            self.output_path.setText(path)

    def _clear_output_directory(self):
        self.output_path.clear()

    def _browse_background_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择背景图片",
            self.background_path.text() or "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if path:
            self.background_path.setText(path)
            self.background_check.setChecked(True)

    def _clear_background_image(self):
        self.background_path.clear()

    def _pick_box_color(self):
        color = QColorDialog.getColor(QColor(self._box_color), self, "选择选区方框颜色")
        if color.isValid():
            self._box_color = color.name()
            self._update_box_color_btn()

    def _update_box_color_btn(self):
        color = QColor(self._box_color)
        self.box_color_btn.setText(self._box_color)
        self.box_color_btn.setStyleSheet(
            f"background-color: {self._box_color}; color: {'#ffffff' if color.lightness() < 128 else '#000000'};"
        )

    def _sync_background_controls(self, enabled: bool):
        self.background_path.setEnabled(enabled)

    def _sync_enhance_controls(self, enabled: bool):
        self.scale_combo.setEnabled(enabled)
        self.sharpen_check.setEnabled(enabled)
        self.saturation_check.setEnabled(enabled)
        self.auto_crf_check.setEnabled(enabled)

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: str):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
