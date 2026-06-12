# email-wiki-demo 代码知识库 — 一键接入

> 把 `email-wiki-demo` 代码搜索能力接到你的 AI 工具（Claude Code / Cursor / CodeMaker / OpenCode），
> **3 步搞定**，5 分钟。

## 🎯 你能得到什么

接入后，AI 工具自动获得 **5 个代码搜索能力**：

| 能力 | AI 怎么说 | 工具链 |
|------|----------|--------|
| **代码定位** | "XX 在哪？" / "找一下 XX" | `code_search` |
| **RAG 问答** | "这段代码什么意思" | `code_chat` |
| **调用链** | "谁调用了 XX" / "调用了什么" | `code_trace` |
| **文件读取** | "看下 XX 文件" | `code_file_context` |
| **仓库列表** | "有哪些代码库" | `code_list_repos` |

## 🚀 三步接入

### 步骤 1：启动 MCP Server

#### 方式 A：随 email-wiki-demo 后端启动（推荐）

```bash
cd email-wiki-demo/backend
source venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# MCP 端点：http://<your-host>:8000/mcp
```

#### 方式 B：独立启动（未来实现 — 等待 P0 实施）

```bash
cd email-wiki-demo/export/mcp
python3 start_mcp_server.py --host 0.0.0.0 --port 8000
```

> **详细安装**（Python 环境/依赖/排错）见 [`INSTALL.md`](INSTALL.md)

### 步骤 2：配置你的 AI 工具

#### Claude Code

```bash
# 加载 Skill（让 AI 知道怎么用）
cp -r skill/ ~/.claude/skills/code-kb/

# 注册 MCP Server
claude mcp add code-kb http://<your-host>:8000/mcp

# 重启 Claude Code
```

#### Cursor

```bash
# 加载 Skill
mkdir -p ~/.cursor/skills
cp -r skill/ ~/.cursor/skills/code-kb/

# 配置 MCP
mkdir -p ~/.cursor
cat > ~/.cursor/mcp.json <<EOF
{
  "mcpServers": {
    "code-kb": {
      "url": "http://<your-host>:8000/mcp",
      "transport": "streamable_http"
    }
  }
}
EOF

# 重启 Cursor
```

#### CodeMaker

```bash
# 加载 Skill
cp -r skill/ ~/.codemaker/skills/code-kb/

# 配置 MCP（参考 CodeMaker 文档）
# MCP endpoint: http://<your-host>:8000/mcp
```

#### OpenCode

```bash
# 加载 Skill
mkdir -p ~/.config/opencode/skill
cp -r skill/ ~/.config/opencode/skill/code-kb/

# 配置 MCP（参考 OpenCode 文档）
# MCP endpoint: http://<your-host>:8000/mcp
```

### 步骤 3：测试

向你的 AI 工具提问：

```
XX 在哪？
```

如果 AI 回答了相关文件路径和代码片段，说明接入成功 ✅

如果 AI 回答"找不到工具"或"MCP 不可用"：
1. 检查 MCP Server 是否在运行（`curl http://<your-host>:8000/mcp`）
2. 重新加载 Skill（重启 AI 工具）
3. 用兜底模式 B 测试（见下方"故障排查"）

## 📁 目录结构

```
export/
├── README.md              ← 你正在读的（一键接入）
├── INSTALL.md             ← 详细安装步骤（Python/依赖/排错）
├── mcp/                   ← MCP Server（给 AI 工具调用的服务端）
│   ├── code_mcp_v2.py     ← MCP Server 主体
│   ├── requirements.txt   ← 最小依赖
│   ├── start_mcp_server.py← 独立启动脚本（占位）
│   └── README.md
└── skill/                 ← AI Agent Skill（教 AI 怎么用）
    ├── SKILL.md           ← 完整使用说明书（13 章节）
    ├── README.md
    └── scripts/
        └── kb_api.py      ← Python 兜底 CLI（占位）
```

## 🔄 双模调用（自动降级）

| 模式 | 适用 | 命令 |
|------|------|------|
| **A：MCP 工具**（首选） | AI 工具已配置 MCP | AI 直接调用 `code_search` 等 |
| **B：Python 脚本**（兜底） | MCP 不可用 | `python3 scripts/kb_api.py search --query "XX"` |

AI Agent 知道自动降级（MCP 失败 → 立即用 Python 脚本继续搜索，不阻塞工作）。

## ❓ 故障排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| AI 回答"找不到工具" | Skill 未加载 | 重新执行 `cp -r skill/ ~/.claude/skills/code-kb/` |
| AI 回答"MCP 不可用" | MCP Server 未启动 | 检查后端是否在 8000 端口运行 |
| 连接超时 | 防火墙 / 网络问题 | `curl http://<host>:8000/mcp` 测试连通性 |
| AI 不主动触发 | 触发句式没命中 | 试试更直接的问法："代码在哪？"/"找一下 XX" |
| 结果为空 | 仓库未索引 | `code_list_repos` 确认仓库是否已索引 |

## 🔗 相关链接

- **升级计划**：`../docs/code-kb-upgrade-plan.md`
- **对标报告**：`../docs/调研/mm-code-search-对标报告-20260611.md`
- **主项目**：`../`（email-wiki-demo 根目录）
- **MCP Server 详细**：`./mcp/README.md`
- **Skill 详细**：`./skill/README.md`
