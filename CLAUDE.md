# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Also read `AGENTS.md` — it holds this project's change-discipline rules (do not modify `LiveMore/`, credential handling, AmazingData entitlement policy, deletion prohibitions). This file covers commands and the cross-file architecture.

## What this repo is

Several workloads sharing one Docker image, deployed to a remote Ubuntu host:

| Directory | Role |
|---|---|
| `M2DivGold/` | Scrapes US M2 (FRED `M2SL`) + gold (LBMA daily fix), renders a self-contained interactive HTML |
| `LiveMoreAmazing/` | Galaxy Securities AmazingData market-data adapter + Livermore strategy backtest |
| `USStockDipWatch/` | Alpaca/Binance drawdown watcher; also owns `site_server.py`, the `front` HTTP server |
| `VibeQuantFront/` | Static portal `index.html`; becomes the site root `/srv/web` |
| `docker/` | Shared image, compose file, Mac-side remote-deploy scripts, host cron scripts |
| `tools/` | One-off local helpers (`livemore-docker-check/`: offline Docker acceptance of the original `LiveMore/`) |
| `local/` | Personal notes / private files. Ignored by git, rsync and the image — never part of the project. |
| `LiveMore/`, `datasrc/` | Original QMT implementation, git-ignored. Reference only — leave untouched. |

**The Mac is edit-only.** There is no pandas/backtrader/pyarrow installed locally, so local `python3` cannot run any of the workloads. Dependency install, data fetching, image builds and every test run happen on the remote host inside the container.

## Commands

All remote commands run from `/Users/lxy/VibeQuant/docker/scripts/remote` on the Mac. They are thin wrappers: `sync.sh` rsyncs the repo, `compose.sh` replays its argv as `docker compose --project-name vibequant …` over SSH.

### Build and sync

```bash
./sync.sh                       # rsync Mac -> remote (per docker/.remoteignore)
./bootstrap.sh                  # sync + build the shared image
./compose.sh build m2divgold    # same build, via that service's definition
./compose.sh ps ; ./compose.sh logs --tail 50 front
./debug-shell.sh                # sync + interactive shell with the repo bind-mounted at /workspace
```

**A sync does not update code copied into the image.** Source is `COPY`ed at build time, so rebuild after any source change. `dev-shell` is the only service that bind-mounts the repo, so `./sync.sh` alone is enough there.

### Tests and diagnostics

`LiveMoreAmazing/scripts/` and `LiveMoreAmazing/tests/` were deleted at the user's request (2026-10-26), so there is no offline test suite and no login / K-line permission checker. Validate with a small real run instead (one stock, short date range). A query rejected with `(None, -95)` / `数据无权限` is a server-side account entitlement problem, not a code defect — report the interface and code, and do not retry. Do a single-stock/short-range check before any bulk collection.

### Probe and backtest

```bash
END=$(date +%Y%m%d)
./compose.sh run --rm livemore-amazing \
  python run_backtest.py --start 20130101 --end "$END" --limit 20 --workers 4
./compose.sh run --rm livemore-amazing \
  python run_backtest.py --codes 000001.SZ 600519.SH --start 20130101 --end "$END" \
  --skip-download --workers 2 --enable-trading
./compose.sh run --rm livemore-amazing \
  python -m livemore.report --csv results/summary_20130101_"$END".csv   # publish to /livemore/
```

`--skip-download` reuses the Parquet cache, so `--start`/`--end`/`--codes` must match what was cached. Trading is off by default (`signals_*.csv`); `--enable-trading` produces `summary_*.csv` plus per-stock charts. `--sector EXTRA_STOCK_A` includes Beijing exchange. The CSI 300 filter is currently hard-disabled (`USE_INDEX_FILTER = False` in `livemore/backtest.py`); `--no-index` is accepted for compatibility but changes nothing.

### M2DivGold

```bash
./run-m2divgold.sh                                            # fetch -> volume vibequant-data
./compose.sh run --rm m2divgold python daily_ratio_chart.py   # regenerate the HTML
./pull-data.sh                                                # volume -> Mac docker/out/*.tar
```

The chart is generated **inside** the container, not locally (`docker/requirements.txt` has no plotting library, and `daily_ratio_chart.py` only needs pandas).

### Results retrieval

Data and results live in named volumes that rsync never touches. `pull-data.sh` tars out `vibequant-data`; for the LiveMoreAmazing volumes use the `docker … tar -czf -` one-liner in `LiveMoreAmazing/README.md` §5.

## Architecture

### One image, several services

`docker/compose.yaml` sets `context: ..` (build context is the **repo root**) and every app service inherits `image: vibequant:dev` from the `x-app` anchor. Service roles:

- `m2divgold` — one-shot fetch; writes `vibequant-data` and the site volume `vibequant-web`
- `front` — resident `USStockDipWatch/site_server.py` over `/srv/web` (static files + DipWatch completion API, reads `.env.web`); **the only service publishing a port**, bound to `${FRONT_BIND}` (default `127.0.0.1`)
- `livemore-amazing` — profile `amazing`; own cache/result volumes; the only service reading `.env.amazing`; default command `run_backtest.py --help`
- `usstock-dip-watch` + `mihomo` — profile `dipwatch`; collector reads `.env.dipwatch`, proxy is project-local
- `dev-shell` — profile `dev`; `sleep infinity` with the repo bind-mounted

`sync.sh` never deletes remote files, so paths that were moved can linger on the server; the root `.dockerignore` lists those retired paths so they never reach the image.

Traffic path: browser → 公网机 nginx/caddy:443 → frps:8080 → FRP tunnel → host `127.0.0.1:${FRONT_PORT}` → `front` container. Details in `docker/README.md`.

### Publishing convention

Any script that emits a web artifact writes to `$VIBEQUANT_SITE_DIR/<project>/` (`/srv/web` in the container) and the portal picks it up immediately — no rebuild, no restart. Locally, with the variable unset, scripts fall back to writing beside their data. `M2DivGold/daily_ratio_chart.py` is the worked example.

### M2DivGold pipeline

`fetch_m2_gold.py` → `data/*.csv` (`m2_monthly`, `gold_daily`, `gold_monthly`, `combined_monthly`) → `daily_ratio_chart.py` interpolates the **monthly** M2 to daily, joins daily gold, and emits one self-contained HTML with the data inlined. One source per series, no fallback: FRED only for M2, LBMA only for gold (pre-1968 gold is two hard-coded official constants). Known limits — daily M2 is interpolated so all day-to-day movement comes from gold, and the series starts 1968-04-01 — are documented in `M2DivGold/README.md`; don't "fix" them in code.

### LiveMoreAmazing: three layers

Library code lives in the `livemore/` package; `run_backtest.py` (project root) is the main CLI; the report publisher is `python -m livemore.report`.

1. **`livemore/amazing_data.py`** — the only module that touches the SDK, and it imports `AmazingData` lazily so offline paths (tests, `run_single`, workers) never load it. It owns the cache contract:
   - `<code>_<start>_<end>_front_ratio.parquet` plus a sibling `.json` commit marker (`schema=1`, `source=AmazingData`). The marker is deleted before writing and rewritten after, so a half-written parquet can never masquerade as valid; `get_daily` rejects anything without a matching marker.
   - `normalize_daily` is the sole gate for incoming bars: takes dates from the `kline_time` column (the real SDK frame has a plain RangeIndex; a numeric non-YYYYMMDD index is rejected, never read as epoch time), strips all-zero suspension rows (never fills gaps), rejects NaN/negative/non-positive prices and inconsistent OHLC, requires `AMAZING_VOLUME_UNIT=shares|lots`, requires adjustment factors for stocks, and refuses to carry a factor backwards from a future date.
   - Output contract: prices ratio-adjusted against the factor at the **last** returned bar (`raw_index`, i.e. unadjusted, for indexes); volume in lots of 100 shares; amount as returned.
   - `install_query_fail_fast()` patches `tgw.QueryKline` so an immediate `(False, code)` rejection raises instead of hanging forever waiting for a callback that never arrives.
2. **`livemore/livermore_strategy.py`** + **`livemore/trading_statistics.py`** — the strategy file is byte-identical to `LiveMore/livermore_strategy.py` (verify with `cmp` before editing; the whole point is that the strategy is unchanged across data sources). `LivermoreMarketKey` is the six-column state machine and the single source of pivots and turning signals; `LivermoreStrategy` only emits `trade_hook(buy=…, sell=…)` — buy on entering `UP_TREND`, sell on leaving it; `PositionStatistics` (an Analyzer) owns orders and accounting (fixed 100-share stake, no pyramiding, no extra stop, reserve stays 0). `PandasDailyFeed` feeds cached DataFrames. Volume is normalized to lots of 100 shares by the adapter.
3. **`run_backtest.py`** (engine `run_single` in `livemore/backtest.py`) — downloads (unless `--skip-download`), validates **every** cache before starting (a missing index is an error, never a silently disabled filter), then fans out to `ProcessPoolExecutor` with **`spawn`** — `fork` would let workers inherit the parent's live SDK threads. Writes `summary_<start>_<end>.csv` (or `signals_…` with trading off) to `LIVEMORE_RESULT_DIR` and fails the process if any symbol errored or no result was valid.

`livemore/charts.py` and `livemore/report.py` render the per-stock BUY/SELL charts and the published report.

### Remote script layer

`docker/scripts/remote/_common.sh` is sourced by every script: it loads `docker/.env.remote`, validates the host/port/path formats, and defines `remote_exec` plus shell quoting for the remote command string. `docker/scripts/host/` holds the scripts that run *on the remote host*, invoked by cron: `daily-update.sh` (installed idempotently by `install-schedule.sh`; uses `compose run --rm` so the resident `front` container is never restarted) and `dipwatch-update.sh` (`install-dipwatch-schedule.sh`). Installed crontabs reference these paths — don't move them.

## Invariants that bite

- **Never `docker compose down -v`** — it destroys `vibequant-data` / `vibequant-web` and the LiveMoreAmazing cache and results.
- `.env`, `.env.remote`, `.env.amazing` are excluded from Git, rsync and the image build. `docker/.env.amazing` on the remote host is the only place real AmazingData credentials may live, and `sync.sh` must never overwrite it.
- The remote `.env.amazing` file, the source tree, docs and shell history must never contain credentials. Vendor SDK output can echo tokens, which is why `suppress_native_output()` exists — preserve it when touching login paths.
- The image is Python 3.12, so the wheels in `docker/wheels/amazing/` must be cp312 / Linux x86_64. The build asserts **exactly one** `amazingdata-*.whl` and one `tgw-*.whl`; other count or a Windows wheel fails immediately. Wheels are git-ignored but do get rsynced.
- `docker/scripts/configure_tgw.py` locates the tgw native library directory from the installed wheel and registers it via `ldconfig` (`libcrypto.so.10`, `libadk.so`, … ship inside the wheel and are not resolvable by SONAME otherwise). It must run as root during build and must keep checking `ldd` for the *current* Python's extension only.
- pip runs with `--only-binary=:all:` against the Tsinghua mirror. A build that stalls for hours is a network problem, not a dependency problem — see the troubleshooting section of `docker/README.md`.
- `swing_pct` / `secondary_pct` are percentages standing in for the book's absolute $6/$3 on ~$30 stocks; they are documented as such in the docstrings. Don't quietly retune them.
- Do not describe a backtest as successful unless collection, offline computation, result generation and the process exit code were all verified. Distinguish code defects from Docker/runtime, network, and account-entitlement failures when reporting.
