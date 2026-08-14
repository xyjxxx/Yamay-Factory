"""Download the pinned LaMa checkpoint used by the packaged application."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
from pathlib import Path


MODEL_URL = (
    "https://github.com/enesmsahin/simple-lama-inpainting/releases/"
    "download/v0.1.0/big-lama.pt"
)
MODEL_FILENAME = "big-lama.pt"


def model_path(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent
    return root / "models" / "hub" / "checkpoints" / MODEL_FILENAME


def download(destination: Path | None = None) -> Path:
    """Download the checkpoint into the layout expected by SimpleLama."""
    destination = destination or model_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 100 * 1024 * 1024:
        print(f"LaMa model already exists: {destination}")
        return destination

    temporary = destination.with_suffix(".pt.part")
    print(f"Downloading LaMa model to: {destination}")
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    if temporary.stat().st_size < 100 * 1024 * 1024:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Downloaded LaMa file is unexpectedly small.")
    temporary.replace(destination)
    print(f"Downloaded {destination.stat().st_size / 1024 / 1024:.0f} MB")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    download(args.output)
