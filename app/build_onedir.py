# -*- coding: utf-8 -*-
import PyInstaller.__main__

PyInstaller.__main__.run([
    "main.py",
    "--name=龙之谷金币查价器",
    "--onedir",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--icon=assets/icon.ico",
    "--add-data=assets;assets",
])
