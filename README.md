<div align="center">
  <h1>nanobotX: Ultra-Lightweight Personal AI Assistant</h1>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

## why branch

    保持简洁,不构建复杂,类似rag记忆系统,和代码流程
    放开权限,不限制LLM发挥,让docker+vps+nanobotX自由发挥
    助理定位,专业的事情让更专业的工具来做
 
    Keep it simple, avoid building complexity, including memory systems and code flow.
    Give it free rein, don't restrict the LLM, let Docker + VPS + nanobotX self-service.
    Establish an assistant role, let the more specialized LLM handle the professional tasks.

## 开发路线图

  - [X] hook 管控 Loop
  - [X] 总结和计划 流程
  - [X] 增加tool日志
  - [X] 封装skill
  - [ ] 显现默认行为 包括skill 和提示词
  - [ ] 完善测试框架


## 其他

  欢迎fork, 暂时不会合并pr, 如果nanobot持续完善,看情况本项目会取消和封存
  

## nanobotX fork from nanobot

🐈 **nanobot** is an **ultra-lightweight** personal AI assistant inspired by [Clawdbot](https://github.com/openclaw/openclaw) 

⚡️ Delivers core agent functionality in just **~4,000** lines of code — **99% smaller** than Clawdbot's 430k+ lines.

## 📢 News

- **2026-02-25** 🚀 Major architecture updates: Hook system, rule engine, tool logging, and enhanced tools.
- **2026-02-01** 🎉 nanobot launched! Welcome to try 🐈 nanobot!

## Key Features of nanobot:

🪶 **Ultra-Lightweight**: Just ~4,000 lines of code — 99% smaller than Clawdbot - core functionality.

🔬 **Research-Ready**: Clean, readable code that's easy to understand, modify, and extend for research.

⚡️ **Lightning Fast**: Minimal footprint means faster startup, lower resource usage, and quicker iterations.

💎 **Easy-to-Use**: One-click to depoly and you're ready to go.

🔧 **Extensible Architecture**: Hook system, rule engine, and comprehensive tool logging for advanced customization.

## 🏗️ Architecture

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## 📦 Install

**Install from source** (latest features, recommended for development)

```bash
git clone git@github.com:xingdao/nanobotX.git
cd nanobot
pip install -e .
```

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.nanobot/config.json`.
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (LLM)
> You can also change the model to `minimax/minimax-m2` for lower cost.

**1. Initialize**

```bash
nanobot onboard
```

**2. Configure** (`~/.nanobot/config.json`)

```json
{
  "provider": {
    "apiKey": "sk-or-v1-xxx"
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```


**3. Chat**

```bash
nanobot agent -m "What is 2+2?"
```

That's it! You have a working AI assistant in 2 minutes.

## 💬 Chat Apps

Talk to your nanobot through Telegram or WhatsApp — anytime, anywhere.

| Channel | Setup |
|---------|-------|
| **Telegram** | Easy (just a token) |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

**2. Configure**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

> Get your user ID from `@userinfobot` on Telegram.

**3. Run**

```bash
nanobot gateway
```

</details>

## ⚙️ Configuration

Config file: `~/.nanobot/config.json`

### Providers

Provider by liteLLM, conifg like  https://www.litellm.ai/


<details>
<summary><b>Full config example</b></summary>

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "provider": {
    "apiKey": "sk-or-v1-xxx"
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC...",
      "allowFrom": ["123456789"]
    },
    "whatsapp": {
      "enabled": false
    }
  }
}
```

</details>

## CLI Reference

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config & workspace |
| `nanobot agent -m "..."` | Chat with the agent |
| `nanobot agent` | Interactive chat mode |
| `nanobot gateway` | Start the gateway |
| `nanobot status` | Show status |
| `nanobot channels status` | Show channel status |

<details>
<summary><b>Scheduled Tasks (Cron)</b></summary>

```bash
# Add a job
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# List jobs
nanobot cron list

# Remove a job
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> The `-v ~/.nanobot:/root/.nanobot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.

Build and run nanobot in a container:

```bash
# Build the image
docker build -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Edit config on host to add API keys
vim ~/.nanobot/config.json

# Run gateway (connects to Telegram/WhatsApp)
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

## 📁 Project Structure

```
nanobot/
├── agent/          # 🧠 Core agent logic
│   ├── loop.py     #    Agent loop (LLM ↔ tool execution)
│   ├── context.py  #    Prompt builder
│   ├── hooks.py    #    Lifecycle hook system
│   ├── rules.py    #    Rule engine for agent behavior
│   ├── memory.py   #    Persistent memory
│   ├── skills.py   #    Skills loader
│   ├── subagent.py #    Background task execution
│   └── tools/      #    Built-in tools (logger, skill, cron, etc.)
├── skills/         # 🎯 Bundled skills (github, weather, tmux...)
├── channels/       # 📱 WhatsApp integration
├── bus/            # 🚌 Message routing
├── cron/           # ⏰ Scheduled tasks
├── heartbeat/      # 💓 Proactive wake-up
├── providers/      # 🤖 LLM providers (OpenRouter, etc.)
├── session/        # 💬 Conversation sessions
├── config/         # ⚙️ Configuration
└── cli/            # 🖥️ Commands
```

## 🤝 Contribute & Roadmap


- [-] **Multi-modal** — See and hear (images, voice, video)
- [-] **Long-term memory** — Never forget important context
- [x] **Better reasoning** — Multi-step planning and reflection
- [-] ~~More integrations — Discord, Slack, email, calendar~~ 
- [x] **Self-improvement** — Learn from feedback and mistakes

<p align="center">
  <em> All Thanks for nanobot!</em><br><br>
</p>


<p align="center">
  <sub>nanobot is for educational, research, and technical exchange purposes only</sub>
</p>
