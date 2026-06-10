# Changelog

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
