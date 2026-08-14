"""Image inpainting for watermark removal.

Supports two backends:
- **LaMa** (Large Mask Inpainting): state-of-the-art, via torch.hub or simple_lama.
- **OpenCV**: fast CPU inpainting (Telea algorithm), no model download needed.
"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Optional

import numpy as np


def _restore_env(environ: dict, saved: dict):
    """Restore environment variables to their original values."""
    for key, val in saved.items():
        if val is None:
            environ.pop(key, None)
        else:
            environ[key] = val


class Inpainter:
    """Remove watermarks from video frames using inpainting.

    LaMa is preferred for quality; falls back to OpenCV if torch is unavailable
    or if the user explicitly chooses the OpenCV backend.
    """

    def __init__(self, method: str = "lama", device: str = "cpu"):
        """
        Args:
            method: "lama" or "opencv".
            device: "cpu" or "cuda" (for LaMa only).
        """
        if method not in ("lama", "opencv"):
            raise ValueError(f"Unknown inpainting method: {method}")

        self.method = method
        self.device = device
        self._lama_model: object | None = None
        self._lama_available: bool | None = None  # tri-state: None = not checked

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inpaint(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Inpaint the masked area in a single frame.

        Args:
            frame: RGB image (H, W, 3) as numpy uint8.
            mask: Binary mask (H, W) as numpy uint8, 255 = area to inpaint.

        Returns:
            Inpainted RGB image (H, W, 3).
        """
        if self.method == "lama":
            return self._inpaint_lama(frame, mask)
        else:
            return self._inpaint_opencv(frame, mask)

    def is_lama_available(self) -> bool:
        """Check whether LaMa (PyTorch) is usable — cheap import check."""
        if self._lama_available is not None:
            return self._lama_available

        try:
            import torch  # noqa: F401
            self._lama_available = True
        except ImportError:
            self._lama_available = False

        return self._lama_available

    def try_init_lama(self, timeout: float = 25.0) -> bool:
        """Actually try to load the LaMa model. Returns True on success.

        Call this from the main thread BEFORE handing the inpainter
        to a background thread — torch models are not thread-safe.

        Uses a timeout to avoid hanging when GitHub is unreachable
        (common in mainland China).
        """
        if self._lama_model is not None:
            return True

        if not self.is_lama_available():
            return False

        import concurrent.futures

        def _load():
            try:
                self._init_lama()
                return self._lama_model is not None
            except Exception:
                return False

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_load)
                return future.result(timeout=timeout)
        except (concurrent.futures.TimeoutError, Exception):
            self._lama_available = False
            return False

    # ------------------------------------------------------------------
    # Backend: OpenCV
    # ------------------------------------------------------------------

    @staticmethod
    def _inpaint_opencv(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """OpenCV Telea inpainting. Fast, no GPU needed."""
        import cv2

        # Ensure correct types
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        mask_u8 = mask.astype(np.uint8)

        result = cv2.inpaint(frame_bgr, mask_u8, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
        return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)

    # ------------------------------------------------------------------
    # Backend: LaMa
    # ------------------------------------------------------------------

    @staticmethod
    def _bundled_model_root() -> str:
        """Return the bundled model root in dev and PyInstaller builds."""
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "models")
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "models",
        )

    def _init_lama(self):
        """Lazy-load the LaMa model. Tries multiple backends.

        Download order:
        1. simple_lama_inpainting package (if installed)
        2. torch.hub from advimman/lama (with China mirror support)
        3. Manual model download instructions
        """
        if self._lama_model is not None:
            return

        # Strategy 1: bundled SimpleLama checkpoint.  SimpleLama resolves the
        # checkpoint from TORCH_HOME/hub/checkpoints/big-lama.pt, so setting
        # this before construction makes the packaged app fully offline.
        try:
            bundled_root = self._bundled_model_root()
            bundled_model = os.path.join(bundled_root, "hub", "checkpoints", "big-lama.pt")
            if not os.path.isfile(bundled_model):
                raise FileNotFoundError(bundled_model)
            os.environ["TORCH_HOME"] = bundled_root
            from simple_lama_inpainting import SimpleLama
            self._lama_model = SimpleLama(device=self.device)
            return
        except (ImportError, FileNotFoundError):
            pass

        # Strategy 2: torch.hub from advimman/lama
        # Try China mirrors first if GitHub is blocked

        # Save original env vars we might override (including absent keys).
        saved_env = {
            key: os.environ.get(key)
            for key in ("HF_ENDPOINT", "TORCH_HOME", "http_proxy", "https_proxy")
        }

        mirrors_to_try = [
            # hf-mirror.com — popular HuggingFace mirror in China
            {"HF_ENDPOINT": "https://hf-mirror.com"},
            # Direct GitHub (default)
            {},
        ]

        last_error = None
        for mirror_env in mirrors_to_try:
            try:
                # Apply mirror settings
                for key, val in mirror_env.items():
                    os.environ[key] = val

                import torch
                self._lama_model = torch.hub.load(
                    "advimman/lama",
                    "lama_fixer",
                    map_location=self.device,
                    trust_repo=True,
                )
                # Success — restore original env and return
                _restore_env(os.environ, saved_env)
                return
            except Exception as e:
                last_error = e
                _restore_env(os.environ, saved_env)

        raise RuntimeError(
            "LaMa 模型加载失败。请尝试以下方法:\n\n"
            "1. OpenCV 模式（推荐，无需下载）\n"
            "2. 手动下载模型:\n"
            "   pip install modelscope\n"
            "   python -c \"from modelscope import snapshot_download; "
            "snapshot_download('aicoco/lama', cache_dir='./models')\"\n\n"
            f"原始错误: {last_error}"
        )

    def _inpaint_lama(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """LaMa-based inpainting for best quality."""
        from PIL import Image

        self._init_lama()

        pil_image = Image.fromarray(frame)
        pil_mask = Image.fromarray(mask)

        # simple_lama API
        if hasattr(self._lama_model, "__call__"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = self._lama_model(pil_image, pil_mask)
            return np.array(result)

        # torch.hub lama_fixer API
        if hasattr(self._lama_model, "inpaint"):
            result = self._lama_model.inpaint(pil_image, pil_mask)
            return np.array(result)

        raise RuntimeError("LaMa model loaded but has unexpected API.")
