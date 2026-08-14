"""Tests for settings panel logic (requires Qt)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from watermark_remover.ui.settings_panel import SettingsPanel

_app = None


@pytest.fixture(scope="module")
def qapp():
    global _app
    if QApplication.instance() is None:
        _app = QApplication([])
    else:
        _app = QApplication.instance()
    return _app


@pytest.fixture
def panel(qapp):
    return SettingsPanel()


def test_redetect_interval_frames(panel):
    panel.redetect_combo.setCurrentIndex(0)
    assert panel.redetect_interval_frames(30.0) == 0

    panel.redetect_combo.setCurrentIndex(1)
    assert panel.redetect_interval_frames(30.0) == 30

    panel.redetect_combo.setCurrentIndex(4)
    assert panel.redetect_interval_frames(24.0) == 120


def test_manual_mode_disables_redetect(panel):
    panel.redetect_combo.setCurrentIndex(2)
    panel.radio_manual.setChecked(True)
    panel._on_detect_method_changed(2)

    assert panel.redetect_combo.isEnabled() is False
    assert panel.redetect_interval_frames(30.0) == 0


def test_detection_options_do_not_include_auto(panel):
    assert not hasattr(panel, "radio_auto")
    assert panel.detection_method == "ocr"
