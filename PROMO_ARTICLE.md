# 抖音私信自动化：我用 MCP 让 AI 帮你管理抖音 DM（不只是下载视频）

> 市面上已有的 douyin-mcp 项目都只做视频提取，而我们的方案能做的是——**私信自动化**。

---

## 痛点：抖音私信，一个被忽略的自动化蓝海

提到「抖音自动化」，大多数开发者想到的是：

- 提取无水印视频
- 获取视频文案/标题
- 批量下载

这些确实是抖音 MCP 生态的主流。在 GitHub 上搜索 `douyin-mcp`，几乎清一色都是视频处理工具。

但抖音的**私信功能**——也就是抖音 DM——却是 AI 自动化的一片蓝海。

为什么？

1. **抖音 DM 是企业获客的核心渠道**——大量电商、短剧推广、KOL 合作都是通过私信完成
2. **没有现成的 API**——抖音没有开放私信管理接口
3. **Web 端私信 UI 极其复杂**——基于 Draft.js 编辑器，标准浏览器自动化工具难以处理

直到现在我们做了 **Douyin MCP Server**，情况才改变。

---

## 我们做了什么：Douyin MCP Server

项目地址：https://github.com/Lozzi1910/Douyin-mcp

这是一个基于 Playwright 的 MCP Server，通过浏览器自动化操控抖音网页版私信功能，暴露为标准 MCP 工具给 AI 助手调用。

### 核心能力

| 功能 | MCP 工具 | 说明 |
|------|----------|------|
| 🔍 搜索用户 | `search_user(keyword)` | 搜索并获取用户信息 |
| 📥 读取私信 | `read_messages(contact, limit)` | DOM 提取消息，零成本 |
| 📤 发送私信 | `send_message(user_id, text)` | Draft.js 注入 + 自动发送 |
| 📋 会话列表 | `list_conversations()` | 获取所有私信会话 |

### 与其他 douyin-mcp 的对比

| 维度 | 其他 douyin-mcp | **Douyin MCP Server** |
|------|----------------|----------------------|
| 聚焦领域 | 视频提取 | **私信自动化** |
| 技术路线 | API 调用/接口爬虫 | Playwright 浏览器自动化 |
| 消息读取 | ❌ 不涉及 | ✅ DOM 级消息提取 |
| 消息发送 | ❌ 不涉及 | ✅ Draft.js JS 注入 |
| 登录方式 | Cookie/API Key | 扫码 + storage_state 持久化 |
| Docker 部署 | N/A | ✅ 完整 Docker 支持 |

**一句话总结：当别人在下载视频的时候，我们在帮你管理抖音私信。**

---

## 技术难点 & 我们的解法

### 1. Draft.js 输入框

抖音聊天框基于 Draft.js，不能使用 Playwright 标准的 `fill()` 或 `type()`。

**解法：** 通过 `page.evaluate()` 注入剪切板事件 `ClipboardEvent('paste')`，触发 Draft.js 的 onChange 回调。这是目前唯一可靠的方案。

核心代码片段：

```python
await page.evaluate(f"""
  navigator.clipboard.writeText({json.dumps(text)}).then(() => {{
    const input = document.querySelector('[data-block-id]');
    if (input) {{
      input.focus();
      const pasteEvent = new ClipboardEvent('paste', {{
        clipboardData: new DataTransfer(),
        bubbles: true,
        cancelable: true,
      }});
      // 手动设置 clipboardData
      Object.defineProperty(pasteEvent, 'clipboardData', {{
        value: (() => {{
          const dt = new DataTransfer();
          dt.setData('text/plain', {json.dumps(text)});
          return dt;
        }})(),
      }});
      input.dispatchEvent(pasteEvent);
    }}
  }});
""")
```

### 2. 反检测机制

抖音的反自动化检测比一般网站严格。我们通过 `add_init_script()` 注入 stealth 脚本，修改以下浏览器指纹：

- `navigator.webdriver` — 设为 `undefined`
- `navigator.plugins` — 填充正常插件列表
- `navigator.languages` — 设为中国用户正常值
- 移除 `navigator.chrome` 的可检测特征

### 3. 登录持久化

使用 Playwright 的 `storage_state()` 保存 cookie 和 localStorage 到本地文件，后续启动自动恢复，无需反复扫码。

---

## 应用场景

### 场景一：客服自动化

```python
# AI 自动回复抖音私信
# 用户发来 "这件衣服还有货吗？"
# AI 搜索库存 → 自动回复
```

接入 MCP Host（Claude Desktop / Cursor / Windsurf）后，AI 可以：

- 定时检查未读私信
- 理解消息意图并自动回复
- 处理退货、咨询等常见问题

### 场景二：KOL 合作管理

- 自动搜索潜在合作达人
- 批量发送合作邀约私信
- 跟踪回复状态

### 场景三：私信营销

- 给粉丝群发私信（注意合规）
- 收集用户反馈
- 产品推广触达

---

## 快速上手

```bash
# 1. 克隆
git clone https://github.com/Lozzi1910/Douyin-mcp.git
cd Douyin-mcp

# 2. 安装
pip install -e .
playwright install chromium

# 3. 启动
python -m douyin_mcp.server

# 4. 手机抖音扫码登录
# 5. 配置到你的 MCP 客户端
```

也支持 Docker 一键部署：

```bash
docker compose up -d
docker compose logs -f  # 等待二维码
open ./data/login_qrcode.png  # 扫码
```

---

## 运营成本

相比其他方案，Douyin MCP Server 的运营成本极低：

- **消息读取：零成本** — 直接从 DOM 提取，无 API 调用
- **消息发送：零成本** — 纯浏览器操作
- **唯一成本：服务器资源** — 最便宜的云服务器即可运行

---

## 未来规划

- [ ] 群发消息功能
- [ ] 消息模板系统
- [ ] 自动回复工作流
- [ ] 私信数据分析
- [ ] 多账号管理

---

## 写在最后

抖音私信自动化是一个被低估的需求。当大家都在做视频下载的时候，真正能帮企业提升效率的恰恰是私信管理。

Douyin MCP Server 目前还是早期版本（v0.1.0），但已经实现了核心链路。如果你有抖音私信自动化的需求，欢迎试用、提 Issue 或 PR。

**项目地址：** https://github.com/Lozzi1910/Douyin-mcp

如果项目对你有帮助，欢迎 ⭐ Star 支持！

---

*本文由 AI 辅助撰写，项目作者 Lozzi 出品。*
