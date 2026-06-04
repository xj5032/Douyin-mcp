# Douyin DM Automation: I Built an MCP Server So AI Can Manage Your TikTok-Style DMs (Not Just Download Videos)

> Every douyin-mcp project out there only does video extraction. Ours does something no one else has tackled — **private message (DM) automation**.

---

## The Problem: Douyin DMs, an Overlooked Automation Frontier

When developers think "Douyin automation," most of them think:

- Extract watermark-free videos
- Grab video captions/titles
- Batch downloads

These are the mainstream of the Douyin MCP ecosystem. Search `douyin-mcp` on GitHub, and you'll find almost exclusively video-processing tools.

But Douyin's **private message feature** — Douyin DMs — is a blue ocean for AI automation.

Why?

1. **Douyin DMs are the core customer acquisition channel** — e-commerce, short-drama promotion, KOL collaborations all happen through DMs
2. **No official API exists** — Douyin has not opened a DM management interface
3. **The web DM UI is extremely complex** — built on Draft.js, standard browser automation tools struggle to handle it

Until now, with **Douyin MCP Server**.

---

## What We Built: Douyin MCP Server

**Repository:** https://github.com/Lozzi1910/Douyin-mcp

This is a Playwright-based MCP Server that controls Douyin's web-based DM interface through browser automation, exposing standard MCP tools for AI assistants to call.

### Core Capabilities

| Feature | MCP Tool | Description |
|---------|----------|-------------|
| 🔍 Search Users | `search_user(keyword)` | Search and retrieve user info |
| 📥 Read Messages | `read_messages(contact, limit)` | DOM-level message extraction — zero cost |
| 📤 Send Messages | `send_message(user_id, text)` | Draft.js injection + auto-send |
| 📋 List Conversations | `list_conversations()` | Get all DM conversations |

### Comparison with Other douyin-mcp Projects

| Dimension | Other douyin-mcp | **Douyin MCP Server** |
|-----------|-----------------|----------------------|
| Focus | Video extraction | **DM automation** |
| Approach | API calls / scraping | Playwright browser automation |
| Read Messages | ❌ Not supported | ✅ DOM-level message extraction |
| Send Messages | ❌ Not supported | ✅ Draft.js JS injection |
| Login Method | Cookie / API Key | QR scan + storage_state persistence |
| Docker Deploy | N/A | ✅ Full Docker support |

**Bottom line: While others are downloading videos, we're helping you manage Douyin DMs.**

---

## Technical Challenges & Our Solutions

### 1. The Draft.js Input Nightmare

Douyin's chat input is built on Draft.js, which means Playwright's standard `fill()` or `type()` methods don't work.

**Solution:** Inject clipboard events via `page.evaluate()` to trigger Draft.js's onChange callback. This is currently the only reliable approach.

Core technique:

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

### 2. Anti-Detection Bypass

Douyin's anti-automation detection is stricter than most sites. We inject stealth scripts via `add_init_script()` to modify browser fingerprints:

- `navigator.webdriver` — set to `undefined`
- `navigator.plugins` — populated with normal plugin entries
- `navigator.languages` — set to Chinese user values
- Detectable `navigator.chrome` traits removed

### 3. Login Persistence

Uses Playwright's `storage_state()` to save cookies and localStorage to a local file. On subsequent launches, the session is restored automatically — no repeated QR scanning required.

---

## Use Cases

### Use Case 1: Customer Service Automation

```python
# AI auto-replies to Douyin DMs
# User sends: "Is this item still in stock?"
# AI checks inventory → auto-replies
```

Connected to an MCP Host (Claude Desktop, Cursor, Windsurf, Cline, etc.), the AI can:

- Periodically check unread DMs
- Understand message intent and auto-reply
- Handle returns, inquiries, and other common questions

### Use Case 2: KOL Partnership Management

- Automatically search for potential collaborators
- Batch-send collaboration invitation DMs
- Track reply status

### Use Case 3: DM Outreach

- Send bulk DMs to followers (please comply with platform policies)
- Collect user feedback
- Product promotion outreach

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Lozzi1910/Douyin-mcp.git
cd Douyin-mcp

# 2. Install
pip install -e .
playwright install chromium

# 3. Start
python -m douyin_mcp.server

# 4. Scan QR code with Douyin mobile app
# 5. Configure in your MCP client
```

Or deploy with Docker:

```bash
docker compose up -d
docker compose logs -f  # wait for QR code
open ./data/login_qrcode.png  # scan with your phone
```

---

## Operating Cost

Compared to other approaches, Douyin MCP Server has remarkably low operating costs:

- **Reading messages: zero cost** — extracted directly from the DOM, no API calls
- **Sending messages: zero cost** — pure browser operations
- **Only cost: server resources** — a cheap cloud server is all you need

---

## Roadmap

- [ ] Bulk messaging
- [ ] Message template system
- [ ] Auto-reply workflows
- [ ] DM analytics
- [ ] Multi-account management

---

## Final Thoughts

Douyin DM automation is a seriously underrated need. While everyone is building video downloaders, what actually helps businesses move the needle is DM management.

Douyin MCP Server is still early-stage (v0.1.0), but the core pipeline is working. If you have a need for Douyin DM automation, give it a try, open an issue, or submit a PR.

**Project:** https://github.com/Lozzi1910/Douyin-mcp

If you find it useful, a ⭐ Star would mean a lot!

---

*Built with ❤️ for the international developer community. AGPL-3.0 licensed.*
