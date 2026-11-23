# -*- coding: utf-8 -*-
"""三个平台的收货报价抓取与解析。

只访问各平台公开的商品/收货列表页，不登录、不绕过人机验证。
"""

from __future__ import annotations

import gzip
import json
import os
import re
import socket
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.cookiejar import CookieJar
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from lxml import html as lxml_html

from . import config
from .models import Offer, PlatformResult

# curl_cffi 用来复刻真实浏览器的 TLS/HTTP2 指纹。
# 没装时退回标准库，此时 DD373 只会拿到 WAF 的滑动验证页。
try:
    from curl_cffi import requests as _cffi_requests
except Exception:  # noqa: BLE001
    _cffi_requests = None


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0"
)

CHALLENGE_MARKERS = (
    "滑动验证",
    "验证您是真人",
    "AliyunCaptcha",
    "captcha-frontend",
    "acw_sc__v2",
)


class FetchError(Exception):
    """可展示给用户的抓取错误。"""


class SkipFetch(Exception):
    """平台处于节流或退避冷却期，本轮不抓取，直接沿用上次数据。"""

    def __init__(self, key: str, remain: float, reason: str):
        self.key = key
        self.remain = remain
        self.reason = reason
        super().__init__(reason)


# 各平台的抓取节奏控制：成功后有最小间隔，失败后按指数退避，
# 避免把出口 IP 打到被对方 WAF 要求人机验证的程度。
_THROTTLE_LOCK = threading.Lock()
_THROTTLE: dict[str, dict] = {}


def _throttle_state(key: str) -> dict:
    with _THROTTLE_LOCK:
        state = _THROTTLE.get(key)
        if state is None:
            state = {"next": 0.0, "streak": 0, "reason": ""}
            _THROTTLE[key] = state
        return state


def throttle_status() -> dict[str, dict]:
    """返回各平台剩余等待时间，供界面提示“N 分钟后重试”。"""
    now = time.monotonic()
    out: dict[str, dict] = {}
    with _THROTTLE_LOCK:
        items = list(_THROTTLE.items())
    for key, state in items:
        remain = state["next"] - now
        out[key] = {
            "remain": max(0.0, remain),
            "reason": state["reason"] if remain > 0 else "",
            "streak": state["streak"],
        }
    return out


def _throttle_guard(fetcher) -> None:
    state = _throttle_state(fetcher.key)
    now = time.monotonic()
    if state["next"] > now:
        raise SkipFetch(fetcher.key, state["next"] - now, state["reason"] or "节流中")


def _throttle_success(fetcher) -> None:
    state = _throttle_state(fetcher.key)
    state["streak"] = 0
    state["reason"] = ""
    state["next"] = time.monotonic() + float(fetcher.min_interval)


def _throttle_failure(fetcher) -> None:
    state = _throttle_state(fetcher.key)
    state["streak"] += 1
    base = float(fetcher.cooldown_base)
    if base <= 0:
        return
    cap = float(fetcher.cooldown_max) or base
    cool = min(base * (2 ** (state["streak"] - 1)), cap)
    state["reason"] = "触发人机验证，暂停抓取"
    state["next"] = time.monotonic() + cool


def _to_float(value, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _clean(text: str) -> str:
    return " ".join((text or "").split())


class HttpSession:
    """带 Cookie 的轻量 HTTP 会话（标准库实现，避免额外依赖）。"""

    def __init__(self, timeout: int = 22):
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.timeout = timeout

    def _read(self, request: Request, timeout: Optional[int] = None) -> str:
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    return raw.decode(charset, errors="replace")
                except LookupError:
                    return raw.decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise FetchError(f"平台返回 HTTP {exc.code}") from exc
        except (URLError, socket.timeout, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise FetchError(f"连接失败：{reason}") from exc

    def get(
        self,
        url: str,
        referer: Optional[str] = None,
        timeout: Optional[int] = None,
        accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    ) -> str:
        headers = {
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return self._read(Request(url, headers=headers), timeout)

    def post_json(
        self,
        url: str,
        payload,
        referer: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json;charset=UTF-8",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return self._read(Request(url, data=body, headers=headers, method="POST"), timeout)


_CA_CACHE: dict[str, object] = {}


def _ca_bundle():
    """给 libcurl 用的 CA 路径。

    Windows 下如果项目路径含中文，libcurl 打不开 certifi 的 cacert.pem
    （报 error adding trust anchors），所以先判断路径是否为纯 ASCII，
    不是就复制一份到纯 ASCII 的临时目录。
    """
    if "path" in _CA_CACHE:
        return _CA_CACHE["path"]
    _CA_CACHE["path"] = True
    try:
        import shutil
        import tempfile

        import certifi

        source = certifi.where()
        if source.isascii() and os.path.exists(source):
            _CA_CACHE["path"] = source
            return source
        for base in ("/tmp", tempfile.gettempdir(), r"C:\Temp", "/var/tmp"):
            if not base.isascii() or not os.path.isdir(base):
                continue
            target = os.path.join(base, "goldpricer_cacert.pem")
            try:
                if not os.path.exists(target):
                    shutil.copyfile(source, target)
                _CA_CACHE["path"] = target
                return target
            except OSError:
                continue
    except Exception:  # noqa: BLE001 - 任何异常都退回 libcurl 默认行为
        pass
    return _CA_CACHE["path"]


class CffiSession:
    """用 curl_cffi 复刻真实浏览器的 TLS/HTTP2 指纹。

    DD373 前置阿里云 WAF，会按 TLS 指纹把 Python/.NET 客户端判定为机器人，
    同样的 IP 用浏览器能正常打开，用 urllib 只会拿到「滑动验证」页。
    换成 Chrome 指纹后即可正常返回商品列表。
    """

    def __init__(self, timeout: int = 22, impersonate: str = "chrome"):
        self.timeout = timeout
        self._session = _cffi_requests.Session(
            impersonate=impersonate,
            timeout=timeout,
            verify=_ca_bundle(),
        )

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # noqa: BLE001
            pass

    def _do(self, method: str, url: str, headers: dict, timeout, **kwargs) -> str:
        try:
            response = self._session.request(
                method, url, headers=headers, timeout=timeout or self.timeout, **kwargs
            )
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"连接失败：{exc}") from exc
        if response.status_code >= 400:
            raise FetchError(f"平台返回 HTTP {response.status_code}")
        return response.text

    def get(
        self,
        url: str,
        referer: Optional[str] = None,
        timeout: Optional[int] = None,
        accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    ) -> str:
        headers = {
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }
        if referer:
            headers["Referer"] = referer
        return self._do("GET", url, headers, timeout)

    def post_json(
        self,
        url: str,
        payload,
        referer: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        headers = {
            "Accept": "application/json,text/plain,*/*;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }
        if referer:
            headers["Referer"] = referer
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._do("POST", url, headers, timeout, data=body)


def _browser_session():
    """DD373 用浏览器指纹会话，其余平台仍用标准库（一直很稳定）。"""
    if _cffi_requests is not None:
        return CffiSession()
    return HttpSession()


class BaseFetcher:
    key = ""
    name = ""
    color = ""
    source_url = ""

    # 抓取节奏：成功后最小间隔 / 首次失败冷却 / 冷却上限 / 单次抓取的重试轮数
    min_interval = 0.0
    cooldown_base = 0.0
    cooldown_max = 0.0
    max_attempts = 1

    @property
    def region(self) -> str:
        return config.PLATFORMS.get(self.key, {}).get("region", "cn")

    def fetch(self) -> PlatformResult:
        offers = self._fetch_offers()
        offers.sort(key=lambda item: item.unit_price, reverse=True)
        return PlatformResult(
            key=self.key,
            name=self.name,
            color=self.color,
            source_url=self.source_url,
            offers=offers,
            ok=True,
            fetched_at=datetime.now(),
            region=self.region,
        )

    def _fetch_offers(self) -> list[Offer]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# DD373
# ---------------------------------------------------------------------------
class Dd373Fetcher(BaseFetcher):
    key = "dd373"
    name = config.PLATFORMS["dd373"]["name"]
    color = config.PLATFORMS["dd373"]["color"]
    source_url = config.DD373_URL
    # DD373 有阿里云 WAF，请求密度过高就会要求滑动验证（纯 HTTP 过不去），
    # 所以它走得比其他平台慢很多，失败后还会指数退避。
    min_interval = float(config.DD373_MIN_INTERVAL)
    cooldown_base = float(config.DD373_COOLDOWN_BASE)
    cooldown_max = float(config.DD373_COOLDOWN_MAX)
    max_attempts = 1

    def __init__(self):
        self._session = _browser_session()
        self._warmed = False
        self._lock = threading.Lock()

    def _reset(self):
        try:
            self._session.close()
        except Exception:  # noqa: BLE001
            pass
        self._session = _browser_session()
        self._warmed = False

    def _warm(self):
        if self._warmed:
            return
        # 先访问首页取得 WAF 会话 Cookie，再访问商品列表页。
        home = self._session.get(config.DD373_HOME, referer=None)
        # 首页已经被要求人机验证时，再请求列表页只会加深“机器行为”判定，
        # 这里立刻放弃，把请求数压到最低。
        if any(marker in home for marker in CHALLENGE_MARKERS):
            raise FetchError("DD373 触发人机验证")
        self._warmed = True

    def _fetch_offers(self) -> list[Offer]:
        with self._lock:
            last_error: Optional[Exception] = None
            rounds = max(1, int(self.max_attempts))
            for attempt in range(rounds):
                try:
                    self._warm()
                    page = self._session.get(self.source_url, referer=config.DD373_HOME)
                    if any(marker in page for marker in CHALLENGE_MARKERS):
                        raise FetchError("DD373 触发了人机验证")
                    return self._parse(page)
                except FetchError as exc:
                    last_error = exc
                    self._reset()
                    if attempt < rounds - 1:
                        time.sleep(1.2 + attempt)
                except Exception as exc:  # noqa: BLE001 - 统一转换为用户可读错误
                    last_error = exc
                    self._reset()
                    if attempt < rounds - 1:
                        time.sleep(0.8)
            if isinstance(last_error, FetchError):
                if "人机验证" in str(last_error):
                    raise FetchError("需要人机验证，已暂停抓取")
                raise last_error
            raise FetchError(f"DD373 获取失败：{last_error}")

    def _server_names(self, doc) -> list[str]:
        """通过页面内嵌的 receiveGoods 顺序，换取出每个收货商家所属区服。"""
        nodes = doc.xpath('//*[@id="invisibleData"]')
        if not nodes:
            return []
        try:
            data = json.loads(nodes[0].get("data-jsdata") or "{}")
        except (TypeError, json.JSONDecodeError):
            return []
        receive_goods = data.get("receiveGoods") or []
        payload = [
            {"LastId": item.get("LastId"), "GoodsTypeId": item.get("GoodsType")}
            for item in receive_goods
            if item.get("LastId") and item.get("GoodsType")
        ]
        if not payload:
            return []
        try:
            raw = self._session.post_json(
                "https://game.dd373.com/Api/Game/GetGameInfoListByIds",
                payload,
                referer=self.source_url,
            )
            obj = json.loads(raw)
            items = (obj.get("StatusData") or {}).get("ResultData") or []
            names: list[str] = []
            for item in items:
                others = item.get("GameOther") or []
                server = next(
                    (entry for entry in others if entry.get("CurrentLevelType") == 3),
                    None,
                )
                if server is None and others:
                    server = others[-1]
                names.append(str(server.get("Name") or "") if server else "")
            return names
        except Exception:  # noqa: BLE001 - 区服映射失败时退回“第一个为目标服”
            return []

    def _parse(self, page: str) -> list[Offer]:
        try:
            doc = lxml_html.fromstring(page)
        except Exception as exc:  # noqa: BLE001
            raise FetchError("DD373 页面解析失败") from exc

        # 新版「收货」专页：每个 platform-receive-content 是一家收货商。
        receive_blocks = doc.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), '
            ' " platform-receive-content ")]'
        )
        if receive_blocks:
            return self._parse_receive_blocks(receive_blocks)

        # 回退：旧版「热门极速收货」轮播（未带 receive 段的旧链接）。
        hot_blocks = doc.xpath(
            '//div[contains(concat(" ", normalize-space(@class), " "), '
            ' " hot-receiving-goods ")]'
        )
        if hot_blocks:
            return self._parse_hot_blocks(doc, hot_blocks)

        raise FetchError("DD373 页面未找到收货区域，可能已改版")

    def _parse_receive_blocks(self, blocks) -> list[Offer]:
        """解析新版 receive 专页的收货块（URL 已按区服筛选，直接全量解析）。"""
        offers: list[Offer] = []
        seen: set[tuple] = set()
        for block in blocks:
            inputs = block.xpath('.//input[contains(@id, "receiveInput")]')
            inp = inputs[0] if inputs else None
            if inp is None:
                continue

            unit_price = _to_float(inp.get("data-singleprice"))
            ratio = _to_float(inp.get("data-bili"))
            if not unit_price:
                continue
            if not ratio:
                ratio = 1.0 / unit_price

            text = _clean(block.text_content())
            # 文本形如："…0.0337元/金 40609 金 起收≥ 1000金 最高≤ 30000金…"
            stock = None
            stock_match = re.search(r"([\d,]+)\s*金\s*起收[≥>]", text)
            if stock_match:
                stock = _to_float(stock_match.group(1))

            min_gold = _to_float(inp.get("data-min"))
            max_gold = _to_float(inp.get("data-max"))
            methods = [
                _clean(item)
                for item in block.xpath(
                    './/*[contains(concat(" ", normalize-space(@class), " "), '
                    ' " receive-lable ")]//span/text()'
                )
                if _clean(item)
            ]
            guarantees = [
                _clean(item)
                for item in block.xpath(
                    './/*[contains(@class, "server-guarantee")]//span/text()'
                )
                if _clean(item)
            ]
            merchant_id = inp.get("id", "").replace("receiveInput", "")
            signature = (merchant_id, round(unit_price, 8), stock)
            if signature in seen:
                continue
            seen.add(signature)

            offers.append(
                Offer(
                    platform=self.key,
                    unit_price=unit_price,
                    ratio=ratio,
                    stock=stock,
                    min_gold=min_gold,
                    max_gold=max_gold,
                    methods=" / ".join(methods),
                    note=" · ".join(guarantees[:2]) or "极速收货",
                    merchant_id=merchant_id,
                )
            )
        return offers

    def _parse_hot_blocks(self, doc, blocks) -> list[Offer]:
        """解析旧版热门收货轮播（按当前服务器名过滤）。"""
        server_names = self._server_names(doc)
        offers: list[Offer] = []
        seen: set[tuple] = set()
        for block in blocks:
            addresses = block.xpath(
                './/*[contains(concat(" ", normalize-space(@class), " "), '
                ' " receive-address ")]'
            )
            for index, address_node in enumerate(addresses):
                container = address_node.getparent()
                if container is None:
                    continue
                label = _clean(address_node.text_content())
                if label:
                    server_name = label
                elif index < len(server_names):
                    server_name = server_names[index]
                elif not server_names and index == 0:
                    server_name = config.SERVER_NAME
                else:
                    server_name = ""
                if config.SERVER_NAME not in server_name:
                    continue

                text = _clean(container.text_content())
                inputs = container.xpath('.//input[contains(@id, "receiveInput")]')
                inp = inputs[0] if inputs else None
                if inp is None:
                    continue

                unit_price = _to_float(inp.get("data-singleprice"))
                ratio = _to_float(inp.get("data-bili"))
                if unit_price is None:
                    match = re.search(r"([\d.]+)\s*元\s*/\s*金", text)
                    unit_price = _to_float(match.group(1)) if match else None
                if ratio is None:
                    match = re.search(r"1\s*元\s*=\s*([\d.]+)\s*金", text)
                    ratio = _to_float(match.group(1)) if match else None
                if not unit_price:
                    continue

                stock_match = re.search(r"收货数量[：:]\s*([\d,]+)", text)
                stock = _to_float(stock_match.group(1)) if stock_match else None
                min_gold = _to_float(inp.get("data-min"))
                max_gold = _to_float(inp.get("data-max"))
                methods = [
                    _clean(item)
                    for item in container.xpath(
                        './/*[contains(concat(" ", normalize-space(@class), " "), '
                        ' " receive-lable ")]//span/text()'
                    )
                    if _clean(item)
                ]
                guarantees = [
                    _clean(item)
                    for item in container.xpath(
                        './/*[contains(@class, "server-guarantee")]//span/text()'
                    )
                    if _clean(item)
                ]
                merchant_id = inp.get("id", "").replace("receiveInput", "")
                signature = (merchant_id, round(unit_price, 8), stock)
                if signature in seen:
                    continue
                seen.add(signature)

                offers.append(
                    Offer(
                        platform=self.key,
                        unit_price=unit_price,
                        ratio=ratio or (1.0 / unit_price if unit_price else 0.0),
                        stock=stock,
                        min_gold=min_gold,
                        max_gold=max_gold,
                        methods=" / ".join(methods),
                        note=" · ".join(guarantees[:2]) or "极速收货",
                        merchant_id=merchant_id,
                    )
                )
        return offers


# ---------------------------------------------------------------------------
# DD373 · 港澳台服 LIVE（同游戏、同收货页结构，仅区服/服务器不同）
# ---------------------------------------------------------------------------
class Dd373TwFetcher(Dd373Fetcher):
    key = "dd373tw"
    name = config.PLATFORMS["dd373tw"]["name"]
    color = config.PLATFORMS["dd373tw"]["color"]
    source_url = config.DD373_TW_LIVE_URL


# ---------------------------------------------------------------------------
# 7881
# ---------------------------------------------------------------------------
class L7881Fetcher(BaseFetcher):
    key = "7881"
    name = config.PLATFORMS["7881"]["name"]
    color = config.PLATFORMS["7881"]["color"]
    source_url = config.L7881_URL
    group_id = config.L7881_GROUP_ID
    server_id = config.L7881_SERVER_ID

    def __init__(self):
        self._session = HttpSession()

    def _fetch_offers(self) -> list[Offer]:
        now_ms = int(time.time() * 1000)
        params = {
            "gameId": config.L7881_GAME_ID,
            "goodsType": config.L7881_GOODS_TYPE,
            "groupId": self.group_id,
            "serverId": self.server_id,
            "campId": "",
            "t": str(now_ms),
            "queryReceiptCallback": "queryReceiptCallback",
            "_": str(now_ms + 1),
        }
        url = f"{config.L7881_RECEIPT_URL}?{urlencode(params)}"
        text = self._session.get(
            url,
            referer=self.source_url,
            accept="application/javascript,text/javascript,*/*;q=0.8",
        )
        start = text.find("(")
        end = text.rfind(")")
        if start < 0 or end <= start:
            raise FetchError("7881 返回格式异常")
        try:
            payload = json.loads(text[start + 1:end])
        except json.JSONDecodeError as exc:
            raise FetchError("7881 返回数据解析失败") from exc

        if str(payload.get("responseCode")) not in ("0000", "0"):
            raise FetchError(f"7881 接口提示：{payload.get('responseMsg') or '未知错误'}")

        items = payload.get("simpleList") or payload.get("detailsList") or []
        offers: list[Offer] = []
        for item in items:
            server_id = str(item.get("serverId") or "")
            server_name = str(item.get("serverName") or "")
            if server_id and server_id != self.server_id:
                continue
            if not server_id and config.SERVER_NAME not in server_name:
                continue

            unit_price = _to_float(item.get("unitOfPrice"))
            if unit_price is None:
                unit_price = _to_float(item.get("price"))
            if not unit_price:
                continue
            ratio = _to_float(item.get("priceOfUnit"))
            if not ratio:
                ratio = 1.0 / unit_price

            methods = str(item.get("tradeWayName") or "").replace(",", " / ")
            cross_name = str(item.get("crossName") or "")
            note = f"跨服：{cross_name}" if item.get("cross") and cross_name else ""
            offers.append(
                Offer(
                    platform=self.key,
                    unit_price=unit_price,
                    ratio=ratio,
                    stock=_to_float(item.get("receiptAmount")),
                    min_gold=_to_float(item.get("minReceipt")),
                    methods=methods,
                    note=note,
                    merchant_id=str(item.get("userId") or ""),
                )
            )
        return offers


# 7881 港澳台LIVE（同接口，仅 groupId/serverId 不同）
class L7881TwFetcher(L7881Fetcher):
    key = "7881tw"
    name = config.PLATFORMS["7881tw"]["name"]
    color = config.PLATFORMS["7881tw"]["color"]
    source_url = config.L7881_TW_URL
    group_id = config.L7881_TW_GROUP_ID
    server_id = config.L7881_TW_SERVER_ID


# ---------------------------------------------------------------------------
# G买卖
# ---------------------------------------------------------------------------
class GmmsjFetcher(BaseFetcher):
    key = "gmmsj"
    name = config.PLATFORMS["gmmsj"]["name"]
    color = config.PLATFORMS["gmmsj"]["color"]
    source_url = config.GMMSJ_URL

    def __init__(self):
        self._session = HttpSession()

    def _fetch_offers(self) -> list[Offer]:
        params = {
            "pageNo": "1",
            "pageSize": "50",
            "pRace": "",
            "gameId": config.GMMSJ_GAME_ID,
            "areaId": config.GMMSJ_AREA_ID,
            "groupId": config.GMMSJ_GROUP_ID,
        }
        url = f"{config.GMMSJ_RECEIVE_URL}?{urlencode(params)}"
        text = self._session.get(
            url,
            referer=config.GMMSJ_URL,
            accept="application/json,text/plain,*/*;q=0.8",
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchError("G买卖 返回数据解析失败") from exc

        if payload.get("return_code") not in (0, "0", None):
            raise FetchError(f"G买卖 接口提示：{payload.get('return_message') or '未知错误'}")

        data = payload.get("data") or {}
        records = data.get("records") or []
        offers: list[Offer] = []
        for record in records:
            if str(record.get("groupId") or "") != config.GMMSJ_GROUP_ID:
                continue
            unit_price = _to_float(record.get("eachPrice"))
            if not unit_price:
                continue
            ratio = _to_float(record.get("priceHint"))
            if not ratio:
                ratio = 1.0 / unit_price

            # 收货商城接口的字段：minBagQty 为起收数量，availQty 为剩余收货量。
            min_gold = _to_float(record.get("minBagQty"))
            if min_gold is None:
                min_gold = _to_float(record.get("minAmount"))
            unit_name = str(record.get("unitName") or "").strip()
            note = "收货商城"
            if unit_name and unit_name != "金":
                note = f"收货商城 · 单位：{unit_name}"

            offers.append(
                Offer(
                    platform=self.key,
                    unit_price=unit_price,
                    ratio=ratio,
                    stock=_to_float(record.get("availQty")),
                    min_gold=min_gold,
                    min_yuan=_to_float(record.get("minAmountYuan")),
                    methods=str(record.get("deliveryModeDesc") or ""),
                    note=note,
                    merchant_id=str(record.get("bookId") or ""),
                )
            )
        return offers


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
_FETCHERS: dict[str, BaseFetcher] = {
    "dd373": Dd373Fetcher(),
    "dd373tw": Dd373TwFetcher(),
    "7881": L7881Fetcher(),
    "7881tw": L7881TwFetcher(),
    "gmmsj": GmmsjFetcher(),
}


def fetch_one(key: str) -> PlatformResult:
    fetcher = _FETCHERS[key]
    _throttle_guard(fetcher)  # 处于节流/退避期时抛 SkipFetch
    try:
        result = fetcher.fetch()
    except SkipFetch:
        raise
    except FetchError:
        _throttle_failure(fetcher)
        raise
    except Exception as exc:  # noqa: BLE001
        _throttle_failure(fetcher)
        raise FetchError(f"{fetcher.name} 获取失败：{exc}") from exc
    _throttle_success(fetcher)
    return result


def error_result(key: str, message: str) -> PlatformResult:
    meta = config.PLATFORMS[key]
    return PlatformResult(
        key=key,
        name=meta["name"],
        color=meta["color"],
        source_url=meta["url"],
        offers=[],
        ok=False,
        error=message,
        fetched_at=None,
        region=meta.get("region", "cn"),
    )


def fetch_all() -> dict[str, PlatformResult]:
    """并行抓取全部平台；单个平台失败不影响其他平台。

    处于节流或退避冷却期的平台不会出现在返回值里，调用方沿用上次数据。
    """
    results: dict[str, PlatformResult] = {}
    with ThreadPoolExecutor(max_workers=len(_FETCHERS)) as pool:
        futures = {key: pool.submit(fetch_one, key) for key in _FETCHERS}
        for key, future in futures.items():
            try:
                results[key] = future.result()
            except SkipFetch:
                continue
            except FetchError as exc:
                results[key] = error_result(key, str(exc))
            except Exception as exc:  # noqa: BLE001
                results[key] = error_result(key, f"未知错误：{exc}")
    return results
