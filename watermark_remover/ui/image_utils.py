"""Shared helpers for converting frames to Qt pixmaps."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage, QPixmap


def pixmap_is_valid(pixmap: QPixmap | None) -> bool:
    """Return True if pixmap can be drawn."""
    return pixmap is not None and not pixmap.isNull() and pixmap.width() > 0 and pixmap.height() > 0


def ndarray_to_pixmap(arr: np.ndarray) -> QPixmap:
    """Convert an RGB numpy array (H, W, 3) uint8 to QPixmap.

    Copies pixel data so the pixmap remains valid after the array is freed.
    """
    if arr is None or arr.size == 0:
        return QPixmap()

    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"Expected RGB image (H, W, 3), got shape {arr.shape}")

    rgb = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = rgb.shape
    bytes_per_line = 3 * w
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())
