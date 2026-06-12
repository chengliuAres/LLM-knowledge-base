---
name: code-kb
description: >-
  email-wiki-demo 本地代码知识库搜索引擎（OC/Swift/Java/Kotlin/Dart/...）。
  找代码 / 查调用 / 参考实现 时触发。支持语义搜索（中文→英文代码）、调用链追踪、
  RAG 问答、文件读取、继承链层级（hierarchy）。

  XX在哪 / 哪里用了XX / 找一下XX / 搜XX / 查找XX /
  谁调用了XX / 调用了什么 / 看下XX怎么实现的 / XX的实现在哪 /
  对比两端 / 其他端有吗 / XX端有吗 / 全端支持吗 /
  参考一下XX / 先看看XX的实现 / 对齐XX端 / 要加XX先看现有方案 /
  改这个会影响哪里 / 删了会怎样 / crash了 / 为什么XX不工作 / 定位问题 /
  架构是怎样的 / XX模块做什么的 / 在哪些地方用到 / XX散落在哪 /
  XX怎么配置的 / 配置在哪 / XX开关在哪 /
  已经有实现了吗 / 重复代码 / 其他地方有吗 /
  XX继承自谁 / XX有哪些子类 / XX父类是什么 /

  时先用 code_search 做语义发现 → 再 code_file_context 补全上下文。
  排除：已指定文件+行号、纯写代码不参考、通用框架问题("UIView 怎么用")。
version: "2.1"
metadata:
  author: 柳哥
  parallel: "用 2-3 个 run_in_background=true 的 search_code 并发调用"
  changelog: "v2.1 description 重写：能力短语放第 2 行 + 新增 4 句继承链触发句"
---

# Skill: code-kb

> 🔴 **核心策略（数据驱动）**：
> ```
> 用户提问 → 触发决策（搜索定位/使用调查/影响分析/参考借鉴/追溯调查）
>          → 阶段 1 同步多 query 并行搜 → 阶段 2 后台补全文+调用链
>          → 喂 LLM 整理答案
> ```
> 翻译层把中文→英文代码标识符是核心，**绝不要一开始 grep**。

## 概述

email-wiki-demo 本地代码知识库的 AI 使用说明书。AI 通过 MCP 工具（首选）或 Python 脚本（兜底）调用后端搜索能力，覆盖 5 个核心操作：搜索、问答、调用链、文件读取、仓库列表。

**协议要点**（实测）：
- 后端是 FastMCP `stateless_http=True` + `json_response=True`
- 响应是 `application/json`（不是 SSE stream）
- `Mcp-Session-Id` 无需持久化（stateless 不校验）

## 执行策略（先快后全）

### 阶段 1：立即展示（同步，0~3 秒）

1. 触发判断：用户问的是"找/参考/对比"还是"写"？前者触发，后者直接写
2. 工具选择：单一仓库 → code_search 单 query；多 query 角度 → **并发调用**（见 §2）
3. 立即展示：拿到第一波结果就整理给用户，不等全部完成

### 阶段 2：后台补充（异步，`run_in_background=true`）

- `code_file_context` 拉阶段 1 命中文件完整内容（**补全上下文**，因为 top_k=10 可能截断）
- `code_trace` 补充调用链信息
- grep 在命中文件上精确深挖

> ⚠️ **反直觉点**：本地有代码也要先 `code_search`（语义发现），再 grep（精确深挖）。
>   不能因为本地有就跳过 code_search——中文描述→英文代码标识符的翻译只有语义搜索能做到。

## Section 1：触发决策树

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

### 不适用场景速查

| 场景 | 原因 | 正确做法 |
|------|------|---------|
| 已指定文件+行号 | 不需要重新发现 | 直接改 |
| 纯写代码 | 无"找/参考"意图 | 直接写 |
| 通用框架问题 | 答案在文档不在代码 | 查官方文档 |
| 帮我实现新功能 | 是生成不是搜索 | 直接生成 |

## Section 2：搜索策略铁律

### 核心原则

1. `code_search` 做发现（语义搜索，告诉你代码在哪）
2. `grep` 做深挖（在 code_search 返回的文件上精确匹配）
3. **绝不要一开始就 grep**——你会漏掉中文描述对应的英文代码
   例："读信顶部引导条" grep→0，code_search→ConversationGuideBar

### 多 query 并行（**核心**——零后端改动）

AI 一次性发出 2-3 个 `search_code` MCP 调用，全部用 `run_in_background=true`：

```python
# ✅ 正确做法（并发）
run_in_background(true): code_search(query="会员 member VIP subscribe", repo=xxx)
run_in_background(true): code_search(query="CloudMember privilege 续费", repo=xxx)
run_in_background(true): code_search(query="membership plus payment", repo=xxx)
# 三个返回后 AI 合并去重
# 总耗时 ≈ 单个查询耗时

# ❌ 错误做法（串行）
code_search(query="A")  # 等结果
code_search(query="B")  # 再等结果
code_search(query="C")  # 又等结果
# 总耗时 = 3 倍单查询
```

### 不传 `repo` 参数：搜所有已索引仓库

> ⚠️ 我们当前是单仓索引（ghmail），此模式实际效果等同于"限定 ghmail"。
> 多仓索引后此模式才有意义。

```python
# ✅ 不传 repo（搜所有已索引仓库；当前只有 ghmail）
code_search(query="邮件发送")

# ❌ 不要"伪多仓"：依次对每个 repo 串行搜
code_search(query="邮件发送", repo="ghmail")
code_search(query="邮件发送", repo="other-repo")  # 浪费时间
```

## Section 2.5：本地交叉验证

⚠️ `code_search` 命中后**必须执行**（即使本地有代码也不能跳过）：

1. `code_search` 返回文件路径
2. `code_file_context` 拉对应文件完整内容（补全 top_k 截断）
3. grep 在本地文件上精确搜索确认
4. 把"语义召回 + 精确上下文"组合喂给 LLM 回答

**理由**：我们是自建索引不存在"过时"问题，但 top_k=10 拿到的可能是不完整的方法体。
阶段 2 必须用 `code_file_context` 补全，再 grep 校准。

## Section 3：工具速查

| 工具 | 用途 | 何时用 | 返回关键字段 |
|------|------|--------|------------|
| `code_search` | 混合搜索（向量+关键词+符号） | 定位代码、查分布、中文描述搜索 | `results[]` 含 `file_path / symbol_name / content` |
| `code_chat` | RAG 代码问答 | 理解代码逻辑、解释实现 | `answer` + `sources[]` |
| `code_trace` | 调用链/继承链追踪 | 查调用关系、影响范围、类继承层次 | `matched_symbols[]` + `traces[].chain`；`direction=hierarchy` 返回 `parents[] / children[]` |
| `code_file_context` | 文件内容读取 | 确认细节、阅读完整实现 | `content` (≤5000 字符) + `truncated` |
| `code_list_repos` | 仓库列表 | 了解有哪些代码库可搜索 | `repos[]` 含 `name / total_chunks` |

## Section 4：场景识别表（5 抽象模式 + 15 具体场景）

### 抽象触发模式（5 类）

| 模式 | 含义 | 典型问法 |
|------|------|---------|
| **搜索定位** | 找到代码在哪、谁实现的 | "XX在哪" / "找一下XX" / "搜XX" |
| **使用调查** | 找出 XX 在哪些地方被引用 | "哪里用了XX" / "XX散落在哪" / "在哪些地方用到" |
| **影响分析** | 改/删/重构 XX 的波及范围 | "改这个影响哪" / "删了会怎样" / "重构前先看" |
| **参考借鉴** | 看现有实现作为新功能参考 | "先看看XX怎么做的" / "XX的实现在哪" / "对齐XX端" |
| **追溯调查** | 查问题根因 / 查历史实现 | "为什么XX不工作" / "crash了" / "老版本怎么做的" |

### 场景识别表（15 场景）

| 场景 | 模式 | 典型问法 | 工具链 |
|------|------|---------|--------|
| 代码定位 | 搜索定位 | "XX在哪" | code_search → code_file_context |
| 使用调查 | 使用调查 | "哪里用了XX" | code_search(多query) → 汇总 |
| 调用链 | 使用调查 | "谁调用了XX" | code_trace(direction=callers) |
| 影响评估 | 影响分析 | "改这个影响哪" | code_trace + code_search |
| 继承链 | 参考借鉴 | "XX继承自谁" / "XX有哪些子类" | code_trace(direction=hierarchy) |
| 重复检测 | 搜索定位 | "其他端有吗" | code_search 多 query 角度（需多仓索引） |
| 配置定位 | 搜索定位 | "XX配置在哪" | code_search → code_file_context |
| 理解逻辑 | 追溯调查 | "这段代码什么意思" | code_chat |
| 参考实现 | 参考借鉴 | "先看看XX怎么做的" | code_search → code_file_context |
| Bug排查 | 追溯调查 | "XX端有这个bug吗" | code_search 多 query 角度（需多仓索引） |
| 架构理解 | 搜索定位 | "整体架构是怎样的" | code_search 多次搜 → 组合 |
| 参考借鉴 | 参考借鉴 | "要加XX先看现有方案" | code_search → code_file_context |
| 追溯调查 | 追溯调查 | "老版本怎么实现的" | code_list_repos 看分支 → code_search |
| 配置定位 | 搜索定位 | "XX开关在哪" | code_search 关键词 |
| 模块对比 | 参考借鉴 | "把XX移植到YY" | code_search 找源 → code_file_context 看实现 |
| 覆盖检查 | 使用调查 | "XX在哪些地方用到" | code_search 多 query 并行 |

## Section 4.5：结果为空 / 假阳性的诊断（5 步自助排查）

```
⚠️ 注意：code_search 极少返回真 0 条，更常见的是返回"假阳性"
（query 中某关键词部分匹配不相关代码）。
判断标准：看每条结果的 match_reason 字段：
  - "符号匹配: X (文件名+符号名匹配提权)" → 高置信度，可信
  - "混合匹配 (文件名+符号名匹配提权)" → 中等置信度，需看 file_path 确认
  - "语义相似" → 低置信度（向量召回），容易假阳性
  - "关键词匹配" → FTS5 字面匹配，看 score 判断

返回结果不相关时（按顺序诊断）：
1. code_list_repos 确认仓库在线（看仓库是否已索引）
2. 加 repo 参数限定仓库（缩小范围）
3. 缩短 query："邮件附件下载进度条"→"附件下载"
4. 尝试不同术语（同义词链）："登录"→"sign in"→"auth"→"authentication"
5. 提示用户：可能需要等待索引同步（首次扫描或刚 commit）

返回 0 条结果时（极少发生）：按上面 1-5 走，但加一步：grep 在关键路径做字面匹配兜底
```

## Section 5：失败回退链（7 步）

```
code_search 返回空时，依次尝试：
1. code_list_repos 确认仓库在线状态
2. 去掉 repo 参数（搜所有已索引仓库；当前单仓下等同于搜 ghmail）
3. 换 query 策略：中文→英文 / 英文→中文 / 同义词
   例："登录"→"sign in"→"authentication"→"auth"
4. 缩短 query："邮件附件下载进度条"→"附件下载"
5. 加 repo 参数限定（缩小范围确认问题在哪）
6. grep 在关键路径做字面匹配兜底
7. 提示用户：可能需要等待索引同步
```

## Section 6：反模式标注（13 条，分两类）

### 行为类反模式（AI 决策错，4 条）

```
❌ 不要一开始就 grep：grep 只会字面匹配，漏语义相关代码
   例："读信顶部引导条" grep→0，code_search→ConversationGuideBar

❌ 已确定文件+行号的修改：直接改，不要搜索
   例：用户说"改第 42 行" → 跳过 code_search
   误判反例：用户说"看下 42 行附近的逻辑" → 仍然要 code_file_context

❌ 纯写代码不需要搜索：无"找/参考"意图不触发
   例外：如果追加了"先看看现有的"→ 立刻触发
   误判反例：用户说"实现一个 XX" → 不触发；说"参考 YY 实现一个 XX" → 触发

❌ 通用框架问题：查官方文档，不搜索代码库
   例：问"UIView 怎么用"→ 不需要；问"项目中 UIView 在哪"→ 需要
   误判反例：问"我们的项目怎么用 UIView 链式调用"→ 需要 code_search
```

### 技巧类反模式（参数/方法用错，9 条）

```
❌ 不要串行搜多次同一个 repo：2-3 组 query 并行搜（用 run_in_background）
   正确：run_in_background(true) × 3 并发 → 合并去重
   错误：search(A) → search(B) → search(C) 三次串行

❌ 不要猜测文件路径：先用 code_search 确认
   错误："肯定在 src/main.py"→ 直接 file 命令 → 报"文件不存在"
   正确：search("入口主函数") → 拿到真实路径 → file 命令

❌ 不要用中文做精确类名搜索：中文描述→code_search 语义发现（翻译层负责中→英）
   错误：search(query="邮件")
   正确：search(query="mail send compose")  ← 翻译层把"邮件"→mail
   或：直接用英文关键词 search(query="MailBox")

❌ 调用链返回空时不要直接说"不存在"：先提示可能需要重建索引
   反例：trace(symbol="foo") 返回 [] → "代码里没有 foo"
   正例：trace(symbol="foo") 返回 [] → "未找到匹配符号，可能是：
         1) 符号名拼写问题
         2) 索引未覆盖（建议全量刷新仓库）
         3) 该符号是动态派发（class_addMethod 等）"

❌ 阶段 2 任务必须 run_in_background：不阻塞用户响应
   错误：file → 等 2 秒 → trace → 等 2 秒 → 给用户
   正确：file + trace 都 run_in_background → 立即给"找到了" → 后台补

❌ 对比时不仅列代码：要总结差异和共同点
   反例：贴两段代码让用户自己看
   正例："A 端用 NotificationCenter，B 端用 RxBus，共同点是都做了解耦"

❌ 多仓库结果要标 source：每条结果都标 repo+file
   反例："找到了 sendMail" → 用户不知道哪个仓
   正例："[ghmail] sendMail 位于 DevPods/GHBIZ/Classes/Exchange/Operation/EASSendMailOperation.m"

❌ 历史追溯先 list_repos 确认仓库：再传 repo 参数
   错误：直接 search → 拿到的是所有仓库混合结果
   正确：list_repos → 确认目标仓库名 → 传 repo 参数限定

❌ code_trace 搜的是方法体内部调用：不要当成多仓库搜索用
   错误：trace(symbol="EASSendMailOperation") 找 ghmail 之外的使用
   正确：search(query="EASSendMailOperation") 多仓找使用点（需多仓索引）
```

## Section 7：双模调用

### 模式 A：MCP 工具（首选）

```bash
# Claude Code（注意：URL 末尾带 / 与后端 Mount 路径一致）
claude mcp add code-kb http://<your-host>:8000/mcp/

# Cursor / CodeMaker / OpenCode
# 在配置文件中加（同样 URL 末尾带 /）：
# {
#   "mcpServers": {
#     "code-kb": {
#       "url": "http://<your-host>:8000/mcp/",
#       "transport": "streamable_http"
#     }
#   }
# }
```

### 模式 B：Python 脚本（兜底）

```bash
# MCP 不可用时立即切换，不阻塞工作
python3 scripts/kb_api.py search --query "XX" --top_k 5
python3 scripts/kb_api.py chat --question "XX"
python3 scripts/kb_api.py trace --symbol XX --direction callers --depth 2
python3 scripts/kb_api.py file --repo <repo-name> --path "src/main.py"
python3 scripts/kb_api.py repos
```

### MCP 不可用时的渐进降级

⚠️ **同时做两件事**：
1. **立即用模式 B** 继续搜索（不阻塞）
2. **引导用户 4 步配置 MCP**：
   - Step 1: 选择 Location（Project / User）
   - Step 2: 输入 Name（如 `code-kb`）
   - Step 3: 选择 Type（HTTP）
   - Step 4: 输入 URL（如 `http://your-host:8000/mcp/`）

## Section 8：分语言查询构造指南

### ObjC 关键词矩阵

| 业务概念 | 推荐 query 关键词 | 反例（会失败） |
|---------|------------------|---------------|
| ViewController | `viewcontroller viewcontroller uiviewcontroller` | "视图控制器" |
| 代理回调 | `delegate protocol callback` | "代理" |
| 分类扩展 | `category uiextension` | "扩展" |
| 单例 | `singleton sharedinstance` | "单例" |
| 异步 | `gcd dispatchasync dispatchqueue` | "异步" |
| 通知 | `notificationcenter nsnotification` | "通知" |
| KVO | `observevalueforkeypath addobserver` | "键值观察" |
| Block | `typedef void block` | "块" |
| NSString | `nsstring stringwithformat` | "字符串" |

### Swift 关键词矩阵

| 业务概念 | 推荐 query 关键词 | 反例（会失败） |
|---------|------------------|---------------|
| View/Modifier | `view modifier viewbuilder` | "视图修饰符" |
| 异步 | `async await task` | "异步" |
| 协议 | `protocol extension` | "协议" |
| 闭包 | `closure escaping` | "闭包" |
| 单例 | `static let shared` | "单例" |
| 组合 | `combinable sink publisher` | "响应式" |
| 状态 | `@State @Binding @ObservableObject` | "状态管理" |

### Java/Kotlin 关键词矩阵

| 业务概念 | Java | Kotlin |
|---------|------|--------|
| 列表适配器 | `adapter recycler view holder` | `adapter recyclerview viewholder` |
| 协程 | ❌ 不支持 | `coroutine suspend flow` |
| 数据绑定 | ❌ | `livedata viewmodel` |
| UI 组件 | `activity fragment dialog` | `activity fragment compose` |
| 网络 | `retrofit okhttp` | `retrofit okhttp` |
| 数据库 | `room sqlite` | `room sqlite` |
| 依赖注入 | `dagger hilt` | `hilt koin` |

**反例警示**：
- 用中文"列表适配器"搜 → 不会命中 Adapter 类（中文→英文翻译层负责）
- 用"adapter list view holder"搜 → 直接命中 Java/Kotlin Adapter 类
- iOS 项目里搜 "ListAdapter" → 命中 RecyclerView；用 "tableView dataSource" → 命中 UITableView

## Section 9：完整对话示例（真实 e2e 验证过的返回）

> 下方所有示例都用 `test/test_e2e_kb_api.py` 跑通过，返回格式是真实协议响应。
> 你应该按相同模式调用。

### 示例 1：搜索定位（中文→英文翻译层）

**用户**：「邮件发送相关的代码在哪？」

**AI**（翻译后）：

```python
code_search(query="邮件发送", top_k=3)
```

**真实返回**（top1 完整字段，`python3 kb_api.py search --query "邮件发送" --top_k 1` 实测）：

```json
{
  "results": [
    {
      "id": "ghmail_DevPods/GHComponents/Classes/Mail/GHMailBoxSelectVC.m___GHMailBoxSelectVC_0",
      "repo_name": "ghmail",
      "project_type": "ios",
      "file_path": "DevPods/GHComponents/Classes/Mail/GHMailBoxSelectVC.m",
      "file_name": "GHMailBoxSelectVC.m",
      "language": "objc",
      "chunk_type": "interface",
      "symbol_name": "GHMailBoxSelectVC",
      "line_start": 32,
      "line_end": 44,
      "hit_count": 1,
      "matched_keywords": ["mail"],
      "source": "symbol",
      "score": 0.84,
      "match_reason": "符号匹配: mail (文件名+符号名匹配提权)",
      "content": "...",
      "rrf_score": 0.062,
      "match_boost": 2.52,
      "parent_symbol_id": null
    }
  ],
  "mode": "hybrid",
  "count": 1
}
```

**AI 整理答案**（从 18 字段里挑出对人类友好的 4 个）：

> 找到 1 个最相关结果（`ghmail` 仓库 iOS 项目）：
> - **`GHMailBoxSelectVC`** — `DevPods/GHComponents/Classes/Mail/GHMailBoxSelectVC.m:32-44`（ObjC interface，score=0.84，符号匹配：mail）
>
> 需要看完整实现吗？我用 `code_file_context` 拉一下。

### 示例 2：调用链追踪

**用户**：「谁实现了 sendMail？」

**AI**：

```python
code_trace(symbol="sendMail", direction="both", depth=1)
```

**真实返回**（`matched_symbols` 完整 5 条，`python3 kb_api.py trace --symbol sendMail --direction both --depth 1` 实测）：

```json
{
  "query": "sendMail",
  "depth": 1,
  "direction": "both",
  "matched_symbols": [
    {
      "symbol": "SendMailParam",
      "file_path": "businessmail-api/src/main/java/com/netease/mail/businessmail/api/domain/param/SendMailParam.java",
      "line_start": 14,
      "chunk_type": "class",
      "match_reason": "混合匹配 (文件名+符号名匹配提权)"
    },
    {
      "symbol": "SendMailSmtp",
      "file_path": "businessmail/src/main/java/com/netease/mail/businessmail/module/mail/sendmail/SendMailSmtp.java",
      "line_start": 25,
      "chunk_type": "class",
      "match_reason": "混合匹配 (文件名+符号名匹配提权)"
    },
    {
      "symbol": "SendMailParser",
      "file_path": "businessmail/src/main/java/com/netease/mail/businessmail/protocol/eas/parser/SendMailParser.java",
      "line_start": 9,
      "chunk_type": "class",
      "match_reason": "混合匹配 (文件名+符号名匹配提权)"
    },
    {
      "symbol": "SendMailService",
      "file_path": "businessmail-api/src/main/java/com/netease/mail/businessmail/api/service/SendMailService.java",
      "line_start": 22,
      "chunk_type": "interface",
      "match_reason": "混合匹配 (文件名+符号名匹配提权)"
    },
    {
      "symbol": "AbstractSendMail",
      "file_path": "businessmail/src/main/java/com/netease/mail/businessmail/module/mail/sendmail/AbstractSendMail.java",
      "line_start": 82,
      "chunk_type": "class",
      "match_reason": "混合匹配 (文件名+符号名匹配提权)"
    }
  ],
  "traces": [/* BFS 调用链，从 SendMailParam 出发的多跳追踪 */]
}
```

**AI 整理答案**：

> ghmail 仓库里 sendMail 相关实现有 5 个（Java 端，Android 业务）：
> 1. **SendMailParam** — 发送邮件参数对象（`SendMailParam.java:14`，class）
> 2. **SendMailSmtp** — SMTP 发送实现（`SendMailSmtp.java:25`，class）
> 3. **SendMailParser** — EAS 协议解析（`SendMailParser.java:9`，class）
> 4. **SendMailService** — 发送服务接口（`SendMailService.java:22`，interface）
> 5. **AbstractSendMail** — 发送抽象基类（`AbstractSendMail.java:82`，class）
>
> 建议看 AbstractSendMail 基类（最高层抽象），要拉完整实现吗？

### 示例 3：失败回退（文件路径错误）

**用户**：「看下 ghmail 仓库 vendor/openspec 目录的代码」

**AI**（错误路径）：

```python
code_file_context(repo="ghmail", file_path="vendor/openspec")
```

**真实返回**：

```json
{"error": "文件不存在: ghmail/vendor/openspec"}
```

**AI 正确处理**（不要直接报"找不到"，要走回退链）：

> 没直接命中 `vendor/openspec` 这个路径。换两个角度试试：
>
> 1. 用搜索定位真实路径：
> ```python
> code_search(query="openspec 规范 spec")
> ```
> 2. 或者用 `code_list_repos` 看看 ghmail 仓库实际结构

### 示例 4：多关键词角度搜（单仓内，多"概念维度"覆盖）

**用户**：「找一下邮件列表相关的视图控制器」

**AI**（不传 repo，单仓内多关键词覆盖中英文）：

```python
code_search(query="MailBox 邮件列表 ViewController", top_k=3)
```

**真实返回**（`python3 kb_api.py search --query "MailBox 邮件列表" --top_k 1` 实测）：

```json
{
  "results": [
    {
      "id": "ghmail_ghmail/GHList/GHMailListViewController.h___0",
      "repo_name": "ghmail",
      "file_path": "ghmail/GHList/GHMailListViewController.h",
      "file_name": "GHMailListViewController.h",
      "language": "objc",
      "chunk_type": "file",
      "symbol_name": "GHMailListViewController.h",
      "line_start": 1,
      "line_end": 25,
      "hit_count": 2,
      "matched_keywords": ["mail", "list"],
      "source": "symbol",
      "score": 1.68,
      "match_reason": "符号匹配: mail, list (文件名+符号名匹配提权)"
    }
  ],
  "count": 1
}
```

**AI 整理答案**：

> 命中 `ghmail` 仓库的 `GHMailListViewController.h:1-25`（ObjC 头文件，score=1.68，命中关键词 mail+list）。
>
> 实战要点：
> - 中英文混搜 ✅（"MailBox 邮件列表" 3 个词混合）
> - 多关键词提权 ✅（hit_count=2，score=1.68 是单关键词的 2 倍）
> - 不传 repo 默认搜所有已索引仓库（当前只有 ghmail）

### 示例 5：继承链追踪（hierarchy，P2 新增）

**用户**：「AccountMocker 继承自哪些类？它和谁在同一层级？」

**AI**：

```python
code_trace(symbol="AccountMocker", direction="hierarchy", depth=2)
```

**真实返回**（`python3 kb_api.py trace --symbol AccountMocker --direction hierarchy --depth 2` 实测，ghmail 仓 473 个 inherit 关系）：

```json
{
  "query": "AccountMocker",
  "depth": 2,
  "direction": "hierarchy",
  "matched_symbols": [{
    "symbol": "AccountMocker",
    "file_path": "mailflutter/lib/base/mock/mock_handler_provider.dart",
    "chunk_type": "class_or_protocol",
    "match_reason": "hierarchy 起始符号"
  }],
  "traces": [{
    "entry_symbol": "AccountMocker",
    "entry_file": "mailflutter/lib/base/mock/mock_handler_provider.dart",
    "chain": {
      "nodes": [
        {"symbol": "AccountMocker", "file": "mailflutter/lib/base/mock/mock_handler_provider.dart"},
        {"symbol": "BaseMockHandler", "file": "mailflutter/lib/base/mock/mock_handler_provider.dart"},
        {"symbol": "MailTagGroupMocker", "file": "mailflutter/lib/base/mock/mock_handler_provider.dart"}
      ],
      "edges": [
        {"from": "AccountMocker", "to": "BaseMockHandler", "relation": "inherits"},
        {"from": "MailTagGroupMocker", "to": "BaseMockHandler", "relation": "inherits"}
      ]
    },
    "parents": [{"symbol": "BaseMockHandler", "via": "AccountMocker", "line": 1}],
    "children": [{"symbol": "MailTagGroupMocker", "via": "BaseMockHandler", "line": 1}]
  }]
}
```

**AI 整理答案**：

> `AccountMocker` 继承自 `BaseMockHandler`（父类，dart `class Foo extends Bar` 语法）。
> 同文件还有 1 个兄弟类 `MailTagGroupMocker` 也继承自 `BaseMockHandler`。
>
> 实战要点：
> - `direction="hierarchy"` 走 `relation_type='inherit'` 边（与 `call` 边完全独立）
> - `parents[]` 是直接父类，`children[]` 是直接子类
> - `chain.nodes/edges` 是多跳 BFS 完整图，深度 1-5
> - 覆盖 6 种语言：ObjC @interface F:P / Java/Kotlin/Swift extends : / Python class F(P) / Dart extends
> - 注意：`POST /api/code/repos/{name}/refresh` 默认 `force_full=True`（v2.0 之后），会跳过 mtime 检查重新 parse 所有 chunk（确保 inherit 关系被提取）。传 `?force_full=false` 才走真增量。

### 示例 6：兜底模式（MCP 不可用）

**场景**：MCP 配置错误，AI 调用 `code_search` 报"MCP 不可用"。

**AI 正确处理**（同时做两件事）：

```bash
# 1. 立即用模式 B 继续工作
python3 scripts/kb_api.py search --query "邮件发送" --top_k 3
```

```text
# 2. 引导用户配置 MCP（4 步）：
# Step 1: Location = User（全局生效）
# Step 2: Name = code-kb
# Step 3: Type = HTTP
# Step 4: URL = http://your-host:8000/mcp/
```

**AI 行为准则**：
- 兜底成功后**继续给答案**，不阻塞
- 顺便提醒用户修复 MCP 配置（不要让用户自己发现）

## Section 10：陷阱汇总

> 详见 Section 6（反模式 13 条分两类）。本节作为速查入口。

## Publishing

- **Source**: `https://git.mail.netease.com/.../email-wiki-demo`
- **Published version**: 2.0
- **Last published**: 2026-06-11
- **MCP endpoint**: `http://<your-host>:8000/mcp/`
- **Fallback CLI**: `python3 export/skill/scripts/kb_api.py`

## 版本日志

- **v2.0** (2026-06-11)：重写
  - Section 6 反模式：每条加"误判反例"和"正例"对照
  - Section 8 语言关键词：补全 ObjC/Swift 完整矩阵，加"反例（会失败）"列
  - Section 9 示例：5 个完整对话，全部用 e2e 真实返回格式
  - 移除 v1.0 中占位 Section 9
- **v1.0** (2026-06-11)：初版，对标 mm-code-search SKILL.md 完整结构
