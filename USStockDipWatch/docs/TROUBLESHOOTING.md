# 分项排障与验收

## 2026-10-10 Alpaca 改造

生产入口改为 `collect.py`。密钥与 HTTP CONNECT 代理配置在远端
`docker/.env.dipwatch`，详见 README。以下 Yahoo/Binance 记录为旧方案；
新采集不请求这两个接口。Alpaca 真实行情需配置账号与代理后验收。

正式方案：已有 `/home/lxy/VibeQuant` 服务器，共用 Docker 镜像和 front 网页服务，不使用第三方源码托管。

## 2026-10-09 验证结果

1. **SSH 权限：已解决。** 当前会话网络已开启。`docker/scripts/remote/compose.sh ps` 退出码 0，现有 front 正常。
2. **网页上线：已完成。** `docker/scripts/remote/deploy-dipwatch-web.sh` 退出码 0；共用镜像构建成功、网页发布成功、内部 HTTP 验证通过。已有 front 保持原容器运行。外部页面、data.json、reminders.json 均 HTTP 200，页面内容和相对路径已核对。
3. **真实行情：阻塞。** 服务器容器访问 Yahoo query1 的 QQQ、NVDA、TSLA、SPCX 全部 HTTP 403；query2 对 QQQ、SPCX 也 HTTP 403。币安 fapi.binance.com 和 api.binance.com 返回 `URLError [Errno 101] Network is unreachable`。Mac 侧 Yahoo HTTP 429，币安连接 15 秒超时。没有取得并验证真实行情，不是回撤计算成功的证据。
4. **每日更新：未启用。** 等行情验证后再安装北京时间 07:00 任务。
5. **苹果提醒事项：未接通。** 等更新链路通过后处理设备授权及安全接入，最终验证 iPhone 通知并启用 07:10 自动化。

已上线地址：<http://121.41.112.193:8080/usstockdipwatch/>。首版明确显示尚未取得行情，未填入模拟价格。

## 下一项：服务器行情源访问

股票接口 HTTP 403 是上游拒绝，不能简单归因于账号权限或股票代码错误。需更换或接入可用、支持真实股票日线的数据源并核对价格日期覆盖。币安连接失败发生在收到 HTTP 响应之前，未确认合约是否存在或可用；需先恢复服务器到币安官方行情接口的有效网络连接，再检查 exchangeInfo 和单日日线。不得绕过地区限制、伪造结果或无限重试。

本地预览端口权限可独立处理，不再阻塞已上线网页。构建和发布命令见 README。
