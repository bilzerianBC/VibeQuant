# VibeQuant Project Instructions

## Scope and project layout

- These instructions apply to the entire VibeQuant repository.
- `LiveMore/` is the original QMT implementation. Preserve it unless the user explicitly requests changes to the original version.
- `LiveMoreAmazing/` is the copied implementation adapted to Galaxy Securities AmazingData. Library code is in `LiveMoreAmazing/livemore/`, the main entry is `run_backtest.py`, reports are published with `python -m livemore.report`. Its `scripts/` and `tests/` were deleted at the user's request (2026-10-26).
- `local/` holds personal, non-project files; never commit, sync or package it.
- `M2DivGold/` and `LiveMoreAmazing/` share the image built from `docker/Dockerfile` and tagged `vibequant:dev`.
- Keep Docker configuration under `docker/` and remote deployment helpers under `docker/scripts/remote/`.

## Change discipline

- Implement AmazingData changes in `LiveMoreAmazing/`, not in `LiveMore/`. Keep `LiveMoreAmazing/livemore/livermore_strategy.py` byte-identical to the original strategy unless the user asks otherwise.
- Do not recreate a standalone AmazingData Dockerfile or Compose stack. Extend the shared image and `docker/compose.yaml` service.
- Preserve unrelated user files and uncommitted changes.
- Do not delete remote Docker volumes, cached market data, result files, containers, or images unless the user explicitly requests that exact deletion.
- Prefer small, reviewable changes and keep documentation consistent with the commands that actually work.

## Credentials and sensitive output

- Never print, quote, commit, or sync AmazingData usernames, passwords, session tokens, or complete login payloads.
- The real credentials belong only in the remote file `/home/lxy/VibeQuant/docker/.env.amazing` with restrictive permissions.
- Keep `docker/.env.amazing` excluded from Git and remote source synchronization.
- Suppress native SDK login and logout output because it may contain a session token.
- Do not place real credentials in command arguments, source code, tests, fixtures, documentation, or shell history.
- Use the configured environment variables: `AMAZING_USERNAME`, `AMAZING_PASSWORD`, `AMAZING_HOST`, and `AMAZING_PORT`.

## AmazingData behavior

- Use AmazingData only for read-only market and reference data. Do not call order, trade, or account-operation interfaces.
- The historical K-line interface used by this project is the high-level `MarketData.query_kline(...)`, backed by `tgw.QueryKline`.
- Before bulk collection, run a single-stock, short-range `run_backtest.py` inside the `livemore-amazing` service.
- `tgw.QueryKline` returning `(None, -95)` means `数据无权限`. Treat it as a server-side account entitlement problem and report the exact interface and error code.
- Do not retry permission errors indefinitely. Immediate native query rejection must fail quickly instead of waiting for a callback that will never arrive.
- `BaseData.get_calendar()` returning `None` does not by itself prove error `-95`. Keep that condition distinct from the confirmed K-line permission error.
- A weekday fallback calendar may be used only to divide requests into date ranges; the server response remains authoritative for actual trading dates.
- Do not guess whether stock daily `volume` is expressed in shares or lots. Require `AMAZING_VOLUME_UNIT=shares` or `AMAZING_VOLUME_UNIT=lots` only after the unit is verified from returned data or confirmed by the provider.
- Do not run the complete backtest until historical K-line permission and volume units have been verified.
- Validate adjustment-factor coverage and never backfill an earlier date using a factor first observed in the future.

## Official SDK dependencies

- Official Linux wheels belong in `docker/wheels/amazing/`.
- The container currently uses Python 3.12, so the AmazingData wheel must match CPython 3.12 and the remote Linux architecture.
- Keep exactly one compatible AmazingData wheel and one compatible `tgw` wheel in the wheel directory.
- The `tgw` wheel ships native libraries. Preserve `docker/scripts/configure_tgw.py` and its linker configuration when changing the image.
- Validate SDK imports as the non-root container user, not only during a root-owned build step.

## Remote Docker workflow

- Local repository: `/Users/lxy/VibeQuant`.
- Remote repository: `/home/lxy/VibeQuant`.
- Run remote helper commands from `/Users/lxy/VibeQuant/docker/scripts/remote`, or use their full repository-relative paths.
- Synchronize with `docker/scripts/remote/sync.sh`.
- Build the shared image with `docker/scripts/remote/compose.sh build m2divgold`.
- Run AmazingData commands with `docker/scripts/remote/compose.sh run --rm livemore-amazing ...`.
- A source sync does not update code copied into the image. Rebuild the shared image after source changes before testing the remote service.
- Never overwrite the remote `.env.amazing` during synchronization.

## Required validation

- There is no offline test suite any more (`LiveMoreAmazing/tests/` was deleted). After changing the adapter or backtest, verify with a small real run: one stock, a short date range, then check the result CSV and the process exit code.
- Use a single stock and a short range for permission diagnostics before requesting a large date range.
- Do not describe the full backtest as successful unless the data collection, offline computation, result generation, and process exit code have all been verified.

## Reporting work

- Lead with the observed outcome.
- Report the exact command tested, its exit status, and the meaningful output without exposing secrets.
- Distinguish code defects, Docker/runtime defects, network failures, and external account-permission failures.
- When blocked by provider permissions, identify the interface, error code, and entitlement the user needs to request.
- Provide complete, directly runnable remote deployment steps after implementation changes.
- Explain how to inspect logs, confirm container exit status, list generated results, and copy results back to the Mac.
