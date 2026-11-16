# -*- coding: utf-8 -*-
"""上次成功报价的本地缓存。

用途：某平台当前没有收货商家（例如 G买卖的收货商城为空）时，
仍然可以在界面上看到上一次成功抓到的报价，并明确标注为“上次数据”。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config
from .models import Offer, PlatformResult

CACHE_VERSION = 1


def _base_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "DragonNestGoldPrice"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "DragonNestGoldPrice"
        base.mkdir(parents=True, exist_ok=True)
    return base


def cache_path() -> Path:
    return _base_dir() / "last_prices.json"


def save_results(results: dict[str, PlatformResult]) -> None:
    """只缓存有报价的平台，避免用空结果覆盖上次数据。"""
    platforms = {}
    for key, result in results.items():
        if not result.offers:
            continue
        platforms[key] = {
            "key": result.key,
            "name": result.name,
            "color": result.color,
            "source_url": result.source_url,
            "region": result.region,
            "fetched_at": result.fetched_at.isoformat() if result.fetched_at else None,
            "offers": [asdict(offer) for offer in result.offers],
        }
    if not platforms:
        return
    payload = {
        "version": CACHE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "platforms": platforms,
    }
    path = cache_path()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    temp_path.replace(path)


def load_results() -> dict[str, PlatformResult]:
    path = cache_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    platforms = payload.get("platforms") or {}
    results: dict[str, PlatformResult] = {}
    for key, item in platforms.items():
        if key not in config.PLATFORMS:
            continue
        offers = []
        for raw in item.get("offers") or []:
            try:
                offers.append(
                    Offer(
                        platform=raw.get("platform") or key,
                        unit_price=float(raw["unit_price"]),
                        ratio=float(raw.get("ratio") or 0),
                        stock=raw.get("stock"),
                        min_gold=raw.get("min_gold"),
                        max_gold=raw.get("max_gold"),
                        min_yuan=raw.get("min_yuan"),
                        methods=raw.get("methods") or "",
                        note=raw.get("note") or "",
                        merchant_id=raw.get("merchant_id") or "",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not offers:
            continue
        fetched_at = None
        if item.get("fetched_at"):
            try:
                fetched_at = datetime.fromisoformat(item["fetched_at"])
            except ValueError:
                fetched_at = None
        meta = config.PLATFORMS[key]
        results[key] = PlatformResult(
            key=key,
            name=item.get("name") or meta["name"],
            color=item.get("color") or meta["color"],
            source_url=item.get("source_url") or meta["url"],
            offers=offers,
            ok=True,
            fetched_at=fetched_at,
            stale=True,
            stale_reason="上次数据",
            region=item.get("region") or meta.get("region", "cn"),
        )
    return results


def loaded_at(results: dict[str, PlatformResult]) -> Optional[datetime]:
    times = [r.fetched_at for r in results.values() if r.fetched_at]
    return max(times) if times else None
