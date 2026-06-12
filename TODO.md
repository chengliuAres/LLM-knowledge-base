# 待解决问题

## 代码搜索准确率

> 当前策略见 `AGENTS.md`「代码搜索准确率策略」章节。
> 三路混搜 + 翻译层 + bge 向量 + 符号 LIKE 精确匹配。
> 下文列出的为已验证方向之外的**后续提升手段**。

### LLM 辅助翻译（词典覆盖不到的查询）

- **现象**：词典 `TERM_MAP` 只能覆盖人工添加的常见词，长尾中文查询（如"阅览信函"）词典不命中 → 降级 MyMemory → 直译不准
- **方案**：词典不命中时，让 LLM 先做翻译+拓词（Token 开销小，~50 tokens），产出英文关键词列表，再走三路搜索
- **优先级**：高（词典手工维护天花板明显，LLM 翻译是低成本补长尾的方案）

### LLM 查询改写 & 意图理解

- **现象**：用户输入可能是自然语言问题（"怎么处理邮件附件下载失败的场景"），而非关键词查询
- **方案**：搜索前 LLM 先解析意图 → 拆成多个子查询（"附件下载" + "错误处理" + "下载失败"）→ 多轮搜索 → 结果合并排序
- **潜在问题**：增加延迟（LLM 调用 ~3-5s），需权衡响应时间 vs 召回质量
- **优先级**：中

### 代码专用 embedding 模型调研

- **现象**：`bge-small-en` 是通用文本模型，不"理解"代码结构（函数调用、继承关系等）
- **方案**：调研支持 Objective-C 的代码 embedding 模型。当前已知：CodeBERT、GraphCodeBERT（不支持 OC）、UniXcoder（多语言但未列 OC）、StarCoder-Embed（基于 StarCoder 的代码模型，可能覆盖 OC）
- **挑战**：OC 不在主流代码语料中（CodeSearchNet 只有 Go/Java/JS/PHP/Python/Ruby），大部分代码专用模型对 OC 的优势归零
- **优先级**：低（tree-sitter AST + 符号精确匹配已在扛 OC 结构信号）

### 向量路权重自适应

- **现象**：当前三路权重固定（向量 1.0x / 关键词 1.0x / 符号 1.5x），不随查询特征变化
- **方案**：根据翻译置信度动态调整——词典命中（高置信）→ 符号权重降、向量权重升；MyMemory/LLM（低置信）→ 反之
- **优先级**：中（改动小但需要标定阈值）

### RRF 融合后重排序

- **现象**：RRF 只按排名融合，不关心内容语义。符号路因为 1.5x 权重经常刷屏
- **方案**：RRF 初排 top-K → LLM 对候选重排序（根据 query 判断每条结果的相关性打分）→ 输出最终排序
- **挑战**：LLM 成本（~500 tokens/result × 10 results），适合对质量要求高的场景
- **优先级**：低

### 搜索日志 & 反馈闭环

- **现象**：不知道用户真正搜了什么、点了什么、哪些结果被忽略了
- **方案**：搜索日志记录（query / 三路命中数 / 用户点击的 result）→ 离线分析 → 词典补词 / 阈值调参
- **优先级**：中（属于基建，一次建立长期受益）

## 性能

### code/dashboard 页面刷新卡顿（疑似 Tailwind 运行时阻塞）
- **现象**：在 `http://localhost:8000/#code/dashboard` 页面刷新时，可能卡 20+ 秒才加载完成
- **实测**：后端 API 每个只要 3-5ms，10 个调用共 22ms，后端不是瓶颈
- **可疑根因**：`vendor/js/tailwindcss.js`（407KB 运行时）每次 tab 切换调用 `tailwind.refresh()` 同步扫描 DOM 生成 CSS，可能在浏览器内存压力/扩展干扰下阻塞主线程
- **优化方案**：用 Tailwind CLI 预编译静态 CSS 替换运行时版本，消除不确定性
- **优先级**：中（不频繁刷新时体验正常）

## 架构重构 — 代码知识库数据库按 repo 隔离（方案 A）

### 背景

当前所有仓库共享 1 个 LanceDB 表 + 1 个 SQLite，靠 chunk_id 前缀区分。存在以下问题：

| 问题 | 说明 |
|------|------|
| 删除慢 | 删一个 repo 需全表扫描过滤（LanceDB 无索引，SQLite LIKE 匹配） |
| 故障耦合 | 一个 repo 数据损坏影响全部仓库 |
| 备份粒度粗 | 无法单 repo 备份/恢复 |
| 中断清理难 | 扫描中断后孤立数据清理需扫全表（2026-06-11 实际遇到） |

### 方案

采用 Codex 推荐的**方案 A：按 repo 物理隔离**。CC 推荐的 B+（共享存储+靶向优化）更务实但治标不治本，等 repo 数量上去再改成本更高。

### 实施步骤（低风险顺序）

1. **引入 `RepoStorageManager`** — `get_repo_db(repo_name)` 按 repo 路由到独立 DB
2. **路径约定** — `data/repos/{repo_name}/lancedb/` + `data/repos/{repo_name}/index.db`
3. **抽象存储接口** — `insert/search/delete/stats` 适配层，上层代码不感知底层实现
4. **先迁移写入+删除路径** — 收益最大（解决删除慢和中断清理）
5. **再迁移查询路径** — 搜索/问答/浏览
6. **跨仓库搜索** — 并发扇出 + topK 合并（RRF score 归一化）
7. **扫描暂存 + 原子切换** — `scan_{id}` 写入临时库，完成后 rename 为 `active`，中断直接删除临时库
8. **离线迁移脚本** — 按 repo_name 拆分现有数据到独立目录
9. **Feature flag** — `STORAGE_MODE=shared|isolated` 可回滚

### 预估工作量

6+ 核心文件、500+ 行改动，涉及 `code_db.py`（全局单例→多实例）、`code_routes.py`（搜索/扫描/删除）、`code_config.py`（记录每个 repo 的 DB 路径）、`code_search.py`（跨库搜索）。

### 触发条件

- repo 数量 > 3
- 单 repo 删除 > 30s
- 需要 per-repo 备份 SLA
- 需要多租户隔离

### 参考

- CC (sonnet) 建议 B+（~80 行改动解决 3/4 痛点，适合当前阶段）
- Codex (o4-mini) 建议 A（从结构上解决，但改动量大）
- 2026-06-11 MailAndroidG 扫描中断事件验证了隔离的必要性

## MCP / kb_api 兜底

### kb_api.py chat 子命令 30s 超时对 LLM 推理偏短（2026-06-11）

- **现象**：`python3 export/skill/scripts/kb_api.py chat --question "..."` 实测 30s 超时返回 `TimeoutError: timed out`（小米 MiMo 慢），e2e 测试靠"协议层 error"判通过
- **影响**：CLI 兜底模式下 chat 经常超时失败，AI Agent 会切到 MCP 模式或直接放弃
- **优化方案**：
  - chat 单独 120s 超时（其他子命令保持 30s）
  - 暴露 `--timeout` 参数让用户按需调整
- **优先级**：中（影响 CLI 兜底可靠性，但 MCP 模式不受影响）
- **参考**：`export/skill/scripts/kb_api.py:39` `TIMEOUT_SEC = 30`

### code_trace callers/callees 对类名返回 0 关系（sendMail 等大写类名搜索）

- **现象**：`code_trace --symbol sendMail --direction callers` 返回 matched=5 但 direct_callers/callees/chain 全空
- **根因**：`code_search` 找类（`SendMailParam`），但 `code_relations` 里 callee_name 是方法名（`sendMailBegin:`）。类名 ≠ 方法名，导致 BFS 找不到任何关系
- **影响**：用户搜类名查调用链，得到"找不到调用"（实际有）
- **修复方向**（P3+）：trace_code 在 BFS 失败时 fallback 搜"包含此符号的类/接口的所有方法"
- **优先级**：中（影响体验，但 hierarchy 不受影响）

## pre-existing 测试失败 — 非本任务范围

> 来源：2026-06-12 Agent 接入页 Skill 集成（commit 9652f2b）合并前 verify 阶段发现。
> 本任务交付的 `backend/tests/test_skill_routes.py` 4 个测试**全过**，以下 6 个失败**与本任务无关**——是主仓早期健康检查模块的设计争议或环境依赖问题。

### health_utils：测试期望 error/warning 语义 vs 实现返回 warning（5 个失败）

- **现象**：
  - `test_check_lancedb_status_ok_when_dir_exists` / `test_check_lancedb_status_error_when_missing`
  - `test_check_model_status_default_not_loaded` / `test_check_model_status_loaded_when_marker_set`
  - `test_check_disk_usage_error_for_missing_path`
- **失败模式**（以代表性为例）：
  - 测试 `test_check_disk_usage_error_for_missing_path` 期望 `result["status"] == "error"`，实现返回 `warning`
  - 测试 `test_check_model_status_loaded_when_marker_set` 期望 `status == "loaded"`，实现返回 `warning`
- **根因**（设计争议，非 bug）：
  - `health_utils.py` 的"路径不存在 → warning"语义（系统还没用过，但能跑）
  - 测试的"路径不存在 → error"语义（健康检查应该报红）
  - 两种语义都自洽，**是产品决策争议**
- **影响范围**：仅 `backend/health_utils.py` 健康检查端点的状态码显示，不影响业务
- **修复方向**（P3）：
  - 选 A：改实现 → warning 改 error（严格按测试）
  - 选 B：改测试 → 接受 warning 实现（按实现）
  - 选 C：分级细化 → 引入 "warning" / "error" / "ok" 三档更细粒度判定
- **优先级**：低（健康检查 UI 不在主路径上，业务不受影响）

### folder_picker：`test_open_in_finder_path_invalid` 失败

- **现象**：单测失败，错误信息 `assert ...` 截断（输出超长）
- **可能根因**（待查）：
  - macOS Popen 行为依赖（沙盒/权限）
  - 测试用 MagicMock 但实现用了 `start_new_session` 后 MagicMock 失效（commit f90bdc2 修复过类似问题）
  - 路径分隔符（macOS 私路径 `/private/var/...` 与 `os.path.realpath` 的偏差）
- **修复方向**（P3）：读 `backend/test_folder_picker.py` 完整 + `backend/folder_picker.py` 实现，对比 f90bdc2 修复模式
- **优先级**：低（仅测试失败，业务路径正常——`/api/code/open-in-finder` 是 IDE 唤起辅助功能）

## 本任务交付 commit 不动

- 13 个 commit 全部保留在 `worktree-skill-integration-tab` 分支（HEAD `9652f2b`）
- 本任务 4 个 skill routes 测试全过（4 passed）
- 6 个 pre-existing 失败不在本任务范围
- 柳哥决定是否合 + 何时修 pre-existing
