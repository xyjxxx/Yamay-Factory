"""Video I/O: read and write video frames via ffmpeg pipes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np


# ffprobe/ffmpeg emit UTF-8; on Chinese Windows the default locale is GBK and
# subprocess text mode would raise UnicodeDecodeError, leaving stdout empty.
_SUBPROCESS_TEXT_KW: dict = {"encoding": "utf-8", "errors": "replace"}

# Cache symlink/short-path aliases for non-ASCII source paths (key = abs path).
_path_alias_cache: dict[str, str] = {}


@dataclass
class VideoInfo:
    """Metadata for a video file."""

    path: str
    width: int
    height: int
    fps: float
    total_frames: int
    duration: float  # seconds
    codec: str = "unknown"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


def _safe_fs_path(path: str) -> str:
    """Convert a file path to a form that ffmpeg/ffprobe can safely consume.

    On Windows, ffmpeg builds often use the ANSI API (CreateProcessA) which
    mangles non-ASCII characters (Chinese, Japanese, etc.) in file paths.
    We work around it by:
    1. Using the 8.3 short-name form if available.
    2. Creating a symlink in %TEMP% (works cross-drive).
    3. Creating a hardlink in %TEMP% (same volume only).
    4. Using the ``\\\\?\\`` extended-length prefix.
  """
    # Non-Windows: no workaround needed
    if sys.platform != "win32":
        return path

    # Normalize to absolute path
    path = os.path.normpath(os.path.abspath(path))

    cached = _path_alias_cache.get(path)
    if cached and os.path.exists(cached):
        return cached

    # Quick check: if already all ASCII, no workaround needed
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        pass

    # ── Strategy 1: Windows 8.3 short path ───────────────────────
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)  # extended-length path max
    result = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
    if 0 < result < len(buf):
        short = buf.value
        if os.path.exists(short):
            _path_alias_cache[path] = short
            return short

    # ── Strategy 2/3: symlink or hardlink in %TEMP% ─────────────
    import uuid
    temp_dir = os.environ.get("TEMP", os.environ.get("TMP", os.getcwd()))
    ext = os.path.splitext(path)[1] or ".mp4"
    link_name = f"_wm_{uuid.uuid4().hex[:8]}{ext}"
    link_path = os.path.join(temp_dir, link_name)

    for make_link in (
        lambda: os.symlink(path, link_path, target_is_directory=False),
        lambda: os.link(path, link_path),
    ):
        try:
            if os.path.lexists(link_path):
                os.unlink(link_path)
            make_link()
            _cleanup_temp_links(fast=True)
            _path_alias_cache[path] = link_path
            return link_path
        except OSError:
            continue

    # ── Strategy 4: extended-length Unicode path ─────────────────
    if not path.startswith("\\\\?\\"):
        extended = "\\\\?\\" + path
        if os.path.exists(extended):
            return extended

    # ── Last resort: return original path ────────────────────────
    return path


def _cleanup_temp_links(fast: bool = False):
    """Remove stale _wm_* hardlink files from the TEMP directory.

    Args:
        fast: If True, only sweep if there are > 10 stale links.
              Used during opportunistic cleanup to avoid overhead.
    """
    if sys.platform != "win32":
        return

    import time as _time
    temp_dir = os.environ.get("TEMP", os.environ.get("TMP", "."))
    threshold = _time.time() - 3600  # 1 hour ago

    try:
        entries = [
            e for e in os.scandir(temp_dir)
            if e.name.startswith("_wm_") and e.is_file()
        ]
    except OSError:
        return

    # Fast mode: only bother if there's accumulated cruft
    if fast and len(entries) <= 10:
        return

    for entry in entries:
        try:
            if entry.stat().st_mtime < threshold:
                os.unlink(entry.path)
        except OSError:
            pass


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable. Returns full path or raises FileNotFoundError."""
    # Build a list of directories to search
    search_dirs: list[str] = []

    # 1. PyInstaller bundle directory (sys._MEIPASS)
    if getattr(sys, "frozen", False):
        meipass = sys._MEIPASS
        search_dirs.extend([
            os.path.join(meipass, "ffmpeg"),
            meipass,
        ])

    # 2. Project root ffmpeg directory (development mode)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(base_dir))  # go up from core/ to watermark_remover/ to root
    search_dirs.extend([
        os.path.join(root, "ffmpeg"),
        root,
    ])

    # 3. Common Windows installation paths
    search_dirs.extend([
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin"),
        os.path.join(os.environ.get("ProgramFiles", ""), "ffmpeg", "bin"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "ffmpeg", "bin"),
    ])

    # 4. PATH — parse into individual directories
    for p in os.environ.get("PATH", "").split(os.pathsep):
        p = p.strip()
        if p and os.path.isdir(p):
            search_dirs.append(p)

    # 5. Current directory
    search_dirs.append(os.getcwd())

    # Deduplicate while preserving order
    seen = set()
    unique_dirs = []
    for d in search_dirs:
        if d and d not in seen:
            seen.add(d)
            unique_dirs.append(d)

    # Search for ffmpeg.exe in each directory
    for d in unique_dirs:
        exe_path = os.path.join(d, "ffmpeg.exe")
        try:
            result = subprocess.run(
                [exe_path, "-version"],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                **_SUBPROCESS_TEXT_KW,
            )
            if result.returncode == 0:
                return exe_path
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    # Also try bare "ffmpeg" / "ffmpeg.exe" (relies on PATH)
    for name in ["ffmpeg", "ffmpeg.exe"]:
        try:
            result = subprocess.run(
                [name, "-version"],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                **_SUBPROCESS_TEXT_KW,
            )
            if result.returncode == 0:
                return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    raise FileNotFoundError(
        "未找到 ffmpeg。请安装 ffmpeg 并将其添加到系统 PATH。\n"
        "下载地址: https://ffmpeg.org/download.html\n"
        "或使用 winget: winget install ffmpeg"
    )


def get_video_info(path: str) -> VideoInfo:
    """Extract video metadata using ffprobe."""
    # Verify file exists first
    if not os.path.isfile(path):
        raise FileNotFoundError(f"视频文件不存在: {path}")

    ffmpeg_path = _find_ffmpeg()
    ffprobe = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")

    if not os.path.isfile(ffprobe):
        raise FileNotFoundError(f"未找到 ffprobe。请确保 ffmpeg 完整安装。\n已找到 ffmpeg: {ffmpeg_path}")

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",  # show errors but not spam
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                _safe_fs_path(path),
            ],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            **_SUBPROCESS_TEXT_KW,
        )
    except FileNotFoundError:
        raise FileNotFoundError(f"未找到 ffprobe: {ffprobe}")

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "未知错误"
        raise RuntimeError(f"ffprobe 读取视频失败:\n{stderr}")

    stdout = result.stdout
    if not stdout:
        stderr_info = result.stderr.strip()
        raise RuntimeError(
            f"ffprobe 未返回任何数据。\n"
            f"文件: {path}\n"
            f"stderr: {stderr_info if stderr_info else '(空)'}\n"
            f"视频文件可能已损坏，或格式不受支持。"
        )

    data = json.loads(stdout)

    # Find the first video stream
    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if video_stream is None:
        raise RuntimeError("视频文件中未找到视频流")

    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)

    # Parse fps (may be a fraction string like "30000/1001")
    fps_str = video_stream.get("avg_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str) if fps_str else 30.0

    # Duration from format info (more reliable) or stream
    fmt = data.get("format", {})
    duration = float(fmt.get("duration", video_stream.get("duration", 0)))

    # Total frames: prefer stream nb_frames, fall back to duration * fps
    nb_frames = video_stream.get("nb_frames")
    if nb_frames is not None and int(nb_frames) > 0:
        total_frames = int(nb_frames)
    else:
        total_frames = int(duration * fps)

    codec = video_stream.get("codec_name", "unknown")

    return VideoInfo(
        path=path,
        width=width,
        height=height,
        fps=fps,
        total_frames=total_frames,
        duration=duration,
        codec=codec,
    )


class VideoReader:
    """Read video frames via ffmpeg rawvideo pipe."""

    def __init__(self, path: str):
        self.path = path
        self.info = get_video_info(path)
        self._ffmpeg = _find_ffmpeg()
        self._process: subprocess.Popen | None = None
        self._frame_size = self.info.width * self.info.height * 3  # RGB24

    def open(self, seek_seconds: float = 0.0):
        """Start ffmpeg and open the pipe for reading.

        Args:
            seek_seconds: If > 0, fast-seek to this timestamp before
                decoding (``-ss`` before ``-i``).
        """
        cmd = [self._ffmpeg]
        if seek_seconds > 0:
            cmd.extend(["-ss", f"{seek_seconds:.6f}"])
        cmd.extend([
            "-i", _safe_fs_path(self.path),
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-vcodec", "rawvideo",
            "-an",  # no audio
            "-sn",  # no subtitles
            "-",
        ])
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**8,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return self

    def read_frame(self) -> np.ndarray | None:
        """Read a single frame. Returns None at end of video."""
        if self._process is None:
            raise RuntimeError("VideoReader not opened. Call open() first.")

        raw = self._process.stdout.read(self._frame_size)
        if len(raw) < self._frame_size:
            return None

        frame = np.frombuffer(raw, dtype=np.uint8).reshape(
            (self.info.height, self.info.width, 3)
        )
        return frame

    def __iter__(self) -> Iterator[np.ndarray]:
        """Iterate over all frames."""
        while True:
            frame = self.read_frame()
            if frame is None:
                break
            yield frame

    def close(self):
        """Clean up the ffmpeg process."""
        if self._process:
            try:
                self._process.stdout.close()
                self._process.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self._process.kill()
            self._process = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *args):
        self.close()


def extract_first_frame(path: str) -> np.ndarray:
    """Extract the first frame of a video for preview."""
    ffmpeg = _find_ffmpeg()
    info = get_video_info(path)
    frame_size = info.width * info.height * 3

    cmd = [
        ffmpeg,
        "-i", _safe_fs_path(path),
        "-vframes", "1",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo",
        "-an",
        "-",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    if result.returncode != 0 or len(result.stdout) < frame_size:
        raise RuntimeError(f"提取首帧失败: {result.stderr.decode(errors='ignore')}")

    frame = np.frombuffer(result.stdout[:frame_size], dtype=np.uint8).reshape(
        (info.height, info.width, 3)
    )
    return frame


def extract_frame_at(path: str, frame_number: int) -> np.ndarray:
    """Extract a specific frame (0-indexed) from a video using ffmpeg seeking.

    Uses ``-ss`` before ``-i`` for fast keyframe-based seeking, then
    ``-frames:v 1`` to output exactly one frame.
    """
    ffmpeg = _find_ffmpeg()
    info = get_video_info(path)
    frame_size = info.width * info.height * 3

    # Clamp frame number
    total = max(1, info.total_frames)
    frame_number = max(0, min(frame_number, total - 1))

    # Timestamp seek
    timestamp = frame_number / info.fps if info.fps > 0 else 0

    cmd = [
        ffmpeg,
        "-ss", f"{timestamp:.6f}",
        "-i", _safe_fs_path(path),
        "-vframes", "1",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo",
        "-an",
        "-",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    if result.returncode != 0 or len(result.stdout) < frame_size:
        raise RuntimeError(
            f"提取第 {frame_number} 帧失败: "
            f"{result.stderr.decode(errors='ignore')[:200]}"
        )

    frame = np.frombuffer(result.stdout[:frame_size], dtype=np.uint8).reshape(
        (info.height, info.width, 3)
    )
    return frame


class VideoWriter:
    """Write processed frames to video via ffmpeg pipe."""

    def __init__(
        self,
        output_path: str,
        info: VideoInfo,
        crf: int = 23,
        width: int | None = None,
        height: int | None = None,
    ):
        self.output_path = output_path
        self.info = info
        self.crf = crf
        self.width = width or info.width
        self.height = height or info.height
        self._ffmpeg = _find_ffmpeg()
        self._process: subprocess.Popen | None = None
        self._frames_written = 0

    def open(self):
        """Start ffmpeg for writing."""
        cmd = [
            self._ffmpeg,
            "-y",  # overwrite
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.info.fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(self.crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            _safe_fs_path(self.output_path),
        ]
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**8,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return self

    def write_frame(self, frame: np.ndarray):
        """Write a single frame."""
        if self._process is None:
            raise RuntimeError("VideoWriter not opened. Call open() first.")
        self._process.stdin.write(frame.tobytes())
        self._frames_written += 1

    def close(self):
        """Finish writing and clean up."""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=30)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self._process.kill()
            self._process = None
        return self._frames_written

    @property
    def frames_written(self) -> int:
        return self._frames_written

    def __enter__(self):
        return self.open()

    def __exit__(self, *args):
        self.close()


def has_audio_stream(path: str) -> bool:
    """Return True if the file contains at least one audio stream."""
    ffmpeg_path = _find_ffmpeg()
    ffprobe = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
    if not os.path.isfile(ffprobe):
        return False

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                _safe_fs_path(path),
            ],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            **_SUBPROCESS_TEXT_KW,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0 and bool(result.stdout.strip())


def mux_audio_from_source(video_path: str, source_path: str, output_path: str) -> None:
    """Merge processed video with audio from the original source file.

    If the source has no audio, the processed video is moved to output_path.
    """
    import shutil

    if not has_audio_stream(source_path):
        if os.path.abspath(video_path) != os.path.abspath(output_path):
            if os.path.exists(output_path):
                os.unlink(output_path)
            shutil.move(video_path, output_path)
        return

    ffmpeg = _find_ffmpeg()
    temp_output = output_path + ".tmp.mp4"

    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i", _safe_fs_path(video_path),
                "-i", _safe_fs_path(source_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-shortest",
                "-movflags", "+faststart",
                _safe_fs_path(temp_output),
            ],
            capture_output=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("合并音轨超时，请稍后重试。")

    if result.returncode != 0:
        if os.path.exists(temp_output):
            os.unlink(temp_output)
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="ignore")
        stderr = stderr.strip() if stderr else "未知错误"
        raise RuntimeError(f"合并音轨失败:\n{stderr}")

    if os.path.exists(output_path):
        os.unlink(output_path)
    os.replace(temp_output, output_path)
