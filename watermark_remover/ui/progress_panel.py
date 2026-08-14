"""Progress panel: bottom bar with progress bar and log output."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class ProgressPanel(QFrame):
    """Bottom panel: progress bar + collapsible log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._log_expanded = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Progress bar row
        bar_row = QHBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("就绪")
        bar_row.addWidget(self.progress_bar, stretch=1)

        self.status_label = QLabel("等待加载视频…")
        self.status_label.setObjectName("infoLabel")
        bar_row.addWidget(self.status_label)

        self.toggle_log_btn = QPushButton("日志")
        self.toggle_log_btn.setObjectName("secondaryBtn")
        self.toggle_log_btn.setFixedWidth(80)
        self.toggle_log_btn.clicked.connect(self._toggle_log)
        bar_row.addWidget(self.toggle_log_btn)

        layout.addLayout(bar_row)

        # Log area (collapsible)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setVisible(False)
        layout.addWidget(self.log_text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_progress(self, pct: int, message: str = ""):
        """Update progress bar and emit a log entry."""
        self.progress_bar.setValue(pct)
        if message:
            self.progress_bar.setFormat(f"{message[:60]}")
            self._log(message)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_error(self, message: str):
        self.progress_bar.setFormat("错误")
        self.status_label.setText("处理失败")
        self._log(f"错误: {message}")

    def set_finished(self, output_path: str):
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("完成！")
        self.status_label.setText("处理完成")
        self._log(f"完成！输出: {output_path}")

    def reset(self):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("就绪")
        self.status_label.setText("等待加载视频…")
        self.log_text.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {message}")

    def _toggle_log(self):
        self._log_expanded = not self._log_expanded
        self.log_text.setVisible(self._log_expanded)
        self.toggle_log_btn.setText("隐藏日志" if self._log_expanded else "日志")
