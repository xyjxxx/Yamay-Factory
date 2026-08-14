"""Entry point for the 羊咩的工厂 Windows application."""

from __future__ import annotations

import sys
import os


def _get_ffmpeg_dir() -> str | None:
    """Locate the ffmpeg directory (bundled or system). Returns path or None."""
    candidates = []

    # PyInstaller bundle: sys._MEIPASS is the temp extraction directory
    if getattr(sys, "frozen", False):
        meipass = sys._MEIPASS
        candidates.extend([
            os.path.join(meipass, "ffmpeg"),
            os.path.join(meipass, "ffmpeg", "bin"),
        ])

    # Development: relative to this file's location
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(base_dir)
    candidates.extend([
        os.path.join(root, "ffmpeg"),
        os.path.join(root, "ffmpeg", "bin"),
    ])

    for path in candidates:
        ffmpeg_exe = os.path.join(path, "ffmpeg.exe")
        if os.path.isfile(ffmpeg_exe):
            return path

    return None


def _setup_ffmpeg_path():
    """Add bundled or system ffmpeg to PATH."""
    ffmpeg_dir = _get_ffmpeg_dir()
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


def _get_icon_path() -> str | None:
    """Locate the application icon file. Returns path or None."""
    candidates = []

    # PyInstaller bundle
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(sys._MEIPASS, "icons", "sheep.ico"))

    # Development: relative to this file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(base_dir)
    candidates.append(os.path.join(root, "icons", "sheep.ico"))

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def _check_optional_deps() -> dict[str, bool]:
    """Check which optional dependencies are importable.

    Uses ``importlib.util.find_spec`` so the check is cheap — we never
    actually *load* torch or easyocr at this point (they initialise slowly).
    """
    from importlib.util import find_spec

    result = {"easyocr": False, "torch": False, "lama": False, "cuda": False}

    if find_spec("easyocr") is not None:
        result["easyocr"] = True

    if find_spec("torch") is not None:
        result["torch"] = True
        # Check CUDA availability (cheap — torch caches this)
        try:
            import torch
            result["cuda"] = torch.cuda.is_available()
        except Exception:
            pass

    # The packaged checkpoint is loaded by SimpleLama.  Do not report LaMa
    # as available with torch alone, otherwise a frozen app would fall back
    # to torch.hub and require a network download.
    result["lama"] = find_spec("simple_lama_inpainting") is not None

    return result


def _maybe_install_deps(parent, deps: dict[str, bool]) -> bool:
    """If optional deps are missing, ask the user and install via pip.

    Returns:
        ``True`` when something was installed (caller should reload/restart).
    """
    if getattr(sys, "frozen", False):
        return False  # PyInstaller bundle — pip won't help

    missing: list[tuple[str, str]] = []  # (pip-name, human-label)
    if not deps["easyocr"]:
        missing.append(("easyocr", "EasyOCR（文字水印自动检测）"))
    if not deps["torch"]:
        missing.append(("torch", "PyTorch（AI 修复引擎）"))
    if not deps["lama"]:
        missing.append(("simple-lama-inpainting", "LaMa 模型（高质量修复）"))

    if not missing:
        return False

    from PySide6.QtWidgets import QMessageBox

    names = "\n".join(f"  • {label}" for _, label in missing)
    reply = QMessageBox.question(
        parent,
        "安装可选依赖",
        f"检测到以下高级功能依赖未安装：\n\n{names}\n\n"
        f"是否立即安装？\n（需要网络连接，PyTorch 约 2 GB）",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply != QMessageBox.Yes:
        return False

    # ── Run pip ────────────────────────────────────────────────
    pkgs = [name for name, _ in missing]
    from PySide6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QTextEdit,
        QPushButton,
        QLabel,
    )

    dlg = QDialog(parent)
    dlg.setWindowTitle("正在安装…")
    dlg.resize(600, 350)
    dlg.setModal(True)

    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(f"正在执行: pip install {' '.join(pkgs)}"))
    text = QTextEdit()
    text.setReadOnly(True)
    lay.addWidget(text)

    btn = QPushButton("安装完成后关闭")
    btn.setEnabled(False)
    lay.addWidget(btn)
    btn.clicked.connect(dlg.accept)

    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-m", "pip", "install", "--no-input"] + pkgs,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if proc.stdout:
        for line in proc.stdout:
            text.append(line.rstrip())
    proc.wait()
    btn.setEnabled(True)
    btn.setText("关闭")
    text.append(f"\n--- pip 退出码: {proc.returncode} ---")
    dlg.exec()

    return proc.returncode == 0


def main():
    """Launch the watermark remover application."""
    _setup_ffmpeg_path()

    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QIcon
    from watermark_remover.ui.main_window import MainWindow

    # ── Global exception hook — prevents silent crashes ──────────
    _setup_exception_hook()

    app = QApplication(sys.argv)
    app.setApplicationName("羊咩的工厂")
    app.setOrganizationName("DoubaoNoMark")

    # Set window icon (title bar + taskbar)
    icon_path = _get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # ── Check & install optional dependencies ──────────────────
    deps = _check_optional_deps()

    installed = _maybe_install_deps(None, deps)
    if installed:
        deps = _check_optional_deps()

    window = MainWindow(deps)
    window.show()

    sys.exit(app.exec())


def _setup_exception_hook():
    """Install a global exception hook to catch unhandled errors.

    PySide6 silently swallows some exceptions in signal/slot dispatch.
    This hook ensures we at least see what went wrong.
    """
    import traceback
    import io

    def _excepthook(exc_type, exc_value, exc_tb):
        # Format the traceback
        buf = io.StringIO()
        traceback.print_exception(exc_type, exc_value, exc_tb, file=buf)
        msg = buf.getvalue()

        # Log to stderr so it's visible in console
        print(f"[FATAL] Unhandled exception:\n{msg}", file=sys.stderr)

        # Try to show a GUI error dialog
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None,
                    "程序错误",
                    f"发生未处理的异常:\n\n{msg[-500:]}",
                )
        except Exception:
            pass

        # Call the original hook
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook


if __name__ == "__main__":
    main()
