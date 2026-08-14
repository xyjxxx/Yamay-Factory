"""Small Windows progress window for the offline PyInstaller build."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk


ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(r"C:\wm_venv\Scripts\python.exe")


def _progress_for_line(line: str) -> tuple[int, str] | None:
    stages = (
        ("[BUILD_PROGRESS]", 10, "正在检查离线组件…"),
        ("Analyzing", 25, "正在分析应用和依赖…"),
        ("Processing module hooks", 40, "正在收集程序组件…"),
        ("Looking for dynamic libraries", 55, "正在收集运行库…"),
        ("Graph cross-reference", 65, "正在整理依赖关系…"),
        ("Building PYZ", 72, "正在压缩 Python 模块…"),
        ("Building PKG", 82, "正在写入离线模型和运行库…"),
        ("Building EXE", 94, "正在生成 EXE 文件…"),
    )
    for marker, percent, message in stages:
        if marker in line:
            return percent, message
    return None


def main() -> int:
    if not PYTHON.is_file():
        tk.Tk().withdraw()
        from tkinter import messagebox
        messagebox.showerror("无法打包", "未找到 C:\\wm_venv\\Scripts\\python.exe。请先运行启动.bat。")
        return 1

    window = tk.Tk()
    window.title("正在打包离线版")
    window.geometry("620x330")
    window.resizable(False, False)

    body = ttk.Frame(window, padding=20)
    body.pack(fill="both", expand=True)
    title = ttk.Label(body, text="正在生成离线 EXE", font=("Microsoft YaHei UI", 16, "bold"))
    title.pack(anchor="w")
    status = ttk.Label(body, text="准备开始…", font=("Microsoft YaHei UI", 10))
    status.pack(anchor="w", pady=(12, 6))
    progress_value = tk.IntVar(value=0)
    progress = ttk.Progressbar(body, maximum=100, variable=progress_value, length=575)
    progress.pack(fill="x")
    percentage = ttk.Label(body, text="0%", font=("Microsoft YaHei UI", 10))
    percentage.pack(anchor="e", pady=(4, 12))
    log = tk.Text(body, height=10, wrap="word", state="disabled", font=("Consolas", 9))
    log.pack(fill="both", expand=True)

    messages: queue.Queue[str | None] = queue.Queue()
    started_at = time.monotonic()
    current_progress = 0

    def append(line: str):
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

    def worker():
        command = [str(PYTHON), "watermark_remover\\build.py"]
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert process.stdout is not None
        for line in process.stdout:
            messages.put(line.rstrip())
        messages.put(f"__EXIT__:{process.wait()}")

    def update():
        nonlocal current_progress
        try:
            while True:
                line = messages.get_nowait()
                if line.startswith("__EXIT__:"):
                    code = int(line.split(":", 1)[1])
                    if code == 0:
                        current_progress = 100
                        status.configure(text=f"打包完成，文件位于：{ROOT / 'dist'}")
                        title.configure(text="离线 EXE 已生成")
                        append("打包完成。")
                    else:
                        status.configure(text="打包失败，请查看下方日志。")
                        title.configure(text="打包失败")
                    progress_value.set(current_progress)
                    percentage.configure(text=f"{current_progress}%")
                    return
                append(line)
                update_info = _progress_for_line(line)
                if update_info:
                    current_progress = max(current_progress, update_info[0])
                    status.configure(text=update_info[1])
                    progress_value.set(current_progress)
                    percentage.configure(text=f"{current_progress}%")
        except queue.Empty:
            pass
        elapsed = int(time.monotonic() - started_at)
        window.after(120, update)

    threading.Thread(target=worker, daemon=True).start()
    window.after(120, update)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
