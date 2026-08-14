@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=C:\wm_venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [错误] 未找到项目运行环境：C:\wm_venv
    echo 请先双击“启动.bat”完成环境安装，再执行本脚本。
    pause
    exit /b 1
)

"%PYTHON%" watermark_remover\build_progress.py
