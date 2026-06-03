# =============================================================================
# Douyin MCP Server — Dockerfile
# =============================================================================
# 基于 Playwright 官方 Python 镜像，预装 Chromium。
# 使用方式:
#   docker compose build && docker compose up -d
# 首次运行需扫码登录:
#   docker compose logs -f  # 查看二维码截图路径
#   open ./data/login_qrcode.png  # (Mac) 或手动打开图片扫码
# =============================================================================

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

LABEL maintainer="Lozzi"
LABEL description="Douyin MCP Server — browser automation for Douyin messages"

# 安装项目依赖
WORKDIR /app
COPY pyproject.toml README.md ./
COPY douyin_mcp/ ./douyin_mcp/

# 安装 Python 依赖 + Playwright Chromium
RUN pip install --no-cache-dir -e . \
    && playwright install chromium \
    && apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# 创建数据目录
RUN mkdir -p /root/.douyin_mcp

# 暴露 MCP 端口 (SSE 模式)
EXPOSE 6789

# SSE 模式运行 (Docker 推荐)
# MCP Host 连接方式: http://localhost:6789/sse
# MCP 消息端点: http://localhost:6789/mcp
CMD ["python", "-m", "douyin_mcp.server", "--transport", "sse", "--port", "6789"]
