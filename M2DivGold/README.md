# M2 ÷ 黄金 —— 数据抓取与图表

抓美国 **M2** 与**黄金**的长期历史数据，算「M2 ÷ 黄金」比值（即全部 M2 能买多少盎司黄金），并生成图表网页。

## 目录结构与文件作用

```text
M2DivGold/
├── README.md                 本文件
├── fetch_m2_gold.py          数据抓取：M2 + 黄金（1959/1968 至今）
└── daily_ratio_chart.py      日度比值交互图（自包含 HTML）
```

| 文件 | 作用 | 输出 |
|---|---|---|
| `fetch_m2_gold.py` | 从 FRED 拉 `M2SL`，从 LBMA 拉日度金价并聚合到月度 | `data/m2_monthly.csv`、`data/gold_daily.csv`、`data/gold_monthly.csv`、`data/combined_monthly.csv` |
| `daily_ratio_chart.py` | 读月度 M2 + 日度金价，算日度比值，出交互网页 | `ratio_m2_gold_daily.html`（默认写在数据同目录） |

`data/` 是数据落地目录（Docker 部署时它是命名卷 `vibequant-data`，不在镜像里，也不会被 rsync 同步）。

## 运行

### 方式一：远端 Docker（推荐，正式用这个）

Mac 终端里跑，见 [`../docker/README.md`](../docker/README.md)：

```bash
cd /Users/lxy/VibeQuant/docker/scripts/remote
./bootstrap.sh        # 改了代码要先重建镜像
./run-m2divgold.sh    # M2 + 黄金（1959/1968 至今）
./pull-data.sh        # 把数据拉回 Mac 的 docker/out/*.tar
```

### 方式二：本机直接跑

需要 Python3 + pandas（只有这一个依赖）：

```bash
pip install pandas
cd /Users/lxy/VibeQuant/M2DivGold
export FRED_API_KEY=你的32位key
python3 fetch_m2_gold.py
```

### 生成图表（在**本机/Mac**跑，不在容器里）

图表脚本只依赖 pandas（容器镜像里没有装绘图库，所以在本机跑）：

```bash
python3 daily_ratio_chart.py     # 日度比值交互图
```

读 `data/m2_monthly.csv`（月度 M2）与 `data/gold_daily.csv`（日度金价），输出 `ratio_m2_gold_daily.html`——**自包含 HTML**（数据内嵌、零外部依赖、离线可开），默认窗口为最近一年，支持拖动平移、滚轮缩放、悬停查看当日数值，并可切 1/2/5/10 年与全部。

容器里会设 `VIBEQUANT_SITE_DIR=/srv/web`，脚本把 HTML 写进 `<站点根>/m2divgold/ratio_m2_gold_daily.html`，供前端门户 `VibeQuantFront` 的 `index.html` 链接；本机跑（没设这个变量）就写到 `data/` 旁边。

## 输出文件与数据字典

| 文件 | 列 | 说明 |
|---|---|---|
| `m2_monthly.csv` | `m2` | M2 月度，索引为月末日期 |
| `gold_daily.csv` | `gold` | LBMA 日度定盘价（美元/盎司），原样落盘 |
| `gold_monthly.csv` | `gold_month_end`、`gold_month_avg` | 月末收盘价 + 月均价 |
| `combined_monthly.csv` | `m2`、`gold_month_end`、`gold_month_avg` | 二者按月末日期合并 |

日度图只用前两份：`m2_monthly.csv` 的 M2（线性插值到日度）+ `gold_daily.csv` 的日度金价。`gold_monthly.csv` / `combined_monthly.csv` 是月度表，留给其他分析用。

## 已知限制

- **没有官方日度 M2**。日度图里的 M2 是用月度值**线性插值**摊到每一天的，当月尚未公布的部分沿用最近一个月末值。也就是说日度比值的**逐日波动全部来自金价**，M2 只贡献平滑趋势。
- **周末和假日没有金价**，日度比值在这些天是断开的，折线会直接跨过去连，不是缺数据。
- **M2 近几个月会被回修**，历史图上早先的读数与现在可能不同。
- **日度图的曲线从 1968-04-01 起**——LBMA 的日度定盘价从这天开始。M2 本身是 1959-01 起（官方序列起点），1968-04 之前的月度和官价段没有日度数据，所以不在日度图里。
- **1968 年前金价是官方钉死的常数**（1919-09~1934-01 = $20.67，1934-02~1968-03 = $35.00），不是市场价，解读历史区间时要注意。
- FRED key 不要写进代码或提交到仓库；本地跑用 `export FRED_API_KEY=…`，正式部署走远端 `docker/.env`。

## 定时更新

宿主机 cron 每天 08:00 自动「拉数据 + 出图」，安装见 [`../docker/README.md`](../docker/README.md) 的「定时更新」一节（Mac 上跑一次 `install-schedule.sh` 即可）。

## 数据源

**只用一个源，不做多源兜底。** M2 只用 FRED，黄金只用 LBMA（1968 年前 LBMA 没有数据，用美国官方金价）。

| 数据 | 来源 | 频率 | 覆盖区间 | 说明 |
|---|---|---|---|---|
| 美国 M2 | [FRED `M2SL`](https://fred.stlouisfed.org/series/M2SL) | 月度 | 1959-01 起 | 美联储官方 M2 存量，季调，单位十亿美元 |
| 黄金 | [LBMA 伦敦金定盘价](https://www.lbma.org.uk/prices-and-data) 日度 JSON | 日度（工作日） | 1968-04-01 起 | 美元/盎司。PM 定盘价为主，AM 为备（同一来源的两个场次） |
| 黄金（1968 年前） | 美国官方金价（历史事实常量，非下载） | 月度 | 1919-09 ~ 1968-03 | 1919-09~1934-01 = **$20.67**；1934-02~1968-03 = **$35.00** |

> **M2 起点就是 1959-01，不再往前。** 美联储官方 M2 序列（H.6）自 1959-01 才有，1959 年前美联储没有发布过官方 M2。本项目只用官方数据源，不引入第三方重构序列，因此「M2 ÷ 黄金」比值也从 1959-01 起：1919–1958 这段只有金价、没有 M2。

LBMA 的日度数据直接从官网 JSON 接口取，无需 API key：

```text
https://prices.lbma.org.uk/json/gold_pm.json     # 下午定盘价（首选）
https://prices.lbma.org.uk/json/gold_am.json     # 上午定盘价（备选）
```

### 关于数据源的几点说明

- **FRED 的 LBMA 金价序列（`GOLDAMGBD228NLBM` / `GOLDPMGBD228NLBM`）已被下架**，没有官方替代，所以金价改从 LBMA 官网直接取。
- **世界银行 Pink Sheet 不再使用**（早期版本曾作为兜底），保留相关环境变量只是为了不破坏旧配置，脚本已不读。
- **不使用第三方重构的 1959 年前 M2 序列**，只用美联储发布的官方序列。
- **1968 年前的黄金没有"数据源"可下**——那段时期美元金价由官方钉死，是两个常数，脚本直接生成。
- 由于 1968 年前金价恒定，那一整段比值的变动**全部来自 M2**，看图时要注意这一点。
