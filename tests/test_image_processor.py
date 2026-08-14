"""Tests for image watermark removal (load / save / inpaint / refine / enhance)."""

from __future__ import annotations

import os

import cv2
import numpy as np
import pytest

from watermark_remover.core.image_processor import (
    enhance_frame,
    is_image_file,
    load_image,
    process_image,
    refine_text_mask,
    save_image,
)


def _gradient_image(size: int = 200) -> np.ndarray:
    """Smooth blue-to-green gradient so inpainting can interpolate cleanly."""
    x = np.linspace(60, 220, size, dtype=np.uint8)
    y = np.linspace(40, 200, size, dtype=np.uint8)
    xx, yy = np.meshgrid(x, y)
    image = np.stack([xx, yy, np.full_like(xx, 120)], axis=-1).astype(np.uint8)
    return np.ascontiguousarray(image)


def test_is_image_file():
    assert is_image_file("a.PNG")
    assert is_image_file("b.webp")
    assert not is_image_file("c.mp4")


def test_load_save_roundtrip(tmp_path):
    image = _gradient_image(64)
    # Use a non-ASCII directory to exercise the Unicode-safe path handling.
    folder = tmp_path / "图片"  # ??
    folder.mkdir()
    out = str(folder / "美工.png")  # ??.png
    save_image(image, out)
    loaded = load_image(out)
    assert loaded.shape == image.shape
    assert loaded.dtype == np.uint8
    diff = np.abs(loaded.astype(int) - image.astype(int)).mean()
    assert diff < 1.0


def test_save_jpeg_webp(tmp_path):
    image = _gradient_image(64)
    for name in ("out.jpg", "out.webp"):
        path = str(tmp_path / name)
        save_image(image, path)
        assert os.path.getsize(path) > 0
        loaded = load_image(path)
        assert loaded.shape == image.shape


def test_process_image_removes_solid_watermark():
    image = _gradient_image(200)
    # Solid red watermark block on the smooth gradient.
    x0, y0, w, h = 80, 90, 40, 24
    image[y0:y0 + h, x0:x0 + w] = (0, 0, 255)

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    mask[y0:y0 + h, x0:x0 + w] = 255

    from watermark_remover.core.inpainter import Inpainter
    inpainter = Inpainter(method="opencv", device="cpu")
    result = process_image(image, mask, inpainter)

    region_before = image[y0:y0 + h, x0:x0 + w].astype(int)
    region_after = result[y0:y0 + h, x0:x0 + w].astype(int)
    # The watermark was solid red: blue channel close to 0 before.
    assert region_before[..., 0].mean() < 30
    # After inpainting the blue channel should be reconstructed (not pure red).
    assert region_after[..., 0].mean() > 80
    # Red channel should drop substantially toward the gradient background.
    assert region_after[..., 2].mean() < 200


def test_refine_text_mask_keeps_strokes_only():
    image = _gradient_image(120)
    # Draw text-like strokes + a large filled square inside the mask.
    image[50:58, 40:80] = (0, 0, 0)          # horizontal stroke
    image[50:90, 55:62] = (0, 0, 0)          # vertical stroke (L shape)
    image[30:45, 30:45] = (255, 255, 255)    # solid block (edge only survives)

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    mask[25:95, 25:85] = 255

    refined = refine_text_mask(image, mask)
    assert refined is not None
    # Refined mask must be a subset of the original mask.
    assert refined.shape == mask.shape
    assert np.all(refined <= mask)
    # Some of the stroke pixels should remain.
    assert refined[50:58, 40:80].sum() > 0


def test_enhance_frame_upscales():
    image = _gradient_image(100)
    out = enhance_frame(image, scale=1.5, sharpen=True, saturation=True)
    assert out.shape[0] == 150 and out.shape[1] == 150
    assert out.dtype == np.uint8
