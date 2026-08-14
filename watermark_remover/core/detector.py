"""Watermark detection using OCR and morphological methods.

Detection strategies (tried in order):
1. OCR text detection (EasyOCR) — best for crisp text watermarks
2. Overlay detection — multi-scale background subtraction for semi-transparent watermarks
3. Morphological edge analysis — fallback for logos / graphic watermarks
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys
from typing import Optional

import numpy as np


@dataclass
class DetectionRegion:
    """A detected watermark candidate region."""

    x: int
    y: int
    width: int
    height: int
    confidence: float = 0.0
    method: str = ""  # "ocr" | "overlay" | "morphology" | "manual"

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Return as (x, y, w, h) tuple."""
        return (self.x, self.y, self.width, self.height)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Return as (x1, y1, x2, y2) tuple."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def expanded(self, padding: int = 8) -> DetectionRegion:
        """Return a new region with padding on all sides."""
        return DetectionRegion(
            x=max(0, self.x - padding),
            y=max(0, self.y - padding),
            width=self.width + 2 * padding,
            height=self.height + 2 * padding,
            confidence=self.confidence,
            method=self.method,
        )


class WatermarkDetector:
    """Detect watermark regions in a video frame.

    Detection strategies (tried in order of reliability):
    1. Overlay detection — for semi-transparent watermarks (doubao/douyin)
    2. OCR text detection (EasyOCR) — for crisp text watermarks
    3. Morphological edge analysis — fallback for graphic watermarks

    NOTE: EasyOCR's readtext() may segfault with certain PyTorch versions.
    We only use detect() (CRAFT text detector) which is safer.
    """

    def __init__(self, use_ocr: bool = True, use_morphology: bool = True, gpu: bool = False):
        self._use_ocr = use_ocr
        self._use_morphology = use_morphology
        self._gpu = gpu
        self._ocr_reader = None

    def _init_ocr(self):
        """Lazy-load EasyOCR reader (slow first import).

        CAUTION: EasyOCR + PyTorch may segfault on some Windows systems
        when calling readtext(). We only use detect() which uses CRAFT
        and appears stable.
        """
        if self._ocr_reader is None:
            try:
                import easyocr
                self._ocr_reader = easyocr.Reader(
                    ["ch_sim", "en"],
                    gpu=self._gpu,
                    verbose=False,
                    model_storage_directory=self._easyocr_model_dir(),
                    download_enabled=False,
                )
            except ImportError:
                self._use_ocr = False
                self._ocr_reader = None

    @staticmethod
    def _easyocr_model_dir() -> str:
        """Return bundled EasyOCR models; never download at application runtime."""
        if getattr(sys, "frozen", False):
            root = sys._MEIPASS
        else:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(root, "models", "easyocr")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, frame: np.ndarray) -> list[DetectionRegion]:
        """Detect all candidate watermark regions in a frame.

        Tries overlay detection first (best for semi-transparent watermarks),
        then OCR, then morphological analysis.
        """
        results: list[DetectionRegion] = []

        # 1. Overlay detection — target semi-transparent overlays
        results.extend(self.detect_overlay(frame))

        # 2. OCR text detection — for crisp text
        if self._use_ocr:
            results.extend(self.detect_ocr(frame))

        # 3. Morphological — fallback
        if self._use_morphology and len(results) == 0:
            results.extend(self.detect_morphology(frame))

        # Merge overlapping regions
        return self._merge_regions(results)

    def detect_with_method(self, frame: np.ndarray, method: str) -> list[DetectionRegion]:
        """Run detection using a specific method name."""
        if method == "ocr":
            return self.detect_ocr(frame)
        if method == "morphology":
            return self.detect_morphology(frame)
        if method == "overlay":
            return self.detect_overlay(frame)
        if method == "manual":
            return []
        return self.detect(frame)

    @staticmethod
    def pick_best_region(regions: list[DetectionRegion]) -> DetectionRegion | None:
        """Return the highest-confidence region, or None."""
        if not regions:
            return None
        return max(regions, key=lambda r: r.confidence)

    @staticmethod
    def mask_for_frame(
        detector: WatermarkDetector,
        frame: np.ndarray,
        method: str,
        mask_padding: int,
        fallback_mask: np.ndarray,
    ) -> np.ndarray:
        """Re-detect watermark on a frame; keep fallback mask if detection fails."""
        regions = detector.detect_with_method(frame, method)
        best = WatermarkDetector.pick_best_region(regions)
        if best is None:
            return fallback_mask
        return WatermarkDetector.generate_mask(
            frame.shape,
            [best],
            dilate_px=mask_padding,
        )

    # ------------------------------------------------------------------
    # Detection: Semi-transparent overlay
    # ------------------------------------------------------------------

    def detect_overlay(self, frame: np.ndarray) -> list[DetectionRegion]:
        """Detect semi-transparent watermark overlays via background subtraction.

        Semi-transparent watermarks (like doubao/douyin) are overlaid with
        a constant alpha, creating a consistent local difference from the
        background. Multi-scale Gaussian background subtraction reveals them.

        This is the PRIMARY detection method — it works without OCR/ML models.
        """
        import cv2

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        # ── Multi-scale background subtraction ───────────────────
        # Small sigma catches fine text edges; large sigma catches
        # broader overlay regions. Merge all scales.
        all_diff = np.zeros_like(gray)
        for sigma in [15, 31]:
            ksize = sigma | 1  # ensure odd
            bg = cv2.GaussianBlur(gray, (ksize, ksize), 0)
            diff = cv2.absdiff(gray.astype(np.float32), bg.astype(np.float32))
            diff = np.clip(diff * 3.0, 0, 255).astype(np.uint8)
            all_diff = cv2.bitwise_or(all_diff, diff)

        # ── Threshold ────────────────────────────────────────────
        _, binary = cv2.threshold(all_diff, 12, 255, cv2.THRESH_BINARY)

        # ── Horizontal grouping (text lines) ─────────────────────
        # Use a wide horizontal kernel to connect nearby characters
        # on the same text line, but keep height small to avoid
        # merging with unrelated content above/below.
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
        grouped = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_h, iterations=1)

        # Small vertical dilation to fill character strokes
        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        grouped = cv2.dilate(grouped, kernel_v, iterations=1)

        # ── Find contours ────────────────────────────────────────
        contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results: list[DetectionRegion] = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area_ratio = (cw * ch) / (w * h)

            # Filter by area
            if area_ratio < 0.0003 or area_ratio > 0.25:
                continue

            # Filter by position: near any edge
            near_top    = y < h * 0.35
            near_bottom = (y + ch) > h * 0.60
            near_left   = x < w * 0.35
            near_right  = (x + cw) > w * 0.60

            if not (near_top or near_bottom or near_left or near_right):
                continue

            # Compute confidence based on position, size, and aspect ratio
            center_x = x + cw / 2
            center_y = y + ch / 2

            # Right side is most common for watermarks
            right_score = 1.2 if center_x > w * 0.55 else (1.0 if center_x > w * 0.4 else 0.6)
            # Bottom is very common
            bottom_score = 1.2 if center_y > h * 0.7 else (1.0 if center_y > h * 0.5 else 0.7)
            # Aspect: watermark text is wide
            aspect = cw / max(ch, 1)
            aspect_score = min(1.2, max(0.5, aspect / 5.0))
            # Size preference: 0.5%-5% of frame is typical
            size_score = 1.0 if 0.005 < area_ratio < 0.08 else 0.6

            confidence = 0.4 + 0.6 * (
                right_score * 0.35 + bottom_score * 0.25 +
                aspect_score * 0.20 + size_score * 0.20
            )

            results.append(DetectionRegion(
                x=x, y=y, width=cw, height=ch,
                confidence=min(0.95, confidence),
                method="overlay",
            ))

        return results

    # ------------------------------------------------------------------
    # Detection: OCR text
    # ------------------------------------------------------------------

    def detect_ocr(self, frame: np.ndarray) -> list[DetectionRegion]:
        """Use EasyOCR's CRAFT text detector to find text regions.

        Only uses detect() — NOT readtext() — because readtext()
        may segfault with certain PyTorch versions on Windows.

        Watermarks are typically text near edges / corners.
        """
        self._init_ocr()
        if self._ocr_reader is None:
            return []

        import cv2

        h, w = frame.shape[:2]
        raw_boxes: list[tuple[int, int, int, int]] = []

        # A low-opacity watermark often has too little contrast for the
        # detector on the original frame.  CLAHE keeps local text contrast
        # while avoiding the harsh noise introduced by a global threshold.
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        try:
            detections = self._ocr_reader.detect(enhanced)
        except Exception:
            return []

        if detections is None or len(detections) == 0:
            return []

        boxes_list = detections[0] if isinstance(detections, (list, tuple)) else detections

        for box in boxes_list:
            # EasyOCR horizontal boxes are [x_min, x_max, y_min, y_max],
            # whereas free-form boxes are point quadrilaterals.  Treating
            # the former as points made the old code discard every result.
            pts = np.asarray(box)
            if pts.size == 4 and (pts.ndim == 1 or 1 in pts.shape):
                x1, x2, y1, y2 = (int(v) for v in pts.reshape(-1))
            elif pts.ndim == 2 and pts.shape[1] >= 2:
                x1 = int(pts[:, 0].min())
                y1 = int(pts[:, 1].min())
                x2 = int(pts[:, 0].max())
                y2 = int(pts[:, 1].max())
            else:
                continue

            x1, x2 = sorted((max(0, x1), min(w, x2)))
            y1, y2 = sorted((max(0, y1), min(h, y2)))

            bw, bh = x2 - x1, y2 - y1
            area_ratio = (bw * bh) / (w * h)

            # Skip implausible sizes
            if area_ratio < 0.0002 or area_ratio > 0.25:
                continue

            # Must be near an edge
            near_top    = y1 < h * 0.35
            near_bottom = y2 > h * 0.60
            near_left   = x1 < w * 0.35
            near_right  = x2 > w * 0.60

            if not (near_top or near_bottom or near_left or near_right):
                continue

            raw_boxes.append((x1, y1, x2, y2))

        # ── Group nearby boxes into text-line regions ──────────────
        raw_boxes.sort(key=lambda b: (b[1], b[0]))
        merged: list[tuple[int, int, int, int]] = []
        used = [False] * len(raw_boxes)

        for i, (x1, y1, x2, y2) in enumerate(raw_boxes):
            if used[i]:
                continue
            gx1, gy1, gx2, gy2 = x1, y1, x2, y2
            for j in range(i + 1, len(raw_boxes)):
                if used[j]:
                    continue
                ox1, oy1, ox2, oy2 = raw_boxes[j]
                char_w = (gx2 - gx1) if (gx2 - gx1) > 0 else 20
                if (abs(ox1 - gx2) < char_w * 2.5 and
                        abs((oy1 + oy2) // 2 - (gy1 + gy2) // 2) < 30):
                    gx2 = max(gx2, ox2)
                    gy1 = min(gy1, oy1)
                    gy2 = max(gy2, oy2)
                    used[j] = True
            used[i] = True
            merged.append((gx1, gy1, gx2, gy2))

        # ── Score each merged region ───────────────────────────────
        results: list[DetectionRegion] = []
        for x1, y1, x2, y2 in merged:
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue

            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2

            right_bias = 1.2 if center_x > w * 0.5 else 0.7
            edge_bias = 1.0 if (center_y < h * 0.2 or center_y > h * 0.8) else 0.7
            size_score = min(1.0, max(0.3, (bw * bh) / (w * h * 0.02)))

            confidence = 0.5 + 0.5 * (right_bias * 0.4 + edge_bias * 0.3 + size_score * 0.3)

            results.append(DetectionRegion(
                x=x1, y=y1, width=bw, height=bh,
                confidence=min(0.99, confidence),
                method="ocr",
            ))

        return results

    # ------------------------------------------------------------------
    # Detection: Morphological edge analysis
    # ------------------------------------------------------------------

    def detect_morphology(self, frame: np.ndarray) -> list[DetectionRegion]:
        """Fallback morphological detector for graphic/logos watermarks.

        Uses edge detection and contour analysis. Only activated when
        overlay and OCR detectors return nothing.
        """
        import cv2

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        # ── Multi-scale Canny edge detection ──────────────────
        edges_soft = cv2.Canny(gray, 25, 80)
        edges_hard = cv2.Canny(gray, 50, 140)
        edges = cv2.bitwise_or(edges_soft, edges_hard)

        # Moderate dilation — smaller kernel to avoid over-connecting
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
        dilated = cv2.dilate(edges, kernel, iterations=1)
        dilated = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results: list[DetectionRegion] = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area_ratio = (cw * ch) / (w * h)

            if area_ratio < 0.0003 or area_ratio > 0.30:
                continue

            near_edge = (
                y < h * 0.30 or (y + ch) > h * 0.65 or
                x < w * 0.30 or (x + cw) > w * 0.65
            )
            if not near_edge:
                continue

            roi = edges[y:y + ch, x:x + cw]
            edge_density = np.count_nonzero(roi) / (cw * ch) if cw * ch > 0 else 0
            if edge_density < 0.04:
                continue

            results.append(DetectionRegion(
                x=x, y=y, width=cw, height=ch,
                confidence=min(0.65, edge_density * 2.5),
                method="morphology",
            ))

        return results

    # ------------------------------------------------------------------
    # Mask generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_mask(
        frame_shape: tuple[int, int, int],
        regions: list[DetectionRegion],
        dilate_px: int = 8,
    ) -> np.ndarray:
        """Create a binary mask from detection regions.

        Args:
            frame_shape: (H, W, C) of the video frame.
            regions: list of confirmed watermark regions.
            dilate_px: extra padding around each region.

        Returns:
            Binary mask (H, W) as uint8, 255 = watermark area.
        """
        mask = np.zeros(frame_shape[:2], dtype=np.uint8)

        for region in regions:
            padded = region.expanded(dilate_px)
            x1, y1, x2, y2 = padded.bbox
            # Clamp to frame bounds
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame_shape[1], x2)
            y2 = min(frame_shape[0], y2)
            mask[y1:y2, x1:x2] = 255

        return mask

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_regions(
        regions: list[DetectionRegion],
        iou_threshold: float = 0.3,
    ) -> list[DetectionRegion]:
        """Merge overlapping detection regions using simple greedy NMS."""
        if len(regions) <= 1:
            return regions

        # Sort by confidence descending
        regions = sorted(regions, key=lambda r: r.confidence, reverse=True)
        kept: list[DetectionRegion] = []

        for r in regions:
            overlaps = False
            for k in kept:
                if WatermarkDetector._iou(r, k) > iou_threshold:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(r)

        return kept

    @staticmethod
    def _iou(a: DetectionRegion, b: DetectionRegion) -> float:
        """Intersection over Union of two regions."""
        ax1, ay1, ax2, ay2 = a.bbox
        bx1, by1, bx2, by2 = b.bbox

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0

        inter = (ix2 - ix1) * (iy2 - iy1)
        area_a = a.width * a.height
        area_b = b.width * b.height
        union = area_a + area_b - inter

        return inter / union if union > 0 else 0.0
