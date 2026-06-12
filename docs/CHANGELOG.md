# Changelog

## 2026-06-12

### feat(code-kb): 升级对标 mm-code-search（P0 + P1 + P2）

完整 3 阶段升级，详见 `docs/code-kb-upgrade-plan.md` §11 实施记录 + §12 review 留痕。

**P0（说明书 + 兜底脚本）**:
- 新增 `export/` 目录（一键集成 AI 工具）：README + INSTALL + mcp/ + skill/，9 文件 1140 行
- 新增 `export/skill/scripts/kb_api.py`（244 行，零依赖，6 子命令含 hierarchy）
- 新增 `export/skill/SKILL.md` v2.0（598 行，13 章节 + 41 触发句 + 6 种语言关键词矩阵）
- 新增 `test/test_e2e_kb_api.py`（端到端验证）

**P1（前端 AI 视角）**:
- `frontend/tabs/code-mcp.html` 加 `🤖 AI 视角` 第 4 子标签（含 5 卡片：核心策略/阶段 1 并行/阶段 2 补全/反模式/双模调用）
- 10 处 `/mcp` → `/mcp/`（与 SKILL.md 一致）
- `frontend/index.html` `__TAB_VERSION` 16 → 17

**P2（继承链追踪）**:
- `code_relations` schema 加 `relation_type` 字段（call/inherit 二元化）
- `code_parser._extract_inherits` 支持 6 种语言 + Java/TypeScript implements
- `code_db.trace_hierarchy` 双向 BFS（parents/children）
- `code_search.trace_code` 加 `direction='hierarchy'` 分支
- `code_mcp_v2.code_trace` depth 上限 3 → 5
- `code_routes.refresh_repo_endpoint` 默认 `force_full=True`（避免 mtime skip）
- 实测：ghmail + MailAndroidG 仓 19878 个 inherit 关系入库

**文档同步**: AGENTS.md / README.md / docs/code-kb-api.md / docs/code-kb-progress.md / docs/code-knowledge-base-design.md 全部更新到 v2.0 状态

## 2026-06-10

### feat(code-repos): 目录选择增强

在"扫描新仓库"tab 的路径输入框右侧新增两个按钮，提供更顺滑的目录选择体验：

#### 新增按钮
- **📁 选择**：浏览器能力探测链
  1. `window.showDirectoryPicker()`（Chrome 86+ / Edge）—— 弹系统原生选择器
  2. `<input type="file" webkitdirectory>`（Safari / Firefox）—— 降级到浏览器自带文件夹选择
  3. 现有 `codeBrowseFolder()` 目录浏览器 —— 兜底
- **🔍 Finder**：在系统文件管理器中打开当前路径
  - macOS → `open`
  - Windows → `explorer`
  - Linux → `xdg-open`
  - 命令缺失 / 未知系统 → 复制路径到剪贴板兜底

#### 后端 endpoint
- `GET /api/code/resolve-path?name=<n>&parent=<p>`：在 parent 下找名为 n 的子目录
  - 唯一命中 → `{"path": "..."}`
  - 多匹配 → `{"matches": [...]}`（最多 20 个）
  - 无匹配 → 404
  - 跳过隐藏目录 + `.git`/`node_modules`/`venv`/`__pycache__`/`Library`/`Applications`
  - 限深 3 层
- `POST /api/code/open-in-finder`：跨平台唤起系统文件管理器
  - macOS / Windows / Linux 命令分支
  - 黑名单校验：`~/.ssh`、`/etc`、`/var`、`/usr`、`/bin`、`/sbin`、`/System`、`/Library/Apple`、`/private`
  - 测试用 `EMAIL_WIKI_SKIP_PATH_DENYLIST=1` 环境变量跳过黑名单（macOS tmp_path 在 `/private/var/...` 下会被误伤）

#### 测试覆盖
- `backend/tests/test_folder_picker.py`：14 个测试
  - 6 个 resolve-path（唯一/多匹配/无匹配/隐藏/限深/无效 parent）
  - 8 个 open-in-finder（macOS/Windows/Linux 命令分支/无效路径/ssh 黑名单/etc 黑名单/未知系统/无 path）
- 全量 `pytest tests/` 29/29 PASS

#### 行为不变
- 原有 `codeBrowseFolder()` 行为完全保留（按钮依然可用，作为兜底）
- 已有仓库索引（`data/code_repos.json`）不受影响
