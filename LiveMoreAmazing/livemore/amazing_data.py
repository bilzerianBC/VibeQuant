"""AmazingData 1.1.9 adapter. SDK imported only for online acquisition.

Cache contract: daily OHLC (ratio-adjusted at the last returned date), volume
in lots of 100 shares, original amount. No synthetic suspension bars.
"""
from __future__ import annotations

import atexit
import importlib
import json
import os
import re
import sys
import tempfile
import time
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根目录（livemore/ 的上一级）；缓存与结果默认放在这里，容器内由环境变量指定。
ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = os.environ.get("LIVEMORE_CACHE_DIR", str(ROOT / ".cache"))
RESULT_DIR = os.environ.get("LIVEMORE_RESULT_DIR", str(ROOT / "results"))
SCHEMA = 1


@contextmanager
def suppress_native_output():
    """Suppress SDK stdout/stderr, including native logs which expose tokens."""
    stdout_fd, stderr_fd = 1, 2
    for stream in (sys.stdout, sys.stderr):
        stream.flush()
    saved = (os.dup(stdout_fd), os.dup(stderr_fd))
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), stdout_fd)
            os.dup2(sink.fileno(), stderr_fd)
            yield
    finally:
        # Flush both Python and C stdio before restoring descriptors.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        try:
            import ctypes
            ctypes.CDLL(None).fflush(None)
        except Exception:
            pass
        os.dup2(saved[0], stdout_fd)
        os.dup2(saved[1], stderr_fd)
        os.close(saved[0])
        os.close(saved[1])


def fallback_calendar(start="19900101", end=None):
    """Weekday boundaries for SDK batching when calendar permission is absent.

    Holidays are intentionally included. query_kline sends date ranges and the
    server remains authoritative about which dates actually contain bars.
    """
    end = end or datetime.now().strftime("%Y%m%d")
    return [int(day.strftime("%Y%m%d")) for day in pd.bdate_range(start, end)]


class QueryRejected(RuntimeError):
    """Native QueryKline refused the request (e.g. -95 no permission); never retried."""


def install_query_fail_fast():
    """Make SDK query_kline raise when native QueryKline rejects immediately.

    AmazingData 1.1.9 ignores ``(False, error_code)`` and then waits forever
    for a callback that will never arrive. Keep the public SDK behavior for
    accepted requests and surface rejected requests synchronously.
    """
    market_module = importlib.import_module("AmazingData.query_api.market_data")
    original = market_module.tgw.QueryKline
    if getattr(original, "_livemore_fail_fast", False):
        return

    def guarded(*args, **kwargs):
        result = original(*args, **kwargs)
        rejected = result is False or result is None
        code = None
        if isinstance(result, tuple) and result:
            rejected = result[0] is False or result[0] is None
            if len(result) > 1:
                code = result[1]
                rejected = rejected or (isinstance(code, int) and code < 0)
        if rejected:
            try:
                from tgw.error_code import GetErrorMsg
                message = GetErrorMsg(code)
            except Exception:
                message = "未知错误"
            raise QueryRejected(f"tgw.QueryKline 被拒绝：{message}（错误码 {code}）")
        return result

    guarded._livemore_fail_fast = True
    market_module.tgw.QueryKline = guarded


def daily_index(values):
    """Support SDK datetime indices and YYYYMMDD integers without ns conversion."""
    index = pd.Index(values)
    text = index.astype(str)
    if all(re.fullmatch(r"\d{8}", x) for x in text):
        dates = pd.to_datetime(text, format="%Y%m%d")
    elif pd.api.types.is_numeric_dtype(index):
        # pandas would read positions 0..n as epoch nanoseconds (all 1970-01-01).
        raise ValueError("日期必须是时间戳或 YYYYMMDD，不能是普通整数序号")
    else:
        dates = pd.to_datetime(index)
    dates = pd.DatetimeIndex(dates)
    if dates.tz is not None:
        dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)
    return dates.normalize()


def validate_range(start, end):
    for value in (start, end):
        if not re.fullmatch(r"\d{8}", value):
            raise ValueError("日期必须为 YYYYMMDD")
        datetime.strptime(value, "%Y%m%d")
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")


def normalize_daily(raw, factors, *, is_index, volume_unit, start, end):
    """Return normalized bars and metadata; reject ambiguous/invalid inputs."""
    if raw is None or raw.empty:
        raise ValueError("SDK 返回空行情；请检查代码、权限及日期范围")
    frame = raw.copy()
    frame.columns = frame.columns.str.lower()
    # AmazingData 1.1.9 query_kline: RangeIndex plus a kline_time column.
    frame.index = daily_index(frame["kline_time"] if "kline_time" in frame.columns else frame.index)
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError("日线包含重复日期，请核对 period 参数")
    frame = frame.loc[pd.Timestamp(start):pd.Timestamp(end)]
    columns = ["open", "high", "low", "close", "volume", "amount"]
    frame = frame[columns].astype(float)
    if frame.empty or not np.isfinite(frame.to_numpy()).all():
        raise ValueError("行情为空或含 NaN/无穷值")
    if (frame[["volume", "amount"]] < 0).any().any():
        raise ValueError("成交量/额不能为负")
    # Some vendors emit all-zero suspension rows. Never turn them into trades.
    zero = (frame[["open", "high", "low", "close"]] == 0).all(axis=1)
    zero &= (frame[["volume", "amount"]] == 0).all(axis=1)
    omitted = int(zero.sum())
    frame = frame.loc[~zero].copy()
    if frame.empty or (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("有效行情为空或包含非正价格")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("OHLC 高低价关系错误")
    if not is_index:
        if volume_unit not in ("shares", "lots"):
            raise ValueError("必须设置 AMAZING_VOLUME_UNIT=shares 或 lots（先确认官方单位）")
        if volume_unit == "shares":
            frame["volume"] /= 100.0
        if factors is None or factors.empty:
            raise ValueError("股票缺少后复权因子，拒绝退回不复权价格")
        factor = factors.copy().astype(float)
        factor.index = daily_index(factor.index)
        factor = factor.sort_index()
        if factor.index.has_duplicates:
            raise ValueError("复权因子日期重复")
        factor = factor.dropna()
        if factor.empty or not np.isfinite(factor.to_numpy()).all() or (factor <= 0).any():
            raise ValueError("复权因子必须为有限正数")
        # Sparse event factors may carry forward; never backfill from future dates.
        aligned = factor.reindex(frame.index, method="ffill")
        if aligned.isna().any():
            raise ValueError("复权因子未覆盖最早日线；不能用未来因子回填")
        anchor = float(aligned.iloc[-1])
        frame[["open", "high", "low", "close"]] = frame[
            ["open", "high", "low", "close"]].mul(aligned / anchor, axis=0)
    else:
        anchor = None
    frame.index.name = "datetime"
    return frame, {"actual_start": frame.index[0].strftime("%Y%m%d"),
                   "actual_end": frame.index[-1].strftime("%Y%m%d"),
                   "bars": len(frame), "anchor_factor": anchor,
                   "omitted_zero_rows": omitted}


class AmazingDataManager:
    DEFAULT_SECTOR = "EXTRA_STOCK_A_SH_SZ"

    def __init__(self, *, offline=False, sdk=None):
        self.offline = offline
        self.sdk = sdk
        self._provided_sdk = sdk is not None
        self.base = None
        self.market = None
        self._logged_in = False
        self._close_registered = False
        self.volume_unit = os.environ.get("AMAZING_VOLUME_UNIT", "")
        self.chunk = int(os.environ.get("AMAZING_BATCH_SIZE", "10"))
        self.pause = float(os.environ.get("AMAZING_REQUEST_PAUSE", "0.3"))
        self.retries = int(os.environ.get("AMAZING_RETRIES", "3"))
        self.retry_wait = float(os.environ.get("AMAZING_RETRY_WAIT", "5"))
        if self.chunk < 1 or self.pause < 0:
            raise ValueError("批大小必须为正数，请求间隔不能为负")
        if self.retries < 1 or self.retry_wait < 0:
            raise ValueError("重试次数必须为正数，重试等待不能为负")
        self.cache = Path(CACHE_DIR)
        self.cache.mkdir(parents=True, exist_ok=True)

    def connect(self):
        if self.offline:
            raise RuntimeError("离线模式不能请求 SDK，请先完成采集")
        if self.base is not None and self.market is not None:
            return
        if not self._provided_sdk and not self._logged_in:
            if self.sdk is None:
                try:
                    self.sdk = importlib.import_module("AmazingData")
                except ImportError as exc:
                    raise RuntimeError("缺少官方 AmazingData/tgw wheel，请按 README 构建镜像") from exc
            names = ("AMAZING_USERNAME", "AMAZING_PASSWORD", "AMAZING_HOST", "AMAZING_PORT")
            missing = [n for n in names if not os.environ.get(n)]
            if missing:
                raise ValueError("缺少配置：" + ", ".join(missing))
            try:
                with suppress_native_output():
                    login_result = self.sdk.login(
                        username=os.environ[names[0]], password=os.environ[names[1]],
                        host=os.environ[names[2]], port=int(os.environ[names[3]]))
            except (Exception, SystemExit):
                raise RuntimeError("AmazingData 登录失败；请检查账号、权限及服务器配置") from None
            if login_result is False:
                raise RuntimeError("AmazingData 登录未通过")
            self._logged_in = True
            if not self._close_registered:
                atexit.register(self.close)
                self._close_registered = True
        try:
            base = self.sdk.BaseData()
            if getattr(self.sdk, "__name__", None) == "AmazingData":
                install_query_fail_fast()
            try:
                calendar = base.get_calendar()
            except Exception:
                calendar = None
            if calendar is None or len(calendar) == 0:
                calendar = fallback_calendar()
                warnings.warn(
                    "AmazingData 交易日历接口不可用，改用工作日划分查询区间；"
                    "真实K线日期仍以服务端返回为准。",
                    RuntimeWarning, stacklevel=2,
                )
            else:
                calendar = sorted(set(int(d.strftime("%Y%m%d")) for d in daily_index(calendar)))
            market = self.sdk.MarketData(calendar)
        except (Exception, SystemExit):
            self.close()
            raise
        # Publish a connected state only once both SDK objects exist.
        self.base, self.market = base, market

    def close(self):
        self.base = self.market = None
        if not self._logged_in or self.sdk is None:
            return
        self._logged_in = False
        try:
            with suppress_native_output():
                self.sdk.logout(os.environ.get("AMAZING_USERNAME", ""))
        except (Exception, SystemExit):
            pass

    def query_kline(self, codes, start, end):
        """Serial SDK query. Recover the 1.1.9 lock on exceptional exits.

        The bundled SDK acquires its global query lock at entry, but only
        releases it on success. Callers must not share a session across threads.
        """
        validate_range(start, end)
        for code in codes:
            self.check_code(code)
        self.connect()
        try:
            return self.market.query_kline(
                codes, begin_date=int(start), end_date=int(end),
                period=self.sdk.constant.Period.day.value)
        except BaseException:
            lock = getattr(self.market, "lock", None)
            if lock is not None and lock.locked():
                lock.release()
            raise

    def get_a_share_list(self, sector=DEFAULT_SECTOR):
        self.connect()
        codes = self.base.get_code_list(security_type=sector)
        result = sorted(set(codes or []))
        if not result:
            raise ValueError("股票池为空，请检查登录和权限")
        for code in result:
            self.check_code(code)
        return result

    @staticmethod
    def check_code(code):
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
            raise ValueError(f"不支持的证券代码格式 {code!r}；需核对 SDK 代码格式")

    def cache_file(self, code, start, end):
        self.check_code(code)
        validate_range(start, end)
        return self.cache / f"{code}_{start}_{end}_front_ratio.parquet"

    def get_daily(self, code, start, end):
        path = self.cache_file(code, start, end)
        metadata = path.with_suffix(".json")
        if not path.exists() or not metadata.exists():
            raise FileNotFoundError(f"缺少完整缓存 {path.name}，请先运行 run_backtest.py 采集")
        info = json.loads(metadata.read_text())
        if info.get("schema") != SCHEMA or info.get("source") != "AmazingData":
            raise ValueError("缓存来源或版本不兼容，请重新采集")
        return pd.read_parquet(path)

    def _save(self, code, start, end, frame, details):
        path = self.cache_file(code, start, end)
        info = dict(details, schema=SCHEMA, source="AmazingData", code=code,
                    requested_start=start, requested_end=end,
                    adjustment="raw_index" if details["anchor_factor"] is None else "ratio_front",
                    adjustment_anchor=details["actual_end"], input_volume_unit=self.volume_unit,
                    suspension_policy="observed_rows_only",
                    fetched_at=datetime.now(timezone.utc).isoformat())
        # Remove commit marker first; failed writes cannot masquerade as complete cache.
        path.with_suffix(".json").unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.cache, suffix=".parquet", delete=False) as f:
            temporary = Path(f.name)
        try:
            frame.to_parquet(temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        path.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
        return info

    def _call_sdk(self, label, function):
        """Run one SDK request, retrying transient failures a bounded number of times.

        AmazingData 1.1.9 sometimes fails inside its own calendar fetch (TypeError on
        None). Native rejections such as -95 (QueryRejected) are raised immediately.
        """
        for attempt in range(1, self.retries + 1):
            try:
                return function()
            except QueryRejected:
                raise
            except Exception as exc:
                if attempt == self.retries:
                    raise RuntimeError(f"{label} 连续 {attempt} 次失败：{type(exc).__name__}: {exc}") from exc
                wait = self.retry_wait * attempt
                print(f"{label} 第 {attempt} 次失败（{type(exc).__name__}），{wait:g}s 后重试", flush=True)
                time.sleep(wait)

    def cached_info(self, code, start, end):
        """Commit marker of a complete cache entry built with the current volume unit, else None."""
        path = self.cache_file(code, start, end)
        marker = path.with_suffix(".json")
        if not (path.exists() and marker.exists()):
            return None
        try:
            info = json.loads(marker.read_text())
        except ValueError:
            return None
        if (info.get("schema") != SCHEMA or info.get("source") != "AmazingData"
                or info.get("input_volume_unit") != self.volume_unit):
            return None
        return info

    def batch_download(self, codes, start, end, *, index_codes=(), resume=False):
        validate_range(start, end)
        codes = list(dict.fromkeys(codes))
        for code in codes:
            self.check_code(code)
        indexes = set(index_codes)
        if any(c not in indexes for c in codes) and self.volume_unit not in ("shares", "lots"):
            raise ValueError("请先确认成交量单位并设置 AMAZING_VOLUME_UNIT=shares 或 lots")
        reports = []
        if resume:
            reports = [info for info in (self.cached_info(c, start, end) for c in codes) if info]
            done = {info["code"] for info in reports}
            codes = [c for c in codes if c not in done]
            print(f"复用已有缓存 {len(done)} 只，待下载 {len(codes)} 只", flush=True)
        if not codes:
            return reports
        self.connect()
        for offset in range(0, len(codes), self.chunk):
            batch = codes[offset:offset + self.chunk]
            raw = self._call_sdk(f"query_kline {batch[0]}~{batch[-1]}", lambda: self.query_kline(batch, start, end))
            stocks = [c for c in batch if c not in indexes]
            factors = None
            if stocks:
                factor_dir = self.cache / "factors"
                factor_dir.mkdir(exist_ok=True)
                factors = self._call_sdk(f"get_backward_factor {stocks[0]}~{stocks[-1]}",
                                         lambda: self.base.get_backward_factor(
                                             stocks, local_path=str(factor_dir.resolve()) + os.sep,
                                             is_local=False))
            for code in batch:
                try:
                    factor = factors[code] if factors is not None and code in factors else None
                    frame, details = normalize_daily(raw.get(code), factor, is_index=code in indexes,
                                                     volume_unit=self.volume_unit, start=start, end=end)
                    reports.append(self._save(code, start, end, frame, details))
                    print(f"{code}: {details['actual_start']}~{details['actual_end']}, {len(frame)} bars", flush=True)
                except Exception as exc:
                    raise RuntimeError(f"{code} 行情处理失败：{exc}") from exc
            time.sleep(self.pause)
        return reports

    def listing_date(self, code):
        self.check_code(code)
        self.connect()
        data = self.sdk.InfoData().get_stock_basic([code])
        row = data.loc[data["MARKET_CODE"] == code, "LISTDATE"]
        if row.empty or pd.isna(row.iloc[0]):
            return None
        return str(int(row.iloc[0]))
