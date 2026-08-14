"""Tests for the temporal watermark tracker region-building logic."""

from __future__ import annotations

from watermark_remover.core.temporal_tracker import TemporalWatermarkTracker


def _tracker(**kwargs) -> TemporalWatermarkTracker:
    defaults = dict(match_threshold=0.45, min_run_seconds=0.25)
    defaults.update(kwargs)
    return TemporalWatermarkTracker(**defaults)


def test_build_regions_extends_boundary_frames():
    """A strong run grows into weaker transitional frames at the same spot."""
    t = _tracker()
    matches = [
        {"t": 0.0, "score": 0.30, "x": 100, "y": 100},
        {"t": 0.5, "score": 0.50, "x": 600, "y": 1200},
        {"t": 1.0, "score": 0.95, "x": 610, "y": 1210},
        {"t": 1.5, "score": 0.92, "x": 608, "y": 1208},
        {"t": 2.0, "score": 0.40, "x": 612, "y": 1212},
        {"t": 2.5, "score": 0.25, "x": 700, "y": 1300},
    ]
    regions = t._build_regions(matches, tw=90, th=55, frame_w=720, frame_h=1280)
    assert len(regions) == 1
    assert abs(regions[0].start_sec - 0.5) < 1e-6
    assert abs(regions[0].end_sec - 2.0) < 1e-6
    assert regions[0].corner == "右下"


def test_build_regions_drops_weak_single_sample():
    """An isolated weak match is treated as scene noise and dropped."""
    t = _tracker()
    matches = [
        {"t": 0.0, "score": 0.46, "x": 600, "y": 1200},
        {"t": 0.5, "score": 0.30, "x": 610, "y": 1210},
    ]
    regions = t._build_regions(matches, tw=90, th=55, frame_w=720, frame_h=1280)
    assert regions == []


def test_build_regions_keeps_confident_single_sample():
    """A very confident single sample survives (short watermark stay)."""
    t = _tracker()
    matches = [
        {"t": 3.0, "score": 0.95, "x": 600, "y": 1200},
    ]
    regions = t._build_regions(matches, tw=90, th=55, frame_w=720, frame_h=1280)
    assert len(regions) == 1
    assert abs(regions[0].start_sec - 3.0) < 1e-6
    assert abs(regions[0].end_sec - 3.0) < 1e-6
    assert regions[0].corner == "右下"


def test_template_threshold_stricter_than_run_threshold():
    t = _tracker()
    assert t._template_threshold() >= t.match_threshold
