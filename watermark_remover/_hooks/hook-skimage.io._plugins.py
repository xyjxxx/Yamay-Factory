"""Prevent PyInstaller from collecting data files from skimage.io._plugins."""
# This pseudo-module causes PyInstaller to crash — skip it entirely.
datas = []
binaries = []
hiddenimports = []
