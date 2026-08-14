"""Download EasyOCR models into the project so packaged builds work offline."""

from __future__ import annotations

from pathlib import Path


def model_directory(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent
    return root / "models" / "easyocr"


def download(destination: Path | None = None) -> Path:
    """Download the Chinese and English OCR models required by this app."""
    import easyocr

    destination = destination or model_directory()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Preparing EasyOCR models in: {destination}")
    easyocr.Reader(
        ["ch_sim", "en"],
        gpu=False,
        verbose=False,
        model_storage_directory=str(destination),
        download_enabled=True,
    )
    return destination


if __name__ == "__main__":
    download()
