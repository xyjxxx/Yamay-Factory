"""Tests for video I/O helpers."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from watermark_remover.core import video_io


def test_safe_fs_path_returns_ascii_path_unchanged(tmp_path):
    path = str(tmp_path / "video.mp4")
    assert video_io._safe_fs_path(path) == os.path.normpath(os.path.abspath(path))


@pytest.mark.skipif(sys.platform == "win32", reason="Non-ASCII path test is for POSIX")
def test_safe_fs_path_non_ascii_posix(tmp_path):
    path = str(tmp_path / "视频.mp4")
    os.makedirs(tmp_path, exist_ok=True)
    open(path, "wb").close()
    assert video_io._safe_fs_path(path) == os.path.normpath(os.path.abspath(path))


def test_has_audio_stream_true():
    with patch.object(video_io, "_find_ffmpeg", return_value="ffmpeg"):
        with patch("watermark_remover.core.video_io.os.path.isfile", return_value=True):
            with patch("watermark_remover.core.video_io.subprocess.run") as run:
                run.return_value = MagicMock(returncode=0, stdout="audio\n")
                assert video_io.has_audio_stream("input.mp4") is True


def test_has_audio_stream_false():
    with patch.object(video_io, "_find_ffmpeg", return_value="ffmpeg"):
        with patch("watermark_remover.core.video_io.os.path.isfile", return_value=True):
            with patch("watermark_remover.core.video_io.subprocess.run") as run:
                run.return_value = MagicMock(returncode=0, stdout="")
                assert video_io.has_audio_stream("input.mp4") is False


def test_get_video_info_uses_utf8_subprocess(monkeypatch):
    """Regression: GBK default encoding must not empty ffprobe stdout on Windows."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return type("R", (), {
            "returncode": 0,
            "stdout": '{"streams":[{"codec_type":"video","width":1920,"height":1080,"avg_frame_rate":"30/1","nb_frames":"100"}],"format":{"duration":"10.0"}}',
            "stderr": "",
        })()

    monkeypatch.setattr(video_io.subprocess, "run", fake_run)
    monkeypatch.setattr(video_io, "_find_ffmpeg", lambda: "ffmpeg.exe")
    monkeypatch.setattr(video_io.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(video_io, "_safe_fs_path", lambda p: p)

    info = video_io.get_video_info("test.mp4")
    assert info.width == 1920
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"


def test_mux_audio_moves_video_when_no_audio(tmp_path):
    video = tmp_path / "out.mp4"
    source = tmp_path / "in.mp4"
    video.write_bytes(b"video")
    source.write_bytes(b"source")

    with patch.object(video_io, "has_audio_stream", return_value=False):
        video_io.mux_audio_from_source(str(video), str(source), str(tmp_path / "final.mp4"))

    final = tmp_path / "final.mp4"
    assert final.is_file()
    assert final.read_bytes() == b"video"
    assert not video.is_file()

