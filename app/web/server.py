# -*- coding: utf-8 -*-
"""龙之谷金币查价器 · Web 版服务端

设计要点：
- 数据层（config / fetchers / models / storage / history）与桌面版完全共用，
  抓取与分组算价逻辑一处修改两边都生效。
- HTTP 层只用 Python 标准库，第三方依赖仅 lxml，镜像小、在路由器上构建快。
- 抓取在服务端后台按 60 秒周期跑，浏览器关掉也继续盯盘；多台设备访问同一份数据。
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent          # app/web
APP_DIR = BASE_DIR.parent                           # app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from goldpricer import config, storage  # noqa: E402
from goldpricer.fetchers import fetch_all  # noqa: E402
from goldpricer.history import HistoryStore  # noqa: E402
from goldpricer.models import (  # noqa: E402
    PlatformResult,
    best_result_by_region,
    fmt_gold,
    fmt_money,
    fmt_ratio,
    fmt_time,
    fmt_unit_price,
    second_best_price,
)

HOST = os.getenv("GOLDPRICER_HOST", "0.0.0.0")
PORT = int(os.getenv("GOLDPRICER_PORT", "8080"))
AUTO_SECONDS = int(
    os.getenv("GOLDPRICER_AUTO_SECONDS", str(config.AUTO_REFRESH_MS // 1000))
)


def split_methods(text: str) -> list[str]:
    """把「当面，邮寄」之类的交易方式拆成标签（与桌面版一致）。"""
    if not text:
        return []
    for sep in ("，", ",", "、", "|"):
        text = text.replace(sep, "/")
    return [part.strip() for part in text.split("/") if part.strip()]


class AppState:
    """服务端状态：一次抓取、所有访问者共享。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.results: dict[str, PlatformResult] = storage.load_results()
        self.history = HistoryStore()
        self.history.load()
        # 把上次缓存的价格补进走势历史（按时间戳去重，与桌面版一致）。
        for result in self.results.values():
            if result.best is not None and result.fetched_at is not None:
                self.history.record(
                    result.key,
                    result.best.unit_price,
                    result.best.ratio,
                    result.fetched_at,
                )
        self.history.save()

        self.fetching = False
        self.last_end = 0.0
        self.last_update: datetime | None = storage.loaded_at(self.results)
        self.status_text = "准备就绪"
        self.status_color = config.MUTED
        self._worker_lock = threading.Lock()

    # ------------------------------------------------------------------ 抓取
    def start_background(self):
        threading.Thread(target=self._loop, daemon=True, name="price-loop").start()

    def _loop(self):
        time.sleep(2)
        self.request_fetch()
        while True:
            time.sleep(AUTO_SECONDS)
            self.request_fetch()

    def request_fetch(self) -> bool:
        """触发一次抓取；正在抓取或刚抓完 2 秒内则忽略。"""
        with self.lock:
            if self.fetching:
                return False
            if self.last_end and time.monotonic() - self.last_end < 2.0:
                return False
            self.fetching = True
            self.status_text = f"正在连接 {len(config.PLATFORMS)} 个平台…"
            self.status_color = config.GOLD
        threading.Thread(target=self._fetch_worker, daemon=True, name="price-fetch").start()
        return True

    def _fetch_worker(self):
        try:
            fresh = fetch_all()
        except Exception as exc:  # noqa: BLE001
            fresh = {}
            for key, meta in config.PLATFORMS.items():
                fresh[key] = PlatformResult(
                    key=key,
                    name=meta["name"],
                    color=meta["color"],
                    source_url=meta["url"],
                    ok=False,
                    error=f"获取失败：{exc}",
                    region=meta.get("region", "cn"),
                )
        with self._worker_lock:
            self._apply_results(fresh)

    def _apply_results(self, fresh: dict[str, PlatformResult]):
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
                # 抓取成功但当前没有收货商家：保留上次报价，标注「上次数据」。
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

        with self.lock:
            self.results = merged
        try:
            storage.save_results(self.results)
        except Exception:  # noqa: BLE001
            pass

        # 只记录本次真正抓到的价格，失败时不要把旧价格重复记成新点。
        for key, result in fresh.items():
            if result.ok and result.offers and result.best is not None:
                self.history.record(
                    key,
                    result.best.unit_price,
                    result.best.ratio,
                    result.fetched_at or datetime.now(),
                )
        self.history.save()

        now = datetime.now()
        ok_count = sum(1 for result in fresh.values() if result.ok)
        stale_count = sum(1 for result in self.results.values() if result.stale)
        total = len(config.PLATFORMS)
        if ok_count == total:
            if stale_count:
                text = f"{ok_count}/{total} 平台已更新 · {stale_count} 家显示上次数据"
                color = config.ORANGE
            else:
                text = f"{ok_count}/{total} 平台更新成功 · {fmt_time(now)}"
                color = config.GREEN
        elif ok_count > 0:
            extra = f" · {stale_count} 家显示上次数据" if stale_count else ""
            text = f"部分平台失败（{ok_count}/{total} 成功）{extra}"
            color = config.ORANGE
        else:
            text = "获取失败，请检查网络后重试"
            color = config.RED

        with self.lock:
            self.fetching = False
            self.last_end = time.monotonic()
            self.last_update = now
            self.status_text = text
            self.status_color = color

    # ------------------------------------------------------------------ 输出
    def _region_block(self, best: PlatformResult | None) -> dict:
        if best is None or best.best is None:
            return {
                "price": "—",
                "price_num": 0,
                "price_color": config.MUTED,
                "platform": "暂无报价",
                "delta": "—",
                "delta_color": config.MUTED,
                "money": "每万金多赚 —",
                "ratio": "—",
            }
        offer = best.best
        stock = f" · 收货量 {fmt_gold(offer.stock)} 金" if offer.stock else ""
        prefix = "上次数据" if best.stale else "最高"
        block = {
            "price": fmt_unit_price(offer.unit_price),
            "price_num": offer.unit_price,
            "price_color": "#c9a86a" if best.stale else config.GOLD,
            "platform": f"{prefix} · {best.name}（1元={fmt_ratio(offer.ratio)}金）{stock}",
            "ratio": fmt_ratio(offer.ratio),
            "delta": "—",
            "delta_color": config.MUTED,
            "money": "组内仅一家有报价",
        }
        second = second_best_price(self.results, best.key, region=best.region)
        if second and second > 0:
            pct = (offer.unit_price / second - 1.0) * 100.0
            diff = (offer.unit_price - second) * 10_000
            block["delta"] = f"+{pct:.1f}%"
            block["delta_color"] = config.GREEN
            block["money"] = f"每万金多赚 {fmt_money(diff)}"
        return block

    def _card_block(self, key: str, gold: float | None, best_keys: set[str]) -> dict:
        meta = config.PLATFORMS[key]
        result = self.results.get(key)
        block = {
            "key": key,
            "name": meta["name"],
            "tag": meta.get("tag", "收货"),
            "color": meta["color"],
            "is_best": key in best_keys,
            "price": "—",
            "price_num": 0,
            "price_color": config.GOLD,
            "price_size": 31,
            "unit": "元/金",
            "ratio": "1元 ≈ — 金",
            "payout": "输入金币数量查看折算",
            "payout_color": "#74e3aa",
            "trend_range": "暂无记录",
            "trend_range_color": config.MUTED_DARK,
            "stats": [
                {"label": "收货量", "value": "—"},
                {"label": "起收", "value": "—"},
                {"label": "单笔上限", "value": "—"},
            ],
            "tags": [],
            "note": "等待获取报价",
            "note_color": config.MUTED,
            "extra": [],
            "extra_more": 0,
            "updated": "尚未获取",
            "updated_color": config.MUTED_DARK,
            "source_url": meta["url"],
            "copy_text": "",
        }
        if result is None:
            return block
        block["stale"] = result.stale
        block["ok"] = result.ok

        best = result.best
        if not result.ok and not best:
            block.update(
                price="获取失败",
                price_color=config.RED,
                price_size=17,
                unit="",
                ratio="点击右上角重试",
                payout="暂无可用报价",
                note=result.error or "平台获取失败",
                note_color=config.RED,
                updated="获取失败",
                updated_color=config.RED,
                source_url=result.source_url,
            )
            return block

        if not best:
            empty_note = (
                "收货商城当前没有收货商家"
                if key == "gmmsj"
                else "平台当前没有该区服的收货报价"
            )
            block.update(
                price="暂无",
                price_color=config.MUTED,
                price_size=22,
                unit="",
                ratio="暂无收货商家",
                payout="暂无可用报价",
                note=empty_note,
                updated=f"抓取于 {fmt_time(result.fetched_at)}",
                source_url=result.source_url,
            )
            return block

        block.update(
            price=fmt_unit_price(best.unit_price),
            price_num=best.unit_price,
            price_color="#c9a86a" if result.stale else config.GOLD,
            price_size=31,
            ratio=f"1元 ≈ {fmt_ratio(best.ratio)} 金",
            source_url=result.source_url,
        )

        block["stats"][0]["value"] = (
            f"{fmt_gold(best.stock)} 金" if best.stock is not None else "—"
        )
        block["stats"][1]["value"] = (
            f"{fmt_gold(best.min_gold)} 金" if best.min_gold is not None else "—"
        )
        if best.max_gold is not None:
            block["stats"][2] = {
                "label": "单笔上限",
                "value": f"{fmt_gold(best.max_gold)} 金",
            }
        elif best.min_yuan is not None:
            block["stats"][2] = {"label": "最低金额", "value": fmt_money(best.min_yuan)}
        else:
            block["stats"][2] = {"label": "单笔上限", "value": "—"}

        block["tags"] = split_methods(best.methods)[:3]

        note = best.note or "收货商家实时报价"
        if result.stale:
            note = f"{note} · 上次数据"
        block["note"] = note
        block["note_color"] = config.ORANGE if result.stale else config.MUTED

        extras = result.offers[1:]
        block["extra"] = [
            f"{fmt_unit_price(o.unit_price)} 元/金  ·  1元={fmt_ratio(o.ratio)}金"
            f"  ·  收 {fmt_gold(o.stock)}"
            for o in extras[:3]
        ]
        block["extra_more"] = max(0, len(extras) - 3)

        if result.stale:
            block["updated"] = (
                f"显示 {fmt_time(result.fetched_at)} 数据"
                f" · {result.stale_reason or '上次数据'}"
            )
            block["updated_color"] = config.ORANGE
        else:
            block["updated"] = f"抓取于 {fmt_time(result.fetched_at)}"
            block["updated_color"] = config.MUTED_DARK

        # 卡片内折算（按本平台自己的最高价）
        if gold is None:
            block["payout"] = "输入金币数量查看折算"
        else:
            amount = gold * best.unit_price
            block["payout"] = f"{fmt_gold(gold)} 金 ≈ {fmt_money(amount)}"
            block["payout_color"] = "#74e3aa"

        # 「复制」按钮的文本（与桌面版 copy_card 一致）
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
        block["copy_text"] = "\n".join(lines)
        return block

    def snapshot(self, gold: float | None) -> dict:
        with self.lock:
            results = dict(self.results)
            fetching = self.fetching
            status_text = self.status_text
            status_color = self.status_color
            last_update = self.last_update

        best_by_region = best_result_by_region(results)
        best_keys = {r.key for r in best_by_region.values()}
        cn_best = best_by_region.get("cn")
        tw_best = best_by_region.get("tw")

        cards = [
            self._card_block(key, gold, best_keys) for key in config.PLATFORMS
        ]

        # 走势区间文案 + 走势点（与桌面版 set_trend 一致）
        for card in cards:
            points = self.history.points(card["key"])
            if not points:
                card["trend_range"] = "暂无记录"
                card["trend_range_color"] = config.MUTED_DARK
            elif len(points) == 1:
                card["trend_range"] = f"{points[-1].unit_price:.5f} · 积累中"
                card["trend_range_color"] = config.GOLD
            else:
                values = [p.unit_price for p in points]
                card["trend_range"] = (
                    f"{min(values):.5f} ~ {max(values):.5f}"
                )
                card["trend_range_color"] = config.MUTED

        history = {}
        for key in config.PLATFORMS:
            history[key] = [
                {"t": point.ts.isoformat(timespec="seconds"), "p": point.unit_price}
                for point in self.history.points(key)
            ]

        # 折算
        amount = {"gold": gold, "cn": "≈ —", "tw": "≈ —", "hint": ""}
        if gold is None:
            amount["hint"] = "请输入大于 0 的金币数量"
        else:
            if cn_best and cn_best.best:
                amount["cn"] = f"≈ {fmt_money(gold * cn_best.best.unit_price)}"
            if tw_best and tw_best.best:
                amount["tw"] = f"≈ {fmt_money(gold * tw_best.best.unit_price)}"
            amount["hint"] = "分别按各组最高单价折算"

        # 结论
        conclusion = {
            "text": "获取报价后，这里会分别给出国服与港澳台LIVE的出手建议。",
            "color": config.TEXT_SOFT,
        }
        if cn_best and cn_best.best:
            second = second_best_price(results, cn_best.key, region="cn")
            if second and second > 0:
                diff = (cn_best.best.unit_price - second) * 10_000
                conclusion = {
                    "text": (
                        f"国服怀旧优先卖 {cn_best.name}：每 1 万金多到手 "
                        f"{fmt_money(diff)}（较国服第二高）；"
                        f"港澳台LIVE为独立参考价，不与国服混算。"
                    ),
                    "color": config.GREEN,
                }
            else:
                conclusion = {
                    "text": f"国服怀旧目前仅 {cn_best.name} 有收货报价，以平台下单页为准。",
                    "color": config.TEXT_SOFT,
                }

        return {
            "app": {
                "name": config.APP_NAME,
                "version": config.APP_VERSION,
                "game": config.GAME_NAME,
                "server": config.SERVER_LABEL,
                "disclaimer": config.DISCLAIMER,
                "auto_seconds": AUTO_SECONDS,
                "region_labels": config.REGION_LABELS,
            },
            "status": {
                "text": status_text,
                "color": status_color,
                "fetching": fetching,
                "last_update": fmt_time(last_update) if last_update else "—",
            },
            "summary": {
                "cn": self._region_block(cn_best),
                "tw": self._region_block(tw_best),
            },
            "cards": cards,
            "history": history,
            "amount": amount,
            "conclusion": conclusion,
        }


STATE = AppState()


class Handler(BaseHTTPRequestHandler):
    server_version = "GoldPricerWeb/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ 工具
    def _send(self, code: int, body: bytes, content_type: str, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control", "public, max-age=3600" if cache else "no-store"
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: dict, code: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _static(self, rel_path: str, cache: bool = False):
        path = (BASE_DIR / rel_path).resolve()
        # 只允许访问 web 目录内的文件
        if BASE_DIR not in path.parents and path != BASE_DIR:
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif path.suffix in (".html", ".htm"):
            ctype = "text/html; charset=utf-8"
        elif path.suffix in (".png", ".ico", ".svg"):
            ctype = ctype or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype or "application/octet-stream", cache)

    def log_message(self, fmt: str, *args):  # 只输出到容器日志，格式精简
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()

    # ------------------------------------------------------------------ 路由
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/":
            self._static("templates/index.html")
            return
        if route == "/favicon.ico":
            self._static("static/icon.png", cache=True)
            return
        if route.startswith("/static/"):
            self._static(route.lstrip("/"), cache=True)
            return
        if route == "/api/state":
            gold = self._parse_gold(parse_qs(parsed.query).get("gold", [""])[0])
            self._send_json(STATE.snapshot(gold))
            return
        if route == "/api/refresh":
            accepted = STATE.request_fetch()
            self._send_json({"ok": True, "accepted": accepted})
            return
        if route == "/healthz":
            self._send_json({"ok": True, "fetching": STATE.fetching})
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route == "/api/refresh":
            accepted = STATE.request_fetch()
            self._send_json({"ok": True, "accepted": accepted})
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    # ------------------------------------------------------------------ 参数
    @staticmethod
    def _parse_gold(raw: str) -> float | None:
        try:
            value = float(raw.replace(",", "").replace("，", ""))
        except (AttributeError, TypeError, ValueError):
            return None
        if value <= 0 or value != value or value == float("inf"):
            return None
        return value


def main():
    STATE.start_background()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(
        f"[goldpricer] web server listening on http://{HOST}:{PORT} "
        f"(auto refresh {AUTO_SECONDS}s, data dir {storage.cache_path().parent})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
