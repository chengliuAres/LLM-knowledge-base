# code-search Skill (REST API 直连版)

> email-wiki-demo 本地代码知识库的 AI 使用说明书 — **直连 REST API，不依赖 MCP 协议**

## 目录结构

```
export/skill-rest/
├── SKILL.md                # AI Agent 完整使用手册（YAML frontmatter + 10 个 Section）
├── README.md               # 本文件
└── scripts/
    └── kb_rest.py          # 零依赖 Python CLI（直连 REST API）
```

## 与旧 `code-kb` (MCP 版) 的区别

| 维度 | code-kb（旧） | code-search（本） |
|------|---------------|-------------------|
| 调用协议 | MCP（JSON-RPC 2.0） | REST API（标准 HTTP POST/GET） |
| HTTP 请求数 | 3 次（initialize + tools/list + tools/call） | 1 次 |
| 脚本复杂度 | kb_api.py 257 行 | kb_rest.py ~280 行（含完整打印） |
| 服务地址配置 | `claude mcp add <name> <url>` | 环境变量 `CODE_KB_URL` |
| file_context | MCP 工具调 HTTP | AI 用 Read 工具读本地文件 |
| 协议依赖 | 需 AI 工具支持 MCP | 仅需 Bash 执行能力 |

**两个 skill 并存互不影响**，可按 AI 工具能力选其一。

## 环境变量

```bash
# 写入 ~/.zshrc 或 ~/.bashrc（全局一次）
export CODE_KB_URL=http://192.168.1.100:8000
# 默认 http://localhost:8000
```

## 安装

```bash
# Claude Code
cp -r export/skill-rest ~/.claude/skills/code-search/

# 或项目级
cp -r export/skill-rest .claude/skills/code-search/
```

## 用法

详见 `SKILL.md`。最常用的几条命令：

```bash
python3 scripts/kb_rest.py repos
python3 scripts/kb_rest.py search --query "邮件发送" --top_k 5
python3 scripts/kb_rest.py trace --symbol sendMail --direction both --depth 2
python3 scripts/kb_rest.py chat --question "sendMail 如何工作"
```
