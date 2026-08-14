# 🐑 羊咩的工厂

<p align="center">
  <img src="icons/sheep.png" alt="羊咩的工厂" width="160" />
</p>

<p align="center"><b>豆包视频水印移除工具 · Windows 桌面应用</b></p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/Platform-Windows%2010%2F11-blue" />
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-green" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-orange" />
</p>

一款基于 **PySide6** 的本地视频 / 图片去水印工具。自动检测视频中的水印区域，结合 **OCR 文字检测（EasyOCR）** 与 **AI 图像修复（LaMa）**，在本地完成去水印处理，无需联网上传，保护你的隐私。

---

## ✨ 功能特性

- **自动检测水印**：智能识别视频 / 图片中的水印区域，无需手动框选
- **手动框选**：在预览画面上拖拽框选水印区域，精准控制
- **OCR 文字检测**：基于 EasyOCR，识别文字类水印位置（中文 + 英文）
- **AI 修复**：基于 LaMa 模型修复被遮挡的画面内容
- **视频 / 图片双支持**：既可去除视频水印，也可处理单张图片
- **批量处理**：支持多文件批量去水印
- **水印位置编辑**：检测结果可手动微调、增删，随时预览修复效果
- **纯本地运行**：所有处理均在本地完成，不上传任何数据

---

## 📋 软件与环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11（64 位） |
| Python | 3.10 或更高（推荐 3.12），仅源码运行时需要 |
| ffmpeg | 已随项目提供（`ffmpeg\` 目录），缺失时可自行安装 |
| 磁盘空间 | 源码运行约 3~5 GB（含模型） |
| 网络 | 首次安装依赖、下载模型时需要联网 |

---

## 🚀 启动软件

### 方式一：双击启动（推荐）

```
双击项目根目录下的  启动.bat
```

- **首次运行**：自动创建虚拟环境（`C:\wm_venv`）→ 自动安装全部依赖 → 自动启动软件
- **之后运行**：直接启动软件

### 方式二：命令行启动（环境已配置好）

已运行过 `启动.bat` 的电脑可直接执行：

**CMD：**

```cmd
cd /d D:\doubao-nomark-main
C:\wm_venv\Scripts\python.exe -m watermark_remover.main
```

**PowerShell：**

```powershell
cd D:\doubao-nomark-main
& C:\wm_venv\Scripts\python.exe -m watermark_remover.main
```

### 方式三：全新电脑从零启动

1. 安装 Python 3.10+（勾选 **Add python.exe to PATH**）
2. 进入项目目录并安装依赖：

   ```cmd
   cd /d D:\doubao-nomark-main
   pip install -r requirements-wm.txt
   ```

3. 下载检测与修复模型（推荐）：

   ```cmd
   python watermark_remover\download_ocr_models.py
   python watermark_remover\download_lama_model.py
   ```

4. 启动软件：

   ```cmd
   python -m watermark_remover.main
   ```

### 方式四：直接运行打包好的 EXE（最省事）

```
双击  dist\羊咩的工厂.exe
```

- 无需安装 Python、无需联网、无需任何依赖
- 可单独拷贝给同事或朋友使用
- 注意：杀毒软件可能误报，需添加信任

---

## 📦 打包为 EXE

### 一键打包

```
双击项目根目录下的  打包.bat
```

完成后 EXE 位于 `dist\羊咩的工厂.exe`（约 663 MB，含 OCR + LaMa 模型）。

### 命令行打包

```cmd
cd /d D:\doubao-nomark-main
C:\wm_venv\Scripts\python.exe watermark_remover\build.py
```

> 打包前请确保 `ffmpeg\`、`icons\`、`models\` 等资源齐全，详见 [启动与打包说明书.md](启动与打包说明书.md)。

---

## 📁 项目结构

| 路径 | 作用 |
|------|------|
| `启动.bat` | 一键启动脚本（普通用户推荐） |
| `打包.bat` | 一键打包脚本（带进度窗口） |
| `requirements-wm.txt` | 全部 Python 依赖清单 |
| `watermark_remover\main.py` | 程序入口 |
| `watermark_remover\build.py` | PyInstaller 打包脚本 |
| `ffmpeg\` | ffmpeg / ffprobe / ffplay 可执行文件 |
| `icons\` | 应用图标（sheep.ico）与动态背景视频（sheep1.mp4） |
| `models\` | OCR 模型 + LaMa 模型（离线打包必需） |
| `dist\` | 打包输出目录（生成的 EXE） |

---

## ❓ 常见问题

| 问题 | 解决方法 |
|------|----------|
| 双击 `启动.bat` 闪退 | 多为未安装 Python，或以管理员身份运行一次以开启长路径支持 |
| pip 安装报长路径错误 | 以管理员身份运行 `启动.bat`，或手动开启 Windows 长路径支持 |
| 提示找不到 ffmpeg | 确保 `ffmpeg\` 目录存在，或执行 `winget install ffmpeg` |
| 打包报 "LaMa checkpoint missing" | 执行 `python watermark_remover\download_lama_model.py` |
| 打包报 "EasyOCR models missing" | 执行 `python watermark_remover\download_ocr_models.py` |
| 打包好的 EXE 被杀毒软件拦截 | 将 EXE 所在目录加入杀毒软件信任 / 排除列表 |
| 打包后的 EXE 首次启动很慢 | 正常现象，单文件模式启动时先解压到临时目录，几秒后恢复 |

更多细节见 [启动与打包说明书.md](启动与打包说明书.md)。

---

## 📄 许可证

本项目基于 **MIT License** 开源，详见 [LICENSE](LICENSE)。
