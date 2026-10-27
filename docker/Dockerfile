# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

# 共用镜像：M2DivGold、LiveMoreAmazing、前端门户。
#
# 构建上下文 = 仓库根目录（compose.yaml 里 context: ..），所以 COPY 路径相对仓库根。

ARG PYTHON_IMAGE=python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /workspace

# 系统运行库：
#   libstdc++6 / libgomp1      —— numpy、numba、scipy 等原生扩展
#   libgssapi-krb5-2 / libkrb5-3 —— tgw 的 Linux 原生扩展 (libtgw_python312) 链接了
#                                 libgssapi_krb5.so.2，slim 镜像默认没有，缺了会
#                                 报 "libtgw_python312: cannot open shared object file"
RUN apt-get update && apt-get install -y --no-install-recommends \
        libstdc++6 libgomp1 \
        libgssapi-krb5-2 libkrb5-3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 vibequant \
    && useradd --system --uid 10001 --gid vibequant --create-home vibequant


FROM base AS runtime

# pip 走国内镜像（默认清华 TUNA）。国际链路访问 pypi.org 极慢甚至挂死，
# 而 pip 在 DNS/连接卡住时可能无限期等待，表现为构建几小时不动。
# 需要换源: 在远端 docker/.env 里加 PIP_INDEX_URL=https://xxx/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# 所有依赖在同一事务中解析，避免 SDK 覆盖回测/M2 的依赖约束。
COPY docker/requirements.txt /tmp/requirements.txt
COPY LiveMoreAmazing/requirements.txt /tmp/livemore-requirements.txt
COPY docker/wheels/amazing/ /tmp/wheels/
RUN python -c "from pathlib import Path; p=list(Path('/tmp/wheels').glob('*.whl')); assert sum(x.name.lower().startswith('amazingdata-') for x in p)==1 and sum(x.name.lower().startswith('tgw-') for x in p)==1, 'Place exactly one matching official AmazingData wheel and one tgw wheel in docker/wheels/amazing/'"
# --only-binary=:all: 强制只用预编译 wheel：若某包没有匹配当前平台/Python 的 wheel，
# pip 会立刻报错，而不是悄悄下载源码包、在容器里编译几个小时（pyarrow/numpy 源码编译极慢）。
#
# tgw wheel 把全部原生依赖（libtgw.so、libadk.so、libcrypto.so.10、libssl.so.10、libssh.so.4 等）
# 打包在 site-packages/tgw/common_linux_lib64/ 里，但 .so 之间按 SONAME 互相引用，加载器默认搜不到。
# 把该目录写进 ld.so.conf 并 ldconfig，让它按名可解析；否则 import AmazingData 会报
# "libcrypto.so.10: cannot open shared object file" / "No module named 'libtgw_python312'"。
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
        --index-url "${PIP_INDEX_URL}" \
        --trusted-host "${PIP_TRUSTED_HOST}" \
        --timeout 30 --retries 3 \
        --only-binary=:all: \
        -r /tmp/requirements.txt -r /tmp/livemore-requirements.txt /tmp/wheels/*.whl \
    && python -m pip check \
    && rm -rf /tmp/wheels

# Separate layer: correcting native-library discovery does not reinstall Python packages.
COPY docker/scripts/configure_tgw.py /tmp/configure_tgw.py
RUN python /tmp/configure_tgw.py \
    && python -c "import AmazingData, pandas, numpy, backtrader, pyarrow; print('Shared image dependencies OK')"

# 应用源码
COPY --chown=vibequant:vibequant M2DivGold /workspace/M2DivGold
COPY --chown=vibequant:vibequant LiveMoreAmazing /workspace/LiveMoreAmazing

# 前端门户：站点根，首次挂载空的命名卷时会被这份内容初始化（index.html）
COPY --chown=vibequant:vibequant VibeQuantFront /srv/web

# 预建运行期可写目录并归 vibequant 所有，命名卷挂载时会继承该属主，避免权限问题
RUN mkdir -p \
      /workspace/M2DivGold/data \
      /workspace/LiveMoreAmazing/.cache \
      /workspace/LiveMoreAmazing/results \
      /srv/web \
    && chown -R vibequant:vibequant /workspace /srv/web

USER vibequant

CMD ["python", "-c", "import pandas, numpy; print('vibequant image ready')"]
