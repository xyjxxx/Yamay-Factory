"""PyInstaller build script — packages the app as a Windows .exe.

Usage:
    cd D:/Yamay-Factory
    python watermark_remover/build.py

Output will be in ./dist/  directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Fix GBK encoding issues on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import PyInstaller.__main__
except ModuleNotFoundError as exc:
    if exc.name != "PyInstaller":
        raise
    raise SystemExit(
        "\n未在当前 Python 环境中找到 PyInstaller。\n"
        "请使用项目已配置的环境执行：\n"
        "  C:\\wm_venv\\Scripts\\python.exe watermark_remover\\build.py\n\n"
        "或先安装构建依赖：\n"
        "  python -m pip install -r requirements-wm.txt\n"
    ) from None


def _try_import(name: str) -> bool:
    """Check if a module can be imported without error."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(f"Build blocked: {message}")


def build():
    print("[BUILD_PROGRESS] Checking offline build prerequisites…")
    root = Path(__file__).resolve().parent.parent
    entry = root / "watermark_remover" / "main.py"
    icon = root / "icons" / "sheep.ico"
    background_video = root / "icons" / "sheep1.mp4"
    qt_translation = root / "translations" / "qtbase_zh_CN.qm"
    lama_models_dir = root / "models"
    easyocr_models_dir = lama_models_dir / "easyocr"

    # ── Collect ffmpeg binaries ──────────────────────────────
    ffmpeg_dir = root / "ffmpeg"
    ffmpeg_binaries: list[str] = []
    if ffmpeg_dir.is_dir():
        for exe in ["ffmpeg.exe", "ffprobe.exe", "ffplay.exe"]:
            exe_path = ffmpeg_dir / exe
            if exe_path.is_file():
                ffmpeg_binaries.append(str(exe_path))

    add_binary_args: list[str] = []
    for binary in ffmpeg_binaries:
        # PyInstaller --add-binary: source;dest_dir
        add_binary_args.extend(["--add-binary", f"{binary}{os.pathsep}ffmpeg"])

    add_data_args: list[str] = [
        f"--add-data={icon}{os.pathsep}icons",
        f"--add-data={background_video}{os.pathsep}icons",
    ]
    _require(qt_translation.is_file(), "Qt Chinese translation missing; keep translations/qtbase_zh_CN.qm")
    add_data_args.append(f"--add-data={qt_translation}{os.pathsep}translations")
    lama_checkpoint = lama_models_dir / "hub" / "checkpoints" / "big-lama.pt"
    _require(icon.is_file(), f"icon missing: {icon}")
    _require(background_video.is_file(), f"background video missing: {background_video}")
    _require(len(ffmpeg_binaries) >= 2, "ffmpeg and ffprobe binaries are required")
    _require(lama_checkpoint.is_file(), "LaMa checkpoint missing; run download_lama_model.py")
    required_ocr_models = ("craft_mlt_25k.pth", "zh_sim_g2.pth")
    _require(easyocr_models_dir.is_dir() and all(
        (easyocr_models_dir / model).is_file() for model in required_ocr_models
    ),
             "EasyOCR models missing; run download_ocr_models.py")
    add_data_args.append(f"--add-data={lama_models_dir}{os.pathsep}models")
    print(f"[OK] bundled LaMa model: {lama_checkpoint}")
    print(f"[OK] bundled EasyOCR models: {easyocr_models_dir}")

    required_modules = ("PySide6", "cv2", "numpy", "PIL", "torch", "torchvision", "easyocr", "simple_lama_inpainting")
    missing_modules = [name for name in required_modules if not _try_import(name)]
    _require(not missing_modules, "missing Python packages: " + ", ".join(missing_modules))

    # ── Build args ───────────────────────────────────────────
    args = [
        str(entry),
        "--name=羊咩的工厂",
        "--onefile",
        "--windowed",  # no console window
        "--clean",
        "--noconfirm",
        f"--distpath={root / 'dist'}",
        f"--workpath={root / 'build' / 'pyinstaller'}",
        f"--specpath={root / 'build'}",
        f"--additional-hooks-dir={root / 'watermark_remover' / '_hooks'}",
        # Bundled binaries
        *add_binary_args,
        # Bundled icon (for window title bar)
        *add_data_args,
        # Hidden imports
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=cv2",
        "--hidden-import=numpy",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtMultimedia",
        "--hidden-import=PySide6.QtMultimediaWidgets",
        # Exclude unnecessary heavy modules
        "--exclude-module=matplotlib",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
        "--exclude-module=jupyter",
        "--exclude-module=notebook",
        "--exclude-module=tensorflow",
        "--exclude-module=keras",
        "--exclude-module=IPython",
        "--exclude-module=sphinx",
        "--exclude-module=pytest",
        "--exclude-module=skimage.io._plugins",
    ]

    args.extend([
        "--collect-all=easyocr",
        "--collect-all=torch",
        "--collect-all=torchvision",
        "--collect-all=simple_lama_inpainting",
    ])
    print("[OK] OCR, LaMa and all required runtime libraries will be included")
    print("[BUILD_PROGRESS] Starting PyInstaller…")

    # Icon
    if icon.exists():
        args.append(f"--icon={icon}")
        print(f"[OK] icon: {icon}")
        print(f"[OK] background video: {background_video}")
    else:
        print("[WARN] icon file not found")

    print("=" * 60)
    print("  Doubao Video Watermark Remover - PyInstaller Build")
    print(f"  Entry: {entry}")
    print(f"  Output: {root / 'dist'}")
    print(f"  ffmpeg binaries: {len(ffmpeg_binaries)}")
    print("=" * 60)

    PyInstaller.__main__.run(args)

    exe_path = root / "dist" / "羊咩的工厂.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Build complete: {exe_path} ({size_mb:.0f} MB)")
    else:
        print("\n[ERROR] Build may have failed - check output above.")


if __name__ == "__main__":
    build()
