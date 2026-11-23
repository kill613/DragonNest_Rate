# 龙之谷金币查价器 · Docker 版部署说明

把桌面版改成「跑在路由器容器里的网页服务」：抓取和算价逻辑与桌面版共用同一份代码，
界面按桌面版深色金色样式 1:1 复刻，局域网任何设备用浏览器访问路由器 IP 即可。

- 镜像基础：`python:3.12-slim`，唯一第三方依赖 `lxml`（有预编译 wheel，不需要现场编译）
- 容器内固定数据目录 `/data`（挂载卷，存上次报价 + 7 天走势历史）
- 服务端口 `8090`（避开 LuCI 占用的 80）
- 时区 `Asia/Shanghai`（否则页面上的「抓取于 xx:xx」会是 UTC 时间）
- 抓取周期 60 秒，服务端后台跑，浏览器关掉也继续盯盘

---

## 一、把文件传到路由器

需要在路由器上有一个目录，包含这几样：

```
dragonnest/
├── Dockerfile
├── requirements.txt
├── .dockerignore
├── docker-compose.yml
├── goldpricer/       # 数据层（config / fetchers / models / storage / history）
└── web/              # 服务端 + 前端页面
```

两种传法，任选：

**A. 从 Windows 直接 scp（推荐）**

```powershell
# 在 Windows PowerShell 里执行（把 IP 换成你主路由地址）
scp "D:\Other\龙之谷金币查价器\app\Dockerfile" `
    "D:\Other\龙之谷金币查价器\app\.dockerignore" `
    "D:\Other\龙之谷金币查价器\app\docker-compose.yml" `
    "D:\Other\龙之谷金币查价器\app\deploy-openwrt.sh" `
    root@192.168.1.1:/root/dragonnest/

scp -r "D:\Other\龙之谷金币查价器\app\goldpricer" "D:\Other\龙之谷金币查价器\app\web" `
       root@192.168.1.1:/root/dragonnest/
```

**B. 用打好的 zip 包**

项目里已经生成 `release\dragonnest-web-docker.zip`，上传后解压：

```sh
mkdir -p /root/dragonnest && cd /root/dragonnest
unzip -o /tmp/dragonnest-web-docker.zip
```

---

## 二、构建并启动

### 方案 A：路由器上直接构建（推荐）

基础镜像会按路由器自身 CPU 架构自动拉取（arm64 / amd64 都不用管）。

**最省事：跑附带的脚本**（构建 + 重建容器 + 等就绪 + 打印访问地址，可重复执行）：

```sh
cd /root/dragonnest
sh deploy-openwrt.sh              # 默认 8090
# PORT=8099 sh deploy-openwrt.sh  # 换宿主机端口（容器内固定 8090）
```

或者手工两步：

```sh
cd /root/dragonnest

# 国内网络建议换 pip 源，否则拉 PyPI 可能很慢
docker build \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t dragonnest-goldpricer:1.5.0 .

docker run -d \
  --name goldpricer \
  --restart unless-stopped \
  -p 8090:8090 \
  -e TZ=Asia/Shanghai \
  -e GOLDPRICER_AUTO_SECONDS=60 \
  -v /root/dragonnest/data:/data \
  dragonnest-goldpricer:1.5.0
```

有 compose 插件的话更省事：

```sh
cd /root/dragonnest && docker compose up -d --build
```

### 方案 B：在电脑上构建好，导出成 tar 再导入

电脑上装了 Docker Desktop 时用这个，路由器就不用装构建环境：

```powershell
# 1) 先看路由器架构：uname -m  →  aarch64 用 linux/arm64，x86_64 用 linux/amd64
docker buildx build --platform linux/arm64 `
  -t dragonnest-goldpricer:1.5.0 `
  "D:\Other\龙之谷金币查价器\app" --load

# 2) 导出
docker save dragonnest-goldpricer:1.5.0 -o D:\goldpricer-arm64.tar

# 3) 传上去并导入
scp D:\goldpricer-arm64.tar root@192.168.1.1:/tmp/
ssh root@192.168.1.1 "docker load -i /tmp/goldpricer-arm64.tar && rm /tmp/goldpricer-arm64.tar"
```

然后在路由器上执行上面那条 `docker run`。

---

## 三、访问

浏览器打开：

```
http://<主路由 IP>:8090
```

例如 `http://192.168.1.1:8090`。手机、平板、其他电脑同一局域网都能开。

首次打开时会先显示缓存（没有缓存就是「等待获取报价」），约 2 秒后开始抓取，
抓完自动刷新，之后每 60 秒更新一次。

---

## 四、常用运维

```sh
docker logs -f goldpricer          # 看抓取日志
docker restart goldpricer          # 重启
docker stop goldpricer && docker rm goldpricer   # 删除容器（数据在 /data 卷里，不会丢）

# 更新代码后重新构建
cd /root/dragonnest && docker build -t dragonnest-goldpricer:1.5.0 . \
  && docker stop goldpricer && docker rm goldpricer \
  && docker run -d --name goldpricer --restart unless-stopped \
     -p 8090:8090 -v /root/dragonnest/data:/data \
     dragonnest-goldpricer:1.5.0
```

**数据文件**（都在挂载的 `data` 目录里）：

| 文件 | 内容 |
| --- | --- |
| `last_prices.json` | 上一次成功抓到的报价（平台无商家时用来显示「上次数据」） |
| `price_history.json` | 7 天价格走势历史 |

**把桌面版的历史曲线搬过来**（可选）：把 Windows 上
`%LOCALAPPDATA%\DragonNestGoldPrice\` 里的 `price_history.json`、`last_prices.json`
拷到路由器的 `/root/dragonnest/data/` 下，重启容器即可接着画。

---

## 五、环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GOLDPRICER_PORT` | `8090` | 容器内监听端口，改这里要同步改 `-p` 的容器侧端口 |
| `GOLDPRICER_AUTO_SECONDS` | `60` | 后台抓取周期（秒），页面底部文案会跟着变 |
| `GOLDPRICER_DD373_INTERVAL` | `300` | DD373 成功抓取后的最小间隔（秒），见下方说明 |
| `GOLDPRICER_DD373_COOLDOWN` | `600` | DD373 首次失败后的冷却（秒），之后每次翻倍 |
| `GOLDPRICER_DD373_COOLDOWN_MAX` | `1800` | DD373 冷却上限（秒），达到后不再翻倍 |
| `GOLDPRICER_DATA_DIR` | `/data` | 数据目录，改了要同步改卷挂载 |
| `TZ` | `Asia/Shanghai` | 容器时区 |

端口被占用时只改宿主机侧即可，例如 `-p 8095:8090`，访问就变成 `http://192.168.1.1:8090`。

### 关于 DD373 的抓取（重要）

DD373 前置阿里云 WAF，它按 **TLS 指纹**识别客户端。同一台电脑、同一个 IP，用浏览器打开列表页完全正常，但 Python 标准库、.NET、curl 这些非浏览器 TLS 栈都会被判定成机器人，返回一个约 1.2 万字节的“滑动验证”页而不是商品列表。

**这不是 IP 被封，也不是抓取频率太高**——把频率降到 10 分钟一次依然失败，换浏览器指纹的库立刻成功。

所以 DD373 的抓取走 `curl_cffi`，它复刻 Chrome 的 TLS / HTTP2 指纹（`impersonate="chrome"`）。7881 和 G买卖 一直很稳定，仍用标准库。

另外还保留了节奏保护，避免请求密度引来额外风控：

- 默认每 5 分钟抓一次（`GOLDPRICER_DD373_INTERVAL=300`），7881 和 G买卖 仍 60 秒
- 失败后自动退避：10 分钟 → 20 分钟 → 30 分钟，成功后计时清零
- 退避期间**完全不发请求**，卡片保留上次价格并提示“约 N 分钟后自动重试”

代价是镜像多约 14MB（curl_cffi 自带 libcurl），页面上的 DD373 数据最多比 7881 慢 5 分钟。ARM64 有现成的预编译包，路由器上构建不需要编译工具链。

DD373 显示失败时，先在容器里跑一次自检：

```sh
docker exec goldpricer python -c "
from curl_cffi import requests
r = requests.get('https://www.dd373.com/', impersonate='chrome', timeout=20)
print(r.status_code, len(r.text))
"
```

返回 200 且长度十万级是正常的；如果只有一万多字节，说明又回到了验证页，可以调大间隔或换公网 IP 再试。

如果想让 DD373 抓得更勤：

```sh
docker run ... -e GOLDPRICER_DD373_INTERVAL=120 ...
```



---

## 六、排查

**页面打不开**
1. `docker ps` 看容器是否在跑、状态是否 `healthy`
2. `docker logs goldpricer` 看有没有 `web server listening`
3. 路由器防火墙是否放行 8090（LuCI → 网络 → 防火墙 → 通信规则）

**页面能开，但全部平台「获取失败」**
容器访问不了外网。先在容器里验证：

```sh
docker exec goldpricer python -c "import urllib.request;print(urllib.request.urlopen('https://www.dd373.com/',timeout=8).status)"
```

不通通常是 OpenWrt 上 docker 的 DNS/转发问题，可以：
- 给 docker 配 DNS：`/etc/docker/daemon.json` 写 `{"dns":["223.5.5.5","119.29.29.29"]}` 后重启 dockerd
- 或临时改用 host 网络：`docker run ... --network host dragonnest-goldpricer:1.5.0`（此时 `-p` 可不写，直接用 8090）

**时间显示不对**
确认启动参数里有 `-e TZ=Asia/Shanghai`。

**路由器存储不够**
`python:3.12-slim` + lxml 的镜像约 180–200 MB。OpenWrt 的 `/overlay` 通常很小，
建议把 docker 的 data-root 指到 U 盘或外置盘（`/etc/docker/daemon.json` 里
`"data-root": "/mnt/sda1/docker"`），否则几个镜像就塞满了。

**想少占资源**
`docker update --memory 256m --cpus 0.5 goldpricer`。
本项目单次抓取是 5 个 HTTP 请求 + lxml 解析，256 MB 内存足够。
