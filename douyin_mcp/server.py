"""
Douyin MCP Server — 将抖音私信/聊天功能暴露为 MCP 工具

使用方式:
    python -m douyin_mcp.server                      # stdio 模式 (默认)
    python -m douyin_mcp.server --transport sse --port 6789  # SSE 模式 (Docker)

暴露的 MCP 工具:
    1. search_user(keyword)          — 搜索抖音用户
    2. list_conversations()          — 列举私信会话列表
    3. read_messages(contact, limit) — 读取与联系人的私信
    4. send_message(user_id, text)   — 向用户发送私信
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from douyin_mcp.core import DouyinController

# ── logger ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("douyin-mcp")

# ── 启动前检查 ──────────────────────────────────────────────────────────


def _check_environment() -> list[str]:
    """检查运行环境是否就绪，返回所有警告信息列表。"""
    warnings: list[str] = []

    # 1. Python 版本
    if sys.version_info < (3, 10):
        warnings.append(
            f"Python >=3.10 推荐 (当前 {sys.version_info.major}.{sys.version_info.minor})"
        )

    # 2. Playwright 浏览器
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browsers = p.chromium
            # Playwright 安装检测：尝试获取浏览器路径
            try:
                browsers.executable_path
            except Exception:
                warnings.append(
                    "Chromium 未安装 (运行 playwright install chromium)"
                )
    except ImportError:
        warnings.append("playwright 未安装 (运行 pip install playwright)")
    except Exception as e:
        warnings.append(f"Playwright 环境检查异常: {e}")

    # 3. 依赖
    missing_deps = []
    for pkg in ["playwright", "httpx"]:
        try:
            __import__(pkg)
        except ImportError:
            missing_deps.append(pkg)
    if missing_deps:
        warnings.append(f"缺少依赖: {', '.join(missing_deps)}")

    return warnings


_checks = _check_environment()
if _checks:
    logger.warning("=" * 50)
    logger.warning("环境检查发现问题:")
    for w in _checks:
        logger.warning(f"  ⚠  {w}")
    logger.warning("=" * 50)
else:
    logger.info("环境检查全部通过 ✅")

# ── controller singleton ────────────────────────────────────────────────

_ctrl: Optional[DouyinController] = None


def _get_ctrl() -> DouyinController:
    global _ctrl
    if _ctrl is None:
        headless = os.environ.get("DOUYIN_HEADLESS", "").lower() in ("true", "1", "yes")
        _ctrl = DouyinController(headless=headless)
    return _ctrl


# ── MCP server ──────────────────────────────────────────────────────────

mcp = FastMCP("Douyin MCP", port=6789)


# ── tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def search_user(keyword: str) -> str:
    """搜索抖音用户，返回用户昵称、抖音号、简介、粉丝数等信息。

    Args:
        keyword: 搜索关键词（用户名、抖音号等）。
    """
    ctrl = _get_ctrl()

    async def _run():
        await ctrl.initialize()
        result = await ctrl.search_user(keyword)
        return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("search_user(%r) failed", keyword)
        return f"搜索用户失败: {exc}"


@mcp.tool()
def list_conversations() -> str:
    """列举当前账号的所有私信会话列表。

    返回每个会话的联系人昵称、最后一条消息的片段、未读消息数。
    """
    ctrl = _get_ctrl()

    async def _run():
        await ctrl.initialize()
        result = await ctrl.list_conversations()
        return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("list_conversations failed")
        return f"列举会话失败: {exc}"


@mcp.tool()
def read_messages(contact: str, limit: int = 20) -> str:
    """读取与指定联系人的私信消息。

    先在会话列表中查找联系人，打开对话后从 DOM 提取消息内容。

    Args:
        contact: 联系人昵称（用于在会话列表中定位）。
        limit: 读取的最大消息条数，默认 20。
    """
    ctrl = _get_ctrl()

    async def _run():
        await ctrl.initialize()
        result = await ctrl.read_messages(contact, limit)
        return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("read_messages(%r) failed", contact)
        return f"读取消息失败: {exc}"


@mcp.tool()
def send_message(user_id: str, text: str) -> str:
    """向指定用户发送私信消息。

    先在会话列表中查找用户，如果不在列表中则通过搜索找到用户并打开私信窗口。
    通过 Draft.js 注入方式输入文本，然后点击发送按钮。

    Args:
        user_id: 目标用户的昵称。
        text: 要发送的消息内容。
    """
    ctrl = _get_ctrl()

    async def _run():
        await ctrl.initialize()
        result = await ctrl.send_message(user_id, text)
        return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.exception("send_message(%r) failed", user_id)
        return f"发送消息失败: {exc}"


# ── main ────────────────────────────────────────────────────────────────


def main():
    """运行 MCP server。

    支持两种传输模式:
      - stdio (默认): 标准输入输出传输，适合 MCP host 本地调用
      - sse: Server-Sent Events，HTTP 模式运行在指定端口，适合 Docker
    """
    parser = argparse.ArgumentParser(description="Douyin MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=os.environ.get("DOUYIN_TRANSPORT", "stdio"),
        help="传输协议 (默认: stdio, Docker 推荐: sse)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DOUYIN_PORT", "6789")),
        help="SSE 模式监听端口 (默认: 6789)",
    )
    args = parser.parse_args()

    logger.info("启动抖音 MCP 服务器...")
    logger.info("暴露的工具: search_user, list_conversations, read_messages, send_message")
    logger.info("传输模式: %s", args.transport)
    if args.transport == "sse":
        logger.info("监听端口: %d", args.port)
        logger.info("MCP 端点: http://localhost:%d/mcp", args.port)
        logger.info("健康检查: http://localhost:%d/health", args.port)
    logger.info("首次启动需要扫码登录，请确保手机抖音 App 可用。")

    if args.transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        from starlette.responses import JSONResponse, FileResponse

        async def health_endpoint(request):
            return JSONResponse({
                "status": "ok",
                "service": "douyin-mcp",
                "version": "0.1.0",
            })

        def token_ok(authorization="", x_api_key=""):
            expected = os.environ.get("DOUYIN_MCP_TOKEN", "").strip()
            if not expected:
                return False

            supplied = ""
            if authorization.lower().startswith("bearer "):
                supplied = authorization[7:].strip()
            elif x_api_key:
                supplied = x_api_key.strip()

            return bool(supplied) and secrets.compare_digest(supplied, expected)

        sse = SseServerTransport("/mcp")

                async def handle_sse(request):
            if not token_ok(
                request.headers.get("authorization", ""),
                request.headers.get("x-api-key", ""),
            ):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                mcp_server = mcp._mcp_server
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )

        async def protected_mcp(scope, receive, send):
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }

            if not token_ok(
                headers.get("authorization", ""),
                headers.get("x-api-key", ""),
            ):
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return

            await sse.handle_post_message(scope, receive, send)

        async def login_qr_endpoint(request):
            expected = os.environ.get("DOUYIN_MCP_TOKEN", "").strip()
            supplied = request.query_params.get("token", "").strip()

            if (
                not expected
                or not supplied
                or not secrets.compare_digest(supplied, expected)
            ):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

            qr_path = os.path.expanduser(
                "~/.douyin_mcp/login_qrcode.png"
            )

            if not os.path.exists(qr_path):
                return JSONResponse({
                    "status": "not_ready",
                    "message": "二维码还没生成，请先从 MCP 调用一次工具触发登录。",
                }, status_code=404)

            return FileResponse(
                qr_path,
                media_type="image/png",
                headers={"Cache-Control": "no-store"},
            )

        app = Starlette(
            routes=[
                Route("/health", endpoint=health_endpoint),
                Route("/login-qr", endpoint=login_qr_endpoint),
                Mount("/mcp", app=protected_mcp),
                Route("/sse", endpoint=handle_sse),
            ],
        )

        import uvicorn
        logger.info("启动 SSE 服务器 http://0.0.0.0:%d ...", args.port)
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
