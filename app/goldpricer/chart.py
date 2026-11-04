# -*- coding: utf-8 -*-
"""卡片内的 7 日价格走势小图（纯 Tkinter Canvas，无额外依赖）。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, time, timedelta

from . import config


def _blend(fg: str, bg: str, alpha: float) -> str:
    """把前景色按 alpha 混到背景色上，用于曲线下方的浅色填充。"""
    fg = fg.lstrip("#")
    bg = bg.lstrip("#")
    fr, fg_, fb = int(fg[0:2], 16), int(fg[2:4], 16), int(fg[4:6], 16)
    br, bg_, bb = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
    r = round(fr * alpha + br * (1 - alpha))
    g = round(fg_ * alpha + bg_ * (1 - alpha))
    b = round(fb * alpha + bb * (1 - alpha))
    return f"#{r:02x}{g:02x}{b:02x}"


class TrendChart(tk.Canvas):
    def __init__(self, parent, app, color: str, height: int = 62):
        super().__init__(
            parent,
            bg=config.CARD,
            height=height,
            highlightthickness=0,
            bd=0,
        )
        self.app = app
        self.color = color
        self._points: list[tuple[datetime, float]] = []
        self._hover: int | None = None
        self._coords: list[tuple[int, float, float]] = []
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    def set_points(self, points: list[tuple[datetime, float]]):
        self._points = sorted(points, key=lambda item: item[0])
        self._hover = None
        self._draw()

    def _on_motion(self, event):
        if not self._coords:
            return
        nearest = None
        nearest_dist = 999
        for index, x, _y in self._coords:
            dist = abs(event.x - x)
            if dist < nearest_dist:
                nearest = index
                nearest_dist = dist
        hover = nearest if nearest_dist <= 14 else None
        if hover != self._hover:
            self._hover = hover
            self._draw()

    def _on_leave(self, _event):
        if self._hover is not None:
            self._hover = None
            self._draw()

    def _draw(self):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 40 or height < 30:
            return

        left, right = 18, 18
        top, bottom = 8, height - 15
        plot_w = max(1, width - left - right)
        plot_h = max(1, bottom - top)

        today = date.today()
        start = datetime.combine(today - timedelta(days=6), time.min)
        end = datetime.combine(today, time.max)
        total_seconds = max(1.0, (end - start).total_seconds())

        # 横轴：最近 7 天的日期（取每天中午作为标签位置）
        for index in range(7):
            day = today - timedelta(days=6 - index)
            center = datetime.combine(day, time(12, 0))
            x = left + (center - start).total_seconds() / total_seconds * plot_w
            color = config.GOLD if day == today else config.MUTED_DARK
            self.create_text(
                x,
                height - 2,
                text=f"{day.month:02d}.{day.day:02d}",
                fill=color,
                font=(self.app.family, 7),
                anchor="s",
            )

        # 三条水平网格线
        for fraction in (0.0, 0.5, 1.0):
            y = top + plot_h * fraction
            self.create_line(
                left,
                y,
                width - right,
                y,
                fill=config.BORDER_SOFT,
                dash=(2, 4),
            )

        points = [
            (ts, price)
            for ts, price in self._points
            if start <= ts <= end and price and price > 0
        ]
        if not points:
            self.create_text(
                width / 2,
                top + plot_h / 2,
                text="近7天暂无本地记录",
                fill=config.MUTED,
                font=(self.app.family, 8),
            )
            self._coords = []
            return

        values = [price for _ts, price in points]
        vmin, vmax = min(values), max(values)
        if vmax <= vmin:
            pad = max(vmin * 0.004, 0.0001)
            vmin -= pad
            vmax += pad
        else:
            pad = max((vmax - vmin) * 0.15, 0.0001)
            vmin -= pad
            vmax += pad
        span = vmax - vmin

        def x_of(ts: datetime) -> float:
            return left + (ts - start).total_seconds() / total_seconds * plot_w

        def y_of(value: float) -> float:
            return top + (vmax - value) / span * plot_h

        coords = [(x_of(ts), y_of(price)) for ts, price in points]

        # 曲线下的浅色填充
        if len(coords) > 1:
            tint = _blend(self.color, config.CARD, 0.16)
            polygon = coords + [(coords[-1][0], bottom), (coords[0][0], bottom)]
            self.create_polygon(*[value for point in polygon for value in point], fill=tint, outline="")
            self.create_line(
                *[value for point in coords for value in point],
                fill=self.color,
                width=2,
                capstyle="round",
                joinstyle="round",
            )

        # 数据点：点太多时只画最后一个，避免糊成一团
        self._coords = []
        show_all = len(coords) <= 24
        for index, ((ts, price), (x, y)) in enumerate(zip(points, coords)):
            self._coords.append((index, x, y))
            if not show_all and index != len(coords) - 1:
                continue
            is_last = index == len(coords) - 1
            radius = 3.2 if is_last else 2.0
            outline = config.GOLD if is_last else config.CARD
            self.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=self.color,
                outline=outline,
                width=1,
            )

        # 鼠标悬停：竖线 + 日期时间/价格
        if self._hover is not None and 0 <= self._hover < len(points):
            ts, price = points[self._hover]
            x = x_of(ts)
            y = y_of(price)
            self.create_line(x, top, x, bottom, fill=config.MUTED, dash=(2, 3))
            self.create_oval(
                x - 4, y - 4, x + 4, y + 4, outline=config.GOLD, width=1
            )
            self.create_text(
                width - right,
                2,
                text=f"{ts:%m.%d %H:%M}  {price:.5f}",
                fill=config.TEXT,
                font=(self.app.family, 7, "bold"),
                anchor="ne",
            )
