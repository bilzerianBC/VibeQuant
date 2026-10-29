# VibeQuant 统一 Docker 部署

把 **M2DivGold**（M2/黄金数据抓取 + 图表）、**LiveMoreAmazing**（银河行情与回测）和 **VibeQuantFront**（前端门户）放进**一个镜像 + 一份 compose**，部署到远端宿主机上跑。

分工约定：**Mac 只做编辑和编排**（写代码、Git、rsync 同步、SSH）；依赖安装、数据抓取、镜像构建全部在远端 Docker 内执行。

- 远端：`lxy@121.41.112.193:2222`，项目目录 `/home/lxy/VibeQuant`，compose 项目名 `vibequant`
- 镜像：`vibequant:dev`（构建上下文 = **仓库根目录**，故 `compose.yaml` 里写 `context: ..`）

## 目录结构

```text
docker/
├── README.md                 本文件
├── Dockerfile                统一镜像定义（构建上下文 = 仓库根）
├── Dockerfile.mihomo         DipWatch 代理镜像（复用共享镜像离线构建，不下载第三方镜像）
├── compose.yaml              服务编排：m2divgold / front / livemore-amazing / usstock-dip-watch / mihomo / dev-shell
├── requirements.txt          Python 依赖（pandas + numpy）
├── .env*.example             各类配置模板（真实 .env / .env.remote / .env.amazing / .env.dipwatch / .env.web 不提交、不同步）
├── .remoteignore             rsync 同步排除规则（Mac → 远端）
├── mihomo/                   Mihomo 代理：说明、配置模板（真实 config.yaml 与 runtime/ 不提交）
├── wheels/amazing/           官方 AmazingData / tgw Linux wheel（不提交，但会同步）
├── out/                      pull-data.sh 等拉回 Mac 的数据/结果（不提交）
└── scripts/
    ├── configure_tgw.py      镜像构建时注册 tgw 原生库路径（ldconfig）
    ├── host/                 **在远端宿主机上**由 cron 调用
    │   ├── daily-update.sh       每日 08:00：拉 M2/金价 + 出图
    │   └── dipwatch-update.sh    每半小时：DipWatch 行情采集
    └── remote/               部署脚本（**全部在 Mac 上执行**）
        ├── _common.sh            所有脚本的公共前置：读 .env.remote、校验、ssh 封装
        ├── sync.sh / compose.sh  同步源码 / 透传 docker compose 命令
        ├── bootstrap.sh / debug-shell.sh
        ├── run-m2divgold.sh / pull-data.sh / install-schedule.sh          M2DivGold
        └── deploy-dipwatch-web.sh / install-dipwatch-schedule.sh /
            prepare-dipwatch-proxy.sh / prepare-web-completions.sh         USStockDipWatch
```

Docker 只读取构建上下文根目录的 `.dockerignore`，所以真正生效的排除规则在**仓库根**的 `/.dockerignore`（本目录不放 `.dockerignore`）。

### 各文件作用

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 基于 `python:3.12-slim`（带 digest 固定），建非 root 用户 `vibequant`(uid 10001)，装 `requirements.txt`，拷入 `M2DivGold/` 和 `VibeQuantFront/`，预建可写目录 |
| `compose.yaml` | 定义 4 个服务与 4 个命名卷；`x-app` 锚点统一 build/image/init 设置 |
| `requirements.txt` | 共用依赖：pandas、numpy，以及 LiveMoreAmazing/requirements.txt 和官方 SDK wheel |
| `.env.example` | 远端 `docker/.env` 的模板（`FRED_API_KEY` / `FRONT_BIND` / `FRONT_PORT`） |
| `.env.remote` | Mac 侧 SSH 四要素（host / port / project dir / compose project），由 `_common.sh` 读取 |
| `.remoteignore` | 同步排除：`.git/`、`**/data/`、`**/results/`、`.env*`、密钥证书、缓存等 |
| `scripts/remote/*.sh` | 见下表，全部是 Mac 端薄封装：`sync.sh` → `compose.sh <命令>` |

### 部署脚本

| 脚本 | 做了什么 |
|---|---|
| `_common.sh` | 被 source 的公共库：加载 `.env.remote`，校验 host/port/路径格式，定义 `remote_exec`、`remote_shell_quote`；缺配置直接退出 |
| `sync.sh` | `rsync --archive` 仓库到 `$REMOTE_PROJECT_DIR`，按 `.remoteignore` 排除，**仅清理三个已废弃的 AmazingData 入口文件** |
| `compose.sh` | `ssh … 'cd <远端docker> && docker compose --project-name vibequant <你的参数>'` |
| `bootstrap.sh` | `sync.sh` + `compose.sh build` → 产出/更新 `vibequant:dev` |
| `debug-shell.sh` | `sync.sh` + `compose.sh run --rm dev-shell bash`（bind 挂载远端源码，改完 `sync.sh` 即生效） |
| `run-m2divgold.sh` | `sync.sh` + `compose.sh run --rm m2divgold` → 抓 M2/黄金，写远端卷 `vibequant_vibequant-data` |
| `install-schedule.sh` | `sync.sh` + 在宿主机 crontab 里装「每天 08:00 拉数据 + 出图」的规则（幂等） |
| `pull-data.sh` | 用一次性容器把数据卷 `tar` 出来，存到 Mac 的 `docker/out/` |

## 服务与数据卷

| Service | 项目 | 命令 | 挂载卷 |
|---|---|---|---|
| `m2divgold` | M2DivGold | `python fetch_m2_gold.py` | `vibequant-data` → `data`；`vibequant-web` → `/srv/web`（图表输出） |
| `front` | VibeQuantFront | `python -m http.server 8000 -d /srv/web`（常驻） | `vibequant-web` → `/srv/web` |
| `dev-shell` | —（profile `dev`） | `sleep infinity` | 仓库根 bind 到 `/workspace` |

命名卷：`vibequant-data`（M2/黄金数据）、`vibequant-web`（前端站点根：`index.html` + 各项目产物）。**数据在卷里，不在镜像里**——镜像只带源码，所以改代码必须重新 build 才生效。

## 前置条件

1. Mac 能免密 ssh 到远端（脚本用 `BatchMode=yes`，不会交互要密码）。
2. 远端装了 Docker + compose 插件，并启用 BuildKit。
3. `docker/.env.remote` 已填好（模板见 `.env.remote.example`）。
4. 远端 `docker/.env` 已按需填好（见下）。

## 首次部署

构建前需先放入官方 wheel，详见下方 LiveMore 说明。

```bash
cd /Users/lxy/VibeQuant/docker/scripts/remote

./bootstrap.sh    # 同步源码 + 构建 vibequant:dev
```

## 远端 .env（应用密钥）

`.env.example` 随源码同步到远端，首次在远端执行：

```bash
ssh -p 2222 lxy@121.41.112.193
cd /home/lxy/VibeQuant/docker
cp .env.example .env
vim .env      # 填 FRED_API_KEY
```

`.env` 和 `.env.remote` 都被 `.remoteignore` 排除：不同步、不进镜像、不提交。

## 跑 M2/黄金数据

远端 `.env` 里要有 `FRED_API_KEY`（免费申请：<https://fred.stlouisfed.org/docs/api/api_key.html>）。

```bash
cd /Users/lxy/VibeQuant/docker/scripts/remote

./run-m2divgold.sh    # 抓 1959 至今（写远端卷）
./pull-data.sh        # 数据卷拉回 Mac 的 docker/out/m2divgold-data.tar
```

解包看数据：

```bash
tar -xf /Users/lxy/VibeQuant/docker/out/m2divgold-data.tar -C 某个目录
```

改了 `M2DivGold/` 的**代码**后必须先 `./bootstrap.sh` 重建镜像，否则容器里跑的还是旧代码。

## 结果网页（经公网机用浏览器访问）

前端门户 `VibeQuantFront/` 是站点入口：`index.html` 列出各项目及其产物链接。各项目在容器里生成的网页写进站点卷 `vibequant-web`，由常驻服务 `front` 对外提供。宿主机与公网机之间走已有 FRP 隧道。

```text
浏览器 → 公网机 nginx/caddy :443
        → http://127.0.0.1:8080（公网机本机，frps 监听）
        → FRP 隧道
        → 宿主机 127.0.0.1:8000（docker 发布）
        → 容器 http.server → 站点卷 /srv/web
```

站点结构：

```text
/srv/web/（命名卷 vibequant-web）
├── index.html                        VibeQuantFront 入口（镜像里 COPY 进来，首次挂卷时初始化）
└── m2divgold/
    └── ratio_m2_gold_daily.html      图表脚本写进来
```

容器端口只绑 `127.0.0.1`，frpc 从宿主机本机连它——**端口不上宿主机局域网、更不上公网**，唯一入口是公网机的 nginx。访问根路径 `http://121.41.112.193:8080/` 时 `http.server` 会自动显示 `index.html`。

### 1) 生成 / 刷新图表（在宿主机）

```bash
cd /Users/lxy/VibeQuant/docker/scripts/remote

./run-m2divgold.sh                                            # ① 拉最新数据（每月跑一次就够）
./compose.sh run --rm m2divgold python daily_ratio_chart.py   # ② 重新生成网页
```

② 不传 `-o` 时，`daily_ratio_chart.py` 读到环境变量 `VIBEQUANT_SITE_DIR=/srv/web`（compose 里已设），把 HTML 写进 `/srv/web/m2divgold/ratio_m2_gold_daily.html`，门户页立刻可见，**不用重启、不用重新 build**。

### 2) 启动常驻服务

远端 `docker/.env`：

```dotenv
FRONT_BIND=127.0.0.1    # 只绑回环，交给 frpc 连
FRONT_PORT=8000
```

```bash
./compose.sh up -d front     # 起服务（restart: unless-stopped，随 Docker 自启）
./compose.sh ps              # 看状态
./compose.sh logs -f front   # 看访问日志
./compose.sh down front      # 停掉
```

宿主机上自测（根路径应返回 index.html，子路径是图表）：

```bash
curl -I http://127.0.0.1:8000/
curl -I http://127.0.0.1:8000/m2divgold/ratio_m2_gold_daily.html
```

### 3) FRP：宿主机把 8000 推到公网机的 8080

改**宿主机**上的 `~/frpc/frpc.toml`（真正生效的是 `/etc/frp/frpc.toml`，见下），在现有 `ssh-tunnel` 后面追加：

```toml
# VibeQuant 前端门户 — 宿主机 8000 -> 公网机 8080
[[proxies]]
name = "vibequant-front"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8000
remotePort = 8080
```

然后 `systemctl restart frpc`。

用 `type = "tcp"` 是为了**不用改 frps 配置**（TCP 代理只借 `bindPort` 的控制通道，不需要 `vhostHTTPPort`）。`frps.toml` 保持原样即可。

### 4) 公网机反代

nginx：

```nginx
server {
    listen 443 ssl;
    server_name m2gold.example.com;

    ssl_certificate     /etc/letsencrypt/live/m2gold.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/m2gold.example.com/privkey.pem;

    # 网页约 400 KB（数据内嵌），开压缩省流量
    gzip on;
    gzip_types text/html text/css application/javascript;
    gzip_proxied any;

    location / {
        proxy_pass http://127.0.0.1:8080;      # frps 在本机监听的 8080
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

caddy（证书自动签，两行就够）：

```text
m2gold.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

改完 `nginx -t && systemctl reload nginx`，浏览器访问 `https://m2gold.example.com/` 即门户页。

如果不打算配域名，也可以跳过 nginx 直接用 TCP 口：浏览器访问 `http://121.41.112.193:8080/`（但要把云安全组的 8080 打开，且没有 HTTPS）。

### 5) 安全

- **门户页是公开的**：能访问到公网机的人都能看。只是宏观数据，一般无所谓；要限制就在公网机加 HTTP Basic 认证（nginx `auth_basic`／caddy `basicauth`）。
- **别把宿主机端口开到公网**：`FRONT_BIND=127.0.0.1`，只让 frpc 连得到。
- **云安全组不要开 8080**：nginx 是经 `127.0.0.1:8080` 访问 frps 的，走回环不受安全组限制，所以 8080 对外开着没有任何必要。**但如果安全组恰好是"全部放行"，那 8080 就会绕过 nginx 直接暴露在公网**——那你加在 nginx 上的认证也就白加了，务必确认这条。
- 容器里跑的是 Python 自带的 `http.server`，简单够用，但不适合高并发和公网裸奔——对外那一层交给公网机的 nginx/caddy。

## 定时更新（每天 08:00）

宿主机上的 cron 每天 08:00（宿主机本地时间）跑一次「拉数据 + 出图」，脚本在 `scripts/host/daily-update.sh`。

```bash
cd /Users/lxy/VibeQuant/docker/scripts/remote
./install-schedule.sh          # 装 cron（幂等，可重复跑）
```

装的规则就是：

```text
0 8 * * * /home/lxy/VibeQuant/docker/scripts/host/daily-update.sh >> /home/lxy/VibeQuant/docker/logs/daily.log 2>&1
```

要点：

- **不重启任何容器**：`daily-update.sh` 用 `docker compose run --rm m2divgold …` 起一次性容器，跑完即删，常驻的 `front` 全程在线，网页不中断。出图是「先写临时文件再 `os.replace` 原子替换」，请求不会读到半截文件。
- 日志在 `docker/logs/daily.log`，每次运行都带起止时间戳。
- **cron 按宿主机本地时间触发**。如果宿主机时区不是 Asia/Shanghai，8 点会落在别的时刻——先 `timedatectl` 核对。
- 改时间：`ssh` 到宿主机 `crontab -e` 改 `0 8` 那两位；卸载：`crontab -e` 删掉那行。

## 构建排障

**构建卡在 pip install、几小时不动**：几乎一定是网络，不是依赖。国际链路访问 `pypi.org` 极慢甚至挂死，pip 在 DNS/连接卡住时不会自己超时。

Dockerfile 默认已把 pip 指向**清华 TUNA 镜像** + 显式 `--timeout 30 --retries 3`，正常应在几分钟内完成。要换源（例如换阿里云），在远端 `docker/.env` 加：

```dotenv
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
PIP_TRUSTED_HOST=mirrors.aliyun.com
```

其它常见情况：

- 卡在下载某个大包（`pyarrow` 约 41 MB、`numpy`、`pandas`，合计约 72 MB）→ 换源后重跑；`--mount=type=cache` 的 pip 缓存会保留已下完的包，**下次构建直接复用、不再重新下载**。
- **`import AmazingData` 报 `libcrypto.so.10 / libssl.so.10 / libtgw_python312 … cannot open shared object file`**：`tgw` 是 Linux 原生 SDK，把一整套依赖（OpenSSL 1.0.2 的 `libcrypto.so.10`/`libssl.so.10`、`libssh.so.4`、`libtgw.so`、`libadk.so` 等）打包在 `site-packages/tgw/common_linux_lib64/` 里。Dockerfile 调用 `docker/scripts/configure_tgw.py`，从已安装 wheel 动态定位库目录，再把该目录写进 `/etc/ld.so.conf.d/tgw.conf` 并 `ldconfig`，让这些 `.so` 按 SONAME 可解析；同时补装 `libgssapi-krb5-2`+`libkrb5-3`（`libtgw_python312` 还链了 Kerberos）。导入前对当前 Python 使用的 tgw 扩展执行 `ldd`，检查其传递依赖，不检查其他 Python 版本的备用扩展。若仍报缺库，先区分 wheel 自带库的搜索路径和真正缺失的系统库；安装 Python 包与动态库配置已分层缓存，修正库配置无需重复安装 Python 依赖。
  - **注意**：这套 SDK 捆绑的是 OpenSSL **1.0.2**（2019 年已 EOL）。它只在该 SDK 内部用（SONAME 与系统的 OpenSSL 3.x 不同，不会冲突），但如果这个库要连外网/不可信端点，需自行评估这层老旧加密栈的风险。
- 怀疑缓存坏了 → 远端执行 `docker builder prune` 后重跑。**注意：这会丢掉 pip 下载缓存，下次构建要重新下 72 MB。**
- 千万别用 `docker compose down -v`：会删掉 `vibequant-data` / `vibequant-web` 等数据卷。

## 常用手工命令

```bash
./compose.sh ps                                              # 看远端服务状态
./compose.sh logs --tail 50 front                            # 看门户服务的访问日志
./compose.sh run --rm m2divgold python -c "import pandas; print(pandas.__version__)"
./debug-shell.sh                                             # 交互调试
```

## 安全边界

- 容器以非 root 用户 `vibequant`(uid 10001) 运行；源码层只读，数据写命名卷。
- 密钥只放远端 `docker/.env`：不同步、不进镜像、不提交。
- 只有 `front` 会发布宿主机端口，且绑定地址由 `FRONT_BIND` 决定——**建议填 `127.0.0.1`**，只让宿主机上的 frpc 连得到；`0.0.0.0` 会连公网网卡一起监听，是否可达取决于云安全组。其余服务（`m2divgold` / `dev-shell`）不发布任何端口。
- `.env.remote` 只含 SSH/部署元数据，权限 `600`。

## LiveMore 的 AmazingData 副本（共用 M2 镜像）

`LiveMoreAmazing/` 已合并到现有 `Dockerfile`、`compose.yaml`，所有服务共用 `vibequant:dev`。新增 `livemore-amazing` 服务（profile: amazing，显式 run 时自动启用），使用独立缓存/结果卷；账号配置只传入此服务。

构建前把匹配 Python 3.12 / Linux x86_64 的官方 AmazingData/tgw wheel 放入 `docker/wheels/amazing/`。统一镜像现在要求这些安装包齐全，缺少时构建失败；现有运行容器不会因构建失败被停止。

```bash
cd docker/scripts/remote
./sync.sh
./compose.sh build m2divgold
./compose.sh run --rm livemore-amazing python -c 'import AmazingData, tgw; print("SDK imports OK")'
```

原 `Dockerfile.amazing`、`compose.amazing.yaml`、`compose.amazing-login.yaml` 已删除。sync.sh 会精确清理远端这三个遗留文件，不删除其他远端文件、账号或数据卷。无需再使用 `-f` 参数。

完整步骤见 [LiveMoreAmazing/README.md](../LiveMoreAmazing/README.md)。
