# LiveMore 临时 Docker 验收

> 2026-10 整理：原仓库根的 `tmp-test-livemore-docker.sh` / `TEMP_LIVEMORE_TEST.md` 移到本目录并改名，
> 行为不变（仍检查仓库根的 `LiveMore/`，报告仍写到仓库根 `tmp/`）。下文保留当时的执行记录。

脚本：`/Users/lxy/VibeQuant/tools/livemore-docker-check/livemore-docker-check.sh`。

本次只新增脚本和本说明，不修改原策略、QMT 框架、Compose 或镜像定义。
此脚本是临时验收入口，不是新策略框架，也不是正式部署或调度服务。

最新状态（2026-08-26）：已在 Ubuntu Docker 实际验证，修复临时脚本的线程资源配置后，
**11 项通过、0 项失败，退出码 0**。原策略代码未改。实际执行记录见本文最后一节。

## 先审查，再手动执行

仅查看方案，不连接服务器、不创建测试目录：

```bash
bash /Users/lxy/VibeQuant/tools/livemore-docker-check/livemore-docker-check.sh --plan
```

检查脚本后，手动启动：

```bash
bash /Users/lxy/VibeQuant/tools/livemore-docker-check/livemore-docker-check.sh --run
```

脚本会通过 `ssh -p 2222 lxy@121.41.112.193` 执行。要求现有 SSH 密钥认证、
主机密钥信任及普通用户的 Docker 权限已经配置；脚本不会安装 Docker、修改 SSH 或索取密码。

## 执行边界

- Mac 仅运行 Bash、SSH、rsync、文件校验和报告下载；不运行 Python/pip/策略。
- Ubuntu 使用本机 `/var/run/docker.sock`；不改现有服务或 `/home/lxy/qmt-remote`。
- 复用 `qmt-remote-test:dev`，验证其 ID 必须等于第 5 步记录的
  `sha256:6b6bde79eb16f592602fcaef5a51ea0377837c2d701e67b85c4372f431a7c980`。
  镜像缺失或 ID 不匹配时直接停止，不自动构建或拉取镜像。
- 每次在 Ubuntu `/tmp/livemore-check.XXXXXXXX` 创建独立快照，只上传
  `livermore_strategy.py`、`run_backtest.py`、`self_test.py` 和源文件 SHA-256 清单。
  不上传 `.env`、真实行情、账户、QMT 配置或其他策略文件。
- 准备容器只从 PyPI 下载固定 Backtrader wheel，不挂载策略；该阶段需要网络。
  使用 `backtrader==1.9.78.123`，SHA-256 为
  `9a07a516b0de9155539a35c56e9404d8711dd7020b3d37b30495e83e1b9d5dfd`，
  来源：[PyPI 发布文件信息](https://pypi.org/project/backtrader/1.9.78.123/#files)。
- 测试容器 `--network none`、非 root、只读根文件系统、只读源码、无端口和 Docker socket 挂载。
  Backtrader 只安装到容器 `/tmp`，不修改镜像或宿主机环境；结果目录单独可写。
  OpenBLAS、OMP、MKL、NumExpr、BLIS 的线程数固定为 1，避免父子 Python 进程共享
  128 PID 配额时，按宿主机 CPU 数自动创建大量计算线程。
- 不运行 `run_backtest.py` 的真实行情主入口，不导入 `qmt_data.py`，不使用真实 QMT。
  `--skip-download` 仍会查询 QMT，故本脚本不用该选项模拟离线。
- 每次手动执行重新同步当前源文件；修改代码不需要重建镜像。
- 正常或失败退出时移除本次容器；不清理其他容器、镜像或数据。
  网络断线/宿主机崩溃等异常可能妨碍清理，可按日志中的唯一运行名检查，不能据此保证绝无残留。

## 验收项目与人工判断

正常完成时共 11 项检查，全部通过才输出 `RESULT=PASS passed=11 failed=0`，并退出 `0`。
依赖准备失败、环境不匹配、断言失败、超时或报告下载失败均返回非零退出码。

| 检查 | 通过条件 |
|---|---|
| 容器隔离 | Linux Docker、非 root、仅 loopback 网络、无 QMT token |
| 原自测 | 原 `self_test.py` 退出 0，且没有被其内部吞掉的 `ERROR` |
| 冷启动与信号重置 | 10% 上涨建立趋势，下一根数据清除旧瞬时信号 |
| 牛市合成行情 | 原 `run_single` 成功，指标有限、字段齐全且收益计算关系一致 |
| 见顶反转合成行情 | 同上；不强制规定盈利数值或每种离场原因都必须触发 |
| 随机合成行情 | 同上；不把正收益作为通过条件 |
| 指数过滤分支 | 传入合成指数后回测可执行，指标有效；并非完整过滤规则证明 |
| 数据不足 | None、空数据和 249 根数据均明确跳过 |
| 最低数据边界 | 250 根合成行情可以进入回测并返回有效结果 |
| 改变输入参数 | 初始资金改为 200000，原函数可运行，资产收益关系仍一致 |
| 重复性 | 相同行情、种子和初始资金的结果完全一致 |

使用原 `self_test.py` 的合成数据生成器，不另写策略或替换原算法。
原自测部分错误只打印后继续，本脚本额外直接检查 `run_single` 返回值，防止误报成功。
本验收只证明这些输入下的运行与结果一致性，不证明策略每条规则正确、历史收益有效或具备实盘收益。
若失败，保留结果先审查原因，不为让测试变绿而自动修改策略或放宽条件。

## 查看结果

每次执行结束会输出本次目录：

```text
/Users/lxy/VibeQuant/tmp/livemore-check.XXXXXXXX/
├── remote.log       SSH 全过程，包括依赖准备和测试输出
├── prepare.log      联网准备容器日志
├── container.log    断网测试容器日志
├── self_test.log    原自测的状态变化、模拟成交和资产日志
├── report.json      每项 PASS/FAIL、错误、依赖版本和源码哈希
├── summary.csv      合成场景回测指标，便于人工比较
├── image.txt        使用的镜像 ID 与架构
├── source.sha256    本次原策略文件指纹
└── script.sha256    本次临时脚本指纹
```

准备阶段失败时，后续文件可能尚未生成，先查看 `remote.log`。
远端同名临时目录也保留，不自动删除，方便核验；它不包含真实账户或行情数据。
脚本不会把容器里的任何改动回写到本地 LiveMore 源码。

## 初版交付时的静态检查记录

初版交付时仅执行静态 Shell 语法和无副作用入口检查；当时尚未连接 Ubuntu 或运行策略。
之后用户授权先执行验证，实际执行记录列于下一节。

初版操作与结果：

| 操作 | 结果 |
|---|---|
| 只读审阅现有策略、自测、回测入口和 QMT 镜像记录 | 完成；没有运行本地 Python |
| 新增临时脚本与本说明 | 完成；仅新增这两个交付文件 |
| 设置临时脚本可执行权限 | 完成 |
| 主脚本 `bash -n` | 通过，退出码 0 |
| 提取远端预检、远端执行两段脚本后分别 `bash -n` | 均通过，退出码 0 |
| 容器内部 Shell 命令 `sh -n` | 通过，退出码 0 |
| `--plan` 无副作用入口 | 通过，退出码 0；没有连接服务器 |
| 非法选项保护 | 按预期返回退出码 2 |
| 策略核心、自测、回测、QMT 数据封装、Compose、Dockerfile 的 SHA-256 前后比较 | 6 个文件均未改变 |

静态 Shell 检查不等于 Python 执行或容器兼容性验证；下面单独记录实际容器运行结果。

## 2026-08-26 实际执行报告

### 结论

最终运行：`RESULT=PASS passed=11 failed=0`，本地脚本与远端命令退出码均为 `0`。
此结论仅适用于当前原策略和本脚本的合成行情用例，不是全部策略规则或真实行情验收。

### 执行操作与结果

| 操作 | 结果 |
|---|---|
| 执行前核对临时脚本与原始源码哈希 | 完成；未在 Mac 检查或运行 Python 环境 |
| 第一次运行 `bash /Users/lxy/VibeQuant/tools/livemore-docker-check/livemore-docker-check.sh --run` | 10 项通过、1 项失败；退出码 1，未误报成功 |
| 检查首次失败日志 | 原自测子进程导入 NumPy 时 OpenBLAS 尝试创建 64 个线程，出现线程资源不足；其他直接回测用例通过 |
| 修复临时脚本 | 仅新增 5 个计算库线程上限环境变量（均为 1），并把设置记录到报告；不提高 PID 配额、不修改策略、不放宽断言 |
| 修复后静态检查 | 主脚本与远程执行段 `bash -n` 通过 |
| 第二次运行同一 `--run` 命令 | **11 项全部通过、退出码 0**；原自测正常完成 |
| 每轮源码与依赖准备 | 3 个原 Python 文件上传校验通过；Backtrader wheel SHA-256 通过；离线安装和 `pip check` 通过 |
| 核对成功结果和原始文件 | `report.json` 的 status=PASS；源码与脚本校验清单通过；策略核心、自测、回测、QMT 数据封装、Compose、Dockerfile 共 6 个文件哈希未变 |
| 比较两轮直接回测指标 | 两个 `summary.csv` 逐字节一致；线程设置调整没有改变这些用例的指标 |
| 最后只读 SSH 核对 | 两轮临时容器残留数均为 0；测试镜像与正式运行镜像的 ID 均未变化；远端成功快照的源码校验通过 |
| 整理交付 | 当前临时脚本保留修复；本说明更新为实际验证状态；两轮日志和结果保留 |

### 文件与报告位置

已修改：

- `/Users/lxy/VibeQuant/tools/livemore-docker-check/livemore-docker-check.sh`：容器线程上限和报告中的线程配置字段。
- `/Users/lxy/VibeQuant/tools/livemore-docker-check/README.md`：本说明和实际执行记录。

成功运行的本地报告：

- [report.json](/Users/lxy/VibeQuant/tmp/livemore-check.E06uCfER/report.json)
- [summary.csv](/Users/lxy/VibeQuant/tmp/livemore-check.E06uCfER/summary.csv)
- [原自测日志](/Users/lxy/VibeQuant/tmp/livemore-check.E06uCfER/self_test.log)
- [完整执行日志](/Users/lxy/VibeQuant/tmp/livemore-check.E06uCfER/remote.log)

首次失败记录保留在 `/Users/lxy/VibeQuant/tmp/livemore-check.6uq3YYGt/`，没有覆盖。

Ubuntu 两个临时目录保留供人工检查：

- `/tmp/livemore-check.6uq3YYGt`：首次失败快照。
- `/tmp/livemore-check.E06uCfER`：修复后成功快照。

每个目录仅含本次上传源码、固定 wheel 和测试结果；没有删除这些可供复查的文件。
两轮共使用 4 个一次性容器，现已全部移除；没有构建、拉取或删除镜像，没有创建数据卷或开放端口。

### 实际运行环境

- Ubuntu Docker 中的 Linux/amd64 容器，非 root UID 1001；策略测试网络为 none。
- Python 3.12.14；Backtrader 1.9.78.123；NumPy 2.5.2；pandas 3.0.5；PyArrow 23.0.1。
- 测试镜像 ID：
  `sha256:6b6bde79eb16f592602fcaef5a51ea0377837c2d701e67b85c4372f431a7c980`。
- 未修改的正式运行镜像 `qmt-remote-runtime:0.1.0` ID：
  `sha256:1c624873f76bc918f01df03a0b6efb3bcf27992e6f3a29c54c80a8722b5690db`。

### 手动检查时值得注意

- 当前合成见顶场景 `top` 返回 0 笔交易；原 verbose 牛市示例（900 根、seed=3）也没有产生成交。
  本次检查的是程序成功执行及结果一致性，不能据此认定这些样例已覆盖加仓、止损或反转离场的全部规则。
  是否符合你的策略预期，需结合原源码和日志人工判断；本次没有擅自改变算法或样例。
- 真实 QMT 连接、真实行情下载、多进程全市场回测、每日调度及前端均未执行。
- Backtrader 在 Python 3.12 下打印了文档字符串转义相关 `SyntaxWarning`；
  另有 pip 新版本提示。两者不影响本次测试通过，未因此升级依赖或修改第三方包。
