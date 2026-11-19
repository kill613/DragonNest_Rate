# 龙之谷金币查价器 · Web/Docker 版
#
# 基础镜像用 Debian 版 slim：lxml 有 cp312 的 manylinux 预编译 wheel，
# 装依赖不需要编译工具链，在 OpenWrt 路由器上 docker build 也很快。
# （Alpine 走 musl 没有预编译轮子，要现场编译 libxml2，路由器上会非常慢）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    GOLDPRICER_DATA_DIR=/data \
    GOLDPRICER_HOST=0.0.0.0 \
    GOLDPRICER_PORT=8090 \
    GOLDPRICER_AUTO_SECONDS=60

# 时区数据：容器默认 UTC，不装 tzdata 的话页面上「抓取于 11:58:04」会变成 UTC 时间
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo "$TZ" > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 允许换成国内源：docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple

# 只装抓取解析要用的 lxml（托盘用的 pystray / Pillow 是桌面版专用，容器里不需要）
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" "lxml==6.1.3"

# 只拷贝服务端真正需要的模块（ui.py / chart.py 是 tkinter 桌面版专用，容器里用不到）
COPY goldpricer ./goldpricer
COPY web ./web

RUN useradd -u 1000 -m appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data /app

USER appuser

VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; \
r=urllib.request.urlopen('http://127.0.0.1:8090/healthz',timeout=4); \
sys.exit(0 if r.status==200 else 1)"

CMD ["python", "-u", "web/server.py"]
