# -*- coding: utf-8 -*-
"""程序入口。"""

import ctypes
import io
import os
import sys
import tempfile
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path

# --windowed 打包后 stdout/stderr 为 None，任何往它们写的库都会抛 AttributeError。
# 必须在导入 goldpricer（进而导入 curl_cffi）之前兜住。
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()


def _log_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "DragonNestGoldPrice"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir())
    return base / "app.log"


def _log(message: str):
    try:
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _log(f"start pid={os.getpid()} frozen={getattr(sys, 'frozen', False)}")
    enable_dpi_awareness()
    root = tk.Tk()
    from goldpricer.ui import PriceApp

    PriceApp(root)
    root.mainloop()
    _log("exit normally")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("CRASH\n" + traceback.format_exc())
        raise
