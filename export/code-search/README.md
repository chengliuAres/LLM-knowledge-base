# code-search Skill (REST API 直连版)

> email-wiki-demo 本地代码知识库的 AI Skill — **直连 REST API，不依赖 MCP 协议**

## 这是什么

给 AI Agent 用的"操作手册"。AI 读完 SKILL.md 后会知道：
- 什么时候该搜代码（触发条件 + 决策树）
- 怎么搜（`kb_rest.py` 的 4 个子命令）
- 搜错了怎么回退（5 步回退链）
- 常见错误（13 条反模式）

## 目录结构

```
export/code-search/
├── SKILL.md                # AI Agent 完整使用手册
├── README.md               # 本文件（人类阅读）
└── scripts/
    └── kb_rest.py          # 零依赖 Python CLI（直连 REST API）
```

## 环境变量

```bash
# 写入 ~/.zshrc 或 ~/.bashrc（全局一次）
export CODE_KB_URL=http://192.168.1.100:8000
# 默认 http://localhost:8000
```

## 安装

```bash
# Claude Code
cp -r export/code-search ~/.claude/skills/code-search/

# 或项目级
cp -r export/code-search .claude/skills/code-search/
```

## 用法

详见 `SKILL.md`。最常用的几条命令：

```bash
python3 scripts/kb_rest.py repos
python3 scripts/kb_rest.py search --query "邮件发送" --top_k 5
python3 scripts/kb_rest.py trace --symbol sendMail --direction both --depth 2
python3 scripts/kb_rest.py chat --question "sendMail 如何工作"
```

## 与旧 `code-kb` (MCP 版) 的关系

旧 `export/skill/code-kb/` 走 MCP 协议（需 `claude mcp add`），本 skill 走 REST API（仅需 Bash 执行 + 环境变量）。两个 skill 并存互不影响，按 AI 工具能力选其一。
