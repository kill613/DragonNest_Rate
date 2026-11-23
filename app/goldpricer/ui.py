# -*- coding: utf-8 -*-
"""Tkinter 桌面界面。"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Optional

from . import config, storage
from .chart import TrendChart
from .fetchers import fetch_all, throttle_status
from .history import HistoryStore
from .models import (
    PlatformResult,
    best_result_by_region,
    fmt_gold,
    fmt_money,
    fmt_ratio,
    fmt_time,
    fmt_unit_price,
    second_best_price,
)


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def _split_methods(text: str) -> list[str]:
    if not text:
        return []
    for sep in ("，", ",", "、", "|"):
        text = text.replace(sep, "/")
    return [part.strip() for part in text.split("/") if part.strip()]


class ScrollArea(tk.Frame):
    """可滚动的内容区域。"""

    def __init__(self, parent, bg: str):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self.after_idle(self._update_scrollbar)

    def _update_scrollbar(self):
        if not self.winfo_exists():
            return
        try:
            need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        except tk.TclError:
            return
        mapped = bool(self.vbar.winfo_ismapped())
        if need and not mapped:
            self.vbar.pack(side="right", fill="y")
        elif not need and mapped:
            self.vbar.pack_forget()


class PriceCard(tk.Frame):
    """单个平台的收货报价卡片。"""

    def __init__(self, parent, app: "PriceApp", meta: dict):
        super().__init__(
            parent,
            bg=config.CARD,
            highlightbackground=config.BORDER,
            highlightthickness=1,
            bd=0,
        )
        self.app = app
        self.meta = meta
        self.key = meta["key"]
        self.color = meta["color"]
        self.result: Optional[PlatformResult] = None
        self._gold: Optional[float] = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # 顶部平台色条
        tk.Frame(self, bg=self.color, height=3, bd=0).grid(
            row=0, column=0, sticky="ew"
        )

        body = tk.Frame(self, bg=config.CARD)
        body.grid(row=1, column=0, sticky="nsew", padx=17, pady=(13, 13))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(11, weight=1)

        # 标题行
        head = tk.Frame(body, bg=config.CARD)
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(
            head,
            text=meta["name"],
            bg=config.CARD,
            fg=config.TEXT,
            font=(app.family, 15, "bold"),
        ).pack(side="left")
        tk.Label(
            head,
            text=meta.get("tag", "收货"),
            bg="#0d2030",
            fg=self.color,
            font=(app.family, 8, "bold"),
            padx=6,
            pady=2,
        ).pack(side="left", padx=8)
        self.best_badge = tk.Label(
            head,
            text="最高",
            bg=config.GOLD,
            fg="#241700",
            font=(app.family, 8, "bold"),
            padx=7,
            pady=2,
        )

        # 价格
        price_row = tk.Frame(body, bg=config.CARD)
        price_row.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.price_label = tk.Label(
            price_row,
            text="—",
            bg=config.CARD,
            fg=config.GOLD,
            font=(app.num_family, 31, "bold"),
        )
        self.price_label.pack(side="left")
        self.unit_label = tk.Label(
            price_row,
            text="元/金",
            bg=config.CARD,
            fg=config.MUTED,
            font=(app.family, 9),
        )
        self.unit_label.pack(side="left", anchor="s", padx=5, pady=7)

        self.ratio_label = tk.Label(
            body,
            text="1元 ≈ — 金",
            bg=config.CARD,
            fg=config.TEXT_SOFT,
            font=(app.family, 10),
            anchor="w",
        )
        self.ratio_label.grid(row=2, column=0, sticky="w", pady=(1, 0))

        # 折算
        self.payout_box = tk.Frame(body, bg="#10261f")
        self.payout_box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.payout_label = tk.Label(
            self.payout_box,
            text="输入金币数量查看折算",
            bg="#10261f",
            fg="#74e3aa",
            font=(app.family, 9),
            anchor="w",
            padx=8,
            pady=5,
        )
        self.payout_label.pack(fill="x")

        # 最近 7 天走势
        trend_head = tk.Frame(body, bg=config.CARD)
        trend_head.grid(row=4, column=0, sticky="ew", pady=(10, 1))
        tk.Label(
            trend_head,
            text="近7天走势",
            bg=config.CARD,
            fg=config.MUTED,
            font=(app.family, 8),
        ).pack(side="left")
        self.trend_range_label = tk.Label(
            trend_head,
            text="暂无记录",
            bg=config.CARD,
            fg=config.MUTED_DARK,
            font=(app.family, 7),
        )
        self.trend_range_label.pack(side="right")
        self.trend_chart = TrendChart(body, app, self.color, height=62)
        self.trend_chart.grid(row=5, column=0, sticky="ew")

        tk.Frame(body, bg=config.BORDER_SOFT, height=1, bd=0).grid(
            row=6, column=0, sticky="ew", pady=(8, 8)
        )

        # 三个数据格
        stats = tk.Frame(body, bg=config.CARD)
        stats.grid(row=7, column=0, sticky="ew")
        for col in range(3):
            stats.columnconfigure(col, weight=1)
        self.stat_labels = []
        self.stat_values = []
        for index, title in enumerate(("收货量", "起收", "单笔上限")):
            cell = tk.Frame(stats, bg=config.CARD)
            cell.grid(row=0, column=index, sticky="w")
            label = tk.Label(
                cell,
                text=title,
                bg=config.CARD,
                fg=config.MUTED_DARK,
                font=(app.family, 8),
                anchor="w",
            )
            label.pack(anchor="w")
            value = tk.Label(
                cell,
                text="—",
                bg=config.CARD,
                fg=config.TEXT_SOFT,
                font=(app.family, 9),
                anchor="w",
            )
            value.pack(anchor="w", pady=2)
            self.stat_labels.append(label)
            self.stat_values.append(value)

        # 交易方式标签
        self.tags_frame = tk.Frame(body, bg=config.CARD)
        self.tags_frame.grid(row=8, column=0, sticky="w", pady=(9, 0))

        # 备注
        self.note_label = tk.Label(
            body,
            text="等待获取报价",
            bg=config.CARD,
            fg=config.MUTED,
            font=(app.family, 8),
            anchor="w",
            justify="left",
            wraplength=285,
        )
        self.note_label.grid(row=9, column=0, sticky="ew", pady=(7, 0))

        # 其他报价
        self.extra_frame = tk.Frame(body, bg=config.CARD)
        self.extra_frame.grid(row=10, column=0, sticky="ew", pady=(6, 0))

        # 弹性空白，把底部信息推到卡片最下方
        tk.Frame(body, bg=config.CARD).grid(row=11, column=0, sticky="nsew")

        # 底部
        footer = tk.Frame(body, bg=config.CARD)
        footer.grid(row=12, column=0, sticky="ew", pady=(10, 0))
        self.updated_label = tk.Label(
            footer,
            text="尚未获取",
            bg=config.CARD,
            fg=config.MUTED_DARK,
            font=(app.family, 8),
        )
        self.updated_label.pack(side="left")
        self.copy_label = tk.Label(
            footer,
            text="复制",
            bg=config.CARD,
            fg=config.MUTED,
            font=(app.family, 8),
            cursor="hand2",
        )
        self.copy_label.pack(side="right", padx=10)
        self.copy_label.bind("<Button-1>", lambda _e: self.app.copy_card(self))
        self.link_label = tk.Label(
            footer,
            text="打开来源 ↗",
            bg=config.CARD,
            fg=self.color,
            font=(app.family, 8),
            cursor="hand2",
        )
        self.link_label.pack(side="right")
        self.link_label.bind("<Button-1>", lambda _e: self._open_source())

    def _open_source(self):
        url = self.result.source_url if self.result else self.meta["url"]
        webbrowser.open(url)

    def set_best(self, is_best: bool):
        if is_best:
            self.best_badge.pack(side="right")
        else:
            self.best_badge.pack_forget()

    def _set_price(self, text: str, color: str, size: int, unit: str):
        self.price_label.config(
            text=text, fg=color, font=(self.app.num_family, size, "bold")
        )
        self.unit_label.config(text=unit)

    def set_loading(self):
        self.result = None
        self._set_price("···", config.GOLD, 31, "元/金")
        self.ratio_label.config(text="正在获取最新报价…")
        self.payout_label.config(text="正在连接平台")
        self.trend_range_label.config(text="读取中…", fg=config.MUTED_DARK)
        for title, label in zip(("收货量", "起收", "单笔上限"), self.stat_labels):
            label.config(text=title, fg=config.MUTED_DARK)
        for value in self.stat_values:
            value.config(text="—")
        self._clear_tags()
        self._clear_extra()
        self.note_label.config(text="正在连接平台，请稍候", fg=config.MUTED)
        self.updated_label.config(text="获取中…", fg=config.GOLD)
        self.set_best(False)

    def _clear_tags(self):
        for child in self.tags_frame.winfo_children():
            child.destroy()

    def _clear_extra(self):
        for child in self.extra_frame.winfo_children():
            child.destroy()

    def _render_tags(self, methods: str):
        self._clear_tags()
        parts = _split_methods(methods)
        for part in parts[:3]:
            tk.Label(
                self.tags_frame,
                text=part,
                bg="#1b2e4b",
                fg="#cfe2ff",
                font=(self.app.family, 8),
                padx=7,
                pady=2,
            ).pack(side="left", padx=5)

    def _render_extra(self, offers):
        self._clear_extra()
        if not offers:
            return
        tk.Label(
            self.extra_frame,
            text="其他收货商家",
            bg=config.CARD,
            fg=config.MUTED_DARK,
            font=(self.app.family, 8),
            anchor="w",
        ).pack(anchor="w")
        for offer in offers[:3]:
            line = (
                f"{fmt_unit_price(offer.unit_price)} 元/金"
                f"  ·  1元={fmt_ratio(offer.ratio)}金"
                f"  ·  收 {fmt_gold(offer.stock)}"
            )
            tk.Label(
                self.extra_frame,
                text=line,
                bg=config.CARD,
                fg=config.TEXT_SOFT,
                font=(self.app.family, 8),
                anchor="w",
                justify="left",
                wraplength=280,
            ).pack(anchor="w", pady=2)
        if len(offers) > 3:
            tk.Label(
                self.extra_frame,
                text=f"另有 {len(offers) - 3} 家未显示",
                bg=config.CARD,
                fg=config.MUTED_DARK,
                font=(self.app.family, 8),
                anchor="w",
            ).pack(anchor="w", pady=2)

    def set_result(self, result: PlatformResult):
        self.result = result
        best = result.best
        if not result.ok and not best:
            self._set_price("获取失败", config.RED, 17, "")
            self.ratio_label.config(text="点击右上角重试")
            for title, label in zip(("收货量", "起收", "单笔上限"), self.stat_labels):
                label.config(text=title)
            for value in self.stat_values:
                value.config(text="—")
            self.payout_label.config(text="暂无可用报价")
            self._clear_tags()
            self._clear_extra()
            self.note_label.config(text=result.error or "平台获取失败", fg=config.RED)
            self.updated_label.config(text="获取失败", fg=config.RED)
            self.set_best(False)
            return

        if not best:
            self._set_price("暂无", config.MUTED, 22, "")
            self.ratio_label.config(text="暂无收货商家")
            for title, label in zip(("收货量", "起收", "单笔上限"), self.stat_labels):
                label.config(text=title)
            for value in self.stat_values:
                value.config(text="—")
            self.payout_label.config(text="暂无可用报价")
            self._clear_tags()
            self._clear_extra()
            if self.key == "gmmsj":
                empty_note = "收货商城当前没有收货商家"
            else:
                empty_note = "平台当前没有该区服的收货报价"
            self.note_label.config(text=empty_note, fg=config.MUTED)
            self.updated_label.config(
                text=f"抓取于 {fmt_time(result.fetched_at)}", fg=config.MUTED_DARK
            )
            return

        self._set_price(
            fmt_unit_price(best.unit_price),
            config.GOLD if not result.stale else "#c9a86a",
            31,
            "元/金",
        )
        self.ratio_label.config(text=f"1元 ≈ {fmt_ratio(best.ratio)} 金")
        self.stat_values[0].config(
            text=f"{fmt_gold(best.stock)} 金" if best.stock is not None else "—"
        )
        self.stat_values[1].config(
            text=f"{fmt_gold(best.min_gold)} 金" if best.min_gold is not None else "—"
        )

        if best.max_gold is not None:
            self.stat_labels[2].config(text="单笔上限")
            self.stat_values[2].config(text=f"{fmt_gold(best.max_gold)} 金")
        elif best.min_yuan is not None:
            self.stat_labels[2].config(text="最低金额")
            self.stat_values[2].config(text=fmt_money(best.min_yuan))
        else:
            self.stat_labels[2].config(text="单笔上限")
            self.stat_values[2].config(text="—")

        self._render_tags(best.methods)
        note = best.note or "收货商家实时报价"
        if result.stale:
            note = f"{note} · 上次数据"
        self.note_label.config(text=note, fg=config.ORANGE if result.stale else config.MUTED)
        self._render_extra(result.offers[1:])

        if result.stale:
            reason = result.stale_reason or "上次数据"
            self.updated_label.config(
                text=f"显示 {fmt_time(result.fetched_at)} 数据 · {reason}",
                fg=config.ORANGE,
            )
        else:
            self.updated_label.config(
                text=f"抓取于 {fmt_time(result.fetched_at)}", fg=config.MUTED_DARK
            )
        self.update_payout(self.app.get_gold_amount())

    def update_payout(self, gold: Optional[float]):
        self._gold = gold
        if not self.result or not self.result.best:
            self.payout_label.config(text="暂无可用报价")
            return
        if gold is None:
            self.payout_label.config(text="输入金币数量查看折算")
            return
        amount = gold * self.result.best.unit_price
        self.payout_label.config(
            text=f"{fmt_gold(gold)} 金 ≈ {fmt_money(amount)}"
        )

    def set_trend(self, points: list):
        chart_points = [(point.ts, point.unit_price) for point in points]
        self.trend_chart.set_points(chart_points)
        if not points:
            self.trend_range_label.config(text="暂无记录", fg=config.MUTED_DARK)
        elif len(points) == 1:
            self.trend_range_label.config(
                text=f"{points[-1].unit_price:.5f} · 积累中", fg=config.GOLD
            )
        else:
            values = [point.unit_price for point in points]
            self.trend_range_label.config(
                text=f"{min(values):.5f} ~ {max(values):.5f}",
                fg=config.MUTED,
            )


class PriceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.results: dict[str, PlatformResult] = storage.load_results()
        self._cache_time = storage.loaded_at(self.results)
        self.history = HistoryStore()
        self.history.load()
        # 把上次缓存的价格也补进走势历史（只补一次，按时间戳去重）。
        for result in self.results.values():
            if result.best is not None and result.fetched_at is not None:
                self.history.record(
                    result.key,
                    result.best.unit_price,
                    result.best.ratio,
                    result.fetched_at,
                )
        self.history.save()
        self._fetching = False
        self._last_fetch_end = 0.0
        self._auto_job = None
        self._amount_job = None
        self._restore_job = None
        self._status_base = "准备就绪"
        self._closed = False
        self._gold_var = tk.StringVar(value="10000")
        self._auto_var = tk.BooleanVar(value=True)
        self._status_var = tk.StringVar(value="准备就绪")

        self._setup_window()
        self._setup_fonts()
        self._setup_style()
        self._build_ui()
        self._bind_keys()

        for key, card in self.cards.items():
            card.set_trend(self.history.points(key))

        if self.results:
            best_by_region = best_result_by_region(self.results)
            best_keys = {r.key for r in best_by_region.values()}
            for key, card in self.cards.items():
                result = self.results.get(key)
                if result is not None:
                    card.set_result(result)
                card.set_best(key in best_keys)
            self._render_summary(best_by_region)
            self._update_calc()
            self.last_update_label.config(
                text=f"上次更新：{fmt_time(self._cache_time)}"
            )
            self._set_status("已载入上次数据，正在刷新…", config.MUTED)

        self.root.after(350, self.refresh)
        if self._auto_var.get():
            self._schedule_auto()
        self._setup_tray()

    # ------------------------------------------------------------------ 系统托盘
    def _setup_tray(self):
        """最小化缩到系统托盘：任务栏不显示，托盘图标双击/单击恢复。"""
        self._tray_queue: queue.Queue = queue.Queue()
        self._tray_intercept_enabled = False
        try:
            from PIL import Image
            from pystray import Icon as PystrayIcon, Menu as PystrayMenu, MenuItem
        except Exception:
            self._tray_icon = None
            return

        icon_path = resource_path("assets/icon.ico")
        try:
            if icon_path.exists():
                image = Image.open(icon_path)
            else:
                image = Image.new("RGBA", (64, 64), (246, 196, 83, 255))
        except Exception:
            image = Image.new("RGBA", (64, 64), (246, 196, 83, 255))

        def on_show(icon, item):
            self._tray_queue.put("show")

        def on_quit(icon, item):
            self._tray_queue.put("quit")

        menu = PystrayMenu(
            MenuItem("显示主窗口", on_show, default=True),
            MenuItem("退出", on_quit),
        )
        self._tray_icon = PystrayIcon(
            "dn_gold_pricer",
            image,
            "龙之谷金币查价器（双击恢复）",
            menu,
        )
        try:
            self._tray_icon.run_detached()
        except Exception:
            self._tray_icon = None
            return

        # 轮询托盘线程发来的消息（show / quit）
        self.root.after(300, self._poll_tray_queue)
        # 延迟绑定最小化拦截：避免启动期 Unmap 事件误把窗口藏起来
        self.root.after(1500, self._arm_minimize_intercept)

    def _arm_minimize_intercept(self):
        if self._closed:
            return
        self._tray_intercept_enabled = True
        self.root.bind("<Unmap>", self._on_root_unmap)

    def _on_root_unmap(self, event):
        if not self._tray_intercept_enabled:
            return
        if event.widget is not self.root:
            return
        if str(self.root.state()) == "iconic":
            self.root.after(20, self._hide_to_tray)

    def _hide_to_tray(self):
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def _poll_tray_queue(self):
        if self._closed:
            return
        try:
            while True:
                msg = self._tray_queue.get_nowait()
                if msg == "show":
                    self._restore_from_tray()
                elif msg == "quit":
                    self._on_close()
                    return
        except queue.Empty:
            pass
        self.root.after(300, self._poll_tray_queue)

    def _restore_from_tray(self):
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 基础
    def _setup_window(self):
        self.root.title(f"{config.APP_NAME} · {config.GAME_NAME}")
        self.root.configure(bg=config.BG)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        total = len(config.PLATFORMS)
        width = min(420 * total + 120, 1360, max(960, screen_w - 60))
        height = min(960, max(640, screen_h - 80))
        self.root.minsize(min(240 * total + 80, width), min(680, height))
        self.root.maxsize(1360, screen_h - 40)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 16)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._set_dark_title_bar)

    def _set_dark_title_bar(self):
        """让 Windows 标题栏与深色界面协调（失败时保持系统默认）。"""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1)
            for attribute in (20, 19):
                try:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                    )
                except Exception:
                    pass
            # Windows 11：标题栏/文字颜色（COLORREF = 0x00BBGGRR）
            try:
                caption = ctypes.c_int(0x0020120B)  # #0b1220
                text = ctypes.c_int(0x00FFEEE9)     # #e9eeff
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)
                )
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 36, ctypes.byref(text), ctypes.sizeof(text)
                )
            except Exception:
                pass
        except Exception:
            pass

    def _setup_fonts(self):
        available = set(tkfont.families(self.root))
        self.family = (
            config.FONT_FAMILY
            if config.FONT_FAMILY in available
            else config.FONT_FALLBACK
            if config.FONT_FALLBACK in available
            else "TkDefaultFont"
        )
        self.num_family = "Segoe UI" if "Segoe UI" in available else self.family

    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Vertical.TScrollbar",
            background=config.CARD,
            troughcolor=config.BG,
            bordercolor=config.BG,
            arrowcolor=config.MUTED,
            darkcolor=config.BG,
            lightcolor=config.BG,
            width=8,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", config.BORDER)],
        )

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        self._build_header()

        self.footer = tk.Frame(self.root, bg="#080e18")
        self.footer.pack(side="bottom", fill="x")
        self._build_footer()

        self.scroll = ScrollArea(self.root, config.BG)
        self.scroll.pack(fill="both", expand=True)
        content = self.scroll.inner
        content.configure(padx=0, pady=0)

        wrapper = tk.Frame(content, bg=config.BG)
        wrapper.pack(fill="both", expand=True, padx=26, pady=12)
        wrapper.columnconfigure(0, weight=1)

        self._build_summary(wrapper)
        self._build_cards(wrapper)
        self._build_conclusion(wrapper)

        tip = tk.Frame(wrapper, bg=config.BG)
        tip.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(
            tip,
            text="小提示：按「元/金」比较，数值越高，卖出同样金币到手越多；"
            "「1元=N金」则是越低越划算。",
            bg=config.BG,
            fg=config.MUTED,
            font=(self.family, 8),
            anchor="w",
        ).pack(side="left")

    def _build_header(self):
        header = tk.Frame(self.root, bg=config.BG)
        header.pack(side="top", fill="x")
        inner = tk.Frame(header, bg=config.BG)
        inner.pack(fill="x", padx=28, pady=12)
        inner.columnconfigure(0, weight=1)

        left = tk.Frame(inner, bg=config.BG)
        left.grid(row=0, column=0, sticky="w")

        icon = tk.Canvas(left, width=50, height=50, bg=config.BG, highlightthickness=0)
        icon.pack(side="left", padx=13)
        icon.create_oval(2, 2, 48, 48, fill=config.GOLD, outline=config.GOLD_LIGHT, width=1)
        icon.create_oval(9, 9, 41, 41, fill="#e0a92b", outline="#f8d97b", width=1)
        icon.create_text(
            25,
            25,
            text="金",
            fill="#2a1b00",
            font=(self.family, 18, "bold"),
        )

        title_box = tk.Frame(left, bg=config.BG)
        title_box.pack(side="left")
        title_row = tk.Frame(title_box, bg=config.BG)
        title_row.pack(anchor="w")
        tk.Label(
            title_row,
            text=config.APP_NAME,
            bg=config.BG,
            fg=config.TEXT,
            font=(self.family, 19, "bold"),
        ).pack(side="left")
        tk.Label(
            title_row,
            text="怀旧服",
            bg="#2a2110",
            fg=config.GOLD,
            font=(self.family, 8, "bold"),
            padx=7,
            pady=2,
        ).pack(side="left", padx=9, pady=3)

        subtitle = (
            f"{config.SERVER_LABEL}  ·  游戏币收货商家实时比价"
        )
        tk.Label(
            title_box,
            text=subtitle,
            bg=config.BG,
            fg=config.MUTED,
            font=(self.family, 9),
        ).pack(anchor="w", pady=4)

        right = tk.Frame(inner, bg=config.BG)
        right.grid(row=0, column=1, sticky="e")

        status_box = tk.Frame(right, bg=config.BG)
        status_box.pack(side="left", padx=18)
        self.status_dot = tk.Canvas(
            status_box, width=9, height=9, bg=config.BG, highlightthickness=0
        )
        self.status_dot.pack(side="left", padx=7)
        self._dot = self.status_dot.create_oval(
            1, 1, 8, 8, fill=config.MUTED, outline=""
        )
        tk.Label(
            status_box,
            textvariable=self._status_var,
            bg=config.BG,
            fg=config.TEXT_SOFT,
            font=(self.family, 9),
        ).pack(side="left")

        self.fetch_btn = tk.Button(
            right,
            text="获取最新价格",
            command=self.refresh,
            bg=config.GOLD,
            fg="#211600",
            activebackground=config.GOLD_LIGHT,
            activeforeground="#211600",
            disabledforeground="#6d5a2a",
            font=(self.family, 10, "bold"),
            relief="flat",
            bd=0,
            padx=20,
            pady=9,
            cursor="hand2",
            takefocus=0,
        )
        self.fetch_btn.pack(side="left")
        self.fetch_btn.bind(
            "<Enter>",
            lambda _e: self.fetch_btn.config(bg=config.GOLD_LIGHT)
            if str(self.fetch_btn["state"]) == "normal"
            else None,
        )
        self.fetch_btn.bind(
            "<Leave>",
            lambda _e: self.fetch_btn.config(bg=config.GOLD)
            if str(self.fetch_btn["state"]) == "normal"
            else None,
        )

        tk.Frame(self.root, bg=config.BORDER_SOFT, height=1).pack(
            side="top", fill="x", padx=28
        )

    def _build_summary(self, parent):
        panel = tk.Frame(
            parent,
            bg=config.SURFACE,
            highlightbackground=config.BORDER,
            highlightthickness=1,
            bd=0,
        )
        panel.grid(row=0, column=0, sticky="ew")
        panel.columnconfigure(0, weight=5)
        panel.columnconfigure(2, weight=4)
        panel.columnconfigure(4, weight=3)

        # 左：最高价（国服怀旧 / 港澳台LIVE 两行，分别计算）
        left = tk.Frame(panel, bg=config.SURFACE)
        left.grid(row=0, column=0, sticky="nsew", padx=(21, 14), pady=(15, 14))
        head = tk.Frame(left, bg=config.SURFACE)
        head.pack(fill="x")
        tk.Label(
            head,
            text="当前最高到手单价（按服务器分组）",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 9),
        ).pack(side="left")
        self.summary_badge = tk.Label(
            head,
            text="最优",
            bg=config.GOLD,
            fg="#241700",
            font=(self.family, 8, "bold"),
            padx=7,
            pady=1,
        )

        # 国服怀旧行
        cn_row = tk.Frame(left, bg=config.SURFACE)
        cn_row.pack(anchor="w", pady=(6, 0))
        tk.Label(
            cn_row, text="国服怀旧", bg=config.SURFACE, fg=config.ORANGE,
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 8))
        self.best_price_label = tk.Label(
            cn_row, text="—", bg=config.SURFACE, fg=config.GOLD,
            font=(self.num_family, 26, "bold"),
        )
        self.best_price_label.pack(side="left")
        tk.Label(
            cn_row, text="元/金", bg=config.SURFACE, fg=config.MUTED,
            font=(self.family, 9),
        ).pack(side="left", anchor="s", padx=5, pady=5)
        self.best_platform_label = tk.Label(
            left, text="等待获取报价", bg=config.SURFACE, fg=config.MUTED,
            font=(self.family, 8), anchor="w",
        )
        self.best_platform_label.pack(anchor="w", pady=1)

        # 港澳台LIVE 行
        tw_row = tk.Frame(left, bg=config.SURFACE)
        tw_row.pack(anchor="w", pady=(6, 0))
        tk.Label(
            tw_row, text="港澳台LIVE", bg=config.SURFACE, fg="#c084fc",
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 8))
        self.best_tw_price_label = tk.Label(
            tw_row, text="—", bg=config.SURFACE, fg=config.GOLD,
            font=(self.num_family, 26, "bold"),
        )
        self.best_tw_price_label.pack(side="left")
        tk.Label(
            tw_row, text="元/金", bg=config.SURFACE, fg=config.MUTED,
            font=(self.family, 9),
        ).pack(side="left", anchor="s", padx=5, pady=5)
        self.best_tw_platform_label = tk.Label(
            left, text="—", bg=config.SURFACE, fg=config.MUTED,
            font=(self.family, 8), anchor="w",
        )
        self.best_tw_platform_label.pack(anchor="w", pady=1)

        self._separator(panel, 1)

        # 中：折算（国服 / 港澳台 分别折算）
        middle = tk.Frame(panel, bg=config.SURFACE)
        middle.grid(row=0, column=2, sticky="nsew", padx=18, pady=(15, 14))
        tk.Label(
            middle,
            text="出售金币，按各自最高折算",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 9),
            anchor="w",
        ).pack(anchor="w")
        entry_row = tk.Frame(middle, bg=config.SURFACE)
        entry_row.pack(anchor="w", pady=5)
        self.amount_entry = tk.Entry(
            entry_row,
            textvariable=self._gold_var,
            width=9,
            bg="#0c1728",
            fg=config.GOLD,
            insertbackground=config.GOLD,
            relief="flat",
            bd=0,
            font=(self.num_family, 15, "bold"),
            justify="right",
            highlightthickness=1,
            highlightbackground=config.BORDER,
            highlightcolor=config.GOLD,
        )
        self.amount_entry.pack(side="left", ipady=5)
        tk.Label(
            entry_row,
            text="金",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 10),
        ).pack(side="left", padx=6)

        # 国服折算
        cn_calc = tk.Frame(middle, bg=config.SURFACE)
        cn_calc.pack(anchor="w", pady=(4, 0))
        tk.Label(
            cn_calc, text="国服", bg=config.SURFACE, fg=config.ORANGE,
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.calc_result_label = tk.Label(
            cn_calc, text="≈ —", bg=config.SURFACE, fg=config.GREEN,
            font=(self.num_family, 18, "bold"), anchor="w",
        )
        self.calc_result_label.pack(side="left")

        # 港澳台折算
        tw_calc = tk.Frame(middle, bg=config.SURFACE)
        tw_calc.pack(anchor="w", pady=(4, 0))
        tk.Label(
            tw_calc, text="港澳台", bg=config.SURFACE, fg="#c084fc",
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.calc_tw_result_label = tk.Label(
            tw_calc, text="≈ —", bg=config.SURFACE, fg=config.GREEN,
            font=(self.num_family, 18, "bold"), anchor="w",
        )
        self.calc_tw_result_label.pack(side="left")
        self.calc_hint_label = tk.Label(
            middle,
            text="输入数量后自动计算",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 8),
            anchor="w",
        )
        self.calc_hint_label.pack(anchor="w", pady=(4, 0))

        self._separator(panel, 3)

        # 右：价差（国服 / 港澳台 分别比较）
        right = tk.Frame(panel, bg=config.SURFACE)
        right.grid(row=0, column=4, sticky="nsew", padx=(18, 20), pady=(15, 14))
        tk.Label(
            right,
            text="组内价差参考",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 9),
            anchor="w",
        ).pack(anchor="w")

        cn_delta = tk.Frame(right, bg=config.SURFACE)
        cn_delta.pack(anchor="w", pady=(6, 0))
        tk.Label(
            cn_delta, text="国服", bg=config.SURFACE, fg=config.ORANGE,
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.delta_label = tk.Label(
            cn_delta, text="—", bg=config.SURFACE, fg=config.GREEN,
            font=(self.num_family, 17, "bold"), anchor="w",
        )
        self.delta_label.pack(side="left")
        self.delta_money_label = tk.Label(
            right, text="每万金多赚 —", bg=config.SURFACE,
            fg=config.TEXT_SOFT, font=(self.family, 8), anchor="w",
        )
        self.delta_money_label.pack(anchor="w", pady=1)

        tw_delta = tk.Frame(right, bg=config.SURFACE)
        tw_delta.pack(anchor="w", pady=(6, 0))
        tk.Label(
            tw_delta, text="港澳台", bg=config.SURFACE, fg="#c084fc",
            font=(self.family, 8, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.delta_tw_label = tk.Label(
            tw_delta, text="—", bg=config.SURFACE, fg=config.MUTED,
            font=(self.num_family, 17, "bold"), anchor="w",
        )
        self.delta_tw_label.pack(side="left")
        self.delta_tw_money_label = tk.Label(
            right, text="每万金多赚 —", bg=config.SURFACE,
            fg=config.TEXT_SOFT, font=(self.family, 8), anchor="w",
        )
        self.delta_tw_money_label.pack(anchor="w", pady=1)
        self.delta_hint_label = tk.Label(
            right,
            text="同一服务器分组内比较",
            bg=config.SURFACE,
            fg=config.MUTED,
            font=(self.family, 8),
            anchor="w",
        )
        self.delta_hint_label.pack(anchor="w", pady=(4, 0))

    def _separator(self, parent, column):
        holder = tk.Frame(parent, bg=config.SURFACE)
        holder.grid(row=0, column=column, sticky="ns", pady=17)
        tk.Frame(holder, bg=config.BORDER_SOFT, width=1).pack(fill="y")

    def _build_cards(self, parent):
        cards = tk.Frame(parent, bg=config.BG)
        cards.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        keys = list(config.PLATFORMS.keys())
        for col in range(len(keys)):
            cards.columnconfigure(col, weight=1, uniform="card")
        self.cards: dict[str, PriceCard] = {}
        for index, key in enumerate(keys):
            meta = dict(config.PLATFORMS[key])
            meta["key"] = key
            card = PriceCard(cards, self, meta)
            padx = (0, 13) if index < len(keys) - 1 else (0, 0)
            card.grid(row=0, column=index, sticky="nsew", padx=padx)
            card.set_loading()
            self.cards[key] = card

    def _build_conclusion(self, parent):
        panel = tk.Frame(
            parent,
            bg="#10251f",
            highlightbackground="#1e4d3a",
            highlightthickness=1,
            bd=0,
        )
        panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        tk.Label(
            panel,
            text="比价结论",
            bg="#10251f",
            fg=config.GOLD,
            font=(self.family, 9, "bold"),
        ).pack(side="left", padx=(14, 12), pady=11)
        self.conclusion_label = tk.Label(
            panel,
            text="获取报价后，这里会给出更划算的平台建议。",
            bg="#10251f",
            fg=config.TEXT_SOFT,
            font=(self.family, 9),
            anchor="w",
        )
        self.conclusion_label.pack(side="left", fill="x", expand=True, pady=11)

    def _build_footer(self):
        inner = tk.Frame(self.footer, bg="#080e18")
        inner.pack(fill="x", padx=28, pady=9)
        pk = dict(bg="#080e18")

        self.last_update_label = tk.Label(
            inner,
            text="上次更新：—",
            fg=config.MUTED_DARK,
            font=(self.family, 8),
            **pk,
        )
        self.last_update_label.pack(side="left")
        tk.Label(
            inner,
            text="  ·  F5 刷新",
            fg=config.MUTED_DARK,
            font=(self.family, 8),
            **pk,
        ).pack(side="left")

        self.auto_check = tk.Checkbutton(
            inner,
            text=f"每 {config.AUTO_REFRESH_MS // 1000} 秒自动刷新",
            variable=self._auto_var,
            command=self._toggle_auto,
            bg="#080e18",
            fg=config.MUTED,
            activebackground="#080e18",
            activeforeground=config.TEXT_SOFT,
            selectcolor=config.CARD,
            font=(self.family, 8),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=0,
        )
        self.auto_check.pack(side="left", padx=24)

        tk.Label(
            inner,
            text=f"v{config.APP_VERSION}",
            fg=config.MUTED_DARK,
            font=(self.family, 8),
            **pk,
        ).pack(side="right", padx=12)
        tk.Label(
            inner,
            text=config.DISCLAIMER,
            fg=config.MUTED_DARK,
            font=(self.family, 8),
            **pk,
        ).pack(side="right")

    def _bind_keys(self):
        self.root.bind("<F5>", lambda _e: self.refresh())
        self._gold_var.trace_add("write", lambda *_: self._schedule_amount_update())
        self.amount_entry.bind("<Return>", lambda _e: self._update_calc())

    # ------------------------------------------------------------------ 交互
    def _schedule_amount_update(self):
        if self._amount_job is not None:
            try:
                self.root.after_cancel(self._amount_job)
            except Exception:
                pass
        self._amount_job = self.root.after(220, self._update_calc)

    def get_gold_amount(self) -> Optional[float]:
        raw = self._gold_var.get().strip().replace(",", "").replace("，", "")
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        if value <= 0 or value != value or value == float("inf"):
            return None
        return value

    def _update_calc(self):
        self._amount_job = None
        gold = self.get_gold_amount()
        best_by_region = best_result_by_region(self.results)
        for card in self.cards.values():
            card.update_payout(gold)

        cn_best = best_by_region.get("cn")
        tw_best = best_by_region.get("tw")

        if gold is None:
            self.calc_result_label.config(text="≈ —", fg=config.MUTED)
            self.calc_tw_result_label.config(text="≈ —", fg=config.MUTED)
            self.calc_hint_label.config(text="请输入大于 0 的金币数量")
            return

        # 国服折算
        if cn_best and cn_best.best:
            amount = gold * cn_best.best.unit_price
            self.calc_result_label.config(text=f"≈ {fmt_money(amount)}", fg=config.GREEN)
        else:
            self.calc_result_label.config(text="≈ —", fg=config.MUTED)

        # 港澳台折算
        if tw_best and tw_best.best:
            amount = gold * tw_best.best.unit_price
            self.calc_tw_result_label.config(text=f"≈ {fmt_money(amount)}", fg=config.GREEN)
        else:
            self.calc_tw_result_label.config(text="≈ —", fg=config.MUTED)

        self.calc_hint_label.config(text="分别按各组最高单价折算")

    def _set_status(self, text: str, color: str):
        self._status_base = text
        self._status_var.set(text)
        self.status_dot.itemconfigure(self._dot, fill=color)

    def refresh(self):
        if self._fetching or self._closed:
            return
        now = time.monotonic()
        if self._last_fetch_end and now - self._last_fetch_end < 2.0:
            return
        self._fetching = True
        if self._restore_job is not None:
            try:
                self.root.after_cancel(self._restore_job)
            except Exception:
                pass
            self._restore_job = None
        self.fetch_btn.config(state="disabled", text="获取中…", bg="#a8862e")
        self._set_status(f"正在连接 {len(config.PLATFORMS)} 个平台…", config.GOLD)
        if not self.results:
            for card in self.cards.values():
                card.set_loading()
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            results = fetch_all()
        except Exception as exc:  # noqa: BLE001
            results = {}
            for key, meta in config.PLATFORMS.items():
                results[key] = PlatformResult(
                    key=key,
                    name=meta["name"],
                    color=meta["color"],
                    source_url=meta["url"],
                    ok=False,
                    error=f"获取失败：{exc}",
                    region=meta.get("region", "cn"),
                )
        if not self._closed:
            try:
                self.root.after(0, self._apply_results, results)
            except tk.TclError:
                pass

    def _apply_results(self, fresh: dict[str, PlatformResult]):
        if self._closed:
            return
        merged: dict[str, PlatformResult] = {}
        for key in config.PLATFORMS:
            new = fresh.get(key)
            old = self.results.get(key)
            if new is None:
                if old is not None:
                    merged[key] = old
                else:
                    merged[key] = PlatformResult(
                        key=key,
                        name=config.PLATFORMS[key]["name"],
                        color=config.PLATFORMS[key]["color"],
                        source_url=config.PLATFORMS[key]["url"],
                        ok=False,
                        error="没有返回结果",
                        region=config.PLATFORMS[key].get("region", "cn"),
                    )
                continue
            if old is not None and old.offers and not new.offers:
                # 平台抓取成功但当前没有收货商家（例如 G买卖收货商城为空），
                # 保留上一次成功报价，明确标注为“上次数据”。
                old.stale = True
                old.stale_reason = "当前无商家" if new.ok else "更新失败"
                old.error = new.error or "当前无商家"
                merged[key] = old
            elif not new.ok and old is not None and old.offers:
                old.stale = True
                old.stale_reason = "更新失败"
                old.error = new.error
                merged[key] = old
            else:
                new.stale = False
                new.stale_reason = ""
                merged[key] = new

        self.results = merged
        try:
            storage.save_results(self.results)
        except Exception:
            pass

        # 只把本次真正抓到的报价写进走势历史，避免失败时把旧价格重复记成新点。
        for key, result in fresh.items():
            if result.ok and result.offers and result.best is not None:
                self.history.record(
                    key,
                    result.best.unit_price,
                    result.best.ratio,
                    result.fetched_at or datetime.now(),
                )
        self.history.save()
        self._fetching = False
        self._last_fetch_end = time.monotonic()
        self.fetch_btn.config(state="normal", text="获取最新价格", bg=config.GOLD)
        self.fetch_btn.bind(
            "<Enter>",
            lambda _e: self.fetch_btn.config(bg=config.GOLD_LIGHT)
            if str(self.fetch_btn["state"]) == "normal"
            else None,
        )

        best_by_region = best_result_by_region(self.results)
        best_keys = {r.key for r in best_by_region.values()}
        for key, card in self.cards.items():
            result = self.results.get(key)
            if result is not None:
                card.set_result(result)
            card.set_trend(self.history.points(key))
            card.set_best(key in best_keys)
        self._render_summary(best_by_region)

        ok_count = sum(1 for result in fresh.values() if result.ok)
        stale_count = sum(1 for result in self.results.values() if result.stale)
        total = len(config.PLATFORMS)
        now = datetime.now()
        self.last_update_label.config(text=f"上次更新：{fmt_time(now)}")

        if ok_count == total:
            if stale_count:
                status_text = f"{ok_count}/{total} 平台已更新 · {stale_count} 家显示上次数据"
                status_color = config.ORANGE
            else:
                status_text = f"{ok_count}/{total} 平台更新成功 · {fmt_time(now)}"
                status_color = config.GREEN
        elif ok_count > 0:
            extra = f" · {stale_count} 家显示上次数据" if stale_count else ""
            status_text = f"部分平台失败（{ok_count}/{total} 成功）{extra}"
            status_color = config.ORANGE
        else:
            status_text = "获取失败，请检查网络后重试"
            status_color = config.RED

        # 处于退避冷却的平台本轮不会发请求，明确告诉用户要等多久，
        # 否则点“获取最新价格”看起来像没反应。
        paused = [
            f"{config.PLATFORMS[key].get('short', key)} 约 {int(info['remain'] // 60) + 1} 分钟"
            for key, info in throttle_status().items()
            if info["reason"] and info["remain"] > 0
        ]
        if paused:
            status_text = f"{status_text} · {'、'.join(paused)}后重试"
            status_color = config.ORANGE
        self._set_status(status_text, status_color)

        self._update_calc()

    def _render_summary(self, best_by_region: dict[str, PlatformResult]):
        def render_group(
            best: Optional[PlatformResult],
            price_label, platform_label, delta_label, delta_money_label,
        ):
            if best is None or best.best is None:
                price_label.config(text="—", fg=config.MUTED)
                platform_label.config(text="暂无报价")
                delta_label.config(text="—", fg=config.MUTED)
                delta_money_label.config(text="每万金多赚 —")
                return
            offer = best.best
            price_label.config(
                text=fmt_unit_price(offer.unit_price),
                fg=config.GOLD if not best.stale else "#c9a86a",
            )
            stock = f" · 收货量 {fmt_gold(offer.stock)} 金" if offer.stock else ""
            prefix = "上次数据" if best.stale else "最高"
            platform_label.config(
                text=f"{prefix} · {best.name}（1元={fmt_ratio(offer.ratio)}金）{stock}"
            )
            second = second_best_price(self.results, best.key, region=best.region)
            if second is None or second <= 0:
                delta_label.config(text="—", fg=config.MUTED)
                delta_money_label.config(text="组内仅一家有报价")
                return
            pct = (offer.unit_price / second - 1.0) * 100.0
            diff = (offer.unit_price - second) * 10_000
            delta_label.config(text=f"+{pct:.1f}%", fg=config.GREEN)
            delta_money_label.config(text=f"每万金多赚 {fmt_money(diff)}")

        cn_best = best_by_region.get("cn")
        tw_best = best_by_region.get("tw")
        render_group(
            cn_best, self.best_price_label, self.best_platform_label,
            self.delta_label, self.delta_money_label,
        )
        render_group(
            tw_best, self.best_tw_price_label, self.best_tw_platform_label,
            self.delta_tw_label, self.delta_tw_money_label,
        )
        self.summary_badge.pack(side="left", padx=9)

        # 比价结论：国服优先建议
        if cn_best and cn_best.best:
            second = second_best_price(self.results, cn_best.key, region="cn")
            if second and second > 0:
                diff = (cn_best.best.unit_price - second) * 10_000
                self.conclusion_label.config(
                    text=(
                        f"国服怀旧优先卖 {cn_best.name}：每 1 万金多到手 "
                        f"{fmt_money(diff)}（较国服第二高）；港澳台LIVE为独立参考价，不与国服混算。"
                    ),
                    fg=config.GREEN,
                )
            else:
                self.conclusion_label.config(
                    text=f"国服怀旧目前仅 {cn_best.name} 有收货报价，以平台下单页为准。",
                    fg=config.TEXT_SOFT,
                )
        else:
            self.conclusion_label.config(
                text="获取报价后，这里会分别给出国服与港澳台LIVE的出手建议。",
                fg=config.TEXT_SOFT,
            )

    def copy_card(self, card: PriceCard):
        result = card.result
        if not result or not result.best:
            self._set_status(f"{card.meta['name']} 暂无可复制的报价", config.MUTED)
            return
        best = result.best
        lines = [
            f"{result.name} 收货价：{fmt_unit_price(best.unit_price)} 元/金"
            f"（1元={fmt_ratio(best.ratio)}金）",
            f"收货量：{fmt_gold(best.stock)} 金；起收：{fmt_gold(best.min_gold)} 金",
        ]
        if best.max_gold:
            lines.append(f"单笔上限：{fmt_gold(best.max_gold)} 金")
        if best.min_yuan:
            lines.append(f"最低金额：{fmt_money(best.min_yuan)}")
        if best.methods:
            lines.append(f"交易方式：{best.methods}")
        if result.stale:
            lines.append(f"备注：上次数据（{result.stale_reason or '未更新'}）")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self._set_status(f"已复制 {result.name} 报价", config.GREEN)
            self._restore_job = self.root.after(2200, self._restore_status)
        except tk.TclError:
            pass

    def _restore_status(self):
        self._restore_job = None
        if self._fetching:
            return
        if not self.results:
            self._set_status("准备就绪", config.MUTED)
            return
        ok_count = sum(1 for result in self.results.values() if result.ok)
        stale_count = sum(1 for result in self.results.values() if result.stale)
        total = len(config.PLATFORMS)
        if ok_count == total:
            if stale_count:
                self._set_status(
                    f"{ok_count}/{total} 平台已更新 · {stale_count} 家显示上次数据",
                    config.ORANGE,
                )
            else:
                self._set_status(f"{ok_count}/{total} 平台已更新", config.GREEN)
        elif ok_count > 0:
            self._set_status(
                f"部分平台失败（{ok_count}/{total} 成功）"
                + (f" · {stale_count} 家显示上次数据" if stale_count else ""),
                config.ORANGE,
            )
        else:
            self._set_status("获取失败，请检查网络后重试", config.RED)

    def _toggle_auto(self):
        if self._auto_var.get():
            self._schedule_auto()
            self._set_status("已开启自动刷新", config.GREEN)
        else:
            if self._auto_job is not None:
                try:
                    self.root.after_cancel(self._auto_job)
                except Exception:
                    pass
                self._auto_job = None
            self._set_status("已关闭自动刷新", config.MUTED)

    def _schedule_auto(self):
        if self._closed:
            return
        self._auto_job = self.root.after(config.AUTO_REFRESH_MS, self._auto_fire)

    def _auto_fire(self):
        self._auto_job = None
        if self._closed or not self._auto_var.get():
            return
        self.refresh()
        self._schedule_auto()

    def _on_close(self):
        self._closed = True
        if self._auto_job is not None:
            try:
                self.root.after_cancel(self._auto_job)
            except Exception:
                pass
        tray = getattr(self, "_tray_icon", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        self.root.destroy()
