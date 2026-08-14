"""Core processing modules for watermark detection and removal."""

from watermark_remover.core.video_io import VideoInfo, VideoReader, VideoWriter, extract_first_frame
from watermark_remover.core.detector import WatermarkDetector
from watermark_remover.core.inpainter import Inpainter
from watermark_remover.core.pipeline import WatermarkPipeline
