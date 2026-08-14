@echo off
chcp 65001 >nul
title 羊咩的工厂

cd /d "%~dp0"

:: ============================================================
:: 羊咩的工厂 — 视频水印移除工具 启动脚本
:: 首次运行自动安装依赖，之后直接启动
:: ============================================================

:: ── Check Windows Long Path support ─────────────────────────
:: PySide6 内部路径很深，默认 260 字符限制会导致安装失败
set "LONG_PATH_KEY=HKLM\SYSTEM\CurrentControlSet\Control\FileSystem"
for /f "tokens=3" %%a in ('reg query "%LONG_PATH_KEY%" /v LongPathsEnabled 2^>nul') do set "LP_VAL=%%a"
if not "%LP_VAL%"=="0x1" (
    echo [提示] Windows 长路径支持未启用
    echo         PySide6 安装需要长路径支持，正在尝试开启...
    reg add "%LONG_PATH_KEY%" /v LongPathsEnabled /t REG_DWORD /d 1 /f >nul 2>&1
    if %errorlevel% neq 0 (
        echo [警告] 自动开启失败（可能需要管理员权限）
        echo         请以管理员身份运行此脚本一次，或手动执行:
        echo           reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
        echo         然后重启电脑。
        echo.
    ) else (
        echo [完成] 长路径已启用，部分功能需重启电脑后生效
        echo.
    )
)

:: ── Locate real Python (skip Windows Store stubs) ───────────
set "REAL_PYTHON="

:: 1. Explicit install locations first
for %%d in (
    "C:\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%PROGRAMFILES%\Python312"
) do (
    if exist "%%~d\python.exe" (
        set "REAL_PYTHON=%%~d\python.exe"
        goto :found_python
    )
)

:: 2. Fallback: PATH (keep original behaviour)
for /f "delims=" %%p in ('where python 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul || (
        set "REAL_PYTHON=%%p"
        goto :found_python
    )
)

:found_python
if "%REAL_PYTHON%"=="" (
    echo [错误] 未找到 Python，请安装 Python 3.12+
    echo        下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [Python] %REAL_PYTHON%

:: Use or create virtual environment (short path to avoid long-path issues)
set "VENV=C:\wm_venv"
set "PYTHON=%VENV%\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [提示] 正在创建虚拟环境...
    "%REAL_PYTHON%" -m venv "%VENV%"
    if %errorlevel% neq 0 (
        echo [错误] 无法创建虚拟环境，请检查 Python 是否安装
        pause
        exit /b 1
    )
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
        set "PATH=%~dp0ffmpeg\bin;%PATH%"
    ) else if exist "%~dp0ffmpeg\ffmpeg.exe" (
        set "PATH=%~dp0ffmpeg;%PATH%"
    ) else (
        echo [警告] 未找到 ffmpeg，视频处理功能不可用
        echo 安装: winget install ffmpeg
        echo 或下载放到当前目录的 ffmpeg\ 文件夹
        echo.
    )
)

:: ============================================================
:: 安装所有依赖（首次运行或更新时）
:: ============================================================
echo [检查] 正在检查依赖...

"%PYTHON%" -c "import PySide6, cv2, numpy, PIL, easyocr, torch, simple_lama_inpainting" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo   首次运行 — 正在安装全部依赖...
    echo   pip install -r requirements-wm.txt
    echo   包含: GUI + 视频处理 + OCR检测 + AI修复
    echo   PyTorch 约 2 GB，请耐心等待...
    echo ========================================
    echo.

    "%PYTHON%" -m pip install -r "%~dp0requirements-wm.txt"
    if %errorlevel% neq 0 (
        echo.
        echo [警告] 部分依赖安装失败，应用仍可启动
        echo        基础模式: 形态学检测 + OpenCV 修复
        echo        手动重试: "%PYTHON%" -m pip install -r "%~dp0requirements-wm.txt"
        echo.
        pause
    ) else (
        echo [完成] 所有依赖已安装
    )
)

:: --- 状态报告 ---
echo.
echo ========================================
echo   依赖检查结果:
"%PYTHON%" -c "import PySide6; print('  [OK] PySide6 ', PySide6.__version__)" 2>nul || echo "  [MISS] PySide6"
"%PYTHON%" -c "import cv2; print('  [OK] OpenCV  ', cv2.__version__)" 2>nul || echo "  [MISS] OpenCV"
"%PYTHON%" -c "import numpy; print('  [OK] NumPy   ', numpy.__version__)" 2>nul || echo "  [MISS] NumPy"
"%PYTHON%" -c "import PIL; print('  [OK] Pillow  ', PIL.__version__)" 2>nul || echo "  [MISS] Pillow"
"%PYTHON%" -c "import easyocr; print('  [OK] EasyOCR ', easyocr.__version__)" 2>nul || echo "  [MISS] EasyOCR（OCR检测不可用）"
"%PYTHON%" -c "import torch; print('  [OK] PyTorch ', torch.__version__)" 2>nul || echo "  [MISS] PyTorch （AI修复不可用）"
echo ========================================
echo.

:: Launch
echo.
echo 正在启动 羊咩的工厂...
"%PYTHON%" -m watermark_remover.main

pause
