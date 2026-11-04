# -*- coding: utf-8 -*-
"""数据模型与显示格式化工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def fmt_unit_price(value: Optional[float]) -> str:
    """元/金，统一保留 5 位小数，便于横向比较。"""
    if value is None:
        return "—"
    return f"{value:.5f}"


def fmt_ratio(value: Optional[float]) -> str:
    """1 元 = N 金。"""
    if value is None:
        return "—"
    return f"{value:,.2f}"


def fmt_gold(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}"


def fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"¥{value:,.2f}"


def fmt_time(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    return value.strftime("%H:%M:%S")


def fmt_percent(value: float) -> str:
    return f"{value:+.1f}%"


@dataclass
class Offer:
    """一条收货商家报价。"""

    platform: str
    unit_price: float          # 元 / 金（到手单价，越高越划算）
    ratio: float               # 1 元 = ratio 金
    stock: Optional[float] = None       # 收货数量（金）
    min_gold: Optional[float] = None    # 起收（金）
    max_gold: Optional[float] = None    # 单笔上限（金）
    min_yuan: Optional[float] = None    # 最低金额（元）
    methods: str = ""          # 当面 / 邮寄
    note: str = ""
    merchant_id: str = ""

    @property
    def payout_per_10k(self) -> float:
        return 10_000 * self.unit_price


@dataclass
class PlatformResult:
    """一个平台的一次抓取结果。"""

    key: str
    name: str
    color: str
    source_url: str
    offers: list[Offer] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    fetched_at: Optional[datetime] = None
    stale: bool = False
    stale_reason: str = ""
    region: str = "cn"

    @property
    def best(self) -> Optional[Offer]:
        return self.offers[0] if self.offers else None

    @property
    def best_price(self) -> Optional[float]:
        return self.best.unit_price if self.best else None


def best_result_by_region(
    results: dict[str, PlatformResult],
) -> dict[str, PlatformResult]:
    """按服务器分组（国服怀旧 / 港澳台LIVE）分别找到手单价最高的平台。"""
    out: dict[str, PlatformResult] = {}
    by_region: dict[str, list[PlatformResult]] = {}
    for r in results.values():
        if not r.offers:
            continue
        by_region.setdefault(r.region, []).append(r)
    for region, candidates in by_region.items():
        out[region] = max(candidates, key=lambda r: r.best_price or 0)
    return out


def second_best_price(
    results: dict[str, PlatformResult],
    exclude_key: str,
    region: Optional[str] = None,
) -> Optional[float]:
    """在同一服务器分组内（可选），找排除某平台后的第二高单价。"""
    prices = []
    for k, r in results.items():
        if k == exclude_key or r.best_price is None:
            continue
        if region is not None and r.region != region:
            continue
        prices.append(r.best_price)
    return max(prices) if prices else None
