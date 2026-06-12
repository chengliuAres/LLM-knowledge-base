# mm-code-search 完整对标验证报告

> 调研日期：2026-06-11
> 调研对象：`https://git.mail.netease.com/awesome-mm-skills/mm-code-search` @ v1.8.1
> 对标基线：`docs/code-kb-upgrade-plan.md`（柳哥 2026-06-11 撰写）
> 调研方式：subagent 全量克隆 + 全文通读（744 行 .py+.md + 91 行 setup.sh）

## 0. 命名说明

升级计划把这个竞品称为 "mm-search"，实际仓库名是 **"mm-code-search"**，**是同一个项目的不同叫法**，本报告统一用 "mm-code-search"。

---

## 1. 仓库概览

| 项 | 值 |
|---|---|
| 仓库地址 | `https://git.mail.netease.com/awesome-mm-skills/mm-code-search.git` |
| 当前 HEAD | `8442e80` release: v1.8.1 |
| 最后发布 | 2026-06-10 20:13:03 +0800 |
| 总提交数 | 34 commits（单一作者 `陈安 <chenan02@corp.netease.com>`） |
| 当前版本 | v1.8.1（v1.3 引入双模调用，v1.4 引入决策树，v1.5 引入 repo 映射，v1.6 引入两阶段策略，v1.7 修 SSE 解析，v1.8 鸿蒙子模块拆分） |
| 远程 MCP URL | `http://10.244.120.140:8888/mcp`（README:20, setup.sh:14） |

### 目录结构

```
mm-code-search/
├── .gitignore
├── INSTALL.md           (37 行)  安装说明
├── README.md            (58 行)  项目介绍 + 双模式调用
├── SKILL.md             (649 行) 核心交付物
├── setup.sh             (91 行)  安装/更新脚本（SSOT：`/tmp/mm-code-search`）
└── scripts/
    └── mm_api.py        (299 行) 零依赖 Python 兜底 CLI
```

**总共 7 个文件**，744 行 .py + .md（不含 setup.sh）。

### 关键统计

| 项 | 数值 | 位置 |
|---|---:|---|
| SKILL.md 二级章节 | 15 | grep `^## ` |
| SKILL.md 三级章节 | 40+ | grep `^### ` |
| ❌ 反模式标记 | 13 处 | 散落在"陷阱"和正文中 |
| ⚠️ 警告标记 | 10 处 | 仓库映射/分支回退/grep 等 |
| 🔴 铁律标记 | 5 处 | mm-search 优先/并行策略/搜索策略等 |
| 抽象触发模式 | 5 类 | SKILL.md:135-145 |
| 场景识别表 | 15 项 | SKILL.md:149-165 |
| 失败回退链步骤 | 8 步 | SKILL.md:419-436 |
| MCP 工具 | 7 个 | search_code / get_file / list_repos / get_code_context / trace_callees / trace_callers / trace_hierarchy |
| 索引仓库 | 7 个 | mail-android、mail-flutter、ghmail、mail-pc、harmonyos-native、harmonyos-rn、harmonyos-cpp |

---

## 2. 14 项能力差距逐条验证表

| # | 能力 | 升级计划结论 | 验证结果 | 证据（文件:行号） | 备注 |
|---|------|------------|---------|------------------|------|
| 1 | 语义搜索 | 我们更强 | **基本确认** | mm-search 走 BGE 双语 + 关键词策略（SKILL.md:267-272），无 RRF/翻译层 | 我们 query_translator.py 走四路混搜+翻译层，**确实更强** |
| 2 | RAG 问答 | 我们有 | **完全确认** | SKILL.md 全文 0 处 "rag"/"问答"/"chat"；mm_api.py 7 个 tool 无 chat | mm-search **没有**任何 RAG 能力 |
| 3 | 调用链追踪 | 互换优劣势 | **确认，可细化** | mm-search: trace_callees/trace_callers/trace_hierarchy（mm_api.py:196-209）。我们: code_trace 支持 callers/callees/both + depth（code_mcp.py:120-125） | mm-search 多 hierarchy，我们多 both + depth |
| 4 | 文件读取 | 持平 | **基本确认** | mm-search: get_file(repo, branch, path)。我们: code_file_context(repo, file_path, line_start?, line_end?) | mm-search 必传 branch，我们不需要；我们支持按行号 |
| 5 | 跨仓库聚合 | 他们有 | **柳哥决定不做** | mm-search: get_code_context(query, repo?, branch?, n_results?) | 单仓场景不需要，**P2 删 get_code_context 和 repo 别名映射** |
| 6 | 多 query 并行 | 我们没 | **走 SKILL.md 路线** | mm-search 后端无并行（mm_api.py 一次只 call 一个 tool），并行是 **SKILL.md 第 3 步明文教 AI 的**（SKILL.md:63-68, 78-92） | 柳哥决定走 B 路线：**零后端改动，SKILL.md 教 AI `run_in_background=true` 并发调用**（mm-code-search 同款做法） |
| 7 | Web UI | 我们有 | **完全确认** | mm-search 全文 0 处 "web ui"/"dashboard"/"前端" | mm-search 是纯 CLI/MCP 接口 |
| 8 | 索引自动刷新 | 我们有 | **完全确认** | mm-search 全文 0 处 "auto refresh"/"watchdog"/"mtime"；SKILL.md:317 只提"调用链信息需要重建索引后才生效（`--reindex`）" | mm-search 索引**人工触发**重建 |
| 9 | 双模调用兜底 | 我们没 | **完全确认** | mm-search: 模式 A MCP + 模式 B python3 scripts/mm_api.py（README:12-32, SKILL.md:178-225, setup.sh） | 升级计划 P0.1 已规划 kb_api.py |
| 10 | AI 使用说明书 | 我们严重不足 | **完全确认，差距比预想更大** | mm-search SKILL.md 649 行，15 二级 + 40+ 三级章节 | 我们 code-mcp.html 是面向人类的，不是面向 AI 的 |
| 11 | repo 别名映射 | 我们没 | **完全确认** | mm-search: 别名映射 3 处强调——SKILL.md:103-107 / 241-251 / 424-427 | 7 个仓库涉及 5 个别名词（MailAndroidG/AndroidG/MailMaster/桌面端/...） |
| 12 | 失败回退链 | 我们没 | **确认，mm-search 实际 8 步** | SKILL.md:419-436 列 0-7 共 8 步 | 升级计划 P0.2 Section 5 写"5 步"漏列了 5/6/7 步 |
| 13 | 反模式标注 | 我们没 | **确认，13 处 ❌** | grep 统计 SKILL.md 共 13 处 ❌ | 升级计划 P0.2 Section 6 列 7 条，覆盖不足 |
| 14 | 场景识别表 | 我们没 | **确认，15 场景 + 5 抽象模式** | SKILL.md:135-145 抽象模式，SKILL.md:149-165 场景表 15 行 | 升级计划 P0.2 Section 4 列 10 场景，**少 5 个** + 漏了 5 个抽象模式 |

---

## 3. 升级计划漏列的能力

### 漏列 1：本地交叉验证（high-value）⭐

**能力描述**：mm-search 在 SKILL.md:95-96 强制要求"mm-search 命中后必须 grep 本地文件交叉验证"，因为远端索引可能过时或片段截断。

**证据**：SKILL.md:95-96
> ⚠️ **本地交叉验证**（mm-search 命中后必须执行）：mm-search 返回文件路径 → 查找当前对话中已打开或提到的本地仓库目录 → 匹配到对应仓库 → grep 在对应本地文件上精确搜索。**mm-search 给的代码片段可能过时或截断，本地 grep 补全完整上下文。**

**是否值得借鉴**：**强烈建议**。我们 email-wiki-demo 是自建索引，**不存在"过时"问题**（索引和代码同步），但**片段截断是真实痛点**（top_k=10 拿到的可能是不完整的方法体）。借鉴时改理由——我们是"补全上下文"而不是"防过时"。

### 漏列 2：两阶段响应策略（highest-value）⭐⭐

**能力描述**：mm-search 的核心工作流创新——阶段 1 立即同步返回首批结果，阶段 2 后台异步追加细节。

**证据**：SKILL.md:50-94
```
### 阶段 1：立即展示（同步，0~3 秒）
  第 1-4 步：确定范围 → repo 映射 → 2-3 组 query 并行搜 → 立即展示

### 阶段 2：后台补充（异步，不阻塞用户）
  - get_file     获取阶段1命中文件的完整代码
  - trace_callers 补充调用链信息
  - 跨仓库补充搜索
  - grep 在命中文件上做精确匹配深挖
```

**是否值得借鉴**：**强烈建议，必须做**。这是 mm-search 工作流层面最具价值的创新。升级计划 P0.2 Section 2 提了"阶段策略（先快后全）"但**只 3 行**（line 142-145），建议扩展为独立小节。

### 漏列 3：触发句式覆盖到 description frontmatter ⭐⭐

**能力描述**：mm-search 的 frontmatter `description:` 字段长达 16 行（SKILL.md:1-21），列了 50+ 触发句式，让 AI 即使没读完整 SKILL.md 也能从 description 命中触发。

**证据**：SKILL.md:1-21
```
description: >-
  XX在哪 / 哪里用了XX / 有哪些场景使用XX / 找一下XX / 搜XX / 查找XX /
  谁调用了XX / 调用了什么 / 继承关系 / 看下XX怎么实现的 / XX的实现在哪 /
  对比两端 / 看看其他端怎么做的 / 各端差异 / XX端有吗 / 全端支持吗 /
  参考一下XX / 先看看XX的实现 / 对齐XX端 / 要加XX先看现有方案 /
  ...
```

**是否值得借鉴**：**强烈建议**。这是 Claude/Cursor/CodeMaker 加载 Skill 时**最先读到**的字段，决定 AI 是否会主动触发。我们 email-wiki-demo 当前没有 SKILL.md，从零开始时应**先写 description，再写正文**。

### 漏列 4：结果为空时的诊断步骤

**能力描述**：SKILL.md:290-297 给"结果为空"时**明确的诊断顺序**：
1. list_repos() 确认仓库/分支在线
2. 去掉 branch 参数
3. 尝试更短关键词
4. 尝试不同术语（同义词）
5. 提示用户等待索引同步

**是否值得借鉴**：**建议**。我们 code_search 返回空时目前是直接返回"未找到"，SKILL.md 可以写"5 步诊断"提示 AI 自助排查。

### 漏列 5：抽象模式 + 具体场景的双层触发 ⭐

**能力描述**：mm-search 用**两层抽象**组织触发逻辑——
- 第一层：5 个**抽象模式**（搜索定位/跨端引用/影响分析/参考借鉴/追溯调查）
- 第二层：15 个**具体场景**（每个场景对应一个"模式 + 典型问法 + 工具链"三列表）

**证据**：SKILL.md:133-165

**是否值得借鉴**：**强烈建议**。升级计划 P0.2 Section 4 只列了 10 场景没写抽象模式，导致 AI 面对**新句式**时无法泛化。**正确写法：先给 3-5 个抽象模式 → 再给 10-15 个具体场景锚定**。

### 漏列 6：分语言查询构造指南

**能力描述**：SKILL.md:374-390 给"按平台/语言适配"的查询构造指南表（Java/Kotlin/Dart/Swift/ObjC/C++/ArkTS 各有推荐 query 模板），让 AI 写 query 时知道用"widget builder component"还是"viewcontroller delegate protocol"。

**是否值得借鉴**：**可选**。我们项目语言相对集中（ObjC/Swift 为主），不一定要做这么细。但可以做一个**轻量版**——给 code_search query 构造提示。

### 漏列 7：❌ 陷阱 vs 反模式的区分

**能力描述**：mm-search SKILL.md:618-636 区分了**两类陷阱**：
- **Agent 使用陷阱**（622-625）—— 4 条 ❌，讲 AI 行为
- **搜索技巧陷阱**（627-635）—— 7 条 ❌，讲查询技巧

**是否值得借鉴**：**建议**。我们 SKILL.md 写"反模式"时分两类：行为类（AI 决策错）+ 技巧类（参数用错）。

### 漏列 8：触发条件的"排除规则"

**能力描述**：SKILL.md:167-175 给出 4 个**不适用场景**（已指定文件+行号 / 纯写代码 / 通用框架问题 / 帮我实现一个新功能），每个都有"原因 + 正确做法"两列。

**是否值得借鉴**：**建议**。升级计划 P0.2 Section 1 决策树结尾有"已指定文件+行号 / 纯写代码 / 通用框架问题 → 不触发"，**但没说"为什么"和"应该怎么做"**。

### 漏列 9：MCP 不可用时的渐进降级

**能力描述**：SKILL.md:184-201 不只说"MCP 不可用就用 Python"，而是给出**完整引导**：
1. 执行 `codemaker mcp add` 交互命令帮用户配置
2. 引导用户 4 步操作（Location→Name→Type→URL）
3. **同时**用模式 B 继续搜索，不阻塞工作

**是否值得借鉴**：**建议**。我们 SKILL.md 可以写"模式 A 不可用 → 提示用户配置 + 立即用模式 B"。

---

## 4. SKILL.md 写作技法分析

### 4.1 章节结构（按重要性排序）

| # | 章节 | 角色 | 借鉴度 |
|---|------|------|--------|
| 1 | description（frontmatter） | **最先被 AI 看到**，决定是否触发 | **必学** |
| 2 | 触发决策（决策树+模式+场景表+排除） | 教 AI 何时用/不用 | **必学** |
| 3 | 能力详解（每个能力独立章节） | 教 AI 怎么用每个工具 | **必学** |
| 4 | 双模调用（模式 A + 模式 B） | 教 AI 怎么调用 | **必学** |
| 5 | 仓库映射速查表 | 翻译用户词到 MCP 名 | **必学** |
| 6 | 失败回退链 | 教 AI 错误恢复 | **必学** |
| 7 | 陷阱（❌ 反模式） | 教 AI 别干什么 | **必学** |
| 8 | 两阶段响应策略 | 教 AI 工作流节奏 | **强烈推荐** |
| 9 | 搜索最佳实践（按目标选策略） | 教 AI 组合工具 | **强烈推荐** |
| 10 | 示例（8 个完整对话） | 给 AI 看完整 case | **强烈推荐** |
| 11 | 结果为空诊断 | 空结果的自助排查 | 推荐 |
| 12 | 跨仓库专用工具 | 跨端场景 | 推荐 |
| 13 | 历史追溯（branch 切换） | 老版本定位 | 可选 |
| 14 | Publishing 版本日志 | 维护元信息 | 可选 |

### 4.2 反模式（❌ 标记）怎么写

mm-search 共 13 处 ❌，分布：
- **陷阱章节（11 处）**：SKILL.md:622-635
- **正文警告块（2 处）**：SKILL.md:99-101

**写作模式提炼**：
```
❌ [错误行为] —— [原因/反直觉点]
   例：[具体反例]
   例外/补充：[边界条件]
```

### 4.3 场景识别表怎么组织

mm-search 15 场景表（SKILL.md:149-165）共 4 列：

| # | 用户意图 / 典型句式 | 模式 | mm-search 操作 |
|---|-------------------|------|---------------|

**列设计要点**：
- **第 1 列**：动词化命名（"代码定位"/"使用调查"），用粗体标识核心词
- **第 2 列**：用 `"XX在哪"` 直接引号包用户原话
- **第 3 列**：回指第 1 层抽象（搜索定位/影响分析/...）
- **第 4 列**：直接给 tool 链 `search_code → get_file`

**前置的 5 个抽象模式**（SKILL.md:135-145）也用同样 3 列：模式名 / 含义 / 典型问法。

### 4.4 失败回退链怎么描述

mm-search 8 步回退（SKILL.md:419-436）：
```
0. ⚠️ repo 名映射重试（最高优先级）
1. list_repos() 确认仓库/分支在线
2. 去掉 branch 参数（自动搜索所有分支）
3. 换 query 策略：中文→英文 / 英文→中文 / 同义词
4. 缩短 query："push notification device register" → "push register"
5. 限定 repo 逐个排查（缩小范围）
6. 以上全失败 → 用 grep 在关键路径做字面匹配
7. 提示用户：可能需要等待索引同步
```

**写作模式提炼**：
- **步骤 0 用 ⚠️ 标识"最高优先级"**（独立于顺序）
- **每步给"动作 + 原因 + 示例"** 三件套
- **示例用 `→` 表示转换**（"登录"→"sign in"→"authentication"→"auth"）
- **最后一步是"人机协作"**，承认 AI 能力的边界

### 4.5 可直接复用的写作模板

```markdown
---
name: <skill-name>
description: >-
  <核心能力一句话>。
  <触发句式 1> / <触发句式 2> / <触发句式 3> /
  ...
  时触发——<核心策略铁律>。
  <反直觉点>。
  排除：<不适用场景 1>、<不适用场景 2>、<不适用场景 3>。
version: "<x.y.z>"
metadata:
  author: <作者>
---

# Skill: <name>

> 🔴 **<核心策略>（数据驱动）**：
> ```
> <决策流程伪代码>
> ```
> <一句精炼总结>

## 概述
## 执行策略（先快后全）
## 何时使用本 Skill（触发决策）
## 调用方式（双模兼容）
## 可用仓库
## 能力一/二/三
## 搜索最佳实践
## 示例（5-8 个完整对话）
## 陷阱
## Publishing
```

完整章节细节见升级计划修订版的 SKILL.md 章节设计（第 4 节 P0.2）。

---

## 5. 升级计划修订建议（详细清单）

### 5.1 必须修订的章节

#### 修订 1：能力差距全景表第 5 行（跨仓库聚合）
- **柳哥 2026-06-11 决定**：**不做跨仓库搜索**
- **现状**：`| 跨仓库聚合 | ✅ get_code_context | ❌ | **我们不需要**（单仓不跨仓） |`
- **同步删除**：P2 的 `get_code_context` 端点（4h）

#### 修订 2：能力差距全景表第 6 行（多 query 并行）
- **柳哥 2026-06-11 决定**：**走 SKILL.md 教 AI 并行，零后端改动**
- **现状**：`| 多 query 并行 | ✅ 2-3 组 query 并行（SKILL.md 教 AI `run_in_background=true`） | ❌ | **我们没教 AI 并行**，P0 SKILL.md 必须补 |`
- **做法**：AI 一次性发出 2-3 个 `search_code` MCP 调用，全部用 `run_in_background=true`

#### 修订 3：P0.2 SKILL.md Section 2 阶段策略
- **现状**（line 142-145）只有 3 行
- **建议**：扩展为独立 Section 2.5 "两阶段响应策略"，包含完整的阶段 1/2 步骤清单和 `run_in_background` 指引

#### 修订 4：P0.2 SKILL.md Section 4 场景识别表
- **现状**（line 156-169）列 10 场景
- **建议**：补到 15 场景 + 前置 5 个抽象模式（搜索定位/跨端引用/影响分析/参考借鉴/追溯调查）

#### 修订 5：P0.2 SKILL.md Section 5 失败回退链
- **现状**（line 170-180）只列 5 步
- **建议**：补到 8 步（补步骤 5/6/7：限定 repo 逐个排查 / grep 兜底 / 提示用户等索引）

#### 修订 6：P0.2 SKILL.md Section 6 反模式
- **现状**（line 183-191）列 7 条 ❌
- **建议**：补到 12-13 条，分两类（行为类 4 条 + 技巧类 8 条）

#### 修订 7：新增章节——frontmatter description 设计
- 升级计划完全没有 frontmatter description 设计指引
- 建议新增 Section 0（在所有章节之前）

### 5.2 优先级调整建议

| 项 | 现状 | 建议 | 理由 |
|---|---|---|---|
| 跨仓库聚合 | ~~P2 4h~~ | **删除** | 柳哥决定不做跨仓 |
| 多 query 并行 | P0（隐含） | **显式提到 P0.2 独立小节** | 是 SKILL.md 工作流问题，不该混在某 Section |
| 失败回退链 | P0.2 Section 5（5 步） | **补到 8 步** | 漏了 3 步 |
| 反模式标注 | P0.2 Section 6（7 条） | **补到 12-13 条，分两类** | 差太多 |
| 场景识别表 | P0.2 Section 4（10 场景） | **补到 15 场景 + 5 抽象模式** | mm-search 是 15+5 |
| frontmatter description | **未规划** | **P0 新增 Section 0** | AI 触发第一关 |
| 本地交叉验证 | **未规划** | **P0 新增小节** | mm-search 高价值创新（改为"补全上下文"） |
| 两阶段响应 | P0.2 Section 2（3 行） | **P0.2 独立小节** | mm-search 核心工作流 |
| 结果为空诊断 | **未规划** | **P0 失败回退链之前** | 5 步自助排查 |
| **P1.1 repo 别名映射** | P1 1h | **降级到 P2** | **单仓库无意义**（我们目前只有 ghmail） |

### 5.3 新章节建议

升级计划 Section 4 P0 应新增以下小节（按重要性）：

1. **4.0 frontmatter description 撰写指南**（P0 新增，5 分钟）
2. **4.3 两阶段响应策略**（P0.2 独立小节，10 分钟）
3. **4.7 结果为空诊断**（P0 失败回退链之前，10 分钟）
4. **4.8 分语言查询构造指南**（P0.2 轻量版，10 分钟）

### 5.4 修订后总工作量估计

| 模块 | 原估计 | 修订后估计 | 变化 |
|---|---:|---:|---|
| P0.1 kb_api.py | 2h | 2h | 不变 |
| **P0.2 SKILL.md 撰写** | **3h** | **5-6h** | **+2-3h**（补全 description / 两阶段 / 抽象模式 / 8 步回退 / 12 条反模式） |
| ~~P1.1 repo 别名映射~~ | 1h | **删除** | 柳哥决定单仓不需要 |
| P1.1 code-mcp.html AI 视角 | 1h | 1h | 不变 |
| **P0 新增小节合计** | — | **+0.5h** | description 5min + 两阶段 10min + 诊断 10min + 分语言 10min |
| ~~P2 get_code_context~~ | 4h | **删除** | 柳哥决定不做跨仓 |
| P2 trace_hierarchy | 3h | 3h | 不变 |
| P2 code_chat 多段对比 | 2h | 2h | 不变 |
| **合计** | **16h** | **13.5-14.5h** | **-1.5 到 -2.5h**（删 2 项省 5h，加 1 项多 3h） |

---

## 6. 风险与注意事项

### 6.1 mm-search 特有、不能照搬的部分

#### 仓库别名映射是**项目特定**的
mm-search 的别名映射（SKILL.md:241-251）绑定网易邮件大师具体仓库（MailAndroidG→mail-android），**不能照搬**。我们 email-wiki-demo 当前的 `code_repos.json` 只有 `ghmail` 单仓库，如果未来要支持多仓库，需要**先确定仓库名**，再设计映射。**降级 P1.1 到 P2，等多仓库需求时再做**。

#### 跨端场景是**邮件大师特定**的
mm-code-search 的"对比 Android/Flutter/iOS/PC/鸿蒙"是我们没有的场景。**柳哥 2026-06-11 决定不做跨端对比**。场景识别表用"模块对比"代替"跨端对比"。

#### "本地交叉验证" 适用场景有限
mm-search 的"本地 grep 交叉验证"（SKILL.md:95-96）是因为远端索引**会过时**。我们 email-wiki-demo 是**自建索引**，不存在"过时"问题。**借鉴时改理由**——我们是"补全上下文"（top_k=10 可能截断）而不是"防过时"。

### 6.2 mm-search 没覆盖、我们需要自己想方案的部分

#### 性能指标追踪
mm-search 全文 0 处提"性能"或"指标"。我们 email-wiki-demo 有 `StepTracker` + `metrics.db`，这些**没在 SKILL.md 体现**。建议在 SKILL.md 加一节"性能与可观测性"。

#### 索引跳过规则（skip rules）
我们 `code_skip_rules.py` 提供扫描时跳过能力，mm-search 没有这个概念。SKILL.md 可以补一节。

#### 翻译词典管理
我们 `query_translator.py` 有 TERM_MAP 词典，mm-search 不需要（远端服务自己处理）。SKILL.md 可以教 AI"如何用翻译词典"。

#### 失败时的 RAG fallback
我们 `code_chat` 走 RAG，mm-search 没有。当 RAG 检索不到时，我们**还没明确策略**。建议在 SKILL.md 补"code_chat 空结果时"回退策略。

### 6.3 mm-search 自带的小问题（避免踩坑）

#### ❌ 标记 6 和正文 270 矛盾
SKILL.md:629 写"❌ 搜索不要用中文"，但 SKILL.md:270 写"中文同样支持：BGE 模型理解中英双语"。**我们写 SKILL.md 时要避免这种内部矛盾**。

#### 阶段 2 没说"什么时候停止"
mm-search SKILL.md:93 写"用户表示'够了'时立即终止后台任务"，但**没说"如何知道用户表示够了"**。我们写 SKILL.md 时要么补具体信号，要么承认这是 AI 自由发挥的地方。

#### Publishing 章节有版本日志但没 changelog 链接
SKILL.md:639-650 把所有版本变更塞在 Publishing 章节。**更好的做法**是单独维护一个 CHANGELOG.md。

---

## 7. 关键文件路径汇总

| 文件 | 路径 |
|---|---|
| mm-search 仓库根 | `/Users/admin/.claude/jobs/494b16d6/tmp/mm-code-search/mm-code-search/` |
| mm-search SKILL.md | `.../mm-code-search/SKILL.md` (649 行) |
| mm-search mm_api.py | `.../mm-code-search/scripts/mm_api.py` (299 行) |
| 我们的升级计划 | `/Users/admin/Desktop/AI产出/email-wiki-demo/docs/code-kb-upgrade-plan.md` |
| 我们的 code_search | `/Users/admin/Desktop/AI产出/email-wiki-demo/backend/code_search.py` |
| 我们的 code_mcp | `/Users/admin/Desktop/AI产出/email-wiki-demo/backend/code_mcp.py` |
| 我们的 code_routes | `/Users/admin/Desktop/AI产出/email-wiki-demo/backend/code_routes.py` |
| 我们的 code_config（mtime 增量） | `/Users/admin/Desktop/AI产出/email-wiki-demo/backend/code_config.py` |

---

## 8. 总结

### 升级计划总体评价

升级计划对 mm-code-search 的分析**整体准确**，14 项差距的判定方向全对，但有 **3 处表述需要修正**（跨仓库聚合 → **柳哥决定不做**；多 query 并行 → **SKILL.md 教 AI 并行**；失败回退链漏 3 步）。

### 升级计划的主要盲点（按严重程度排序）

1. **漏了 frontmatter description**（AI 触发第一关）—— **最严重**的漏列
2. **漏了"两阶段响应策略"作为独立小节** —— mm-code-search 的核心工作流创新
3. **漏了"本地交叉验证"** —— 即使不适用全部场景，"补全上下文"的思路值得借鉴
4. **场景识别表只列具体场景没列抽象模式** —— 5 个抽象模式 + 15 个具体场景的双层结构是关键

### 优先级建议（柳哥二轮反馈后）

- **P0.2 SKILL.md 撰写时**（原 3h → 修订 5-6h），按本报告 §5.1 修订点 + §5.3 新章节全部补齐
- **P0.1 kb_api.py** 维持 2h 估计
- **P2 跨仓库聚合** **删除**（柳哥决定不做跨仓）
- **P1.1 repo 别名映射** **删除**（单仓无意义）
- **P0 总计**：7-8h（原 5h，+2-3h 来自 9 项漏列）
- **P2 总计**：5h（原 10h，-5h 来自删除 2 项）

---

## 9. 未解决问题

无。所有 14 项差距均已找到证据，mm-search 仓库 7 个文件全部读完。

---

## 10. 实施状态（2026-06-12 更新）

本报告作为"调研输入"已转化为落地实施，详见 `docs/code-kb-upgrade-plan.md`：

| 阶段 | 状态 | 关键产出 |
|------|------|---------|
| **P0** 说明书 + 兜底脚本 | ✅ 实施完成（6 轮 review 验证）| `export/` 9 文件 1140 行；`SKILL.md` v2.0；`kb_api.py` 244 行；e2e 6/6 |
| **P1** 前端 AI 视角 | ✅ 实施完成 | `code-mcp.html` 第 4 子标签 + 10 处 URL 修；bump v16→17 |
| **P2** 继承链追踪（hierarchy）| ✅ 实施完成 | `relation_type` 二元化 + 6 语言 implements + trace_hierarchy 19878 入库 |

**遗留 TODO**（P3 方向）:
1. `trace` 类名 vs 方法名 BFS 不匹配（callers/callees 模式对大写类名返回空）
2. Java/TypeScript generic `<T>` 边界（implements 完整捕获）
3. `kb_api.py` chat 默认 30s 仍适用其他子命令（chat 单独 120s 已修）
