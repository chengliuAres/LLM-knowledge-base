# Skill 文件夹 — AI Agent 使用说明

> `email-wiki-demo` 代码知识库的 AI Agent Skill 文件。
> 加载后 AI 知道怎么用 code_search / code_chat / code_trace 等工具。

## 文件清单

| 文件 | 角色 | 状态 |
|------|------|------|
| `SKILL.md` | AI Agent 完整使用说明书 | ✅ Day 1 下午 v1.0 完工 |
| `scripts/kb_api.py` | Python 兜底 CLI（MCP 不可用时用） | ⚠️ 占位，P0.1 实施 |

## SKILL.md 章节结构（13 节）

| 章节 | 内容 | 来源 |
|------|------|------|
| YAML frontmatter | 50+ 触发句式 + metadata | 漏列 1 |
| 概述 | 本质说明 | 升级计划 |
| 执行策略（先快后全） | 阶段 1 同步 + 阶段 2 异步 | 漏列 2 |
| Section 1 触发决策树 | 何时用/不用 + 排除规则 | 升级计划 + 漏列 8 |
| Section 2 搜索策略铁律 | 核心原则 + 多 query 并行 | 升级计划 + **柳哥决定走 SKILL.md 教 AI** |
| Section 2.5 本地交叉验证 | 补全上下文 | 漏列 3 |
| Section 3 工具速查 | 5 个 tool | 升级计划 |
| Section 4 抽象模式（5）+ 场景识别（15） | 双层触发 | 漏列 4 |
| Section 4.5 结果为空诊断 | 5 步自助排查 | 漏列 5 |
| Section 5 失败回退链（8 步） | 别名→list→去branch→换query→缩短→限仓→grep→提示 | 升级计划 + 修订 |
| Section 6 反模式（13 条分两类） | 行为类 4 + 技巧类 9 | 升级计划 + 漏列 7 |
| Section 7 双模调用 | MCP + Python + 渐进降级 | 升级计划 + 漏列 9 |
| Section 8 分语言查询构造 | ObjC/Swift/Java/Kotlin 关键词 | 漏列 6（轻量版） |
| Section 9 示例 | 5-8 个完整对话 | 占位（Day 1 下午补充） |
| Section 10 陷阱汇总 | 反模式速查入口 | 升级计划 |
| Publishing | 版本元信息 | 升级计划 |

## 加载方式

### Claude Code

```bash
# 方式 1：放入项目级 skills 目录
cp SKILL.md <project>/.claude/skills/code-kb/SKILL.md

# 方式 2：放入全局 skills 目录
cp SKILL.md ~/.claude/skills/code-kb/SKILL.md
```

### Cursor

```bash
# 复制到 Cursor skills 目录
cp SKILL.md ~/.cursor/skills/code-kb/SKILL.md
```

### CodeMaker / OpenCode

```bash
# 复制到对应 skills 目录
cp SKILL.md ~/.codemaker/skills/code-kb/SKILL.md
cp SKILL.md ~/.config/opencode/skill/code-kb/SKILL.md
```

## scripts/kb_api.py 状态

⚠️ **占位文件** — 等待 P0.1 实施（2h 估计）

实施后用法：
```bash
python3 scripts/kb_api.py search --query "邮件发送" --top_k 5
python3 scripts/kb_api.py chat --question "sendMail 如何工作"
python3 scripts/kb_api.py trace --symbol sendMail --direction both --depth 2
python3 scripts/kb_api.py file --repo ghmail --name "login_page.dart"
python3 scripts/kb_api.py repos
```

## 详细说明

- 升级计划：`../../docs/code-kb-upgrade-plan.md` 第 4 节 P0.2
- 对标参考：`../../docs/调研/mm-code-search-对标报告-20260611.md`
- mm-code-search 原版：`https://git.mail.netease.com/awesome-mm-skills/mm-code-search/blob/main/SKILL.md` (649 行)
