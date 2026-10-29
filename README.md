# VibeQuant

用 AI 做量化的个人项目集合。几个子项目共用**一个 Docker 镜像 + 一份 compose**，部署在远端 Ubuntu 主机上，产物统一发布到同一个网站（经公网机反向代理对外访问）。

**Mac 只做编辑和编排**（写代码、Git、rsync、SSH）；依赖安装、数据抓取、镜像构建和测试都在远端容器里执行。

## 子项目

| 目录 | 做什么 | 网站入口 | compose 服务 |
|---|---|---|---|
| [`M2DivGold/`](M2DivGold/README.md) | 抓美国 M2（FRED）与黄金（LBMA），生成「M2 ÷ 黄金」日度交互图 | `/m2divgold/` | `m2divgold` |
| [`LiveMoreAmazing/`](LiveMoreAmazing/README.md) | 银河 AmazingData 只读行情 + 利弗莫尔六栏状态机 + Backtrader 回测 | `/livemore/` | `livemore-amazing` |
| [`USStockDipWatch/`](USStockDipWatch/README.md) | 美股/合约回撤观察：Alpaca + Binance 采集，网页勾选完成记录 | `/usstockdipwatch/` | `usstock-dip-watch`、`mihomo` |
| `VibeQuantFront/` | 门户首页 `index.html`，成为站点根 `/srv/web` | `/` | `front` |
| [`docker/`](docker/README.md) | 共享镜像、compose、Mac 侧部署脚本、远端 cron 脚本 | — | — |
| [`tools/`](tools/livemore-docker-check/README.md) | 一次性的本机辅助工具（原版 LiveMore 离线 Docker 验收脚本） | — | — |

## 仓库结构

```text
VibeQuant/
├── README.md               本文件：总览
├── AGENTS.md               AI 协作的变更纪律（凭据、AmazingData 权限、禁止删除的数据……）
├── CLAUDE.md               命令速查与跨文件架构说明
├── M2DivGold/
│   ├── fetch_m2_gold.py        抓 M2 + 金价 → data/*.csv
│   └── daily_ratio_chart.py    data/*.csv → 自包含交互 HTML
├── LiveMoreAmazing/
│   ├── run_backtest.py         主入口：采集 + 并行回测
│   ├── livemore/               核心库：数据适配、策略、回测引擎、图表、报告（含报告发布命令）
│   └── docs/
├── USStockDipWatch/
│   ├── collect.py  publish.py  site_server.py  reminder_state.py
│   ├── web/                    页面源文件
│   ├── tests/  docs/
│   └── legacy/                 已退役的 Cloudflare Worker 原型（不进镜像）
├── VibeQuantFront/index.html
├── docker/
│   ├── Dockerfile  Dockerfile.mihomo  compose.yaml  requirements.txt  .env*.example
│   ├── mihomo/  wheels/  out/
│   └── scripts/{configure_tgw.py, host/, remote/}
├── tools/livemore-docker-check/
└── local/                  个人笔记、本机私有文件（git / rsync / 镜像都忽略）
```

`tmp/`（临时检查结果）、`*/data/`、`*/results/`、`*/.cache/`、`docker/out/` 都是运行产物，已在 `.gitignore` 中忽略。

## 快速开始（M2DivGold）

```bash
# 1) 同步源码 + 构建镜像（Mac 终端）
cd docker/scripts/remote
./bootstrap.sh

# 2) 拉数据 + 出图
./run-m2divgold.sh
./compose.sh run --rm m2divgold python daily_ratio_chart.py

# 3) 起门户服务
./compose.sh up -d front

# 4) 每天 08:00 自动更新（可选）
./install-schedule.sh
```

其余子项目的运行步骤见各自 README；部署、公网访问、定时任务、排障见 [`docker/README.md`](docker/README.md)。

> 改动源码后要**重建镜像**（源码是 `COPY` 进镜像的，只同步不会更新容器里的代码）。
> 同步脚本不会删除远端文件，旧路径可能残留在服务器上；镜像构建已通过 `.dockerignore` 排除这些旧路径。

## M2DivGold 数据源

| 数据 | 来源 | 覆盖 |
|---|---|---|
| 美国 M2 | FRED `M2SL`（美联储官方序列） | 1959-01 起 |
| 黄金 | LBMA 伦敦金定盘价（官网 JSON） | 1968-04-01 起 |
| 黄金（1968 年前） | 美国官方金价常量 $20.67 / $35.00 | 1919-09 ~ 1968-03 |

## 关于 LiveMore 原版

`LiveMore/`（原版 QMT 实现）与 `datasrc/` 被 git 忽略，只作参考、不修改；`LiveMoreAmazing/` 是改用银河 AmazingData 的独立副本。
