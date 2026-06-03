# Douyin MCP Server

将抖音网页版私信/聊天功能暴露为 MCP (Model Context Protocol) 工具，让 AI 助手可以搜索用户、读取和发送抖音私信。

## 核心功能

| # | 功能 | MCP 工具 | 实现方式 |
|---|------|----------|----------|
| 1 | 🔍 搜索用户 | `search_user(keyword)` | 搜索页面 → DOM 提取用户信息 |
| 2 | 📥 读取私信 | `read_messages(contact, limit)` | DOM 提取消息文本（零成本） |
| 3 | 📤 发送私信 | `send_message(user_id, text)` | Draft.js JS 注入 + 点击发送 |
| 4 | 📋 会话列表 | `list_conversations()` | DOM 提取会话项（昵称、最后消息、未读） |

## 技术架构

```
┌─────────────────────────────────────┐
│          MCP Host (Claude 等)         │
├─────────────────────────────────────┤
│         Douyin MCP Server            │
│  ┌─────────┐  ┌───────────────────┐  │
│  │ server.py │→│  FastMCP 暴露工具  │  │
│  ├─────────┤  ├───────────────────┤  │
│  │ core.py  │→│  DouyinController   │  │
│  ├─────────┤  ├───────────────────┤  │
│  │browser.py│→│ BrowserManager     │  │
│  │          │  │ 扫码登录 + 持久化   │  │
│  └─────────┘  └───────────────────┘  │
├─────────────────────────────────────┤
│       Playwright + Chromium           │
├─────────────────────────────────────┤
│      抖音网页版 (www.douyin.com)       │
└─────────────────────────────────────┘
```

## 快速开始

### 前提条件

- Python 3.10+
- 手机抖音 App（用于扫码登录）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/jp7454yv4f-sudo/Douyin-mcp.git
cd Douyin-mcp

# 2. 安装依赖
pip install -e .

# 3. 安装 Playwright Chromium 浏览器
playwright install chromium
```

### 启动

```bash
# 方式一：直接运行（stdio 模式，适合本地 MCP Host）
python -m douyin_mcp.server

# 方式二：SSE 模式（HTTP 端口，适合远程调用）
python -m douyin_mcp.server --transport sse --port 6789

# 方式三：通过 mcp CLI
mcp run douyin_mcp/server.py --port 6789
```

---

## Docker 部署

### 首次部署

```bash
# 1. 构建镜像
docker compose build

# 2. 启动
docker compose up -d

# 3. 查看日志（等待二维码出现）
docker compose logs -f

# 4. 用手机抖音 App 扫码
#    二维码保存在 ./data/login_qrcode.png
open ./data/login_qrcode.png
```

### 连接 MCP Host

```bash
# 容器运行在 SSE 模式
# MCP Host 通过 SSE 端点连接:
#   http://localhost:6789/sse   (SSE 事件流)
#   http://localhost:6789/mcp   (MCP 消息端点)
#   http://localhost:6789/health (健康检查)

# 测试健康状态
curl http://localhost:6789/health
```

### Docker Compose 配置

```yaml
services:
  douyin-mcp:
    build: .
    container_name: douyin-mcp
    ports:
      - "6789:6789"
    volumes:
      - ./data:/root/.douyin_mcp        # 持久化登录态
      - ./logs:/var/log/douyin-mcp      # 日志
    environment:
      - TZ=Asia/Shanghai
      - DOUYIN_HEADLESS=true            # Docker 强制 headless
      - DOUYIN_TRANSPORT=sse            # SSE 传输模式
      - DOUYIN_PORT=6789                # 监听端口
    restart: unless-stopped
```

### 管理命令

```bash
# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down

# 重新构建（代码更新后）
docker compose build --no-cache && docker compose up -d
```

## 使用指南

### 首次启动

首次运行需要扫描抖音二维码登录：

1. 启动服务后，浏览器自动打开抖音登录页面
2. 终端显示二维码截图路径
3. 用手机抖音 App 扫描二维码
4. 登录成功后，登录态自动保存到 `~/.douyin_mcp/storage.json`
5. 后续启动自动恢复登录态

### 工具说明

**search_user(keyword)** — 搜索抖音用户
- 在抖音搜索页面搜索指定关键词
- 返回用户昵称、抖音号、简介、粉丝数

**list_conversations()** — 列举私信会话
- 提取 `/messages` 页面的会话列表
- 返回每个会话的昵称、最后消息、未读标记

**read_messages(contact, limit=20)** — 读取私信
- 在会话列表中定位联系人
- 从 DOM 提取消息文本和发送者信息

**send_message(user_id, text)** — 发送私信
- 在会话列表查找用户
- 通过 Draft.js JS 注入输入文本
- 点击发送按钮完成发送

## 项目结构

```
douyin-mcp-server/
├── pyproject.toml            # 项目配置
├── README.md                 # 本文件
├── TECHNICAL_REPORT.md       # 技术调研报告
├── douyin_mcp/
│   ├── __init__.py           # 包导出
│   ├── server.py             # MCP 服务器入口（FastMCP）
│   ├── core.py               # 核心操作（DouyinController）
│   └── browser.py            # 浏览器管理（扫码登录、持久化）
└── tests/
    └── test_controller.py    # 测试（TODO）
```

## 关键技术实现

### Draft.js 输入

抖音聊天输入框基于 Draft.js，不能使用标准 `fill()` 或 `type()`。
通过 `page.evaluate()` 注入 `ClipboardEvent('paste')` 事件触发 Draft.js 的 onChange 回调。

### 登录持久化

使用 Playwright 的 `storage_state()` 保存 cookie 和 localStorage 到
`~/.douyin_mcp/storage.json`，后续启动自动恢复。

### 反检测

通过 `add_init_script()` 注入 stealth 脚本，修改 `navigator.webdriver`、
`navigator.plugins`、`navigator.languages` 等浏览器指纹，绕过抖音反自动化检测。

## 对比 WeChat-mcp

| 维度 | WeChat-mcp | Douyin-mcp |
|------|-----------|------------|
| 自动化对象 | macOS 微信客户端 | 抖音网页版 (Web SPA) |
| 自动化方式 | cua-driver + osascript + screencapture | Playwright 浏览器控制 |
| 消息读取 | 截图 → Qwen-VL OCR | DOM 提取（更可靠、零成本） |
| 消息发送 | 剪贴板 + Cmd+V | Draft.js JS 注入 |
| 登录方式 | 用户手动登录微信 | Playwright 扫码 + storage_state |

## 开发

```bash
# 开发模式安装
pip install -e ".[dev]"

# 代码检查
ruff check douyin_mcp/
```

## 许可证

AGPL-3.0-only
