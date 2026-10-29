#!/usr/bin/env bash
# 临时人工验收脚本；不修改 LiveMore，不接真实 QMT，不构建/拉取镜像。
# Mac: Bash + SSH + rsync + 文件校验。Python/pip/策略只在 Ubuntu Docker 中运行。
# 默认仅显示方案；检查本文件后显式加 --run 才执行。
set -Eeuo pipefail

# 可审查的固定配置：镜像 ID 来自已完成的第 5 步，标签变化时拒绝继续。
SSH_TARGET='lxy@121.41.112.193'
SSH_PORT='2222'
TEST_IMAGE='qmt-remote-test:dev'
EXPECTED_IMAGE_ID='sha256:6b6bde79eb16f592602fcaef5a51ea0377837c2d701e67b85c4372f431a7c980'
SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
# 本脚本位于 tools/livemore-docker-check/，仓库根在上两级。
PROJECT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")/../.." && pwd)"
STRATEGY_DIR="${PROJECT_DIR}/LiveMore"

case "${1:---plan}" in
  --plan|--help|-h)
    printf '%s\n' \
      '用途：用原有 LiveMore 做 Ubuntu Docker 离线验收，不验证盈利能力。' \
      "策略目录：${STRATEGY_DIR}" \
      "SSH：${SSH_TARGET}:${SSH_PORT}" \
      "现有镜像：${TEST_IMAGE}（校验固定 ID；不 build、不 pull）" \
      '1. 在 Ubuntu /tmp 下创建独立目录，只上传 3 个原始 Python 文件及校验清单。' \
      '2. 准备容器仅下载 Backtrader 1.9.78.123 wheel，并验证 SHA-256；不挂载策略。' \
      '3. 测试容器 --network none；临时安装 wheel，执行原自测及附加断言。' \
      '4. 源码只读；仅临时结果目录可写，不使用真实 QMT 配置。' \
      '5. 日志/JSON/CSV 下载到 VibeQuant/tmp/；远端临时目录保留供检查。' \
      '6. 容器退出后移除，不创建常驻服务、端口、镜像或数据卷。' \
      "执行：bash \"${SCRIPT_PATH}\" --run"
    exit 0
    ;;
  --run) ;;
  *) printf '只支持 --plan、--help 或 --run。\n' >&2; exit 2 ;;
esac
if (( $# != 1 )); then
  printf '执行时必须且只能提供 --run。\n' >&2
  exit 2
fi

SOURCE_FILES=(livermore_strategy.py run_backtest.py self_test.py)
for name in "${SOURCE_FILES[@]}"; do
  if [[ ! -f "${STRATEGY_DIR}/${name}" || -L "${STRATEGY_DIR}/${name}" ]]; then
    printf '缺少普通源文件（不接受软链接）：%s\n' "${STRATEGY_DIR}/${name}" >&2
    exit 2
  fi
done

# 不读取/上传 .env、.claude、QMT 账户或真实行情；SSH 必须使用已信任的主机密钥。
SSH_OPTIONS=(-T -p "${SSH_PORT}" -o BatchMode=yes -o ConnectTimeout=15
  -o StrictHostKeyChecking=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
RSYNC_SSH="ssh -T -p ${SSH_PORT} -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3"

printf '检查 Ubuntu Docker 和固定镜像，不检查 Mac Python 环境。\n'
REMOTE_RUN_DIR="$(ssh "${SSH_OPTIONS[@]}" "${SSH_TARGET}" \
  bash -s -- "${TEST_IMAGE}" "${EXPECTED_IMAGE_ID}" <<'REMOTE_PREFLIGHT'
set -Eeuo pipefail
[[ "$(uname -s)" == Linux ]] || { printf '目标必须是 Linux。\n' >&2; exit 2; }
(( $(id -u) != 0 )) || { printf '请以普通用户运行，不接受 root SSH。\n' >&2; exit 2; }
for tool in docker rsync sha256sum timeout; do command -v "$tool" >/dev/null; done
DOCKER=(docker --host unix:///var/run/docker.sock)
actual_id="$("${DOCKER[@]}" image inspect --format '{{.Id}}' "$1")"
[[ "$actual_id" == "$2" ]] || {
  printf '镜像 ID 不匹配；停止，不自动构建或下载。实际 ID：%s\n' "$actual_id" >&2
  exit 3
}
[[ "$("${DOCKER[@]}" image inspect --format '{{.Os}}/{{.Architecture}}' "$2")" == linux/amd64 ]]
umask 077
run_dir="$(mktemp -d /tmp/livemore-check.XXXXXXXX)"
mkdir "$run_dir/source" "$run_dir/source/results" "$run_dir/results" "$run_dir/wheels"
printf '%s\n' "$run_dir"
REMOTE_PREFLIGHT
)"
if [[ ! "${REMOTE_RUN_DIR}" =~ ^/tmp/livemore-check\.[A-Za-z0-9]{8}$ ]]; then
  printf '远端返回了非预期临时路径，停止。\n' >&2
  exit 3
fi

umask 077
mkdir -p "${PROJECT_DIR}/tmp"
LOCAL_REPORT_DIR="${PROJECT_DIR}/tmp/${REMOTE_RUN_DIR##*/}"
mkdir "${LOCAL_REPORT_DIR}"
printf '本地结果：%s\n远端临时目录：%s\n' "${LOCAL_REPORT_DIR}" "${REMOTE_RUN_DIR}"
(
  cd -- "${STRATEGY_DIR}"
  shasum -a 256 "${SOURCE_FILES[@]}"
) > "${LOCAL_REPORT_DIR}/source.sha256"
shasum -a 256 "${SCRIPT_PATH}" > "${LOCAL_REPORT_DIR}/script.sha256"

# 白名单上传；不使用 --delete，不覆盖原服务器项目。
rsync --archive --itemize-changes --rsh="${RSYNC_SSH}" \
  "${STRATEGY_DIR}/livermore_strategy.py" \
  "${STRATEGY_DIR}/run_backtest.py" \
  "${STRATEGY_DIR}/self_test.py" \
  "${LOCAL_REPORT_DIR}/source.sha256" \
  "${SSH_TARGET}:${REMOTE_RUN_DIR}/source/"

set +e
ssh "${SSH_OPTIONS[@]}" "${SSH_TARGET}" bash -s -- \
  "${REMOTE_RUN_DIR}" "${EXPECTED_IMAGE_ID}" <<'REMOTE_EXEC' 2>&1 | tee "${LOCAL_REPORT_DIR}/remote.log"
set -Eeuo pipefail
run_dir="$1"
image_id="$2"
[[ "$run_dir" =~ ^/tmp/livemore-check\.[A-Za-z0-9]{8}$ && -d "$run_dir/source" ]]
DOCKER=(docker --host unix:///var/run/docker.sock)
run_uid="$(id -u)"
run_gid="$(id -g)"
(( run_uid != 0 ))
run_name="${run_dir##*/}"
prepare_name="${run_name}-prepare"
test_name="${run_name}-test"

# 只移除本次创建且标签匹配的两个容器；保留临时目录和结果，不清理其他资源。
cleanup_containers() {
  status=$?
  trap - EXIT
  for container_name in "$prepare_name" "$test_name"; do
    owner="$("${DOCKER[@]}" container inspect --format '{{index .Config.Labels "vibequant.temp-run"}}' "$container_name" 2>/dev/null || true)"
    if [[ "$owner" == "$run_name" ]]; then
      "${DOCKER[@]}" container rm --force "$container_name" >/dev/null 2>&1 || true
    fi
  done
  printf '远端退出码：%s；临时目录保留：%s\n' "$status" "$run_dir"
  exit "$status"
}
trap cleanup_containers EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd -- "$run_dir/source"
sha256sum --check source.sha256
cp source.sha256 "$run_dir/results/source.sha256"
"${DOCKER[@]}" image inspect --format 'Id={{.Id}} Platform={{.Os}}/{{.Architecture}}' "$image_id" > "$run_dir/results/image.txt"

COMMON=(--rm --init --pull never --read-only --user "$run_uid:$run_gid"
  --security-opt no-new-privileges:true --cap-drop ALL --pids-limit 128
  --memory 2g --cpus 2 --label "vibequant.temp-run=$run_name"
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777
  --env HOME=/tmp --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1
  --env PIP_DISABLE_PIP_VERSION_CHECK=1 --env PIP_NO_CACHE_DIR=1
  # 主进程和原自测子进程共享容器 PID 配额，避免 BLAS 按宿主机 CPU 数创建线程。
  --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 --env MKL_NUM_THREADS=1
  --env NUMEXPR_NUM_THREADS=1 --env BLIS_NUM_THREADS=1)

# 唯一联网阶段：无策略/凭据挂载，只下载固定的纯 Python wheel，不执行包代码。
# 版本与校验值来源：https://pypi.org/project/backtrader/1.9.78.123/#files
printf '\n[1/2] 准备固定依赖（仅此容器联网）\n'
timeout --signal=TERM --kill-after=15s 180s "${DOCKER[@]}" run \
  "${COMMON[@]}" --name "$prepare_name" --network bridge \
  --mount "type=bind,src=$run_dir/wheels,dst=/wheels" \
  --entrypoint python "$image_id" -m pip --isolated download \
  --no-deps --only-binary=:all: --index-url https://pypi.org/simple \
  --timeout 20 --retries 2 --dest /wheels 'backtrader==1.9.78.123' \
  2>&1 | tee "$run_dir/results/prepare.log"
(
  cd -- "$run_dir/wheels"
  printf '%s  %s\n' \
    '9a07a516b0de9155539a35c56e9404d8711dd7020b3d37b30495e83e1b9d5dfd' \
    'backtrader-1.9.78.123-py2.py3-none-any.whl' | sha256sum --check
)

printf '\n[2/2] 断网容器：运行原策略自测及附加验收\n'
timeout --signal=TERM --kill-after=15s 420s "${DOCKER[@]}" run -i \
  "${COMMON[@]}" --name "$test_name" --network none --workdir /strategy \
  --env PYTHONPATH=/tmp/backtrader:/strategy \
  --env QMT_REAL_TEST=0 --env QMT_URL=ws://127.0.0.1:1 --env QMT_TOKEN= \
  --mount "type=bind,src=$run_dir/source,dst=/strategy,readonly" \
  --mount "type=bind,src=$run_dir/results,dst=/strategy/results" \
  --mount "type=bind,src=$run_dir/wheels,dst=/wheels,readonly" \
  --entrypoint /bin/sh "$image_id" -ec '
    python -m pip --isolated install --no-deps --no-index --no-compile \
      --target /tmp/backtrader /wheels/backtrader-1.9.78.123-py2.py3-none-any.whl
    python -m pip check
    exec python -
  ' <<'CONTAINER_PY' 2>&1 | tee "$run_dir/results/container.log"
# 全部 Python 仅由上面的 Ubuntu Docker 容器解释执行。
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

RESULTS = Path('/strategy/results')
report = {
    'status': 'FAIL',
    'scope': '原 LiveMore 合成行情离线验收；不是实盘、真实行情回测或盈利能力认证',
    'environment': {'python': sys.version, 'platform': platform.platform(), 'uid': os.getuid(),
                    'thread_limits': {name: os.environ.get(name) for name in
                                      ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                                       'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS')}},
    'checks': [],
    'metrics': [],
}
fields = ['case', 'code', 'bars', 'start', 'end', 'end_value', 'reserve',
          'total_return', 'annual_return', 'max_drawdown', 'sharpe', 'trades',
          'winrate', 'buy_and_hold', 'excess_vs_bh']


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check(name, function, *args):
    started = time.monotonic()
    try:
        value = function(*args)
        report['checks'].append({'name': name, 'status': 'PASS', 'seconds': round(time.monotonic() - started, 3)})
        print(f'[PASS] {name}', flush=True)
        return value
    except Exception as exc:
        report['checks'].append({'name': name, 'status': 'FAIL', 'error': str(exc), 'trace': traceback.format_exc()})
        print(f'[FAIL] {name}: {exc}', flush=True)
        traceback.print_exc()
        return None


def isolation():
    require(sys.platform == 'linux' and Path('/.dockerenv').exists(), '不是 Linux Docker 环境')
    require(os.getuid() != 0, '容器不应使用 root')
    require({p.name for p in Path('/sys/class/net').iterdir()} == {'lo'}, '测试容器必须只有 loopback 网络')
    require(not os.environ.get('QMT_TOKEN'), '不允许真实 QMT token')


def original_self_test():
    log_path = RESULTS / 'self_test.log'
    with log_path.open('w', encoding='utf-8') as stream:
        result = subprocess.run([sys.executable, '/strategy/self_test.py'],
                                stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False)
    text = log_path.read_text(encoding='utf-8')
    print(text, end='', flush=True)
    require(result.returncode == 0, f'原 self_test.py 退出码 {result.returncode}，见 self_test.log')
    # 原 test_pipeline 遇 error 字典只打印并 continue；不能据退出码误判成功。
    require('] ERROR:' not in text, '原自测打印了 ERROR，见 self_test.log')


def signal_reset():
    key = strategy.LivermoreMarketKey(swing_pct=0.10, secondary_pct=0.05)
    key.update(100.0)
    require(key.col is None, '首根数据应只建立锚点')
    key.update(110.0)
    require(key.col == strategy.Col.UP_TREND and key.signal_breakout_up, '上涨 10% 应确立上涨趋势')
    key.update(111.0)
    require(not key.signal_breakout_up and not key.signal_reversal_down and not key.signal_uptrend_failing,
            '下一根数据不应保留上一根的瞬时信号')


def validate_metrics(result, df, cash):
    require(isinstance(result, dict), 'run_single 必须返回字典')
    require('error' not in result and 'skipped' not in result, f'回测没有成功：{result}')
    require(set(fields[1:]).issubset(result), '回测结果字段缺失')
    require(result['bars'] == len(df), 'bars 不一致')
    require(result['start'] == df.index[0].strftime('%Y-%m-%d'), '开始日期不一致')
    require(result['end'] == df.index[-1].strftime('%Y-%m-%d'), '结束日期不一致')
    for field in fields[5:]:
        require(math.isfinite(float(result[field])), f'{field} 不是有限数值')
    require(result['end_value'] >= 0 and result['reserve'] >= 0, '资产或储备金为负')
    require(result['max_drawdown'] >= 0 and 0 <= result['winrate'] <= 1, '回撤或胜率范围异常')
    require(result['trades'] >= 0 and int(result['trades']) == result['trades'], '交易计数异常')
    require(math.isclose(result['total_return'], result['end_value'] / cash - 1, abs_tol=1e-7),
            '累计收益与期末资产不一致（允许金额四舍五入误差）')
    require(math.isclose(result['excess_vs_bh'], result['total_return'] - result['buy_and_hold'], abs_tol=1e-12),
            '超额收益与基准关系不一致')


def scenario(kind, with_index=False, bars=1200, cash=100000.0, label=None):
    label = label or kind
    df = existing_tests._synth_ohlcv(kind, n=bars, seed=7)
    index_df = existing_tests._synth_ohlcv('bull', n=bars, seed=11) if with_index else None
    result = backtest.run_single(f'SYNTH_{kind}', df, index_df=index_df, initial_cash=cash)
    validate_metrics(result, df, cash)
    # 标准化 numpy 标量；若出现非有限值，拒绝生成“成功”指标。
    result = json.loads(json.dumps(result, default=lambda value: value.item(), allow_nan=False))
    report['metrics'].append({'case': label, **result})
    print(json.dumps({'case': label, **result}, ensure_ascii=False), flush=True)
    return result


def insufficient_data():
    short = existing_tests._synth_ohlcv('bull', n=249, seed=7)
    for frame, expected_bars in [(None, 0), (short.iloc[:0], 0), (short, 249)]:
        result = backtest.run_single('SYNTH_SHORT', frame)
        require(result.get('skipped') == 'insufficient_data' and result.get('bars') == expected_bars,
                f'不足 250 根数据时应明确跳过：{result}')


def reproducible():
    require(baseline is not None, '牛市基准用例未通过，不能验证重复性')
    repeated = scenario('bull', label='bull_repeat')
    require(repeated == baseline, '相同输入、随机种子和资金下结果不一致')


try:
    isolation()  # 安全前置条件不满足时，不继续执行策略。
    report['checks'].append({'name': 'container_isolation', 'status': 'PASS'})
    import livermore_strategy as strategy
    import run_backtest as backtest
    import self_test as existing_tests
    for module in (strategy, backtest, existing_tests):
        require(Path(module.__file__).resolve().parent == Path('/strategy'), '导入了非本次上传的源码')
    for package in ('backtrader', 'numpy', 'pandas', 'pyarrow'):
        report['environment'][package] = importlib.metadata.version(package)
    require(report['environment']['backtrader'] == '1.9.78.123', 'Backtrader 版本不匹配')
    check('original_self_test', original_self_test)
    check('cold_start_and_signal_reset', signal_reset)
    baseline = check('bull_pipeline', scenario, 'bull')
    check('top_reversal_pipeline', scenario, 'top')
    check('random_pipeline', scenario, 'random')
    check('index_filter_pipeline', scenario, 'bull', True, 1200, 100000.0, 'bull_with_index')
    check('insufficient_data', insufficient_data)
    check('minimum_250_bars', scenario, 'bull', False, 250, 100000.0, 'bull_250_bars')
    check('alternate_initial_cash', scenario, 'bull', False, 1200, 200000.0, 'bull_cash_200000')
    check('deterministic_repeat', reproducible)
except Exception as exc:
    report['checks'].append({'name': 'preconditions_or_imports', 'status': 'FAIL',
                             'error': str(exc), 'trace': traceback.format_exc()})
    traceback.print_exc()
finally:
    report['source_sha256'] = {name: hashlib.sha256(Path('/strategy', name).read_bytes()).hexdigest()
                               for name in ('livermore_strategy.py', 'run_backtest.py', 'self_test.py')}
    report['passed'] = sum(item['status'] == 'PASS' for item in report['checks'])
    report['failed'] = sum(item['status'] == 'FAIL' for item in report['checks'])
    report['status'] = 'PASS' if report['failed'] == 0 and report['passed'] == 11 else 'FAIL'
    (RESULTS / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    with (RESULTS / 'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report['metrics'])
    print(f"RESULT={report['status']} passed={report['passed']} failed={report['failed']}", flush=True)
sys.exit(0 if report['status'] == 'PASS' else 1)
CONTAINER_PY
REMOTE_EXEC
pipeline_status=("${PIPESTATUS[@]}")
set -e

# 即使断言失败也下载已生成报告；准备阶段失败则可能没有 report.json。
if ! rsync --archive --rsh="${RSYNC_SSH}" \
  "${SSH_TARGET}:${REMOTE_RUN_DIR}/results/" "${LOCAL_REPORT_DIR}/"; then
  printf '报告下载失败；远端结果仍在 %s/results。\n' "${REMOTE_RUN_DIR}" >&2
  exit 4
fi
printf '\n人工检查目录：%s\n' "${LOCAL_REPORT_DIR}"
printf '重点检查 report.json、summary.csv、self_test.log 和 remote.log。\n'
printf '远端临时目录保留：%s（仅本次快照、依赖和结果；不会自动删除）。\n' "${REMOTE_RUN_DIR}"
if (( pipeline_status[0] != 0 )); then exit "${pipeline_status[0]}"; fi
if (( pipeline_status[1] != 0 )); then exit "${pipeline_status[1]}"; fi
printf '容器验收命令成功；仍需你审查策略输出是否符合业务预期。\n'
