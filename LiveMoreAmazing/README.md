# LiveMoreAmazing

使用银河证券 AmazingData 只读行情，计算 Livermore 六栏状态，并通过 Backtrader 进行可选的模拟回测。代码不调用券商实盘下单、交易或账户操作接口。

本说明按 2026-10-25 的代码整理。`LiveMore/` 是项目约定中的原版 QMT 实现，当前工作区没有该目录；本目录是 AmazingData 适配版本。历史研究文档不作为当前交易规则的依据。

## 当前策略与执行规则

- 默认关闭模拟交易，只计算六栏状态，输出 `signals_<start>_<end>.csv`。
- 显式传入 `--enable-trading` 后：从其他状态进入 `UP_TREND`（上涨趋势）时产生买入信号；从 `UP_TREND` 离开时产生全平信号。
- 买入不要求突破此前历史最高价。上涨趋势持续期间不会重复产生买入信号；若订单因资金不足等原因被拒绝，不会仅因仍处于上涨趋势而重试。
- 固定买入 100 股，已有持仓不加仓，不做空，不设额外止损，不提取储备金，不做均线、大盘或成交量过滤。
- 六栏状态机默认转向参数为 `swing_pct=0.06`、`secondary_pct=0.03`，其内部状态判定逻辑保留。
- 信号按当日收盘状态计算；Backtrader 默认市场单在后续可成交 K 线上执行，成交标记可能比信号晚一根 K 线。
- `--no-index` 是保留的兼容参数；当前大盘过滤固定关闭，该参数不改变行为。
- 模拟成本在 `livemore/backtest.py` 的 `AShareCommission` 中设置：双边佣金万二、卖出印花税千一，另设万五滑点。这是代码中的固定假设，需按研究日期另行核对。

`livemore/livermore_strategy.py` 只产生 `trade_hook(buy=..., sell=...)` 信号；`livemore/trading_statistics.py` 负责挂单、成交和持仓记账。直接构建 Cerebro 并开启交易时，需挂载 `PositionStatistics`，或提供自己的执行 hook。

## 目录结构

```text
LiveMoreAmazing/
├── run_backtest.py              主入口：在线采集、续传、离线并行计算、CSV 输出
├── livemore/                    核心库（被入口与脚本导入，不直接运行）
│   ├── amazing_data.py              SDK 登录退出、股票池、日历、历史日线、复权、成交量换算、校验与缓存
│   ├── livermore_strategy.py        六栏状态机、状态切换买卖信号、Backtrader 日线接口（与原版 LiveMore 保持一致）
│   ├── trading_statistics.py        模拟订单执行、待成交去重、成交明细与持仓统计
│   ├── backtest.py                  单标的回测引擎 run_single、A 股交易成本 AShareCommission
│   ├── charts.py                    六栏阶段分段 / 极值点 / 成交标记的 K 线 HTML
│   └── report.py                    summary CSV → 回测报告 HTML，并发布到网站（python -m livemore.report）
├── docs/                        策略研究笔记
├── requirements.txt
└── results/  .cache/            运行产物与行情缓存（自动创建，不提交 Git）
```

研究笔记：[docs/Livemore策略原文总结.md](docs/Livemore策略原文总结.md)、[docs/源码走读.md](docs/源码走读.md)，当前行为以本 README 和源码为准。

2026-10-26：按需求删除了 `scripts/`（诊断、分析、可视化工具）和 `tests/`（离线单元测试）。
它们都不参与网页数据的生成：回测结果由 `run_backtest.py` 产生，网页报告由 `python -m livemore.report` 发布。
需要找回时，可从 Git 历史或 `tmp/` 下的备份包中恢复。

## Docker 与数据约定

本项目和 M2DivGold、美股观察及门户共用 `docker/Dockerfile` 构建的 `vibequant:dev` 镜像，通过 `docker/compose.yaml` 中不同服务运行，并非全部运行在同一个容器。

- 行情服务：`livemore-amazing`，工作目录 `/workspace/LiveMoreAmazing`。
- 缓存卷：`livemore-amazing-cache`，挂载至 `/workspace/LiveMoreAmazing/.cache`。
- 结果卷：`livemore-amazing-results`，挂载至 `/workspace/LiveMoreAmazing/results`。
- 网站卷：`vibequant-web`，挂载至 `/srv/web`。
- 官方 Linux wheel 放在 `docker/wheels/amazing/`：保留一个兼容的 AmazingData 和一个 tgw wheel，匹配 Python 3.12 与远端架构。
- `docker/scripts/configure_tgw.py` 配置 tgw 自带原生库的链接路径，不能省略；验证 SDK 导入时应使用非 root 用户。

默认回测请求起点为 `19900101`，实际覆盖由服务端数据和复权因子决定，不保证上市以来全部历史。旧起点缓存不能冒充更早区间的完整缓存；离线运行的代码和起止日期必须匹配已准备缓存。

历史接口为高层 `MarketData.query_kline(...)`，底层是 `tgw.QueryKline`。返回 `(None, -95)` 表示“数据无权限”，应请求提供方开通历史 K 线权限，不无限重试。`BaseData.get_calendar()` 返回 `None` 与确认为 `-95` 的查询拒绝不同。工作日日历只辅助拆分请求，不代表真实交易日期。

成交量单位必须根据返回数据定义或提供方确认后设置 `AMAZING_VOLUME_UNIT=shares`（股）或 `lots`（手）。不得根据单个比值猜测。复权因子必须覆盖请求范围，不能用未来首次出现的因子回填更早日期。

## 配置、构建和验证

以下 Mac 命令从当前仓库根目录执行；本工作区路径为 `/Users/sionlv/VibeQuant`。远端默认路径为 `/home/lxy/VibeQuant`，具体 SSH 信息以本机 `docker/.env.remote` 为准。

```bash
cd /Users/sionlv/VibeQuant
test -f docker/.env.remote || cp docker/.env.remote.example docker/.env.remote
nano docker/.env.remote
./docker/scripts/remote/sync.sh
./docker/scripts/remote/compose.sh build m2divgold
```

真实账号只配置在远端 `/home/lxy/VibeQuant/docker/.env.amazing`，不要提交或同步。首次配置时在远端执行：

```bash
cd /home/lxy/VibeQuant/docker
test -f .env.amazing || cp .env.amazing.example .env.amazing
chmod 600 .env.amazing
nano .env.amazing
```

填写 `AMAZING_USERNAME`、`AMAZING_PASSWORD`、`AMAZING_HOST`、`AMAZING_PORT`；成交量单位核实后填写 `AMAZING_VOLUME_UNIT`。其他批量和重试参数见模板。不要把真实值放入代码、命令参数、文档或日志。

回到 Mac，确认 SDK 能以非 root 用户导入：

```bash
./docker/scripts/remote/compose.sh run --rm livemore-amazing python -c 'import os; assert os.getuid() != 0; import AmazingData, tgw; print("SDK imports OK")'
```

登录、单股单日权限检查脚本已随 `scripts/` 删除；建议先用 `run_backtest.py --codes 000001.SZ` 加短日期区间小样本采集来验证。权限和成交量单位都确认后，才继续批量采集。源码同步不会更新镜像中的代码，改动后必须重建共享镜像。以上是运行步骤，不是已完成验证的声明。

## 采集与回测

先用小样本，固定日期以便重跑。以下示例在 Mac 仓库根目录执行：

```bash
START=19900101
END=20261023

# 在线采集并计算行情信号；默认不模拟交易。
./docker/scripts/remote/compose.sh run --rm livemore-amazing \
  python run_backtest.py --codes 000001.SZ 600519.SH \
  --start "$START" --end "$END" --workers 2 --resume

# 同一区间、同一代码使用已有缓存，开启模拟交易。
./docker/scripts/remote/compose.sh run --rm livemore-amazing \
  python run_backtest.py --codes 000001.SZ 600519.SH \
  --start "$START" --end "$END" --workers 2 --skip-download --enable-trading
```

| 参数 | 说明 |
|---|---|
| `--start`、`--end` | 请求日期范围，格式 `YYYYMMDD`；实际覆盖可能更短 |
| `--codes` | 明确指定股票；省略时读取股票池 |
| `--sector` | 股票池，默认 `EXTRA_STOCK_A_SH_SZ` |
| `--limit` | 限制股票数量，默认不限制 |
| `--workers` | 离线计算进程数，默认 4 |
| `--resume` | 复用完整缓存，只下载缺失标的；保持起止日期和成交量单位一致 |
| `--skip-download` | 只读取已有缓存；未指定 codes 时还要求对应股票池清单存在 |
| `--enable-trading` | 开启 Backtrader 模拟交易并输出 summary |
| `--no-index` | 兼容参数，当前不影响行为 |

全样本采集前必须先完成上述权限、单位和小样本验证。需要远端后台运行时，使用新的容器名称保留旧任务：

```bash
# 在远端 /home/lxy/VibeQuant/docker 执行。
JOB="livemore-amazing-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose -p vibequant run -d --name "$JOB" livemore-amazing \
  python run_backtest.py --start 19900101 --end 20261023 \
  --workers 4 --resume --enable-trading
docker logs -f "$JOB"
docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}}' "$JOB"
```

`Ctrl+C` 只退出日志跟随。只有状态为 exited、退出码为 0，并核实采集、计算与结果文件后，才视为本次完整运行成功。不要删除旧容器、缓存卷或结果卷来解决命名冲突。

## 报告发布、日志与结果导出

开启模拟交易会生成 `summary_<start>_<end>.csv` 和成交图 `chart_<code>_<hash>.html`；默认信号模式生成 `signals_*.csv`，不能发布为交易绩效报告。

回测成功后在 Mac 发布指定 CSV：

```bash
./docker/scripts/remote/compose.sh run --rm livemore-amazing python -m livemore.report \
  --csv /workspace/LiveMoreAmazing/results/summary_19900101_20261023.csv
```

网站入口为 `/livemore/`。报告保留逐股回测结果，不把跨股票中位数当作组合收益。BUY/SELL 标记来自实际模拟成交日、成交价和新增成交量。CSV 中的 `chart_file` 对应图表必须与 CSV 保持在同一目录；缺失时发布失败。页面会随机展示最多 10 个标的，支持换组和查看全部明细；ECharts 图表依赖浏览器访问 jsDelivr。

发布写入共享网站卷并更新门户模板，无需重启 front；历史报告保留。修改规则不会自动重算或替换旧报告，需重新回测后发布。

查看文件和取回全部结果（Mac 仓库根目录）：

```bash
./docker/scripts/remote/compose.sh run --rm livemore-amazing python -c \
  'from pathlib import Path; print(*Path("/workspace/LiveMoreAmazing/results").glob("*"), sep="\n")'
mkdir -p docker/out/livemore-amazing
./docker/scripts/remote/compose.sh run --rm -T livemore-amazing \
  tar -C /workspace/LiveMoreAmazing/results -czf - . \
  > docker/out/livemore-amazing-results.tar.gz
tar -xzf docker/out/livemore-amazing-results.tar.gz -C docker/out/livemore-amazing
```

需要保存前台运行日志时，先执行 `set -o pipefail`，在运行命令末尾加 `2>&1 | tee /tmp/livemore-run.log`，随后立即执行 `printf 'exit=%s\n' "$?"`。用 `tail -n 50 /tmp/livemore-run.log` 检查末尾输出。

## Git 提交范围

提交整个 `LiveMoreAmazing/` 的源码、requirements 和 Markdown 文档；由 `.gitignore` 排除缓存与产物。同时提交共享部署所需文件：

- 根目录 `.gitignore`、`.dockerignore` 和建议保留的 `AGENTS.md`。
- `docker/Dockerfile`、`docker/compose.yaml`、`docker/requirements.txt`、`docker/.remoteignore`、`docker/README.md`。
- `docker/scripts/configure_tgw.py`，远端 `_common.sh`、compose、sync、bootstrap、pull-data、debug-shell 等相关脚本。
- `.env.example`、`.env.remote.example`、`.env.amazing.example` 等无真实凭据的配置模板，以及 `docker/wheels/amazing/README.md`。

当前共享 Dockerfile 还复制 `M2DivGold/`、`USStockDipWatch/`、`VibeQuantFront/`；完整仓库必须包含这些依赖和 Compose 引用的相关配置模板／脚本，不能只提交本目录就认为能够构建。若只归档策略源码，可提交本目录，但应说明不包含完整部署环境。

不要提交真实 env、账号密码或 token、SDK wheel、行情缓存、results、生成 CSV／HTML、日志、Python 字节码、代理节点真实配置、镜像归档及临时测试文件。SDK wheel 不随 Git 分发，部署时从官方渠道单独准备；同步工具会按其规则上传本机准备好的 wheel。

先使用 `git status --short` 和 `git diff --cached --stat` 检查提交清单，再检查暂存内容；共享 Docker 文件混有其他项目改动，不要未经审查直接 `git add .`。
