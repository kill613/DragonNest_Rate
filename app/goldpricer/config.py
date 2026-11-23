# -*- coding: utf-8 -*-
"""应用配置：服务器、数据源地址与界面主题。"""

import os

APP_NAME = "龙之谷金币查价器"
APP_VERSION = "1.5.0"

GAME_NAME = "龙之谷怀旧服"
AREA_NAME = "怀旧大区"
SERVER_NAME = "神圣天堂"
SERVER_LABEL = f"{AREA_NAME} / {SERVER_NAME}"

# ---------------------------------------------------------------------------
# 数据源参数（当前固定为：龙之谷怀旧服 / 怀旧大区 / 神圣天堂 / 游戏币）
# 如果以后要换区服，需要同时修改下面的 ID 和 URL。
# ---------------------------------------------------------------------------

# DD373
DD373_HOME = "https://www.dd373.com/"
DD373_URL = (
    "https://www.dd373.com/"
    "s-cbk5a5-bqufr0-j8cdwa-0-0-0-vxf5cd-0-0-receive-0-0-1-0-0-0.html"
)
# 港澳台服 / LIVE 服务器（同游戏币分类 vxf5cd，areaId=hf9q12，serverId=wu8pv9）
DD373_TW_LIVE_URL = (
    "https://www.dd373.com/"
    "s-cbk5a5-hf9q12-wu8pv9-0-0-0-vxf5cd-0-0-receive-0-0-1-0-0-0.html"
)
DD373_GAME_ID = "cbk5a5"
DD373_AREA_ID = "bqufr0"
DD373_SERVER_ID = "j8cdwa"

# DD373 前置阿里云 WAF。抓取已改用 curl_cffi 的 Chrome 指纹（这是能拿到真实
# 页面的关键），但请求密度仍然不宜太高，失败后也要退避，避免被额外盯上。
# 单位：秒；可用环境变量覆盖，桌面版不设置时使用下面的默认值。
DD373_MIN_INTERVAL = int(os.getenv("GOLDPRICER_DD373_INTERVAL", "300"))
DD373_COOLDOWN_BASE = int(os.getenv("GOLDPRICER_DD373_COOLDOWN", "600"))
DD373_COOLDOWN_MAX = int(os.getenv("GOLDPRICER_DD373_COOLDOWN_MAX", "1800"))

# 7881（国服怀旧 / 港澳台LIVE 同 gameId，不同 groupId/serverId）
L7881_URL = (
    "https://search.7881.com/"
    "G5909-100001-G5909P001-G5909P001001-0.html?pageNum=1"
)
L7881_TW_URL = (
    "https://search.7881.com/"
    "G5909-100001-G5909P003-G5909P003001-0.html?pageNum=1"
)
L7881_RECEIPT_URL = "https://shou.7881.com/ajax/querySearchReceiptGoodsList.htm"
L7881_GAME_ID = "G5909"
L7881_GOODS_TYPE = "100001"
L7881_GROUP_ID = "G5909P001"
L7881_SERVER_ID = "G5909P001001"
L7881_TW_GROUP_ID = "G5909P003"
L7881_TW_SERVER_ID = "G5909P003001"

# G买卖（gmmsj）
GMMSJ_URL = (
    "https://www.gmmsj.com/dy/791000748_jb.shtml"
    "?keyword=&areaId=501&groupId=10001&gameOs=&operatorId=&special=&sourceType="
)
# 注意：这里取的是「收货商城」接口，不是「精选店铺」接口。
GMMSJ_RECEIVE_URL = "https://www.gmmsj.com/api/securedbpe/receive/product/list"
GMMSJ_GAME_ID = "791000748"
GMMSJ_AREA_ID = "501"
GMMSJ_GROUP_ID = "10001"

PLATFORMS = {
    "dd373": {
        "name": "DD373·神圣天堂",
        "short": "DD373",
        "tag": "怀旧服·极速收货",
        "color": "#ff8a4c",
        "url": DD373_URL,
        "region": "cn",
    },
    "dd373tw": {
        "name": "DD373·港澳台LIVE",
        "short": "台LIVE",
        "tag": "港澳台·LIVE收货",
        "color": "#c084fc",
        "url": DD373_TW_LIVE_URL,
        "region": "tw",
    },
    "7881": {
        "name": "7881·神圣天堂",
        "short": "7881",
        "tag": "收货商家",
        "color": "#5aa9ff",
        "url": L7881_URL,
        "region": "cn",
    },
    "7881tw": {
        "name": "7881·港澳台LIVE",
        "short": "7881台",
        "tag": "港澳台·收货商家",
        "color": "#7cc4ff",
        "url": L7881_TW_URL,
        "region": "tw",
    },
    "gmmsj": {
        "name": "G买卖·神圣天堂",
        "short": "G买卖",
        "tag": "收货商城",
        "color": "#3ddc97",
        "url": GMMSJ_URL,
        "region": "cn",
    },
}

# 服务器分组显示名（国服怀旧 / 港澳台LIVE），最高价分别按组计算
REGION_LABELS = {
    "cn": "国服怀旧",
    "tw": "港澳台LIVE",
}

# ---------------------------------------------------------------------------
# 主题（深色 + 金色）
# ---------------------------------------------------------------------------
BG = "#0b1220"
BG_SOFT = "#0e1728"
SURFACE = "#121d31"
CARD = "#15223a"
CARD_HOVER = "#1a2a46"
BORDER = "#263854"
BORDER_SOFT = "#1d2c45"
TEXT = "#e9f0ff"
TEXT_SOFT = "#c3d2ea"
MUTED = "#8798b8"
MUTED_DARK = "#61718f"
GOLD = "#f6c453"
GOLD_LIGHT = "#ffe6a3"
GOLD_DARK = "#d9a52f"
GREEN = "#4ade80"
RED = "#fb7185"
ORANGE = "#fbbf24"
BLUE = "#60a5fa"

# 常用字体（Windows 上优先微软雅黑 UI）
FONT_FAMILY = "Microsoft YaHei UI"
FONT_FALLBACK = "Microsoft YaHei"

# 自动刷新间隔（毫秒）
AUTO_REFRESH_MS = 60_000

DISCLAIMER = "数据来自各平台公开收货页，实际成交价以平台下单页为准。"
