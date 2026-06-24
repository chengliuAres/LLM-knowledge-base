# code-search

AI Agent 用本地代码知识库 skill — **直连 REST API，不走 MCP**。

## 这是什么

给 AI Agent 的"操作手册"。AI 读完 SKILL.md 后会知道：什么时候该搜代码、怎么搜、搜错了怎么回退、13 条常见反模式。

## 目录结构

```
export/code-search/
├── SKILL.md                # AI Agent 操作手册（472 行）
├── README.md               # 本文件
└── scripts/
    └── kb_rest.py          # 零依赖 Python CLI（4 个子命令）
```

## 安装

```bash
# 全局（推荐）
cp -r export/code-search ~/.claude/skills/code-search/

# 项目级
cp -r export/code-search .claude/skills/code-search/
```

## 环境变量

```bash
# 写入 ~/.zshrc 或 ~/.bashrc
export CODE_KB_URL=http://your-host:8000   # 默认 http://localhost:8000
```

## 调用

AI 读完后会用这 4 个子命令：

```bash
python3 scripts/kb_rest.py repos
python3 scripts/kb_rest.py search --query "邮件发送" --top_k 5
python3 scripts/kb_rest.py trace --symbol sendMail --direction both --depth 2
python3 scripts/kb_rest.py chat --question "sendMail 如何工作"
```

读完整文件用 Claude Code 原生 `Read` 工具（search 返回 file_path 后）。

## 配套

旧 `export/skill/code-kb/`（走 MCP 协议）仍保留，两套并存互不影响。
