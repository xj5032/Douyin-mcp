# =============================================================================
# Douyin MCP Server — Dockerfile
# =============================================================================
# 使用流程:
#   docker compose build && docker compose up -d
# 首次运行需扫码登录:
#   docker compose logs -f
#   open ./data/login_qrcode.png
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="Lozzi"
LABEL description="Douyin MCP Server — browser automation for Douyin messages"

# 中国 PyPI 镜像
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 Playwright 系统依赖（仅 Chromium 需要的最小依赖集）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2t64 \
    xvfb curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖 + Playwright Chromium
WORKDIR /app
COPY pyproject.toml README.md ./
COPY douyin_mcp/ ./douyin_mcp/

RUN pip install --no-cache-dir -e . && \
    playwright install chromium
# 环境变量
ENV DOUYIN_HEADLESS=true
ENV DOUYIN_TRANSPORT=sse
ENV DOUYIN_PORT=6789
ENV TZ=Asia/Shanghai

# 持久化目录
RUN mkdir -p /root/.douyin_mcp

EXPOSE 6789

CMD ["python", "-m", "douyin_mcp.server", "--transport", "sse", "--port", "6789"]
