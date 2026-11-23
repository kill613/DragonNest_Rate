#!/bin/sh
# 龙之谷金币查价器 · OpenWrt 一键构建并启动
#
# 用法：
#   sh deploy-openwrt.sh              # 默认 8090 端口
#   PORT=8099 sh deploy-openwrt.sh    # 换宿主机端口（容器内固定 8090）
#   PIP_INDEX_URL= sh deploy-openwrt.sh   # 用官方 PyPI 源
#
# 脚本可重复执行：会自动停掉旧容器、重新构建、再启动，数据目录不动。

set -e

APP_DIR=$(cd "$(dirname "$0")" && pwd)
NAME=goldpricer
IMAGE=dragonnest-goldpricer:1.5.0
PORT=${PORT:-8090}
DATA=${DATA:-$APP_DIR/data}

# 国内网络默认走清华源，拉 PyPI 快很多
PIP_INDEX_URL=${PIP_INDEX_URL-https://pypi.tuna.tsinghua.edu.cn/simple}

echo "==> 检查 docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "错误：找不到 docker，先在路由器上安装并启动 dockerd" >&2
  exit 1
fi

echo "==> 构建镜像 $IMAGE"
if [ -n "$PIP_INDEX_URL" ]; then
  docker build --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" -t "$IMAGE" "$APP_DIR"
else
  docker build -t "$IMAGE" "$APP_DIR"
fi

echo "==> 重建容器（数据目录 $DATA）"
mkdir -p "$DATA"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  -p "${PORT}:8090" \
  -e TZ=Asia/Shanghai \
  -e GOLDPRICER_AUTO_SECONDS=60 \
  -v "${DATA}:/data" \
  "$IMAGE" >/dev/null

echo "==> 等待服务就绪"
i=0
while [ $i -lt 30 ]; do
  if docker exec "$NAME" python -c \
    "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/healthz',timeout=3)" 2>/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
[ -z "$IP" ] && IP=$(uci get network.lan.ipaddr 2>/dev/null)
[ -z "$IP" ] && IP="<路由器IP>"

echo ""
echo "完成。浏览器打开： http://${IP}:${PORT}"
echo "查看日志： docker logs -f $NAME"
