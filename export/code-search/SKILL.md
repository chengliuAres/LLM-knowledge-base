---
name: code-search
description: |
  email-wiki-demo 本地代码知识库搜索引擎（OC/Swift/Java/Kotlin/Dart/...）。
  找代码 / 查调用 / 参考实现 时触发。支持语义搜索（中文→英文代码）、调用链追踪、
  RAG 问答、文件读取、继承链层级（hierarchy）。

  触发词：XX在哪 / 哪里用了XX / 找一下XX / 搜XX / 查找XX /
  谁调用了XX / 调用了什么 / 看下XX怎么实现的 / XX的实现在哪 /
  对比两端 / 其他端有吗 / XX端有吗 / 全端支持吗 /
  参考一下XX / 先看看XX的实现 / 对齐XX端 / 要加XX先看现有方案 /
  改这个会影响哪里 / 删了会怎样 / crash了 / 为什么XX不工作 /
  架构是怎样的 / XX模块做什么的 / 在哪些地方用到 / XX散落在哪 /
  XX怎么配置的 / 配置在哪 / XX开关在哪 /
  已经有实现了吗 / 重复代码 / 其他地方有吗 /
  XX继承自谁 / XX有哪些子类 / XX父类是什么 /

  策略：用 2-3 个 run_in_background 的搜索并发调用，先 search 语义发现 → Read 补全。
  排除：已指定文件+行号、纯写代码不参考、通用框架问题。
version: "1.0"
author: 柳哥
changelog: "v1.0: 直连 REST API（不走 MCP），环境变量 CODE_KB_URL 配服务地址"
---

# Skill: code-search

> 🔴 **核心策略（数据驱动）**：
> ```
> 用户提问 → 触发决策（搜索定位/使用调查/影响分析/参考借鉴/追溯调查）
>          → 阶段 1 同步多 query 并行搜 → 阶段 2 后台补全文+调用链
>          → 喂 LLM 整理答案
> ```
> 翻译层把中文→英文代码标识符是核心，**绝不要一开始 grep**。

## 概述

email-wiki-demo 本地代码知识库的 AI 使用说明书。AI 通过 **REST API 客户端脚本**（`kb_rest.py`）调用后端搜索能力，覆盖 4 个核心操作：搜索、问答、调用链、仓库列表。

**调用方式**：直连后端 REST API（不走 MCP 协议），零依赖（仅 Python 3.9+ 标准库），通过环境变量 `CODE_KB_URL` 配置服务地址。

**为什么不用 MCP**：
- MCP 协议需要 `initialize` 握手 + JSON-RPC 包装，3 次 HTTP 请求才拿到结果
- 服务地址 IP 经常变，配置麻烦（`claude mcp add` 改 URL）
- 后端 REST API 已经完整支持，直接 POST 一步到位
- 任何能跑 Bash 的 AI 工具都能用

## 环境变量配置

```bash
# 写入 ~/.zshrc 或 ~/.bashrc（全局一次）
export CODE_KB_URL=http://192.168.1.100:8000
# 默认 http://localhost:8000，AI 工具运行时自动读取
```

AI 调用 `kb_rest.py` 时，脚本内部读取 `CODE_KB_URL` 决定服务地址，**无需硬编码**。

## 执行策略（先快后全）

### 阶段 1：立即展示（同步，0~3 秒）

1. 触发判断：用户问的是"找/参考/对比"还是"写"？前者触发，后者直接写
2. 工具选择：单一仓库 → search 单 query；多 query 角度 → **并发调用**（见 §2）
3. 立即展示：拿到第一波结果就整理给用户，不等全部完成

### 阶段 2：后台补充（异步，`run_in_background=true`）

- `Read` 工具读 search 命中文件的完整内容（**补全上下文**，因为 top_k=10 可能截断，且只返回 chunk 不返回整文件）
- `trace` 补充调用链信息
- grep 在命中文件上精确深挖

> ⚠️ **反直觉点**：本地有代码也要先 `search`（语义发现），再 grep（精确深挖）。
>   不能因为本地有就跳过 search——中文描述→英文代码标识符的翻译只有语义搜索能做到。

## Section 1：触发决策树

```
用户提问…
├─ 涉及"找代码"/"查XX在哪"/"搜索"？
│   └─ ✅ 触发 → search 语义发现
├─ 涉及"谁调用了XX"/"调用链"？
│   └─ ✅ 触发 → trace
├─ 涉及"看下XX文件"/"XX怎么实现的"？
│   └─ ✅ 触发 → search 定位 → Read 工具读完整文件
├─ 涉及"这个代码什么意思"？
│   └─ ✅ 触发 → chat RAG 问答
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

1. `search` 做发现（语义搜索，告诉你代码在哪）
2. `Read` 工具做完整文件读取（Claude Code 原生能力，无需 API）
3. `grep` 做深挖（在 search 返回的文件上精确匹配）
4. **绝不要一开始就 grep**——你会漏掉中文描述对应的英文代码
   例："读信顶部引导条" grep→0，search→ConversationGuideBar

### 多 query 并行（**核心**——零后端改动）

AI 一次性发出 2-3 个 `search` 调用，全部用 `run_in_background=true`。**注意**：`workdir` 需设为 skill base directory，命令需 `source scripts/.env &&` 前缀（见 Section 7 执行规则）。

```python
# ✅ 正确做法（并发）
run_in_background(true): python3 scripts/kb_rest.py search --query "会员 member VIP subscribe"
run_in_background(true): python3 scripts/kb_rest.py search --query "CloudMember privilege 续费"
run_in_background(true): python3 scripts/kb_rest.py search --query "membership plus payment"
# 三个返回后 AI 合并去重
# 总耗时 ≈ 单个查询耗时

# ❌ 错误做法（串行）
search --query "A"  # 等结果
search --query "B"  # 再等结果
search --query "C"  # 又等结果
# 总耗时 = 3 倍单查询
```

### 不传 `--repo` 参数：搜所有已索引仓库

> ⚠️ 我们当前是单仓索引（ghmail），此模式实际效果等同于"限定 ghmail"。
> 多仓索引后此模式才有意义。

```bash
# ✅ 不传 repo（搜所有已索引仓库；当前只有 ghmail）
python3 scripts/kb_rest.py search --query "邮件发送"

# ❌ 不要"伪多仓"：依次对每个 repo 串行搜
python3 scripts/kb_rest.py search --query "邮件发送" --repo ghmail
python3 scripts/kb_rest.py search --query "邮件发送" --repo other-repo  # 浪费时间
```

## Section 2.5：本地交叉验证

⚠️ `search` 命中后**必须执行**（即使本地有代码也不能跳过）：

1. `search` 返回文件路径
2. `Read` 工具拉对应文件完整内容（补全 top_k 截断 + 看完整实现）
3. grep 在本地文件上精确搜索确认
4. 把"语义召回 + 精确上下文"组合喂给 LLM 回答

**理由**：我们是自建索引不存在"过时"问题，但 top_k=10 拿到的可能是不完整的方法体。
阶段 2 必须用 `Read` 工具补全，再 grep 校准。

## Section 3：工具速查

| 工具 | 用途 | 何时用 | 返回关键字段 |
|------|------|--------|------------|
| `search` | 混合搜索（向量+关键词+符号） | 定位代码、查分布、中文描述搜索 | `results[]` 含 `file_path / symbol_name / content` |
| `chat` | RAG 代码问答 | 理解代码逻辑、解释实现 | `answer` + `sources[]` |
| `trace` | 调用链/继承链追踪 | 查调用关系、影响范围、类继承层次 | `matched_symbols[]` + `traces[].chain`；`direction=hierarchy` 返回 `parents[] / children[]` |
| `Read`（Claude Code 原生） | 文件内容读取 | 确认细节、阅读完整实现 | 完整文件内容 |
| `repos` | 仓库列表 | 了解有哪些代码库可搜索 | `repos[]` 含 `name / total_chunks` |

> ⚠️ **不再有 `file_context` 端点**：AI Agent 直接用 `Read` 工具读本地文件，无需后端 API。

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
| 代码定位 | 搜索定位 | "XX在哪" | search → Read |
| 使用调查 | 使用调查 | "哪里用了XX" | search(多query) → 汇总 |
| 调用链 | 使用调查 | "谁调用了XX" | trace(direction=callers) |
| 影响评估 | 影响分析 | "改这个影响哪" | trace + search |
| 继承链 | 参考借鉴 | "XX继承自谁" / "XX有哪些子类" | trace(direction=hierarchy) |
| 重复检测 | 搜索定位 | "其他端有吗" | search 多 query 角度（需多仓索引） |
| 配置定位 | 搜索定位 | "XX配置在哪" | search → Read |
| 理解逻辑 | 追溯调查 | "这段代码什么意思" | chat |
| 参考实现 | 参考借鉴 | "先看看XX怎么做的" | search → Read |
| Bug排查 | 追溯调查 | "XX端有这个bug吗" | search 多 query 角度（需多仓索引） |
| 架构理解 | 搜索定位 | "整体架构是怎样的" | search 多次搜 → 组合 |
| 参考借鉴 | 参考借鉴 | "要加XX先看现有方案" | search → Read |
| 追溯调查 | 追溯调查 | "老版本怎么实现的" | repos 看分支 → search |
| 配置定位 | 搜索定位 | "XX开关在哪" | search 关键词 |
| 模块对比 | 参考借鉴 | "把XX移植到YY" | search 找源 → Read 看实现 |
| 覆盖检查 | 使用调查 | "XX在哪些地方用到" | search 多 query 并行 |

## Section 4.5：失败回退链（5 步 + 1 兜底）

> search 极少返回真 0 条，更常见的是返回"假阳性"（query 中某关键词部分匹配不相关代码）。
> 判断置信度：看 `match_reason` 字段：
> - `符号匹配: X` → 高置信度，可信
> - `混合匹配` → 中等置信度，需看 file_path 确认
> - `语义相似` → 低置信度（向量召回），容易假阳性
> - `关键词匹配` → FTS5 字面匹配，看 score 判断

按顺序诊断（结果不相关时）：

1. `repos` 确认仓库在线（看仓库是否已索引）
2. 加 `--repo` 限定仓库，或去掉 `--repo` 搜所有已索引仓库
3. 缩短 query：`"邮件附件下载进度条"`→`"附件下载"`
4. 换术语（同义词链）：`"登录"`→`"sign in"`→`"auth"`→`"authentication"`
5. 提示用户：可能需要等待索引同步（首次扫描或刚 commit）

**真 0 条结果时**（极少）：按上面 1-5 走 + grep 在关键路径做字面匹配兜底。

## Section 6：反模式标注（13 条，分两类）

### 行为类反模式（AI 决策错，4 条）

```
❌ 不要一开始就 grep：grep 只会字面匹配，漏语义相关代码
   例："读信顶部引导条" grep→0，search→ConversationGuideBar

❌ 已确定文件+行号的修改：直接改，不要搜索
   例：用户说"改第 42 行" → 跳过 search
   误判反例：用户说"看下 42 行附近的逻辑" → 仍然要 Read

❌ 纯写代码不需要搜索：无"找/参考"意图不触发
   例外：如果追加了"先看看现有的"→ 立刻触发
   误判反例：用户说"实现一个 XX" → 不触发；说"参考 YY 实现一个 XX" → 触发

❌ 通用框架问题：查官方文档，不搜索代码库
   例：问"UIView 怎么用"→ 不需要；问"项目中 UIView 在哪"→ 需要
   误判反例：问"我们的项目怎么用 UIView 链式调用"→ 需要 search
```

### 技巧类反模式（参数/方法用错，9 条）

```
❌ 不要串行搜多次同一个 repo：2-3 组 query 并行搜（用 run_in_background）
   正确：run_in_background(true) × 3 并发 → 合并去重
   错误：search(A) → search(B) → search(C) 三次串行

❌ 不要猜测文件路径：先用 search 确认
   错误："肯定在 src/main.py"→ 直接 Read → 报"文件不存在"
   正确：search("入口主函数") → 拿到真实路径 → Read

❌ 不要用中文做精确类名搜索：中文描述→search 语义发现（翻译层负责中→英）
   错误：search --query "邮件"
   正确：search --query "mail send compose"  ← 翻译层把"邮件"→mail
   或：直接用英文关键词 search --query "MailBox"

❌ 调用链返回空时不要直接说"不存在"：先提示可能需要重建索引
   反例：trace --symbol "foo" 返回 [] → "代码里没有 foo"
   正例：trace --symbol "foo" 返回 [] → "未找到匹配符号，可能是：
         1) 符号名拼写问题
         2) 索引未覆盖（建议全量刷新仓库）
         3) 该符号是动态派发（class_addMethod 等）"

❌ 阶段 2 任务必须 run_in_background：不阻塞用户响应
   错误：Read → 等 2 秒 → trace → 等 2 秒 → 给用户
   正确：Read + trace 都 run_in_background → 立即给"找到了" → 后台补

❌ 对比时不仅列代码：要总结差异和共同点
   反例：贴两段代码让用户自己看
   正例："A 端用 NotificationCenter，B 端用 RxBus，共同点是都做了解耦"

❌ 多仓库结果要标 source：每条结果都标 repo+file
   反例："找到了 sendMail" → 用户不知道哪个仓
   正例："[ghmail] sendMail 位于 DevPods/GHBIZ/Classes/Exchange/Operation/EASSendMailOperation.m"

❌ 历史追溯先 repos 确认仓库：再传 --repo 参数
   错误：直接 search → 拿到的是所有仓库混合结果
   正确：repos → 确认目标仓库名 → 传 --repo 参数限定

❌ trace 搜的是方法体内部调用：不要当成多仓库搜索用
   错误：trace --symbol "EASSendMailOperation" 找 ghmail 之外的使用
   正确：search --query "EASSendMailOperation" 多仓找使用点（需多仓索引）
```

## Section 7：调用方式

> ⚠️ **执行规则**：
> 1. 所有命令**必须**通过 Bash 工具的 `workdir` 参数设置工作目录为本 skill 的 base directory
> 2. 每条命令前加 `source scripts/.env &&` 以注入 `CODE_KB_URL`（URL 存储在 `scripts/.env`）
> 3. 脚本路径 `scripts/kb_rest.py` 相对于 skill 目录，不依赖项目根

### 直连 REST API（唯一模式）

```bash
# 列出仓库
source scripts/.env && python3 scripts/kb_rest.py repos

# 混合搜索（向量+关键词+符号）
source scripts/.env && python3 scripts/kb_rest.py search --query "邮件发送" --top_k 5
source scripts/.env && python3 scripts/kb_rest.py search --query "sendMail" --repo ghmail

# 调用链追踪
source scripts/.env && python3 scripts/kb_rest.py trace --symbol sendMail --direction both --depth 2
source scripts/.env && python3 scripts/kb_rest.py trace --symbol AccountMocker --direction hierarchy

# RAG 问答
source scripts/.env && python3 scripts/kb_rest.py chat --question "sendMail 如何工作"
```

### 完整参数

```
search  --query <text>        必填，搜索关键词
         [--top_k N]          返回数量（默认 10）
         [--mode MODE]        hybrid / vector / keyword（默认 hybrid）
         [--repo REPO]        限定仓库
         [--language LANG]    限定语言（objc/swift/java/kotlin/dart/...）
         [--symbol SYM]       限定符号名（精确匹配）

chat    --question <text>     必填，问题
         [--top_k N]          检索条数（默认 5）
         [--repo REPO]        限定仓库
         [--language LANG]    限定语言

trace   --symbol <name>       必填，符号名
         [--repo REPO]        限定仓库
         [--direction DIR]    callers / callees / both / hierarchy（默认 both）
         [--depth N]          追踪深度（1-3，默认 2）

repos   （无参数）
```

### 配合 Read 工具读完整文件

```
search 返回 file_path 后：
  → Read(file_path) 直接读本地文件（Claude Code 原生）
  → 不需要再调后端 API
```

## Section 7.5：脚本错误处理

脚本出错时会向 stderr 输出 `{"error": "...", "status": N}` 格式 JSON，AI 应识别 3 类错误：

| 错误形态 | 含义 | AI 应对 |
|---------|------|--------|
| `无法连接 http://...` | 服务未起 / IP 不通 / 端口错 | 提示用户检查 `CODE_KB_URL` 环境变量 + 后端服务状态 |
| `请求超时（120s）` | chat 涉及 LLM 推理超时 | 建议缩小 `--top_k` 或稍后重试 |
| HTTP 400/500 + FastAPI detail | 业务校验失败（query 为空/符号不存在） | 把 detail 字段原样告诉用户 + 建议修正入参 |

**不要**默默吞掉错误。**不要**看到 error 就"重试 3 次"——重试连接错误无意义。

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

## Section 9：对话示例

### 示例 1：搜索定位

**用户**：「邮件发送相关的代码在哪？」

**AI**：

```bash
python3 scripts/kb_rest.py search --query "邮件发送" --top_k 3
```

**AI 整理答案**（只挑对人类友好的字段：repo + file + symbol + score）：

> 找到 1 个最相关结果（`ghmail` 仓库 iOS 项目）：
> - **`GHMailBoxSelectVC`** — `DevPods/GHComponents/Classes/Mail/GHMailBoxSelectVC.m:32-44`（score=0.84，匹配原因：符号匹配 mail）
>
> 需要看完整实现吗？我用 Read 工具读一下。

**实战要点**：
- 中英文混搜 ✅（"邮件发送" 中文经翻译层→"mail send"）
- 多关键词提权 ✅（hit_count 越多 score 越高）

### 示例 2：调用链追踪

**用户**：「谁实现了 sendMail？」

**AI**：

```bash
python3 scripts/kb_rest.py trace --symbol sendMail --direction both --depth 1
```

**AI 整理答案**：

> ghmail 仓库里 sendMail 相关实现有 5 个：
> 1. **ASSendMailRequest** — `DevPods/GHExchange/Classes/Net/ASSendMailRequest.m:37`
> 2. **EASSendMailOperation** — `DevPods/GHBIZ/Classes/Exchange/Operation/EASSendMailOperation.m:34`
> 3. **ASSendMail** — `DevPods/GHExchange/Classes/Entity/ASSendMail.h:16`
>
> 建议看 EASSendMailOperation（核心发送流程），要拉完整实现吗？

### 示例 3：失败回退

**用户**：「看下 ghmail 仓库 urs_web_login_page 的实现」

**AI**（拼错文件名的处理）：

```bash
python3 scripts/kb_rest.py search --query "urs_web_login 登录网页"
```

**AI 正确处理**（不要直接说"找不到"）：

> 没找到 `urs_web_login_page`（拼错了，应该是 `.dart`）。从搜索结果挑了最像的一个：
> `mailflutter/lib/ui/pages/login/login_page.dart`
>
> 要用 Read 工具读完整文件吗？

**关键教训**：先 search 定位 → 再 Read 完整文件，不要直接猜路径。

## Publishing

- **Source**: `https://git.mail.netease.com/.../email-wiki-demo`
- **Published version**: 1.0
- **Last published**: 2026-06-12
- **REST API endpoint**: `http://<your-host>:8000/api/code/*`
- **环境变量**: `CODE_KB_URL`（默认 `http://localhost:8000`）
- **配套脚本**: `scripts/kb_rest.py`（零依赖 CLI）
- **对应的 MCP skill**: `code-kb`（旧版，走 MCP 协议，保留兼容）

## 版本日志

- **v1.0** (2026-06-12)：初版
  - 直连 REST API，不走 MCP 协议
  - 4 个子命令：search / chat / trace / repos
  - 环境变量 `CODE_KB_URL` 配置服务地址（替代 `claude mcp add`）
  - `file_context` 不再需要端点（AI 用 Read 工具直接读本地文件）
  - 与旧 `code-kb` skill（走 MCP）并存，互不冲突
