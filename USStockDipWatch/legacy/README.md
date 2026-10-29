# legacy/ —— 已退役的原型，不参与生产流程

`cloudflare-worker/` 是 DipWatch 早期的 Cloudflare Worker / Sites 原型（Yahoo + Binance，JS 实现）。
生产流程已改为 Python：`collect.py` 采集、`publish.py` 发布、`site_server.py` 提供网页与勾选接口。

保留在这里只为留档与对照，不被 Docker 镜像打包（见仓库根 `.dockerignore`）。
仍可在本目录单独构建与测试：

```sh
cd USStockDipWatch/legacy/cloudflare-worker
npm run build   # 读取 ../../web/index.html，生成 dist/server/index.js
npm test
```
