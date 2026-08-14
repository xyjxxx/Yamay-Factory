"""Tests for watermark detection and mask generation."""

from __future__ import annotations

import numpy as np
import pytest

from watermark_remover.core.detector import DetectionRegion, WatermarkDetector


class _FakeDetector:
    """Minimal stand-in for periodic re-detection tests."""

    def __init__(self, regions: list[DetectionRegion] | None = None):
        self._regions = regions or []

    def detect_with_method(self, frame: np.ndarray, method: str) -> list[DetectionRegion]:
        return list(self._regions)


def test_generate_mask_fills_regions():
    shape = (100, 200, 3)
    regions = [DetectionRegion(10, 20, 30, 15)]
    mask = WatermarkDetector.generate_mask(shape, regions, dilate_px=0)

    assert mask.shape == (100, 200)
    assert mask.dtype == np.uint8
    assert mask[20:35, 10:40].min() == 255
    assert mask[0, 0] == 0


def test_generate_mask_respects_padding_and_bounds():
    shape = (50, 50, 3)
    regions = [DetectionRegion(0, 0, 10, 10)]
    mask = WatermarkDetector.generate_mask(shape, regions, dilate_px=5)

    assert mask[0, 0] == 255
    assert mask[14, 14] == 255
    assert mask[20, 20] == 0


def test_pick_best_region():
    regions = [
        DetectionRegion(0, 0, 10, 10, confidence=0.3),
        DetectionRegion(5, 5, 10, 10, confidence=0.9),
    ]
    best = WatermarkDetector.pick_best_region(regions)
    assert best is not None
    assert best.confidence == 0.9


def test_pick_best_region_empty():
    assert WatermarkDetector.pick_best_region([]) is None


def test_merge_regions_removes_overlap():
    regions = [
        DetectionRegion(0, 0, 40, 20, confidence=0.9),
        DetectionRegion(5, 5, 40, 20, confidence=0.5),
        DetectionRegion(100, 100, 20, 20, confidence=0.7),
    ]
    merged = WatermarkDetector._merge_regions(regions)
    assert len(merged) == 2
    assert merged[0].confidence == 0.9


def test_iou_identical_regions():
    a = DetectionRegion(0, 0, 20, 20)
    b = DetectionRegion(0, 0, 20, 20)
    assert WatermarkDetector._iou(a, b) == pytest.approx(1.0)


def test_mask_for_frame_updates_when_detection_succeeds():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    fallback = np.zeros((80, 120), dtype=np.uint8)
    fallback[0:10, 0:10] = 255

    detector = _FakeDetector([DetectionRegion(50, 50, 20, 10, confidence=0.8)])
    mask = WatermarkDetector.mask_for_frame(detector, frame, "ocr", 2, fallback)

    assert mask[50:60, 50:70].min() == 255
    assert mask[0, 0] == 0


def test_mask_for_frame_keeps_fallback_when_detection_fails():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    fallback = np.zeros((80, 120), dtype=np.uint8)
    fallback[5:15, 5:15] = 255

    detector = _FakeDetector([])
    mask = WatermarkDetector.mask_for_frame(detector, frame, "ocr", 2, fallback)

    np.testing.assert_array_equal(mask, fallback)


def test_detect_morphology_on_synthetic_frame():
    detector = WatermarkDetector(use_ocr=False, use_morphology=True)
    frame = np.full((200, 300, 3), 180, dtype=np.uint8)
    # High-contrast text-like block near corner
    frame[10:30, 10:120] = 20

    regions = detector.detect_morphology(frame)
    assert isinstance(regions, list)


def test_detect_ocr_accepts_easyocr_horizontal_boxes(monkeypatch):
    class FakeReader:
        def detect(self, frame):
            return ([[[220, 295, 170, 195]]], [])

    detector = WatermarkDetector(use_ocr=True)
    detector._ocr_reader = FakeReader()
    frame = np.full((200, 300, 3), 180, dtype=np.uint8)

    regions = detector.detect_ocr(frame)

    assert len(regions) == 1
    assert regions[0].rect == (220, 170, 75, 25)
