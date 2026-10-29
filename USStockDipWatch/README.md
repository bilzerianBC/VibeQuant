# 回撤观察 / Alpaca

远端 `/home/lxy/VibeQuant` 复用共享镜像和现有 front 网页卷。
`usstock-dip-watch` 默认执行 `python collect.py`，仅调用 Alpaca 只读行情接口。
`publish.py` 只负责发布网页。旧 JS/Worker/Sites 原型已移到 `legacy/cloudflare-worker/`，不属于生产流程。

## 目录结构

```text
USStockDipWatch/
├── collect.py          行情采集（Alpaca 美股 + Binance 合约），写 data.json / reminders.json
├── publish.py          把 web/ 下的页面和估值数据原子发布到网站卷 /srv/web/usstockdipwatch/
├── site_server.py      front 服务的 HTTP 服务器：静态门户 + 网页勾选完成记录接口
├── reminder_state.py   目标价列表与完成记录合并（site_server 使用）
├── web/                页面源文件：index.html、pe-history.json
├── tests/              Python 单元测试
├── docs/               排障记录（TROUBLESHOOTING.md）
└── legacy/             已退役的 Cloudflare Worker 原型，不打包进镜像
```

每半小时取最新分钟收盘价，与近 52 周最高已完成日线收盘价比较；历史日线使用
`adjustment=split`，不做分红调整，至少需要 180 根日线。IEX 是单交易所行情。
首次记录当前达到的 10%–60% 档位；之后按相邻成功采集比较，记录新越过的档位。
两次采集之间发生又恢复的越界不会记录。重复行情去重，反弹后再次跌破重新记录。
工作日纽约时间 10:00–16:00，行情超过 45 分钟暂停新提醒（休市也暂停）；其他时间超过 5 天暂停。
失败保留旧结果和提醒历史，文件锁防止并发更新，请求有 20 秒超时和分页上限。

默认采集 QQQ、NVDA、TSLA、SPCX（Alpaca），并独立采集 ANTHROPICUSDT（Binance 公开合约行情）。
不会用其他股票或 Alpaca 行情替代币安合约。默认最高 3/5，退出码 1 表示仍有待确认项。
需要五只股票时，在 DIPWATCH_SYMBOLS 配置五个经过核实的美股/ETF代码，替换默认列表。

## 注册账号

访问 https://app.alpaca.markets/ 注册、验证邮箱，按平台要求填写信息。
切换到 Paper / 模拟账户，找到 API Keys，选择 Generate New Keys，保存 Key ID 和 Secret Key。
本程序无需入金或调用交易接口；账号资格以平台审核为准。
默认 `ALPACA_DATA_FEED=iex`，只有确认 SIP 权限后才改为 `sip`。

官方说明：
- https://docs.alpaca.markets/us/docs/getting-started-with-alpaca-market-data
- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/reference/stockbars

## 同步、构建（Mac）

```sh
cd /Users/sionlv/VibeQuant
./docker/scripts/remote/sync.sh
./docker/scripts/remote/compose.sh build m2divgold
./docker/scripts/remote/compose.sh run --name dipwatch-tests-$(date +%Y%m%d%H%M%S) usstock-dip-watch python -m unittest discover -s tests -p 'test_*.py' -v
```

源码改动必须重建镜像。同步不删除远端文件，也不覆盖 `.env.dipwatch` 或 `.env.amazing`。

## 配置密钥和代理（远端）

```sh
ssh -p 2222 lxy@121.41.112.193
cd /home/lxy/VibeQuant/docker
umask 077
test -e .env.dipwatch || cp .env.dipwatch.example .env.dipwatch
chmod 600 .env.dipwatch
nano .env.dipwatch
```

在编辑器中填写 `ALPACA_API_KEY_ID`、`ALPACA_API_SECRET_KEY`。不要把真实密钥写在命令行或发到聊天。
代理使用项目内 Mihomo 服务：

```dotenv
HTTP_PROXY=http://mihomo:7890
HTTPS_PROXY=http://mihomo:7890
```

节点配置放在 `docker/mihomo/config.yaml`，详细步骤见 [Mihomo 配置说明](../docker/mihomo/README.md)。
先在 Mac 运行 `bash docker/scripts/remote/prepare-dipwatch-proxy.sh` 准备文件，
手工填写节点后在远端执行 `docker compose --project-name vibequant --profile dipwatch up -d mihomo`。
无需宿主机额外目录、不映射公网代理端口；配置与缓存都位于项目目录内。
现有 `.env.dipwatch` 不会被覆盖，请手工将旧代理地址改为上面的两项。
真实 config.yaml、runtime 和 .env.dipwatch 不参与源码同步、Git 或镜像打包，迁移时私下复制。

## 连通性、采集和发布验收（远端）

```sh
cd /home/lxy/VibeQuant/docker
# 单标的只读诊断，不写网页数据，不输出凭证。
docker compose --project-name vibequant run --name dipwatch-probe-$(date +%Y%m%d%H%M%S) usstock-dip-watch python collect.py --diagnose
echo "exit=$?"
# 更新页面并保留已有行情，再运行采集。
docker compose --project-name vibequant run --name dipwatch-page-$(date +%Y%m%d%H%M%S) usstock-dip-watch python publish.py
docker compose --project-name vibequant run --name dipwatch-collect-$(date +%Y%m%d%H%M%S) usstock-dip-watch
echo "exit=$?"
docker compose --project-name vibequant ps -a --format json usstock-dip-watch
docker compose --project-name vibequant exec -T front ls -lh /srv/web/usstockdipwatch
```

退出码 0=全部成功；1=部分失败/标的待确认；2=配置、锁或运行环境错误。
401 检查密钥；403 检查 feed 权限或上游拒绝；407 检查代理认证；429 为限流。
网络/代理/TLS 异常不会输出包含代理密码的原始异常。
诊断成功只代表接口可用，完整采集还需核对时间、历史覆盖和网页。
网页：http://121.41.112.193:8080/usstockdipwatch/ 。

## 验收通过后安装每半小时任务（Mac）

```sh
cd /Users/sionlv/VibeQuant
bash docker/scripts/remote/install-dipwatch-schedule.sh
```

任务在每小时 00、30 分运行。本次准备不自动启用 cron 或手机提醒。
保留每次容器用于检查退出码，长期会积累容器，清理需另行明确授权。

```sh
# 远端检查日志、容器状态
 tail -n 100 /home/lxy/VibeQuant/docker/logs/dipwatch.log
cd /home/lxy/VibeQuant/docker
docker compose --project-name vibequant ps -a --format json usstock-dip-watch
# 将 NAME 替换为上一步的容器名
docker logs NAME
```

复制结果回 Mac：

```sh
cd /Users/sionlv/VibeQuant
mkdir -p USStockDipWatch/outputs
./docker/scripts/remote/compose.sh exec -T front tar -C /srv/web -cf - usstockdipwatch/index.html usstockdipwatch/data.json usstockdipwatch/reminders.json > USStockDipWatch/outputs/usstockdipwatch.tar
```

本地测试：在 USStockDipWatch 内执行 `python3 -m unittest discover -s tests -p 'test_*.py' -v`。

## 网站勾选与完成记录

每个价位直接在网页勾选完成，按股票记录完成时间和当时目标价。不使用苹果提醒事项或 Mac 定时同步。
取消勾选恢复待办，历史完成记录保留。完成状态保存在现有网页卷的 `usstockdipwatch/completions.json`，行情采集不会覆盖。
写入需要网站操作密码，配置在远端 `docker/.env.web` 的 `DIPWATCH_EDIT_PASSWORD`，权限 600。
该文件只注入 front 服务，不包含 Alpaca 密钥，不提交、不同步、不打入镜像。
密码只在当前浏览器标签页保存，点击“锁定”清除；各设备使用同一密码解锁。

远端首次配置（已有文件不要覆盖）：

```sh
cd /home/lxy/VibeQuant/docker
umask 077
test -e .env.web || cp .env.web.example .env.web
chmod 600 .env.web
nano .env.web
docker compose --project-name vibequant up -d --no-deps front
```

代码同步、重建共享镜像后发布网页：

```sh
cd /Users/sionlv/VibeQuant
./docker/scripts/remote/sync.sh
./docker/scripts/remote/compose.sh build m2divgold
./docker/scripts/remote/compose.sh run --name dipwatch-page-$(date +%Y%m%d%H%M%S) usstock-dip-watch python publish.py
./docker/scripts/remote/compose.sh up -d --no-deps front
```

查看日志和状态：`compose.sh logs --tail 50 front`、`compose.sh ps front`。
备份完成记录：

```sh
./docker/scripts/remote/compose.sh exec -T front tar -C /srv/web -cf - usstockdipwatch/completions.json > /tmp/dipwatch-completions.tar
```

现有入口是 HTTP，公网传输没有 HTTPS 加密；使用可信网络或已有 HTTPS 入口操作密码。

## 市盈率时间序列

页面估值图读取 `web/pe-history.json`，由 `publish.py` 原子发布到共享网站卷。2026-10-11 核实的快照包含 2023 年以来 NVDA、TSLA 季度 TTM PE、标普 500 月度 TTM PE，以及 QQQ 2026-06-30 官方持仓加权调和平均 TTM PE 单点。来源链接、日期、估计标记和口径保留在 JSON 及网页中。QQQ 完整历史尚未取得；SPCX 身份已核实但历史 TTM PE 未核实；ANTHROPICUSDT 为 Pre-IPO 合约，不能直接计算公司 PE。

这份估值快照不会随 Alpaca 半小时价格采集更新；补充数据时必须核对来源、真实观察日期和 PE 口径，再更新 JSON 并发布。个股财季月份与标普月度观察日期不同，图中不计算逐点溢价。历史财季 PE 可能使用事后公布或重述盈利，不能直接用于无前视偏差回测。

从仓库根目录部署（保留网站完成记录）：

```bash
./docker/scripts/remote/sync.sh
./docker/scripts/remote/compose.sh build m2divgold
./docker/scripts/remote/compose.sh run --name dipwatch-pe-publish usstock-dip-watch python publish.py
```

发布写入共享卷，网页刷新即可显示，无需重启正在运行的策略。

## 新上市与合约行情

SPCX 只使用 2026-06-12 起的 SpaceX 数据，过滤此前同代码资产历史。ANTHROPICUSDT 使用 Binance USDⓈ-M 公开 ticker/price 最新成交价和 klines 已完成 UTC 日线，无需 Binance 密钥；复用 env 代理，不发送 Alpaca 鉴权头。数据源分别处理故障，保留上次有效结果。

上市不足一年使用上市以来最高已完成日线收盘价，需要至少 30 根日线，首条日线不晚于上市后 7 天；满一年恢复近 52 周和至少 180 根要求。股票使用纽约交易日、合约使用 UTC。合约最新价超过 5 分钟视为过期。网页显示实际基准、覆盖天数、价格类型和时区。

远端 .env.dipwatch 设置 DIPWATCH_SYMBOLS=QQQ,NVDA,TSLA,SPCX；ANTHROPICUSDT 不放入这个美股列表。同步并重建共享镜像后运行（容器名称每次使用不同后缀）：

```bash
./docker/scripts/remote/compose.sh run --name dipwatch-five-assets usstock-dip-watch python collect.py
./docker/scripts/remote/compose.sh run --name dipwatch-five-publish usstock-dip-watch python publish.py
```
