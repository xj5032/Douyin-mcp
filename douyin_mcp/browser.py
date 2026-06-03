"""
Douyin MCP Browser — Playwright 浏览器管理模块

职责:
  - 管理 Playwright chromium 浏览器实例生命周期
  - 处理抖音网页版扫码登录流程
  - 持久化/恢复 storage_state（cookie + localStorage）
  - 提供已登录的 BrowserContext 给 core 模块使用

配置路径:
  storage_state 保存在 ~/.douyin_mcp/storage.json
  配置目录: ~/.douyin_mcp/
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

logger = logging.getLogger("douyin-mcp.browser")

# ── 常量 ──────────────────────────────────────────────────────────────

DATA_DIR = Path.home() / ".douyin_mcp"
STORAGE_STATE_PATH = DATA_DIR / "storage.json"
DOUYIN_URL = "https://www.douyin.com"
MESSAGES_URL = "https://www.douyin.com/messages"
QR_TIMEOUT = 120  # 等待扫码超时（秒）

# ── 反检测脚本 — 修改浏览器指纹绕过抖音反爬 ──────────────────────────

STEALTH_SCRIPT = """
// 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 覆盖 chrome 属性
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// 覆盖 permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// 覆盖 plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// 覆盖 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en']
});

// 覆盖 platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'MacIntel'
});
"""


# ══════════════════════════════════════════════════════════════════════
#  BrowserManager
# ══════════════════════════════════════════════════════════════════════


class BrowserManager:
    """Playwright 浏览器管理器。

    负责:
      - 启动/关闭浏览器
      - 创建带反检测配置的 BrowserContext
      - 存储/恢复登录态 (storage_state)
      - 引导用户扫码登录
    """

    def __init__(self, headless: bool = False) -> None:
        self._headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── 属性 ────────────────────────────────────────────────────────

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("BrowserContext not initialized. Call start() first.")
        return self._context

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Page not initialized. Call start() first.")
        return self._page

    @property
    def is_authenticated(self) -> bool:
        """检查是否已保存登录态。"""
        return STORAGE_STATE_PATH.exists()

    # ── 生命周期 ────────────────────────────────────────────────────

    async def start(self) -> None:
        """启动浏览器并创建 Context。

        如果存在 storage_state 则恢复登录态，否则打开登录页等待扫码。
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-web-security",
            "--disable-features=BlockInsecurePrivateNetworkRequests",
            "--no-sandbox",
        ]

        if self._headless:
            launch_args.append("--headless=new")

        # ── 使用系统已安装的 Google Chrome ────────────────────────────
        # 优先通过 channel="chrome" 调用系统 Chrome，避免从网络下载 Chromium
        user_data_dir = tempfile.mkdtemp(prefix="douyin_mcp_")

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=False,
                args=launch_args,
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            logger.info("通过 channel='chrome' 成功启动系统 Google Chrome")
        except Exception as exc:
            logger.warning(
                "channel='chrome' 启动失败，尝试 executable_path 回退: %s", exc
            )
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                headless=False,
                args=launch_args,
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            logger.info("通过 executable_path 成功启动 Google Chrome")

        self._browser = self._context.browser

        # 注入反检测脚本
        await self._context.add_init_script(STEALTH_SCRIPT)

        self._page = await self._context.new_page()

        # 设置默认超时
        self._page.set_default_timeout(30000)

        # 恢复登录态 — 从 storage.json 加载 cookies 并注入
        if self.is_authenticated:
            try:
                import json
                raw = STORAGE_STATE_PATH.read_text()
                state = json.loads(raw)
                cookies = state.get("cookies", [])
                if cookies:
                    await self._context.add_cookies(cookies)
                    logger.info("已从 %s 恢复 %d 个 cookies", STORAGE_STATE_PATH, len(cookies))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("storage_state 读取失败，将重新登录: %s", exc)

        logger.info("浏览器启动完成")

    async def ensure_authenticated(self) -> None:
        """确保当前处于登录状态，未登录则引导扫码。"""
        if not self.is_authenticated:
            logger.info("未检测到登录态，开始扫码登录流程")
            await self._login_flow()
            return

        # 有 storage_state，但有可能过期，快速验证
        await self._page.goto(DOUYIN_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        if await self._check_login_status():
            logger.info("登录态有效 ✅")
            return

        # 登录态过期，重新扫码
        logger.warning("登录态已过期，需要重新扫码")
        await self._login_flow()

    async def _login_flow(self) -> None:
        """扫码登录流程：
        1. 打开抖音首页
        2. 点击登录按钮
        3. 等待二维码出现
        4. 提示用户扫码
        5. 等待登录成功
        6. 保存 storage_state
        """
        await self._page.goto(DOUYIN_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 点击登录按钮 — 尝试多个选择器
        login_selectors = [
            "text=登录",
            ".login-button",
            "[class*='login']",
            "button:has-text('登录')",
            "span:has-text('登录')",
            "a:has-text('登录')",
        ]
        clicked = False
        for sel in login_selectors:
            try:
                btn = await self._page.wait_for_selector(sel, timeout=5000)
                if btn:
                    await btn.click()
                    clicked = True
                    logger.info("点击登录按钮: %s", sel)
                    break
            except Exception:
                continue

        if not clicked:
            # 可能已经弹出登录面板
            logger.info("登录按钮未找到，假设登录面板已显示")

        await asyncio.sleep(2)

        # 等待二维码出现 — 尝试侦测二维码图片
        logger.info("等待二维码加载...")
        try:
            # 多种二维码检测方式
            qr_detected = False
            qr_selectors = [
                "img[src*='qrcode']",
                "img[class*='qrcode']",
                "[class*='qrcode'] img",
                "canvas",
                "img[alt*='扫码']",
            ]
            for qs in qr_selectors:
                try:
                    el = await self._page.wait_for_selector(qs, timeout=8000)
                    if el:
                        qr_detected = True
                        logger.info("二维码元素已找到: %s", qs)
                        break
                except Exception:
                    continue

            if not qr_detected:
                # 截图整个页面给用户看
                logger.info("未检测到标准二维码元素，首屏截图如下")

            # 截屏保存二维码
            screenshot_path = DATA_DIR / "login_qrcode.png"
            await self._page.screenshot(path=str(screenshot_path))
            logger.info("二维码截图已保存到 %s", screenshot_path)

        except Exception as exc:
            logger.warning("二维码检测异常: %s", exc)
            screenshot_path = DATA_DIR / "login_qrcode.png"
            await self._page.screenshot(path=str(screenshot_path))
            logger.info("已保存登录页面截图到 %s", screenshot_path)

        # 提示用户扫码
        print(
            "\n" + "=" * 60,
            "\n  请使用手机抖音 App 扫码登录",
            "\n  二维码截图已保存到:",
            f"\n    {DATA_DIR / 'login_qrcode.png'}",
            "\n",
            "\n  若二维码不可见，请手动打开浏览器并扫码登录。",
            "\n  登录后脚本会自动检测并保存登录态。",
            "\n" + "=" * 60,
            file=sys.stderr,
        )

        # 等待登录成功 — 轮询检测页面是否跳转/变化
        await self._wait_for_login()

        # 保存 storage_state
        await self._save_storage_state()
        logger.info("扫码登录完成，登录态已保存 ✅")

    async def _wait_for_login(self, timeout: int = QR_TIMEOUT) -> None:
        """等待用户扫码登录成功。

        通过检测 URL 变化或登录态元素判断登录是否成功。
        """
        start = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"扫码登录超时（{timeout}秒），请重试"
                )

            current_url = self._page.url

            # 登录成功后可能会跳转回首页
            if DOUYIN_URL in current_url and "/passport" not in current_url:
                # 再检查是否有登录态 cookie
                if await self._check_login_status():
                    return

            # 检查是否存在用户头像等登录后元素
            logged_in_selectors = [
                "[class*='user-info']",
                "[class*='avatar']",
                "[class*='userAvatar']",
                "img[class*='avatar']",
            ]
            for sel in logged_in_selectors:
                try:
                    el = await self._page.wait_for_selector(sel, timeout=3000)
                    if el:
                        return
                except Exception:
                    continue

            await asyncio.sleep(2)

    async def _check_login_status(self) -> bool:
        """通过检测 cookie 或 DOM 判断是否已登录。"""
        try:
            # 检测是否有 session cookie
            cookies = await self._context.cookies()
            cookie_names = {c["name"] for c in cookies}
            # 抖音登录态 cookie 常见名称
            session_cookies = {"sessionid", "sid_guard", "sid_ucp_virtual"}
            if session_cookies & cookie_names:
                return True

            # 降级：检查 localStorage 中的 token
            token = await self._page.evaluate(
                "() => localStorage.getItem('sessionid')"
            )
            if token:
                return True
        except Exception:
            pass
        return False

    async def _save_storage_state(self) -> None:
        """保存当前浏览器上下文的 storage_state 到文件。"""
        state = await self._context.storage_state()
        STORAGE_STATE_PATH.write_text(
            __import__("json").dumps(state, ensure_ascii=False, indent=2)
        )
        logger.info("登录态已保存到 %s", STORAGE_STATE_PATH)

    async def navigate(self, url: str) -> None:
        """导航到指定 URL 并等待页面加载。"""
        await self._page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

    async def close(self) -> None:
        """清理资源，关闭浏览器。"""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("浏览器已关闭")
