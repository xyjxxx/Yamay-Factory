"""Processing pipeline that coordinates reading, inpainting, and writing.

Runs on a QThread to keep the UI responsive.
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from watermark_remover.core.video_io import VideoReader, VideoWriter, mux_audio_from_source
from watermark_remover.core.inpainter import Inpainter
from watermark_remover.core.detector import DetectionRegion, WatermarkDetector
from watermark_remover.core.image_processor import enhance_frame, refine_text_mask


class WatermarkPipeline(QThread):
    """Background thread that processes a video frame-by-frame.

    Signals:
        progress(int, str):  emitted with percentage 0-100 and status message.
        finished(str):       emitted when done, with the output file path.
        error(str):          emitted on failure.
    """

    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        mask: np.ndarray | None,
        inpainter: Inpainter,
        crf: int = 23,
        detector: WatermarkDetector | None = None,
        detection_method: str = "ocr",
        mask_padding: int = 8,
        redetect_interval: int = 0,
        temporal_regions: list[dict] | None = None,
        fine_mask: bool = False,
        enhance: bool = False,
        enhance_scale: float = 1.0,
        enhance_sharpen: bool = False,
        enhance_saturation: bool = False,
        auto_crf: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        self.mask = mask
        self.inpainter = inpainter
        self.crf = crf
        self.detector = detector
        self.detection_method = detection_method
        self.mask_padding = mask_padding
        self.redetect_interval = redetect_interval
        self.temporal_regions = temporal_regions or []
        self.fine_mask = fine_mask
        self.enhance = enhance
        self.enhance_scale = max(1.0, float(enhance_scale))
        self.enhance_sharpen = enhance_sharpen
        self.enhance_saturation = enhance_saturation
        self.auto_crf = auto_crf
        self._cancelled = False

    def _active_region(self, timestamp: float) -> dict | None:
        """Return the temporal watermark region covering the timestamp."""
        for region in self.temporal_regions:
            if region["start_sec"] <= timestamp <= region["end_sec"]:
                return region
        return None

    def _mask_from_region(self, region: dict, frame: np.ndarray) -> np.ndarray:
        det = DetectionRegion(
            x=region["x"],
            y=region["y"],
            width=region["w"],
            height=region["h"],
            method="temporal",
        ).expanded(padding=self.mask_padding)
        mask = WatermarkDetector.generate_mask(
            frame.shape,
            [det],
            dilate_px=self.mask_padding,
        )
        if self.fine_mask:
            refined = self._refine_mask(frame, mask)
            if refined is not None:
                return refined
        return mask

    def _refine_mask(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
        """Keep only the text strokes inside the masked area (Canny + components)."""
        return refine_text_mask(frame, mask)

    def _enhance_frame(self, frame: np.ndarray) -> np.ndarray:
        if not self.enhance:
            return frame
        return enhance_frame(
            frame,
            scale=self.enhance_scale,
            sharpen=self.enhance_sharpen,
            saturation=self.enhance_saturation,
        )

    @staticmethod
    def _auto_crf(width: int) -> int:
        if width >= 2560:
            return 14
        if width >= 1920:
            return 16
        if width >= 1280:
            return 18
        return 20

    def cancel(self):
        """Request cancellation. Graceful ? finishes current frame."""
        self._cancelled = True

    def run(self):
        """Main processing loop."""
        reader = None
        writer = None
        video_only_path = self.output_path + ".video_only.tmp.mp4"

        try:
            self.progress.emit(0, "正在打开视频…")
            reader = VideoReader(self.input_path)
            reader.open()
            info = reader.info

            self.progress.emit(
                1,
                f"视频信息: {info.resolution}, {info.fps:.2f} fps, {info.total_frames} 帧",
            )

            out_width = info.width
            out_height = info.height
            crf = self.crf
            if self.enhance and self.enhance_scale > 1.0:
                out_width = max(2, int(round(out_width * self.enhance_scale / 2) * 2))
                out_height = max(2, int(round(out_height * self.enhance_scale / 2) * 2))
            if self.auto_crf:
                crf = self._auto_crf(out_width)

            writer = VideoWriter(
                video_only_path,
                info,
                crf=crf,
                width=out_width,
                height=out_height,
            )
            writer.open()

            current_mask = self.mask
            fps = info.fps if info.fps and info.fps > 0 else 24.0
            for i, frame in enumerate(reader):
                if self._cancelled:
                    self.progress.emit(100, "已取消")
                    return

                if self.temporal_regions:
                    region = self._active_region(i / fps)
                    if region is None:
                        out_frame = self._enhance_frame(frame)
                        writer.write_frame(out_frame)
                        continue
                    frame_mask = self._mask_from_region(region, frame)
                    try:
                        fixed = self.inpainter.inpaint(frame, frame_mask)
                    except Exception as e:
                        self.error.emit(f"处理第 {i + 1} 帧时出错: {e}")
                        return
                    out_frame = self._enhance_frame(fixed)
                    writer.write_frame(out_frame)
                else:
                    if (
                        self.redetect_interval > 0
                        and i > 0
                        and i % self.redetect_interval == 0
                        and self.detector is not None
                        and self.detection_method != "manual"
                    ):
                        current_mask = WatermarkDetector.mask_for_frame(
                            self.detector,
                            frame,
                            self.detection_method,
                            self.mask_padding,
                            current_mask,
                        )
                    if self.fine_mask and current_mask is not None:
                        refined = self._refine_mask(frame, current_mask)
                        if refined is not None:
                            current_mask = refined
                    try:
                        fixed = self.inpainter.inpaint(frame, current_mask)
                    except Exception as e:
                        self.error.emit(f"处理第 {i + 1} 帧时出错: {e}")
                        return
                    out_frame = self._enhance_frame(fixed)
                    writer.write_frame(out_frame)

                pct = int((i + 1) / info.total_frames * 95) if info.total_frames else 0
                if i % 10 == 0 or pct > 0:
                    self.progress.emit(
                        pct,
                        f"处理中… {i + 1}/{info.total_frames} 帧 ({pct}%)",
                    )

            frames_written = writer.close()
            writer = None
            reader.close()
            reader = None

            if self._cancelled:
                self.progress.emit(100, "已取消")
                return

            self.progress.emit(96, "正在合并原视频音轨…")
            mux_audio_from_source(video_only_path, self.input_path, self.output_path)

            self.progress.emit(100, f"完成！共处理 {frames_written} 帧")
            self.finished.emit(self.output_path)

        except Exception as e:
            self.error.emit(str(e))

        finally:
            if reader:
                try:
                    reader.close()
                except Exception:
                    pass
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass
            if os.path.exists(video_only_path):
                try:
                    os.unlink(video_only_path)
                except OSError:
                    pass
