# 项目内 Mihomo / Clash 代理

真实配置：`docker/mihomo/config.yaml`；节点、密码、订阅地址都在此文件中手动配置。
运行缓存：`docker/mihomo/runtime/`。这两项不提交、不源码同步、不进入共享镜像。
迁移时将其连同 `docker/.env.dipwatch` 私下复制到新机器同一项目目录，不需要宿主机外的配置目录。

Mihomo 使用本地离线构建的 `vibequant-mihomo:1.19.31`，基于远端已有 `vibequant:dev`，不下载代理镜像。
代理与行情容器使用专用 Docker 网络。7890 和控制端口均不发布到宿主机；不启用 TUN/特权模式。
`.env.dipwatch` 中设置 `HTTP_PROXY=http://mihomo:7890`、`HTTPS_PROXY=http://mihomo:7890`。
Compose 设置 `pull_policy: never`。安装包 SHA-256 在构建时与官方发布值核对。
下载的 `mihomo-linux-amd64-compatible-v1.19.31.gz` 放在本目录；不提交 Git，但会同步到远端用于离线构建。

## 准备（Mac）

```sh
cd /Users/sionlv/VibeQuant
./docker/scripts/remote/sync.sh
bash docker/scripts/remote/prepare-dipwatch-proxy.sh
./docker/scripts/remote/compose.sh --profile dipwatch build --pull=false mihomo
```

准备脚本只在文件不存在时复制模板，不覆盖任何已配置节点、密钥或代理值。
空模板选择 REJECT，不会假装已连通或自动直连。此模板尚未配置真实节点。

## 手工配置（远端）

代理镜像从本地安装包构建，不再使用 Docker Hub 下载方式。节点与密钥仍由用户手工配置。

2026-10-10 验证：安装包 SHA-256 与官方发布值一致；
`compose.sh --profile dipwatch build --pull=false mihomo` 退出 0，
内核显示 `Mihomo Meta v1.19.31 linux amd64`。
公开模板以只读挂载覆盖 `/etc/mihomo/config.yaml` 运行 `mihomo -t`，退出 0，
输出 `configuration file /etc/mihomo/config.yaml test is successful`。
这不代表真实节点或 Alpaca 已连通；尚未替用户填写节点或密钥。

```sh
ssh -p 2222 lxy@121.41.112.193
cd /home/lxy/VibeQuant/docker
nano mihomo/config.yaml
nano .env.dipwatch
```

在 config.yaml 的 `proxies:` 填入服务商给出的 Clash/Mihomo 节点 YAML；
把 `proxy-groups` 中 `[REJECT]` 改成 `[你的节点名称]`，名称须与节点的 `name` 完全相同。
节点类型与字段照服务商配置填写，不要把 VMess/VLESS/SS 单链接直接贴入 YAML。
保留 `mixed-port: 7890`、`allow-lan: true`、`bind-address: "*"`。
不需要 external-controller，不要开启 TUN 或增加公网端口映射。

若使用兼容的 Clash 节点订阅，可将 `proxies: []` 保留并新增：

```yaml
proxy-providers:
  subscription:
    type: http
    url: "在编辑器中填入你的订阅地址"
    path: ./providers/subscription.yaml
    interval: 86400
```

同时把原有 proxy-groups 替换为：

```yaml
proxy-groups:
  - name: ALPACA-PROXY
    type: select
    use: [subscription]
```

订阅须返回 Mihomo 支持的节点列表，首次获取通过远端直接网络；若订阅本身不可达，
先使用一个手动节点或在可信设备下载后手动配置。程序不会把完整配置上传到第三方转换网站。
注意自动选择的首个节点须满足数据服务的地区/账号要求。

在 `.env.dipwatch` 填好 Alpaca 密钥，并将两项代理地址改为 `http://mihomo:7890`。
不要输出配置文件内容或将密钥、订阅链接、节点密码发到聊天。

## 校验、启动、行情验收（远端）

```sh
cd /home/lxy/VibeQuant/docker
# 会显示本地配置诊断，真实节点信息应保留在自己的终端中。
docker compose --project-name vibequant run --name mihomo-check-$(date +%Y%m%d%H%M%S) mihomo -t -d /root/.config/mihomo -f /etc/mihomo/config.yaml
echo "exit=$?"
docker compose --project-name vibequant --profile dipwatch up -d mihomo
docker compose --project-name vibequant run --name alpaca-probe-$(date +%Y%m%d%H%M%S) usstock-dip-watch python collect.py --diagnose
echo "exit=$?"
docker compose --project-name vibequant run --name dipwatch-collect-$(date +%Y%m%d%H%M%S) usstock-dip-watch
echo "exit=$?"
docker compose --project-name vibequant ps -a --format json usstock-dip-watch mihomo
```

语法通过不代表节点可用；Alpaca probe 成功才代表数据接口通过当前链路可访问。
模板未改时连通测试应失败。默认只有 3 个已确认股票，完整采集仍可能为 3/5、退出码 1。
修改节点后执行 `docker compose --project-name vibequant restart mihomo` 重新加载。

节点故障时可在自己的终端查看 `docker compose --project-name vibequant logs --tail 50 mihomo`。
不要公开原始日志，可能包含节点或订阅地址。行情日志与结果复制见 USStockDipWatch/README.md。
验收后在 Mac 运行 `bash docker/scripts/remote/install-dipwatch-schedule.sh` 安装每半小时任务；
任务会先确保 Mihomo 已启动。保留任务容器、不自动删除任何缓存或结果。
