# -*- coding: utf-8 -*-
"""本地 7 日价格历史。

三个平台目前都没有公开的「收货价历史」接口，所以走势图由本软件
每次成功获取到的最高收货价累积而成；只保留最近 7 天。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import storage

HISTORY_DAYS = 8
MAX_POINTS = 3000
MIN_INTERVAL_SECONDS = 600


@dataclass
class PricePoint:
    ts: datetime
    unit_price: float
    ratio: float


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or storage.cache_path().with_name("price_history.json")
        self.data: dict[str, list[PricePoint]] = {}

    # ------------------------------------------------------------------ 读写
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        platforms = payload.get("platforms") or {}
        for key, items in platforms.items():
            points: list[PricePoint] = []
            for item in items or []:
                try:
                    points.append(
                        PricePoint(
                            ts=datetime.fromisoformat(item["ts"]),
                            unit_price=float(item["unit_price"]),
                            ratio=float(item.get("ratio") or 0),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            if points:
                points.sort(key=lambda p: p.ts)
                self.data[key] = points
        self._prune()

    def save(self) -> None:
        payload = {"version": 1, "platforms": {}}
        for key, points in self.data.items():
            if not points:
                continue
            payload["platforms"][key] = [
                {
                    "ts": p.ts.isoformat(timespec="seconds"),
                    "unit_price": p.unit_price,
                    "ratio": p.ratio,
                }
                for p in points
            ]
        try:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
            temp.replace(self.path)
        except OSError:
            pass

    # ------------------------------------------------------------------ 记录
    def record(
        self,
        key: str,
        unit_price: float,
        ratio: float,
        when: datetime | None = None,
    ) -> bool:
        if not unit_price or unit_price <= 0:
            return False
        ts = when or datetime.now()
        points = self.data.setdefault(key, [])
        if points:
            # 同一个时间点的缓存补录不要重复写入。
            if any(abs((point.ts - ts).total_seconds()) < 2 for point in points):
                return False
            last = points[-1]
            # 同价且 10 分钟内重复获取，不重复记点，避免曲线被刷新按钮挤满。
            if (
                abs(last.unit_price - unit_price) < 1e-12
                and abs((ts - last.ts).total_seconds()) < MIN_INTERVAL_SECONDS
            ):
                return False
        points.append(PricePoint(ts=ts, unit_price=unit_price, ratio=ratio))
        points.sort(key=lambda p: p.ts)
        if len(points) > MAX_POINTS:
            del points[: len(points) - MAX_POINTS]
        self._prune()
        return True

    def _prune(self) -> None:
        cutoff = datetime.now() - timedelta(days=HISTORY_DAYS)
        for key, points in list(self.data.items()):
            kept = [p for p in points if p.ts >= cutoff]
            if kept:
                self.data[key] = kept
            else:
                self.data.pop(key, None)

    # ------------------------------------------------------------------ 查询
    def points(self, key: str, days: int = 7) -> list[PricePoint]:
        cutoff = datetime.now() - timedelta(days=days)
        return [p for p in self.data.get(key, []) if p.ts >= cutoff]

    def daily_last(self, key: str, days: int = 7) -> list[tuple[date, float]]:
        """按自然日取当天最后一个价格；返回最近 7 天内有记录的日期。"""
        today = date.today()
        first_day = today - timedelta(days=days - 1)
        buckets: dict[date, PricePoint] = {}
        for point in self.data.get(key, []):
            day = point.ts.date()
            if day < first_day or day > today:
                continue
            buckets[day] = point
        return [(day, buckets[day].unit_price) for day in sorted(buckets)]
