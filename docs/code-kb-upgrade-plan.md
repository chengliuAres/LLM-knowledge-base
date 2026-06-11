# 代码知识库能力升级计划 — 对标 mm-search 竞品分析

> 2026-06-11 | 基于对网易邮件大师 mm-search Skill (v1.8.1) 的完整分析

## 1. 竞品定位

| | mm-search | 我们 (email-wiki code KB) |
|---|----------|--------------------------|
| **本质** | Claude Code Skill（AI 使用说明书） | 完整知识库系统（MCP Provider + 搜索引擎 + Web UI） |
| **作者** | chenan | 柳哥 |
| **角色** | MCP Consumer — 教 AI *怎么用* 远端搜索服务 | MCP Provider — 提供搜索服务给 AI |
| **传输** | Remote MCP (Streamable HTTP) | Streamable HTTP (mcp SDK v1.12.4) |
| **部署形态** | 内网服务 + 本地 Skill 文件 | 打包机部署 + Web UI + REST API |

**关键认知**：我们是搜索能力提供方，mm-search 是搜索使用指南——两者互补而非竞争。我们能力强但缺说明书，他们说明书好但缺管理界面和自建索引能力。

---

## 2. 能力差距全景

| 能力 | mm-search | 我们 | 差距 |
|------|----------|------|------|
| 语义搜索 | ✅ search_code | ✅ code_search（三路混搜+RRF+中文→英文翻译层） | **我们更强** |
| RAG 问答 | ❌ | ✅ code_chat（LLM + 检索增强） | **我们有** |
| 调用链追踪 | ✅ callers/callees/hierarchy | ✅ callers/callees/both | 他们多 hierarchy，我们多 both |
| 文件读取 | ✅ get_file | ✅ code_file_context | 持平 |
| 跨仓库聚合 | ✅ get_code_context | ❌ | **他们没有** |
| 多 query 并行 | ✅ 2-3 组不同 query 并行 | ❌ | **我们没有** |
| Web 管理界面 | ❌ | ✅ 10 tab SPA UI | **我们有** |
| 索引自动刷新 | ❌ 依赖远端 | ✅ git_watchdog + mtime 增量 | **我们有** |
| **双模调用兜底** | ✅ MCP + Python 零依赖脚本 | ❌ 仅 MCP + REST | **我们没有** |
| **AI 使用说明书** | ✅ 650 行 SKILL.md | ⚠️ code-mcp.html（仅面向人类） | **严重不足** |
| **repo 别名映射** | ✅ MailAndroidG→mail-android | ❌ | **我们没有** |
| **失败回退链** | ✅ 7 步自动回退 | ❌ | **我们没有** |
| **反模式标注** | ✅ 大量 ❌ 教 AI 别干什么 | ❌ | **我们没有** |
| **场景识别表** | ✅ 15 场景 + 5 抽象模式 | ❌ | **我们没有** |

---

## 3. 优先级分层

```
P0（立刻做，纯增量，不动后端）  → 补齐"说明书"短板，ROI 最高
P1（本期做，少量后端改动）      → 补齐关键功能缺口
P2（下期做，需新功能开发）      → 超越竞品
```

---

## 4. P0 — 立刻执行（预计 5h）

### 4.1 `scripts/kb_api.py` — Python CLI 零依赖兜底脚本

**对标**：mm-search `scripts/mm_api.py` (300行)

**目标**：让 AI 在 MCP 不可用时，通过 `python3 scripts/kb_api.py <command>` 直接调用后端搜索服务。

**设计要点**：
- **零依赖**：`urllib.request` + `json` + `argparse`，兼容 Python 3.9+
- **Streamable HTTP 适配**：支持 `Mcp-Session-Id` header、session 自动初始化
- **SSE 兼容解析**：处理 `event: message\ndata: {...}` 格式（对标 `_parse_body()`）
- **自动发现 URL**：`KB_MCP_URL` 环境变量 > `http://localhost:8000/mcp`
- **覆盖全部 tool**：search / chat / trace / file_context / list_repos
- **30s 超时 + 友好错误**：网络不可达、超时、空结果都有明确提示

**用法示例**：
```bash
python3 scripts/kb_api.py search --query "邮件发送" --top_k 5
python3 scripts/kb_api.py chat --question "sendMail 如何工作"
python3 scripts/kb_api.py trace --symbol sendMail --direction both --depth 2
python3 scripts/kb_api.py file --repo mailflutter --path "lib/main.dart"
python3 scripts/kb_api.py repos
```

**核心实现架构**：
```python
class KBMCPClient:
    def __init__(self, url: str):
        self.url = url
        self.session_id = None
        self._rpc_id = 0

    def _parse_body(self, raw: str) -> dict:
        """解析 SSE + JSON 混合响应"""
        ...

    def initialize(self) -> dict:
        """MCP 握手：session_id 获取"""
        ...

    def call_tool(self, name: str, args: dict) -> dict:
        """JSON-RPC tools/call，自动附加 session"""
        ...

def main():
    # argparse 子命令分发
    # search / chat / trace / file / repos
    ...
```

### 4.2 `SKILL.md` — AI Agent 代码搜索使用说明书

**对标**：mm-search `SKILL.md` (650行)

**目标**：让 Claude Code / Cursor / CodeMaker 的 AI Agent 知道：
- 什么时候该用 code_search（做什么）
- 什么时候不该用（别做什么）
- 怎么组合工具效率最高（怎么做）

**核心章节设计**：

#### Section 1: 触发决策树
```
用户提问…
├─ 涉及"找代码"/"查XX在哪"/"搜索"？
│   └─ ✅ 触发 → code_search 语义发现
├─ 涉及"谁调用了XX"/"调用链"？
│   └─ ✅ 触发 → code_trace
├─ 涉及"看下XX文件"/"XX怎么实现的"？
│   └─ ✅ 触发 → code_file_context
├─ 涉及"这个代码什么意思"？
│   └─ ✅ 触发 → code_chat RAG 问答
├─ 已指定文件+行号 / 纯写代码 / 通用框架问题？
│   └─ ❌ 不触发
└─ 其他 → 不触发
```

#### Section 2: 搜索策略铁律
```
🔴 核心原则：
1. code_search 做发现（语义搜索，告诉你代码在哪）
2. grep 做深挖（在 code_search 返回的文件上精确匹配）
3. 绝不要一开始就 grep——你会漏掉中文描述对应的英文代码
   例："读信顶部引导条" grep→0，code_search→ConversationGuideBar

🔴 多 query 并行策略（和 mm-search 一模一样的理念）：
同一仓库用 2-3 组不同角度 query 并行搜：
  code_search(query="会员 member VIP subscribe", repo=xxx)
  code_search(query="CloudMember privilege 续费", repo=xxx)
  code_search(query="membership plus payment", repo=xxx)

🔴 阶段策略（先快后全）：
阶段 1（立即）：code_search 并行搜 → 展示结果
阶段 2（后台）：code_file_context + code_trace + grep 深挖 → 追加
```

#### Section 3: 工具速查
| 工具 | 用途 | 何时用 |
|------|------|--------|
| code_search | 混合搜索 (向量+关键词+符号) | 定位代码、查分布、中文描述搜索 |
| code_chat | RAG 代码问答 | 理解代码逻辑、解释实现 |
| code_trace | 调用链追踪 | 查调用关系、影响范围评估 |
| code_file_context | 文件内容读取 | 确认细节、阅读完整实现 |
| code_list_repos | 仓库列表 | 了解有哪些代码库可搜索 |

#### Section 4: 场景识别表 (10+ 场景)
| 场景 | 典型问法 | 工具链 |
|------|---------|--------|
| 代码定位 | "XX在哪" | code_search → code_file_context |
| 使用调查 | "哪里用了XX" | code_search(多query) → 汇总 |
| 调用链 | "谁调用了XX" | code_trace(direction=callers) |
| 影响评估 | "改这个影响哪" | code_trace + code_search |
| 重复检测 | "其他端有吗" | code_search 逐仓库 |
| 配置定位 | "XX配置在哪" | code_search → code_file_context |
| 理解逻辑 | "这段代码什么意思" | code_chat |
| 参考实现 | "先看看XX怎么做的" | code_search → code_file_context |
| Bug排查 | "XX端有这个bug吗" | code_search 跨仓库对比 |
| 架构理解 | "整体架构是怎样的" | code_search 多次搜 → 组合分析 |

#### Section 5: 失败回退链
```
code_search 返回空时，依次尝试：
0. 检查 repo 名是否为别名 → 换成注册名重试
1. 去掉 repo 参数（自动跨仓库搜）
2. 换 query 策略：中文→英文 / 英文→中文 / 同义词
   例："登录"→"sign in"→"authentication"→"auth"
3. 缩短 query："邮件附件下载进度条"→"附件下载"
4. grep 在关键路径做字面匹配兜底
5. 提示用户：可能需要等待索引同步
```

#### Section 6: 反模式标注
```
❌ 不要一开始就 grep：grep 只会字面匹配，漏语义相关代码
❌ 不要串行搜多次同一个 repo：2-3 组 query 并行搜
❌ 不要猜测文件路径：先用 code_search 确认
❌ 不要用中文做精确类名搜索：中文描述→code_search 语义发现
❌ 已确定文件+行号的修改：直接改，不要搜索
❌ 纯写代码不需要搜索：无"找/参考"意图不触发
❌ 通用框架问题：查官方文档，不搜索代码库
```

#### Section 7: 双模调用
```
模式 A（首选）：MCP 工具
  Claude Code: claude mcp add code-kb http://打包机:8000/mcp
  Cursor: .cursor/mcp.json 配置
  直接用 MCP tool 调用

模式 B（兜底）：Python 脚本
  python3 scripts/kb_api.py search --query "xxx"
  MCP 不可用时立即切换，不阻塞工作
```

---

## 5. P1 — 本期执行（预计 3h）

### 5.1 repo 别名映射
在 `code_mcp_v2.py` 加内置别名表，SKILL.md 中同步维护：
```python
_REPO_ALIAS_MAP = {
    "MailAndroidG": "mail-android",
    "AndroidG": "mail-android",
    "MailMaster": "mail-pc",
    "桌面端": "mail-pc",
    # ... 按项目实际仓库扩展
}
```
MCP tool 内部自动解析：`repo=_REPO_ALIAS_MAP.get(repo, repo)`。

### 5.2 code-mcp.html 补充 AI 使用视角
现有 code-mcp.html 只有人类视角（怎么配 Cursor/Claude Desktop），追加"AI Agent 怎么高效使用这些工具"说明：搜索策略、多 query 并行技巧。

---

## 6. P2 — 下期执行（预计 9h）

| 优化项 | 说明 | 投入 |
|--------|------|------|
| trace_hierarchy | tree-sitter AST 解析类继承链，code_relations 表扩字段 | 3h |
| get_code_context | 跨仓库一次性聚合返回，适合 LLM 深度分析 | 4h |
| code_chat 多段对比 | 支持传入多段代码 diff 风格对比分析 | 2h |

---

## 7. 执行顺序建议

```
Day 1: P0.1 kb_api.py 脚本（2h）
Day 1: P0.2 SKILL.md 撰写（3h）
Day 2: P1.1 repo 别名映射（1h）
Day 2: P1.2 code-mcp.html AI 视角补充（1h）
Week 2: P2 三项（9h，按需择一）
```

---

## 8. 成功标准

| 指标 | 现状 | 目标 |
|------|------|------|
| AI 能不经 MCP 配置直接用搜索 | ❌ | ✅ `python3 scripts/kb_api.py` |
| AI 知道什么时候用/不用搜索 | ❌ | ✅ SKILL.md 触发决策树 |
| AI 能自动做多 query 并行搜索 | ❌ | ✅ SKILL.md 并行策略指导 |
| AI 搜索结果为空时有回退链 | ❌ | ✅ 5 步自动回退 |
| 仓库别名自动映射 | ❌ | ✅ 内置 alias map |

---

> **来源**：2026-06-11 对标网易 mm-search Skill (chenan, v1.8.1) 的完整竞品分析
