"""Image watermark removal: load / save / detect / inpaint single images.

Reuses the same detector and inpainter as the video pipeline so behaviour
stays consistent.  All functions are Unicode-path safe on Windows.
"""

from __future__ import annotations

import os

import cv2
import numpy as np


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def is_image_file(path: str) -> bool:
    """Return True when the file extension looks like an image."""
    return path.lower().endswith(IMAGE_EXTS)


def load_image(path: str) -> np.ndarray:
    """Load an image as a BGR uint8 array (Unicode-path safe).

    Alpha channels are flattened (composited onto white) so the rest of the
    pipeline can treat every frame as plain 3-channel BGR.
    """
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        raise ValueError(f"\u6587\u4ef6\u4e3a\u7a7a\u6216\u65e0\u6cd5\u8bfb\u53d6: {path}")
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"\u65e0\u6cd5\u89e3\u7801\u56fe\u7247\u6587\u4ef6\uff08\u683c\u5f0f\u53ef\u80fd\u4e0d\u53d7\u652f\u6301\uff09: {path}")
    if image.ndim == 3 and image.shape[2] == 4:
        alpha = image[..., 3:4].astype(np.float32) / 255.0
        rgb = image[..., :3].astype(np.float32)
        image = (rgb * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(image)


def image_dimensions(path: str) -> tuple[int, int]:
    """Return (width, height) reading only the header (fast)."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            return int(img.width), int(img.height)
    except Exception:
        image = load_image(path)
        return int(image.shape[1]), int(image.shape[0])


def save_image(image: np.ndarray, output_path: str) -> str:
    """Save a BGR image using a codec picked from the output extension.

    JPEG / WebP use quality 95; PNG is lossless.  Returns the output path.
    """
    ext = os.path.splitext(output_path)[1].lower()
    params: list[int] = []
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    elif ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, 95]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]

    ok, encoded = cv2.imencode(ext if ext else ".png", image, params)
    if not ok:
        raise ValueError(f"\u56fe\u7247\u7f16\u7801\u5931\u8d25: {output_path}")
    encoded.tofile(output_path)
    return output_path


def refine_text_mask(frame: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """Keep only the text strokes inside the masked area (Canny + components).

    Returns None when nothing survives (caller should fall back to the raw
    mask).  This is shared with the video pipeline.
    """
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    x1 = max(0, int(xs.min()) - 2)
    y1 = max(0, int(ys.min()) - 2)
    x2 = min(frame.shape[1], int(xs.max()) + 3)
    y2 = min(frame.shape[0], int(ys.max()) + 3)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 80)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.dilate(edges, kernel, iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    clean = np.zeros_like(edges)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 40:
            clean[labels == i] = 255
    if clean.sum() == 0:
        return None
    result = np.zeros(frame.shape[:2], dtype=np.uint8)
    result[y1:y2, x1:x2] = clean
    result = cv2.bitwise_and(result, mask)
    if result.sum() == 0:
        return None
    return result


def enhance_frame(
    frame: np.ndarray,
    scale: float = 1.0,
    sharpen: bool = False,
    saturation: bool = False,
) -> np.ndarray:
    """Optional quality enhancement shared with the video pipeline."""
    out = frame
    if scale > 1.0:
        new_w = max(2, int(round(out.shape[1] * scale / 2) * 2))
        new_h = max(2, int(round(out.shape[0] * scale / 2) * 2))
        out = cv2.resize(out, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    if sharpen:
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        edge_strength = cv2.Canny(gray, 50, 150).sum() / max(gray.size, 1)
        if edge_strength > 0.1:
            kernel = np.array([[-0.3, -0.3, -0.3],
                               [-0.3, 3.4, -0.3],
                               [-0.3, -0.3, -0.3]])
        else:
            kernel = np.array([[-0.5, -0.5, -0.5],
                               [-0.5, 5.0, -0.5],
                               [-0.5, -0.5, -0.5]])
        out = cv2.filter2D(out, -1, kernel)
        out = np.clip(out, 0, 255).astype(np.uint8)
    if saturation:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        s = cv2.multiply(s, 1.1)
        s = np.clip(s, 0, 255).astype(np.uint8)
        out = cv2.merge([h, s, v])
        out = cv2.cvtColor(out, cv2.COLOR_HSV2BGR)
    return out


def process_image(
    image: np.ndarray,
    mask: np.ndarray,
    inpainter,
    fine_mask: bool = False,
    enhance: bool = False,
    enhance_scale: float = 1.0,
    enhance_sharpen: bool = False,
    enhance_saturation: bool = False,
) -> np.ndarray:
    """Inpaint a watermark mask on a single image, with optional extras."""
    effective_mask = mask
    if fine_mask:
        refined = refine_text_mask(image, mask)
        if refined is not None:
            effective_mask = refined
    fixed = inpainter.inpaint(image, effective_mask)
    if enhance:
        fixed = enhance_frame(
            fixed,
            scale=enhance_scale,
            sharpen=enhance_sharpen,
            saturation=enhance_saturation,
        )
    return fixed
