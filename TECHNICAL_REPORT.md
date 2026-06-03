# 抖音网页版私信/聊天功能技术调研报告

## 1. 概述

目标：构建一个 Douyin MCP Server，通过浏览器自动化操作抖音网页版，实现搜索用户、收发私信、检测未读消息等功能，类似 WeChat-mcp 但面向抖音。

决定采用 **抖音网页版 (https://www.douyin.com) + Playwright 浏览器自动化** 方案，因为：
- 抖音 Mac 客户端不暴露 accessibility 元素
- 抖音网页版是唯一可编程控制的官方渠道
- 抖音聊天桌面版 (imdesktop.douyin.com) 依赖专有协议，不可自动化

---

## 2. 抖音网页版私信功能架构

### 2.1 技术架构概览

抖音网页版的私信/聊天功能由**三层**组成：

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端渲染 | React SPA | 整个 douyin.com 是单页应用，私信 UI 由 React 组件动态渲染 |
| 实时通信 | WebSocket (WSS) | `wss://frontier-im.douyin.com/ws/v2` — 基于 Protobuf 的消息协议 |
| REST API | HTTPS | `https://imapi.snssdk.com/v2/message/*` — 历史消息拉取等操作 |

### 2.2 URL 路径

| 功能 | URL | 说明 |
|------|-----|------|
| 首页 | `https://www.douyin.com` | 主站，需要登录 |
| 私信/聊天 | `https://www.douyin.com/messages` | 私信主页面（登录后可见） |
| 具体聊天 | `https://www.douyin.com/messages/{conversation_id}` | 与某人的聊天对话 |
| 用户主页 | `https://www.douyin.com/user/{sec_uid}` | 用户主页，可发私信 |
| 搜索 | `https://www.douyin.com/search/{keyword}` | 搜索用户/内容 |

> 注：私信功能**完全在 douyin.com 域内**，不需要跳转其他域名。聊天消息界面通过 React Router 在 `/messages` 路径下管理。

### 2.3 DOM 结构分析

根据对抖音网页版的研究和逆向工程资料，聊天区域的 DOM 结构大致如下：

```
<div id="root">
  <div class="app">
    <!-- 左侧导航栏 -->
    <nav class="navigation">
      <!-- 私信入口按钮（信封图标）-->
      <a href="/messages">私信</a>
    </nav>
    
    <!-- 消息页面 /messages -->
    <div class="message-page">
      <!-- 左侧：会话列表 -->
      <div class="conversation-list">
        <div class="conversation-item">          <!-- 每个会话 -->
          <img class="avatar" />                 <!-- 用户头像 -->
          <span class="nickname">用户名</span>     <!-- 用户名 -->
          <span class="last-message">最后消息</span>
          <span class="unread-badge">99+</span>   <!-- 未读标记 -->
        </div>
      </div>
      
      <!-- 右侧：聊天区域 -->
      <div class="chat-area">
        <div class="message-list">
          <div class="message-item">             <!-- 每条消息 -->
            <div class="message-content">内容</div>
            <span class="timestamp">时间</span>
          </div>
        </div>
        <!-- 输入区域 -->
        <div class="input-area">
          <div class="DraftEditor-root">         <!-- 基于 Draft.js -->
            <div class="DraftEditor-editor">
              <span data-text="true">输入文本</span>
            </div>
          </div>
          <button class="send-btn">发送</button>
        </div>
      </div>
    </div>
  </div>
</div>
```

**关键发现**：
- 聊天输入框使用 **Draft.js** (Facebook 的富文本编辑器)，不是普通 `<input>` 或 `<textarea>`
- 消息内容被 `<span data-text="true">` 包裹
- 发送需要触发 Draft.js 的内部状态更新，不能简单地设置 `value` 属性
- 未读消息通过红点/数字角标显示在会话列表项上

### 2.4 WebSocket 协议（底层通信）

抖音网页版私信使用 **WebSocket + Protobuf** 协议进行实时通信：

- **WSS 地址**: `wss://frontier-im.douyin.com/ws/v2`
- **协议**: 基于 Protobuf 的二进制帧，包含 push_frame / response 结构
- **数据格式**: 消息体通过 Protobuf 序列化，需解析 `.proto` 文件
- **消息类型 (cmd)**: 不同操作对应不同 cmd 值
  - `203` — 获取用户初始消息列表
  - `207` — 发送消息
  - 其他 cmd 用于心跳、已读回执等

**消息内容格式（JSON 字符串，包含在 Protobuf 的 content 字段内）**:

```json
{
  "text": "消息内容",
  "aweType": 700,
  "richTextInfos": [],
  "is_card": false,
  "msgHint": ""
}
```

**已有逆向成果参考**：
- `Airmole/douyin-wss` — WSS 抓包分析，包含消息结构定义
- `douyin-live` — 直播间 WebSocket + Protobuf 解析（已关闭）
- `zhonghangAlex/DySpider` — 抖音弹幕 Protobuf 解析

---

## 3. 登录方案

### 3.1 抖音网页版登录方式

抖音网页版仅支持**手机抖音 App 扫码登录**，不支持账号密码登录。

### 3.2 自动化登录流程

```
1. Playwright 打开 https://www.douyin.com
2. 检测当前登录状态（检查是否存在登录态 cookie / localStorage token）
3. 若未登录：
   a. 点击"登录"按钮 → 弹出二维码
   b. 截图二维码并通过终端展示
   c. 等待用户用手机抖音扫码
   d. 检测页面跳转（登录成功后 douyin.com 会刷新）
   e. 保存 cookie / storage state 到本地文件
4. 若已登录但 cookie 过期：
   a. 尝试刷新 cookie（抖音 cookie 有效期约 7-30 天）
   b. 失败则重新扫码
```

### 3.3 Cookie 持久化

Playwright 的 `browser_context.storage_state()` 和 `context.add_cookies()` 可用于持久化登录态：

```python
# 保存登录态
context = await browser.new_context()
# ...扫码登录...
await context.storage_state(path="douyin_auth.json")

# 恢复登录态
context = await browser.new_context(storage_state="douyin_auth.json")
```

**关注点**：
- 抖音有完善的**反爬虫/反自动化检测**机制
- 首次访问会弹出滑块验证码/图片验证
- 需要使用 Playwright 的 stealth 配置（修改 navigator.webdriver、WebGL 指纹等）
- 推荐使用 `playwright-stealth` 或 `playwright-extra` 插件

---

## 4. 功能清单与技术实现

### 4.1 核心功能

| # | 功能 | MCP 工具 | 技术实现 |
|---|------|----------|----------|
| 1 | 🔍 **搜索用户** | `search_user(keyword)` | 导航到搜索页面 `https://www.douyin.com/search/{keyword}` → 等待用户列表渲染 → 提取用户信息 |
| 2 | 📥 **读私信** | `read_messages(contact, limit)` | 点击会话 → 等待消息区域渲染 → 从 DOM 提取消息文本和元数据 |
| 3 | 📤 **发私信** | `send_message(user_id, text)` | 打开用户聊天 → 操作 Draft.js 输入框 → 注入文本 → 点击发送按钮 |
| 4 | 🔴 **检测未读** | `detect_unread()` | 导航到 `/messages` → 检查会话列表中的未读角标/红点元素 |
| 5 | 📋 **会话列表** | `list_conversations()` | 提取 `/messages` 页面左侧的所有会话项（用户名、最后消息、未读数） |

### 4.2 扩展功能（后续）

| # | 功能 | 说明 |
|---|------|------|
| 6 | 获取用户信息 | 通过用户主页提取昵称、头像、粉丝数 |
| 7 | 发送图片 | 通过文件上传 + 消息发送 |
| 8 | 消息已读回执 | 标记会话为已读 |
| 9 | 自动回复 | 基于 MCP 的工具链编排 |

### 4.3 关键技术难点

#### 难点一：Draft.js 输入框操作
抖音聊天输入框基于 Draft.js，不能直接用 `fill()` 或 `type()`。

**解决方案**（参考已有成功案例）：
```python
# 方案 A：通过 js 直接操作 Draft.js 内部状态
await page.evaluate("""
  const editor = document.querySelector('[data-contents="true"]');
  const editorState = editor.__internal_getEditorState();
  // ... 操作 Draft.js ContentState
""")

# 方案 B：通过剪贴板注入 + 触发粘贴事件
# 先用 clipboard API 写入文本，然后触发 paste 事件
await page.evaluate("""text => {
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  const pasteEvent = new ClipboardEvent('paste', {
    clipboardData: dt,
    bubbles: true
  });
  document.querySelector('.DraftEditor-editor').dispatchEvent(pasteEvent);
}""", text)

# 方案 C：直接调用封装的发送 API（如果前端暴露了）
# 通过 page.evaluate() 调用前端 XHR/fetch 发送消息
```

**推荐方案 B**：模拟剪贴板粘贴，触发 Draft.js 的 onChange 回调，兼容性最好。已验证在 CSDN 的抖音自动化文章中有效。

#### 难点二：反爬虫检测
抖音使用多种反自动化技术：
- `navigator.webdriver` 检测
- WebGL 指纹检测
- 行为轨迹分析
- Cookie 风控

**对策**：
- 使用 `playwright-stealth` 或手动修改浏览器指纹
- 控制操作间隔（模拟人类行为）
- 使用持久化 cookie 减少登录频率
- 避免固定 IP 高频请求

#### 难点三：Protobuf 消息解析
如果通过 WebSocket 接入，需要解析 Protobuf：
```python
# 需从抖音前端 JS 中提取 .proto 定义，或通过抓包反推
# 替代方案：通过 DOM 提取消息即可，不介入 WebSocket 层
```

**建议**：初期**不接入 WebSocket 层**，仅通过 DOM 操作提取消息和发送消息。WebSocket 层作为后期优化选项（用于实时消息推送）。

---

## 5. 技术栈选择

### 5.1 方案对比：Browser MCP 工具 vs Playwright Python 库

| 维度 | Playwright Python | Browser MCP 工具 |
|------|------------------|-----------------|
| **控制粒度** | 完全控制（导航、点击、输入、JS 执行） | 有限（仅支持导航、点击、输入、截图、JS 执行） |
| **离线/缓存** | 支持 storage_state 持久化 | 依赖外部浏览器会话 |
| **JS 注入** | `page.evaluate()` 完全支持 | 通过 `browser_console(expression=...)` 支持 |
| **截图/视觉** | 原生截图 + OpenCV 处理 | 内置截图 + vision 分析 |
| **网络请求** | `page.route()` 拦截请求 | 无此能力 |
| **部署** | 直接 pip install | 需先启动 MCP browser server |
| **开发灵活性** | 极高 | 中等 |
| **稳定性** | 高（Playwright 成熟项目） | 依赖 MCP host 实现 |

### 5.2 推荐方案：Playwright Python 库

**为什么选 Playwright Python 而不是 Browser MCP 工具**：

1. **Draft.js 输入需要 JS 注入** — 需要通过 `page.evaluate()` 操作 Draft.js 内部状态，Playwright Python 直接支持
2. **Login persistence** — Playwright 的 `storage_state` 直接保存/恢复 cookie 和 localStorage
3. **网络请求拦截** — 需要拦截 XHR 请求获取消息 API 响应（获取原始 JSON 数据比从 DOM 提取更可靠）
4. **反反爬配置** — 可以精细控制浏览器启动参数（`--disable-blink-features=AutomationControlled` 等）
5. **独立部署** — 作为 MCP Server 运行，不依赖外部 browser MCP 服务

### 5.3 推荐技术栈

| 组件 | 技术 | 理由 |
|------|------|------|
| 协议层 | **MCP Python SDK** (`mcp>=1.0.0`) | 与 WeChat-mcp 保持一致 |
| 浏览器自动化 | **playwright** (Python) | 最成熟的浏览器自动化库 |
| 反检测 | **playwright-stealth** / 手动配置 | 绕过抖音反爬 |
| 视觉识别 (可选) | **DashScope Qwen-VL-Plus** | 截图 OCR（降级方案，需要 API key） |
| 红点检测 (可选) | **OpenCV** (`opencv-python-headless`) | 本地化，零成本 |
| 消息解析 | **DOM 提取** (优先) / **Protobuf** (可选) | DOM 提取更稳定 |
| 红包检测 | DOM 元素属性检测 | 比 OpenCV 更可靠 |

### 5.4 项目依赖

```toml
[project]
name = "douyin-mcp-server"
version = "0.1.0"
description = "MCP Server for Douyin — let AI read and send Douyin direct messages"
requires-python = ">=3.10"

dependencies = [
    "mcp>=1.0.0",
    "playwright>=1.40.0",
    "httpx>=0.25.0",        # 用于 API 调用（Qwen-VL 等）
    "opencv-python-headless>=4.8.0",  # 可选：红点检测
    "numpy>=1.24.0",
]
```

---

## 6. 与 WeChat-mcp 架构的差异点

| 维度 | WeChat-mcp | Douyin-mcp (方案) |
|------|-----------|------------------|
| **自动化对象** | macOS WeChat 客户端 (原生应用) | 抖音网页版 (Web SPA) |
| **自动化方式** | `cua-driver` + `osascript` 快捷键 + `screencapture` | Playwright 浏览器直接控制 |
| **消息读取** | 截图 → Qwen-VL OCR | DOM 提取 (优先) / 截图 OCR (降级) |
| **消息发送** | 剪贴板 + Cmd+V + Enter 快捷键 | Draft.js JS 注入 + 点击发送按钮 |
| **登录方式** | 用户手动登录微信（持久化进程） | Playwright 扫码 + storage_state 持久化 |
| **联系人获取** | 读取 ~/.wechat_bot/ 本地数据库 | DOM 提取会话列表 / 搜索 API |
| **未读检测** | OpenCV HSV 红点检测 | DOM 元素属性检测 (.unread-badge) |
| **反检测** | 无（macOS 原生应用无需反爬） | Playwright stealth / 浏览器指纹修改 |
| **网络需求** | 无（纯本地操作） | 需要网络连接（浏览器自动化） |
| **部署** | 单机本地 | 单机本地（需安装 Chromium） |

### 6.1 架构优势（相对于 WeChat-mcp）

1. **DOM 提取比 OCR 更可靠** — 直接从 DOM 获取消息文本，准确率 100%，无需视觉 API 调用和成本
2. **浏览器自动化更可控** — Playwright 提供完整的页面控制能力
3. **无截图延迟** — DOM 操作毫秒级，无需等待截图和 OCR

### 6.2 架构劣势

1. **反爬虫挑战** — 抖音对自动化浏览器检测严格，需要持续维护反检测策略
2. **页面结构变更风险** — 抖音前端迭代频繁，DOM 选择器需要定期更新
3. **浏览器资源消耗** — 需要运行 Chromium 实例，比 WeChat-mcp 的快捷键方式重

---

## 7. 推荐项目结构

```
/Users/luoqizhang/Projects/Douyin-mcp/
├── pyproject.toml              # 项目配置
├── README.md                   # 项目说明
├── douyin_mcp/
│   ├── __init__.py
│   ├── server.py               # MCP server 入口，暴露工具
│   ├── browser.py              # Playwright 浏览器管理（启动、上下文、cookie 持久化）
│   ├── controller.py           # DouyinController — 核心操作
│   ├── login.py                # 扫码登录流程
│   ├── dom_ops.py              # DOM 操作工具（Draft.js 输入、消息提取等）
│   ├── config.py               # 配置管理
│   └── utils.py                # 工具函数
└── tests/
    └── test_controller.py
```

---

## 8. 风险与建议

### 8.1 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 抖音加强反爬检测 | 🟡 中 | stealth 配置 + 降级到截图 OCR 方案 |
| 前端 DOM 结构变更 | 🟡 中 | 使用数据属性而非 class 名做选择器 + 定期回归测试 |
| 登录态过期 | 🟢 低 | storage_state 持久化 + 过期自动提示扫码 |
| WebSocket 协议变更 | 🟢 低 | 初期不使用 WebSocket，依赖 DOM 操作 |

### 8.2 实施建议

1. **MVP 阶段** — 只做核心 4 个工具（search_user, send_message, read_messages, list_conversations），纯 DOM 操作
2. **第二阶段** — 添加未读检测 + 自动回复编排
3. **第三阶段** — 评估是否接入 WebSocket 实现实时消息推送
4. **持续维护** — 关注抖音前端更新，定期更新 DOM 选择器

---

## 9. 关键参考资料

- `Airmole/douyin-wss` — 抖音网页版私信 WSS 抓包分析 (https://github.com/Airmole/douyin-wss)
- `CSDN 抖音自动化` — 基于 Draft.js 的私信输入方案 (https://blog.csdn.net/qq_28821897/article/details/154570263)
- `WeChat-mcp` — 参考项目结构 (https://github.com/jp7454yv4f-sudo/WeChat-mcp)
- `抖音开放平台 IM 文档` (https://developer.open-douyin.com/docs/resource/zh-CN/dop/ability/interaction-management/im)
- `抖音创作者平台私信 Protobuf` (https://www.piaoyi.org/network/douyin-creator-im-protobuf.html)
- `zhonghangAlex/DySpider` — 抖音直播 Protobuf 解析 (https://github.com/zhonghangAlex/DySpider)
