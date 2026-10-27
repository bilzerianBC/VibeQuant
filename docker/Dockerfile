# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

# VibeQuant 运行镜像 —— 用于 M2DivGold 数据抓取 + 前端门户静态服务。
#
# 构建上下文 = 仓库根目录（compose.yaml 里 context: ..），所以 COPY 路径相对仓库根。

ARG PYTHON_IMAGE=python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /workspace

RUN groupadd --system --gid 10001 vibequant \
    && useradd --system --uid 10001 --gid vibequant --create-home vibequant


FROM base AS runtime

# 运行依赖：M2DivGold 只需 pandas（numpy 是其依赖）
COPY docker/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --requirement /tmp/requirements.txt

# 应用源码
COPY --chown=vibequant:vibequant M2DivGold /workspace/M2DivGold

# 前端门户：站点根，首次挂载空的命名卷时会被这份内容初始化（index.html）
COPY --chown=vibequant:vibequant VibeQuantFront /srv/web

# 预建运行期可写目录并归 vibequant 所有，命名卷挂载时会继承该属主，避免权限问题
RUN mkdir -p \
      /workspace/M2DivGold/data \
      /srv/web \
    && chown -R vibequant:vibequant /workspace /srv/web

USER vibequant

CMD ["python", "-c", "import pandas, numpy; print('vibequant image ready')"]
