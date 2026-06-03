"""
Douyin MCP Core — 抖音操作核心模块

基于 Playwright 浏览器自动化，通过 DOM 操作实现：
  - 搜索用户（search_user）
  - 读取私信（read_messages）
  - 发送私信（send_message）
  - 列举会话（list_conversations）

关键依赖:
  - playwright: 浏览器自动化
  - 抖音网页版 (https://www.douyin.com/messages)

注意:
  - 聊天输入框使用 Draft.js，通过 page.evaluate() 注入文本
  - 消息读取通过 DOM 提取，零成本
  - 所有操作需要先登录（由 browser.BrowserManager 管理）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from douyin_mcp.browser import BrowserManager, MESSAGES_URL, DOUYIN_URL

logger = logging.getLogger("douyin-mcp.core")

# ── Draft.js 文本注入脚本 ────────────────────────────────────────────
#
# 抖音聊天输入框基于 Draft.js，不能直接用 fill() 或 type()。
# 通过模拟 ClipboardEvent('paste') 触发 Draft.js 的 onChange 回调。
#
# 参考: https://blog.csdn.net/qq_28821897/article/details/154570263

DRAFTJS_PASTE_SCRIPT = """text => {
    // 找到 Draft.js 编辑器的可编辑区域
    const editor = document.querySelector('[data-contents="true"]') ||
                   document.querySelector('.DraftEditor-editor [contenteditable="true"]') ||
                   document.querySelector('.DraftEditor-root [contenteditable="true"]');

    if (!editor) {
        // 降级：尝试找任何 contenteditable 元素
        const fallback = document.querySelector('[contenteditable="true"]');
        if (!fallback) {
            return { success: false, error: 'Draft.js editor not found' };
        }
        // 尝试直接设置 innerText
        fallback.innerText = text;
        // 触发 input 事件
        fallback.dispatchEvent(new Event('input', { bubbles: true }));
        return { success: true, method: 'innerText' };
    }

    // 方案 A: 直接设置 innerText + 触发 input
    editor.innerText = text;
    editor.dispatchEvent(new Event('input', { bubbles: true }));

    // 方案 B: 额外触发 paste 事件（兼容 Draft.js）
    const dt = new DataTransfer();
    dt.setData('text/plain', text);
    dt.setData('text/html', text);
    const pasteEvent = new ClipboardEvent('paste', {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
    });
    editor.dispatchEvent(pasteEvent);

    return { success: true, method: 'paste' };
}
"""


# ══════════════════════════════════════════════════════════════════════
#  DouyinController
# ══════════════════════════════════════════════════════════════════════


class DouyinController:
    """抖音私信操作控制器。

    提供搜索用户、读取私信、发送私信、列举会话四个核心功能。
    所有操作通过 Playwright 控制抖音网页版完成。
    """

    def __init__(self, headless: bool = False) -> None:
        self._browser = BrowserManager(headless=headless)
        self._initialized = False

    async def initialize(self) -> str:
        """初始化浏览器并确保已登录。

        Returns:
            状态信息字符串。
        """
        if self._initialized:
            return "已经初始化"

        await self._browser.start()
        await self._browser.ensure_authenticated()
        self._initialized = True
        return "浏览器初始化完成，已登录 ✅"

    async def close(self) -> None:
        """关闭浏览器，释放资源。"""
        await self._browser.close()
        self._initialized = False

    @property
    def page(self):
        return self._browser.page

    # ── 工具函数 ────────────────────────────────────────────────────

    async def _ensure_messages_page(self) -> None:
        """确保当前在 /messages 页面。"""
        if MESSAGES_URL not in self.page.url:
            await self._browser.navigate(MESSAGES_URL)

    async def _safe_text(self, element_handle, default: str = "") -> str:
        """安全地获取元素文本内容。"""
        try:
            text = await element_handle.inner_text()
            return text.strip() or default
        except Exception:
            return default

    # ══════════════════════════════════════════════════════════════════
    #  Tool 1: search_user
    # ══════════════════════════════════════════════════════════════════

    async def search_user(self, keyword: str) -> str:
        """搜索抖音用户。

        在抖音搜索页面搜索用户，返回匹配的用户列表。

        Args:
            keyword: 搜索关键词（用户名、抖音号等）。

        Returns:
            用户列表文本（昵称、抖音号、粉丝数等）。
        """
        search_url = f"{DOUYIN_URL}/search/{keyword}"

        logger.info("搜索用户: %s", keyword)
        await self._browser.navigate(search_url)

        # 等待搜索结果渲染
        await asyncio.sleep(3)

        # 切换到"用户"标签页（如果有）
        user_tab_selectors = [
            "span:has-text('用户')",
            "div:has-text('用户')",
            "[class*='tab']:has-text('用户')",
            "a:has-text('用户')",
        ]
        for sel in user_tab_selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=3000)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    logger.info("切换到用户标签")
                    break
            except Exception:
                continue

        # 提取用户信息 — 尝试多种 DOM 结构
        results = []

        # 方法 1: 用户卡片通用选择器
        user_cards = await self._query_user_cards()

        if not user_cards:
            # 方法 2: 搜索结果的通用选择
            user_cards = await self._query_search_results()

        if not user_cards:
            return f"未找到用户「{keyword}」的搜索结果"

        for card in user_cards[:10]:  # 最多返回 10 个
            results.append(card)

        output = [f"搜索「{keyword}」的结果 ({len(results)}):\n"]
        for i, r in enumerate(results, 1):
            output.append(
                f"  {i}. {r.get('nickname', '?')} "
                f"(@{r.get('unique_id', '?')})"
            )
            if r.get("desc"):
                output.append(f"     简介: {r['desc']}")
            if r.get("followers"):
                output.append(f"     粉丝: {r['followers']}")
            output.append("")

        return "\n".join(output).strip()

    async def _query_user_cards(self) -> list[dict]:
        """从搜索页面提取用户卡片信息。"""
        results = []

        # 尝试多种卡片选择器
        card_selectors = [
            "[class*='user-card']",
            "[class*='UserCard']",
            "[class*='search-result-item']",
            "[class*='searchResultItem']",
            "li[class*='user']",
            "div[class*='user-item']",
        ]

        cards = []
        for sel in card_selectors:
            try:
                els = await self.page.query_selector_all(sel)
                if els:
                    cards = els
                    break
            except Exception:
                continue

        for card in cards:
            try:
                info = await self._extract_user_info(card)
                if info.get("nickname"):
                    results.append(info)
            except Exception:
                continue

        return results

    async def _query_search_results(self) -> list[dict]:
        """降级方案：从页面中提取所有可能的用户信息。"""
        results = []
        try:
            # 提取所有链接中的用户信息
            links = await self.page.query_selector_all("a[href*='/user/']")
            seen = set()
            for link in links[:10]:
                try:
                    href = await link.get_attribute("href") or ""
                    text = await self._safe_text(link)
                    if text and href not in seen:
                        seen.add(href)
                        sec_uid = href.split("/user/")[-1].split("?")[0]
                        results.append({
                            "nickname": text,
                            "unique_id": sec_uid[:12] + "...",
                            "sec_uid": sec_uid,
                            "desc": "",
                            "followers": "",
                        })
                except Exception:
                    continue
        except Exception:
            pass

        return results

    async def _extract_user_info(self, card) -> dict:
        """从用户卡片元素提取信息。"""
        info = {
            "nickname": "",
            "unique_id": "",
            "sec_uid": "",
            "desc": "",
            "followers": "",
        }

        # 昵称
        for sel in [
            "[class*='nickname']",
            "[class*='Nickname']",
            "[class*='name']",
            "a[href*='/user/']",
            "span",
        ]:
            try:
                el = await card.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text:
                        info["nickname"] = text
                        break
            except Exception:
                continue

        # 抖音号 (@xxx)
        for sel in [
            "[class*='unique-id']",
            "[class*='uniqueId']",
            "[class*='douyin-id']",
            "span:has-text('@')",
        ]:
            try:
                el = await card.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text:
                        info["unique_id"] = text.strip("@")
                        break
            except Exception:
                continue

        # 如果找不到 unique_id，尝试从昵称元素提取
        if not info["unique_id"] and info["nickname"]:
            # 很多卡片在昵称下方有 @xxx
            pass

        # 简介
        for sel in ["[class*='desc']", "[class*='signature']", "p"]:
            try:
                el = await card.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text and text != info["nickname"]:
                        info["desc"] = text
                        break
            except Exception:
                continue

        # 粉丝数
        for sel in [
            "[class*='follower']",
            "[class*='follow-count']",
            "span:has-text('粉丝')",
        ]:
            try:
                el = await card.query_selector(sel)
                if el:
                    info["followers"] = await self._safe_text(el)
                    break
            except Exception:
                continue

        # sec_uid
        try:
            link = await card.query_selector("a[href*='/user/']")
            if link:
                href = await link.get_attribute("href") or ""
                sec_uid = href.split("/user/")[-1].split("?")[0]
                if sec_uid:
                    info["sec_uid"] = sec_uid
        except Exception:
            pass

        return info

    # ══════════════════════════════════════════════════════════════════
    #  Tool 2: list_conversations
    # ══════════════════════════════════════════════════════════════════

    async def list_conversations(self) -> str:
        """列举当前所有的私信会话列表。

        从 /messages 页面左侧会话面板提取会话信息。

        Returns:
            会话列表文本（用户名、最后消息、未读数等）。
        """
        await self._ensure_messages_page()
        await asyncio.sleep(3)  # 等待左侧列表渲染

        conversations = await self._extract_conversations()

        if not conversations:
            return "没有找到会话（可能是没有私信历史，或页面结构变化）"

        output = [f"会话列表 ({len(conversations)}):\n"]
        for i, conv in enumerate(conversations, 1):
            unread = conv.get("unread", "")
            unread_tag = f" [未读: {unread}]" if unread else ""
            output.append(
                f"  {i}. {conv.get('nickname', '?')}{unread_tag}"
            )
            if conv.get("last_message"):
                output.append(f"     最后消息: {conv['last_message'][:80]}")
            output.append("")

        return "\n".join(output).strip()

    async def _extract_conversations(self) -> list[dict]:
        """从 /messages 页面提取会话列表。"""
        results = []

        # 尝试多个会话列表容器的选择器
        container_selectors = [
            "[class*='conversation-list']",
            "[class*='message-list']",
            "[class*='chat-list']",
            "[class*='session-list']",
            "div[class*='list']",
        ]

        container = None
        for sel in container_selectors:
            try:
                container = await self.page.query_selector(sel)
                if container:
                    break
            except Exception:
                continue

        # 会话项选择器
        item_selectors = [
            "[class*='conversation-item']",
            "[class*='message-item']",
            "[class*='chat-item']",
            "[class*='session-item']",
            "li[class*='item']",
            "div[class*='item']",
        ]

        items = []
        if container:
            for sel in item_selectors:
                try:
                    els = await container.query_selector_all(sel)
                    if els:
                        items = els
                        break
                except Exception:
                    continue
        else:
            # 降级：从整个页面找
            for sel in item_selectors:
                try:
                    els = await self.page.query_selector_all(sel)
                    if els:
                        items = els
                        break
                except Exception:
                    continue

        for item in items:
            try:
                conv = await self._extract_conversation_item(item)
                if conv.get("nickname"):
                    results.append(conv)
            except Exception:
                continue

        return results

    async def _extract_conversation_item(self, item) -> dict:
        """从单个会话项提取信息。"""
        conv = {
            "nickname": "",
            "last_message": "",
            "unread": "",
            "timestamp": "",
        }

        # 昵称
        for sel in [
            "[class*='nickname']",
            "[class*='name']",
            "[class*='title']",
            "span",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text and len(text) < 30:
                        conv["nickname"] = text
                        break
            except Exception:
                continue

        # 最后消息
        for sel in [
            "[class*='last-message']",
            "[class*='lastMessage']",
            "[class*='content']",
            "[class*='message']",
            "p",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text and text != conv["nickname"]:
                        conv["last_message"] = text
                        break
            except Exception:
                continue

        # 未读标记
        for sel in [
            "[class*='unread']",
            "[class*='badge']",
            "[class*='count']",
            "span[class*='num']",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    conv["unread"] = await self._safe_text(el)
                    break
            except Exception:
                continue

        # 时间戳
        for sel in [
            "[class*='time']",
            "[class*='timestamp']",
            "time",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    conv["timestamp"] = await self._safe_text(el)
                    break
            except Exception:
                continue

        return conv

    # ══════════════════════════════════════════════════════════════════
    #  Tool 3: read_messages
    # ══════════════════════════════════════════════════════════════════

    async def read_messages(self, contact: str, limit: int = 20) -> str:
        """读取指定联系人的私信消息。

        Args:
            contact: 联系人昵称（用于在会话列表中定位）。
            limit: 读取的最大消息条数（默认 20）。

        Returns:
            消息列表文本。
        """
        await self._ensure_messages_page()
        await asyncio.sleep(2)

        # 1. 在会话列表中点击指定联系人
        opened = await self._open_conversation(contact)
        if not opened:
            return f"未找到与「{contact}」的会话"

        # 2. 等待消息区域加载
        await asyncio.sleep(2)

        # 3. 提取消息
        messages = await self._extract_messages(limit)

        if not messages:
            return f"与「{contact}」的会话中没有找到消息"

        output = [f"与「{contact}」的私信 (最近 {len(messages)} 条):\n"]
        for msg in messages:
            sender = msg.get("sender", "?")
            text = msg.get("text", "")
            time = msg.get("time", "")
            output.append(f"  [{time}] {sender}: {text}")

        return "\n".join(output)

    async def _open_conversation(self, contact: str) -> bool:
        """在会话列表中点击指定联系人的会话。

        支持精确匹配和模糊匹配。
        """
        conversations = await self._extract_conversations()

        target = None
        for conv in conversations:
            name = conv.get("nickname", "")
            if contact == name or contact in name or name in contact:
                target = conv
                break

        if target is None:
            logger.warning("未找到联系人: %s", contact)
            return False

        # 尝试点击 — 用昵称文本定位
        nickname = target["nickname"]
        try:
            # 方法 1: 用文本定位
            link = await self.page.query_selector(f"text='{nickname}'")
            if link:
                await link.click()
                return True

            # 方法 2: 包含文本
            link = await self.page.query_selector(f"text={nickname}")
            if link:
                await link.click()
                return True

            # 方法 3: 用 XPath
            xpath = f"//*[contains(text(), '{nickname}')]"
            link = await self.page.wait_for_selector(f"xpath={xpath}", timeout=5000)
            if link:
                await link.click()
                return True

        except Exception as exc:
            logger.warning("点击联系人失败: %s", exc)

        return False

    async def _extract_messages(self, limit: int = 20) -> list[dict]:
        """从聊天区域提取消息列表。"""
        messages = []

        # 消息容器选择器
        container_selectors = [
            "[class*='message-list']",
            "[class*='chat-area']",
            "[class*='chat-content']",
            "[class*='message-area']",
        ]

        container = None
        for sel in container_selectors:
            try:
                container = await self.page.query_selector(sel)
                if container:
                    break
            except Exception:
                continue

        # 消息项选择器
        item_selectors = [
            "[class*='message-item']",
            "[class*='MessageItem']",
            "[class*='chat-message']",
            "div[class*='message']",
        ]

        items = []
        if container:
            for sel in item_selectors:
                try:
                    els = await container.query_selector_all(sel)
                    if els:
                        items = els
                        break
                except Exception:
                    continue
        else:
            # 降级：从页面找消息元素
            for sel in item_selectors:
                try:
                    els = await self.page.query_selector_all(sel)
                    if els:
                        items = els
                        break
                except Exception:
                    continue

        if not items:
            # 最后的降级：找包含 data-text 的 span
            try:
                text_spans = await self.page.query_selector_all(
                    "span[data-text='true']"
                )
                for span in text_spans[-limit:]:
                    text = await self._safe_text(span)
                    if text:
                        messages.append({
                            "sender": "对方",
                            "text": text,
                            "time": "",
                        })
                return messages[-limit:]
            except Exception:
                pass

            return messages

        for item in items[-limit:]:
            try:
                msg = await self._extract_message(item)
                if msg.get("text"):
                    messages.append(msg)
            except Exception:
                continue

        return messages[-limit:]

    async def _extract_message(self, item) -> dict:
        """从单个消息元素提取信息。"""
        msg = {
            "sender": "",
            "text": "",
            "time": "",
        }

        # 判断发送者：自己还是对方
        # 抖音中自己的消息通常在右侧，对方在左侧
        class_attr = ""
        try:
            class_attr = await item.get_attribute("class") or ""
        except Exception:
            pass

        is_self = "self" in class_attr or "mine" in class_attr or "right" in class_attr
        msg["sender"] = "我" if is_self else "对方"

        # 消息文本
        for sel in [
            "[class*='content']",
            "[class*='text']",
            "span[data-text='true']",
            "div",
            "span",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    text = await self._safe_text(el)
                    if text:
                        msg["text"] = text
                        break
            except Exception:
                continue

        # 时间戳
        for sel in [
            "[class*='time']",
            "[class*='timestamp']",
            "time",
        ]:
            try:
                el = await item.query_selector(sel)
                if el:
                    msg["time"] = await self._safe_text(el)
                    break
            except Exception:
                continue

        return msg

    # ══════════════════════════════════════════════════════════════════
    #  Tool 4: send_message
    # ══════════════════════════════════════════════════════════════════

    async def send_message(self, user_id: str, text: str) -> str:
        """向指定用户发送私信。

        流程:
          1. 打开 /messages 页面
          2. 通过联系人昵称打开会话（或通过搜索用户打开新会话）
          3. 操作 Draft.js 输入框注入文本
          4. 点击发送按钮

        Args:
            user_id: 用户昵称（用于查找会话或搜索用户）。
            text: 消息内容。

        Returns:
            发送结果描述。
        """
        await self._ensure_messages_page()
        await asyncio.sleep(2)

        # 1. 尝试在会话列表中找到该用户
        opened = await self._open_conversation(user_id)

        if not opened:
            # 2. 如果不在会话列表中，尝试搜索用户并发送私信
            logger.info("会话列表未找到 %s，尝试搜索并发送私信", user_id)
            result = await self._search_and_send(user_id, text)
            return result

        # 3. 等待聊天区域加载
        await asyncio.sleep(2)

        # 4. 在输入框中输入文本
        typed = await self._type_message(text)
        if not typed:
            return f"向「{user_id}」发送消息失败：无法操作输入框"

        # 5. 点击发送按钮
        sent = await self._click_send()
        if not sent:
            return (
                f"向「{user_id}」的消息已输入但未能自动发送（输入框内容已设置），"
                f"请手动点击发送按钮"
            )

        await asyncio.sleep(1)
        return f"✅ 已向「{user_id}」发送消息: {text[:50]}{'...' if len(text) > 50 else ''}"

    async def _search_and_send(self, user_id: str, text: str) -> str:
        """搜索用户并发送私信的降级方案。"""
        # 搜索用户
        search_result = await self.search_user(user_id)

        if "未找到" in search_result:
            return f"未找到用户「{user_id}」，无法发送消息"

        # 尝试点击第一个搜索结果的链接
        try:
            link = await self.page.query_selector("a[href*='/user/']")
            if link:
                href = await link.get_attribute("href") or ""
                await self._browser.navigate(DOUYIN_URL + href)
                await asyncio.sleep(3)

                # 在用户主页找"发私信"按钮
                send_btn_selectors = [
                    "button:has-text('发私信')",
                    "span:has-text('发私信')",
                    "[class*='send-message']",
                    "button:has-text('私信')",
                ]
                for sel in send_btn_selectors:
                    try:
                        btn = await self.page.wait_for_selector(sel, timeout=3000)
                        if btn:
                            await btn.click()
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue

                # 输入并发送
                typed = await self._type_message(text)
                if not typed:
                    return f"无法操作输入框向「{user_id}」发送消息"

                sent = await self._click_send()
                if sent:
                    await asyncio.sleep(1)
                    return f"✅ 已向「{user_id}」发送消息: {text[:50]}{'...' if len(text) > 50 else ''}"
                else:
                    return f"消息已输入但未能自动发送，请手动点击发送按钮"

        except Exception as exc:
            logger.warning("搜索并发送失败: %s", exc)

        return f"向「{user_id}」发送消息失败"

    async def _type_message(self, text: str) -> bool:
        """在 Draft.js 输入框中输入文本。

        通过 page.evaluate() 注入文本，兼容 Draft.js 编辑器。

        Args:
            text: 要输入的文本内容。

        Returns:
            True 如果输入成功。
        """
        try:
            # 先点击输入框，确保焦点
            input_selectors = [
                "[data-contents='true']",
                ".DraftEditor-editor",
                "[contenteditable='true']",
                ".DraftEditor-root",
                "div[class*='input']",
                "textarea",
            ]

            clicked = False
            for sel in input_selectors:
                try:
                    el = await self.page.wait_for_selector(sel, timeout=3000)
                    if el:
                        await el.click()
                        await asyncio.sleep(0.5)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("未找到输入框")
                return False

            # 注入文本
            result = await self.page.evaluate(DRAFTJS_PASTE_SCRIPT, text)
            logger.info("Draft.js 注入结果: %s", result)

            if isinstance(result, dict) and result.get("success"):
                await asyncio.sleep(0.5)
                return True

            # 降级方案：逐字符输入（对普通 input/textarea 有效）
            try:
                input_el = await self.page.query_selector("textarea, input[type='text']")
                if input_el:
                    await input_el.fill(text)
                    return True
            except Exception:
                pass

            return False

        except Exception as exc:
            logger.warning("输入文本失败: %s", exc)
            return False

    async def _click_send(self) -> bool:
        """点击发送按钮。"""
        send_selectors = [
            "button:has-text('发送')",
            "[class*='send-btn']",
            "[class*='sendButton']",
            "[class*='send'] button",
            "div[class*='send']",
            "button[type='submit']",
            "//button[contains(text(), '发送')]",
        ]

        for sel in send_selectors:
            try:
                if sel.startswith("//"):
                    el = await self.page.wait_for_selector(f"xpath={sel}", timeout=3000)
                else:
                    el = await self.page.wait_for_selector(sel, timeout=3000)

                if el:
                    await el.click()
                    return True
            except Exception:
                continue

        # 降级：按 Enter 发送
        try:
            await self.page.keyboard.press("Enter")
            return True
        except Exception:
            pass

        return False
