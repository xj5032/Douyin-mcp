"""
Douyin MCP Server — 将抖音私信/聊天功能暴露为 MCP 工具

使用方式:
    python -m douyin_mcp.server
    # 或通过 MCP host:
    #   mcp run douyin_mcp/server.py --port 6789

暴露的 MCP 工具:
    1. search_user(keyword)        — 搜索抖音用户
    2. list_conversations()        — 列举私信会话列表
    3. read_messages(contact, limit) — 读取与联系人的私信
    4. send_message(user_id, text) — 向用户发送私信
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from mcp.server import FastMCP

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
        _ctrl = DouyinController(headless=False)
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
    """运行 MCP server（默认使用 stdio 传输）。"""
    logger.info("启动抖音 MCP 服务器...")
    logger.info("暴露的工具: search_user, list_conversations, read_messages, send_message")
    logger.info("首次启动需要扫码登录，请确保手机抖音 App 可用。")
    mcp.run()


if __name__ == "__main__":
    main()
