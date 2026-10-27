# VibeQuant

抓美国 **M2** 与**黄金**的长期数据，算「M2 ÷ 黄金」比值并生成图表网页，部署在远端 Docker 上、经公网机对外访问。

## 仓库结构

```text
VibeQuant/
├── M2DivGold/            数据抓取 + 日度比值交互图
│   ├── fetch_m2_gold.py      从 FRED 拉 M2、从 LBMA 拉金价，聚合成月度/日度 CSV
│   ├── daily_ratio_chart.py  生成自包含交互 HTML（日度 M2÷黄金，默认最近一年）
│   └── README.md             数据源、运行方式、已知限制
├── VibeQuantFront/       前端门户
│   └── index.html            站点入口，链接各项目产物
└── docker/               统一镜像 + compose + 部署脚本
    ├── Dockerfile
    ├── compose.yaml          服务：m2divgold（抓取）、front（静态门户）、dev-shell
    ├── requirements.txt      pandas + numpy
    └── scripts/              部署/同步/cron 脚本（详见 docker/README.md）
```

## 快速开始

```bash
# 1) 同步源码 + 构建镜像（Mac 终端）
cd docker/scripts/remote
./bootstrap.sh

# 2) 拉数据 + 出图
./run-m2divgold.sh
./compose.sh run --rm m2divgold python daily_ratio_chart.py

# 3) 起门户服务
./compose.sh up -d front

# 4) 每天 08:00 自动更新（可选）
./install-schedule.sh
```

完整说明见 [`docker/README.md`](docker/README.md)（部署、公网访问、定时更新）和 [`M2DivGold/README.md`](M2DivGold/README.md)（数据源、图表、限制）。

## 数据源

| 数据 | 来源 | 覆盖 |
|---|---|---|
| 美国 M2 | FRED `M2SL`（美联储官方序列） | 1959-01 起 |
| 黄金 | LBMA 伦敦金定盘价（官网 JSON） | 1968-04-01 起 |
| 黄金（1968 年前） | 美国官方金价常量 $20.67 / $35.00 | 1919-09 ~ 1968-03 |
