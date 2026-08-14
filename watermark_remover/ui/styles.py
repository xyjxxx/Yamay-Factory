"""QSS stylesheet -- teal cinematic glass theme for the watermark remover."""

DARK_STYLE = r"""
/* ===== App shell ===== */
QMainWindow {
    background-color: #031312;
    color: #ecfeff;
    font-family: "Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "Segoe UI", sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: transparent;
    color: #ecfeff;
}

/* ===== Dialogs ===== */
QDialog, QMessageBox {
    background-color: #03231f;
    color: #ecfeff;
}

/* ===== Check Boxes ===== */
QCheckBox {
    spacing: 9px;
    padding: 4px 0;
    color: #ccfbf1;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 2px solid rgba(125, 211, 204, 150);
    background-color: rgba(4, 47, 43, 210);
}
QCheckBox::indicator:checked {
    border-color: #5eead4;
    background-color: #0d9488;
}
QCheckBox:disabled {
    color: #668a86;
}

/* ===== Menu Bar ===== */
QMenuBar {
    background-color: rgba(2, 24, 22, 220);
    padding: 4px 8px;
    border-bottom: 1px solid rgba(45, 212, 191, 98);
}
QMenuBar::item {
    padding: 7px 14px;
    background: transparent;
    border-radius: 8px;
    color: #c7eee8;
}
QMenuBar::item:selected {
    background-color: rgba(20, 184, 166, 58);
    color: #ffffff;
}
QMenu {
    background-color: rgba(3, 35, 32, 244);
    border: 1px solid rgba(94, 234, 212, 118);
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 32px 8px 22px;
    border-radius: 7px;
    color: #d7fffa;
}
QMenu::item:selected {
    background-color: #0d9488;
    color: #ffffff;
}

/* ===== Buttons ===== */
QPushButton {
    min-height: 36px;
    background-color: #0d9488;
    color: #ffffff;
    border: 2px solid rgba(94, 234, 212, 96);
    border-radius: 10px;
    padding: 8px 18px;
    font-weight: 700;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #2dd4bf;
    border-color: rgba(153, 246, 228, 170);
}
QPushButton:pressed {
    background-color: #0f766e;
}
QPushButton:focus {
    border-color: #ffffff;
}
QPushButton:disabled {
    background-color: rgba(51, 65, 85, 132);
    color: #6d928d;
    border-color: rgba(125, 211, 204, 48);
}


QPushButton#compactBtn {
    min-height: 32px;
    background-color: rgba(6, 78, 71, 194);
    color: #ccfbf1;
    border: 2px solid rgba(45, 212, 191, 96);
    border-radius: 10px;
    padding: 6px 10px;
    font-weight: 700;
    font-size: 12px;
}
QPushButton#compactBtn:hover {
    background-color: rgba(13, 108, 98, 218);
    border-color: rgba(94, 234, 212, 154);
}
QPushButton#compactBtn:focus {
    border-color: #ffffff;
}

QPushButton#secondaryBtn {
    background-color: rgba(6, 78, 71, 194);
    color: #ccfbf1;
    border: 1px solid rgba(45, 212, 191, 96);
}
QPushButton#secondaryBtn:hover {
    background-color: rgba(13, 108, 98, 218);
    border-color: rgba(94, 234, 212, 154);
}

QPushButton#dangerBtn {
    background-color: #e11d48;
    border-color: rgba(251, 113, 133, 120);
    color: #ffffff;
}
QPushButton#dangerBtn:hover {
    background-color: #fb4266;
}

/* ===== File drop zone ===== */
QFrame#dropZone {
    border: 1px dashed rgba(94, 234, 212, 138);
    border-radius: 18px;
    background-color: rgba(2, 34, 31, 138);
    padding: 22px;
}
QFrame#dropZone:hover {
    border: 1px solid rgba(45, 212, 191, 212);
    background-color: rgba(6, 78, 71, 158);
}
QLabel#dropLabel {
    color: #c7eee8;
    font-size: 13px;
    font-weight: 500;
}
QLabel#dropIcon {
    color: #5eead4;
    font-size: 22px;
    letter-spacing: 2px;
}

/* ===== Panels ===== */
QFrame#panel {
    background-color: rgba(5, 43, 39, 164);
    border: 1px solid rgba(45, 212, 191, 88);
    border-radius: 16px;
    padding: 14px;
}

QFrame#panel:hover {
    border-color: rgba(94, 234, 212, 132);
}

QLabel#sectionTitle {
    color: #ccfbf1;
    font-size: 12px;
    font-weight: 800;
    padding-top: 4px;
    padding-bottom: 3px;
}

QLabel#infoLabel {
    color: #a7d8d0;
    font-size: 12px;
}
QLabel#valueLabel {
    color: #f0fdfa;
    font-size: 12px;
}

/* ===== Preview boards ===== */
QLabel#previewCanvas, QLabel#resultCanvas {
    background-color: rgba(1, 22, 20, 122);
    border: 1px solid rgba(45, 212, 191, 58);
    border-radius: 14px;
    color: #8fbdb5;
}

/* ===== Group Box ===== */
QGroupBox {
    border: 1px solid rgba(45, 212, 191, 82);
    border-radius: 14px;
    margin-top: 12px;
    padding: 16px 10px 10px 10px;
    font-weight: 700;
    color: #ccfbf1;
    background-color: rgba(2, 30, 27, 96);
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #99f6e4;
}

/* ===== Radio Buttons ===== */
QRadioButton {
    spacing: 9px;
    padding: 5px 0;
    color: #ccfbf1;
}
QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border-radius: 9px;
    border: 2px solid rgba(125, 211, 204, 150);
    background-color: rgba(4, 47, 43, 210);
}
QRadioButton::indicator:checked {
    border-color: #5eead4;
    background-color: #0d9488;
}
QRadioButton:disabled {
    color: #668a86;
}

/* ===== Inputs ===== */
QLineEdit, QComboBox, QSpinBox {
    min-height: 32px;
    background-color: rgba(3, 45, 41, 190);
    color: #ecfeff;
    border: 1px solid rgba(45, 212, 191, 86);
    border-radius: 10px;
    padding: 5px 10px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 2px solid #ffffff;
    padding: 4px 9px;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #042f2e;
    color: #ecfeff;
    border: 1px solid rgba(94, 234, 212, 128);
    selection-background-color: #0d9488;
    selection-color: #ffffff;
    outline: none;
}

/* ===== Lists ===== */
QListWidget {
    background-color: rgba(2, 29, 27, 156);
    color: #ccfbf1;
    border: 1px solid rgba(45, 212, 191, 74);
    border-radius: 12px;
    padding: 6px;
}
QListWidget::item {
    padding: 7px 8px;
    border-radius: 8px;
}
QListWidget::item:selected {
    background-color: rgba(13, 148, 136, 178);
    color: #ffffff;
}

/* ===== Progress Bar ===== */
QProgressBar {
    background-color: rgba(2, 29, 27, 180);
    border: 1px solid rgba(45, 212, 191, 76);
    border-radius: 8px;
    height: 22px;
    text-align: center;
    color: #d7fffa;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar::chunk {
    background-color: #14b8a6;
    border-radius: 7px;
}

/* ===== Text Edit / Log ===== */
QTextEdit, QPlainTextEdit {
    background-color: rgba(1, 22, 20, 212);
    color: #c7eee8;
    border: 1px solid rgba(45, 212, 191, 76);
    border-radius: 12px;
    padding: 8px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 11px;
}

/* ===== Sliders ===== */
QSlider::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background: rgba(125, 211, 204, 110);
}
QSlider::sub-page:horizontal {
    background: #2dd4bf;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #2dd4bf;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: #ccfbf1;
    border-color: #5eead4;
}
QSlider:disabled::groove:horizontal {
    background: rgba(71, 85, 105, 120);
}
QSlider:disabled::handle:horizontal {
    background: #668a86;
    border-color: #315f5a;
}

/* ===== Scrollbar ===== */
QScrollBar:vertical {
    background: rgba(4, 47, 43, 120);
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: rgba(94, 234, 212, 126);
    border-radius: 5px;
    min-height: 34px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(153, 246, 228, 178);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: rgba(4, 47, 43, 120);
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: rgba(94, 234, 212, 126);
    border-radius: 5px;
    min-width: 34px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: rgba(45, 212, 191, 86);
    width: 6px;
    height: 6px;
    border-radius: 3px;
}
QSplitter::handle:hover {
    background-color: rgba(94, 234, 212, 166);
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #042f2e;
    color: #ecfeff;
    border: 1px solid #2dd4bf;
    border-radius: 8px;
    padding: 6px 9px;
}

/* ===== Tabs, if used later ===== */
QTabWidget::pane {
    border: 1px solid rgba(45, 212, 191, 88);
    background-color: rgba(5, 43, 39, 164);
    border-radius: 12px;
}
QTabBar::tab {
    background-color: rgba(4, 47, 43, 180);
    color: #86c9c0;
    padding: 8px 18px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background-color: rgba(6, 78, 71, 220);
    color: #ffffff;
}
"""
