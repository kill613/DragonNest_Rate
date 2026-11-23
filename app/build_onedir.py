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
    # curl_cffi 自带的 libcurl 动态库和证书需要一并收集，
    # 否则打包后 DD373 会退回 Python 的 TLS 指纹，直接被 WAF 拦成验证页。
    "--collect-all=curl_cffi",
])
