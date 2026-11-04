# -*- coding: utf-8 -*-
"""程序入口。"""

import ctypes
import os
import sys
import tempfile
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path


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
