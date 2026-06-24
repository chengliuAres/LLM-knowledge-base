# 排除规则弹窗：Tab 化 + 添加区上移 设计

> 2026-06-10 · 柳哥
>
> 目标：让"添加新排除规则"操作在弹窗任意滚动位置都随手可点，避免当前"滚到底才能加"的问题。

## 1. 背景

排除规则弹窗（`#skip-rules-modal`）当前有 3 个主要区：

1. 📊 **预览统计**（顶部固定）
2. 📋 **.gitignore 目录**（绿色面板，可全选）
3. 📁 **排除目录** + 📄 **排除扩展名**（两个对称的表格 + 各自的"添加"行）

添加行的位置在**表格下方**（`code-repos.html:130-134` 和 `150-154`），用户要先滚动到表格末尾才能看到"添加"。当规则数量多时，添加操作被推到屏幕外，体验差。

## 2. 目标 / 非目标

### 目标
- 排除规则弹窗的"添加操作"始终在视线内（不依赖滚动）
- 目录 / 扩展名 两个 section 改为 tab 切换（弹窗内独立 tab，不影响项目路由）
- 已有功能 100% 保留：保存 / 恢复默认 / Finder / 刷新 / 关闭 不变

### 非目标
- 不重写后端 API（`/api/code/skip-rules` 不动）
- 不持久化 tab 选择（每次开弹窗默认第一个 tab）
- 不改 .gitignore 目录区
- 不改预览统计区
- 不引入前端框架（继续用 vanilla JS + Tailwind CDN runtime）

## 3. 设计

### 3.1 弹窗内布局（before → after）

**改前**（当前结构）：

```
[头部] ⚙️ 排除规则 + 5按钮
─────────────────────────────────
📊 预览统计
─────────────────────────────────
📋 .gitignore 目录
─────────────────────────────────
📁 排除目录
  ┌──────────────────────┐
  │ 表格（多条规则）      │
  └──────────────────────┘
  [input][select][+ 添加]  ← 在表下方
─────────────────────────────────
📄 排除扩展名
  ┌──────────────────────┐
  │ 表格                  │
  └──────────────────────┘
  [input][select][+ 添加]  ← 在表下方
```

**改后**：

```
[头部] ⚙️ 排除规则 + 5按钮                       ← 不变
─────────────────────────────────
📊 预览统计                                       ← 留在 tab 上面（固定）
─────────────────────────────────
📋 .gitignore 目录                                ← 留在 tab 上面（固定）
─────────────────────────────────
[📁 排除目录] [📄 排除扩展名]  ← tab 标签栏（弹窗内独立切换）
═════════════════════════════════════
  [input 名称][select 分类][+ 添加]  ← tab 内的"第一行"（添加区上移）
  ┌──────────────────────┐
  │ 表格（仅当前 tab）    │
  └──────────────────────┘
```

### 3.2 三个固定区 + 一个 tab 区

| 区 | 处理 |
|----|------|
| 📊 预览统计 | **固定在 tab 上面**，不参与切换 |
| 📋 .gitignore 目录 | **固定在 tab 上面**，不参与切换 |
| 📁 排除目录 / 📄 排除扩展名 | **tab 切换**，弹窗内独立 2 tab |

### 3.3 Tab 容器

弹窗内**独立 tab**，与项目路由的 10 个 tab（doc/upload、code/repos 等）**无关**。

- 实现：原 `<div class="space-y-5">` 内的"排除目录"和"排除扩展名"两块，包到一个新的 tab 容器里
- 标签栏：两个按钮 `.tab-btn` + `.tab-btn-active` 切换
- 内容区：两个 `<div class="tab-pane" id="skip-pane-dirs">` 和 `id="skip-pane-exts"`，通过 `hidden` class 显隐
- 默认激活：第一个 tab（排除目录）
- 状态不持久：localStorage 不存 tab 位置，简单

### 3.4 添加区上移

每个 tab pane 的结构：

```html
<div class="tab-pane" id="skip-pane-dirs">
    <!-- 添加区：移到 tab 顶部（首行） -->
    <div class="flex gap-2 mb-3">
        <input id="skip-dir-input" type="text" ... />
        <select id="skip-dir-category" ... ></select>
        <button onclick="addSkipRule('dirs')" ...>+ 添加</button>
    </div>
    <!-- 表格：保持不变 -->
    <table>...</table>
</div>
```

`id` 保持不变（`skip-dir-input` / `skip-dir-category` / `skip-dirs-body` 等），现有 `addSkipRule()` 和 `renderSkipTable()` 函数**零改动**。

### 3.5 Tab 切换实现（最小代码）

```javascript
function switchSkipTab(name) {
    // 1. 切换按钮高亮
    document.querySelectorAll('#skip-rules-modal .skip-tab-btn').forEach(b => {
        b.classList.toggle('skip-tab-btn-active', b.dataset.tab === name);
    });
    // 2. 切换内容显示
    document.getElementById('skip-pane-dirs').classList.toggle('hidden', name !== 'dirs');
    document.getElementById('skip-pane-exts').classList.toggle('hidden', name !== 'exts');
}
```

~10 行 JS，不引入新依赖。Tab 按钮直接 `onclick="switchSkipTab('dirs')"` 即可。

## 4. 验收标准

打开排除规则弹窗后，**必须**满足：

1. ✅ 预览统计（📊 ⏳ 计算中...）在 tab 标签栏**上方**可见
2. ✅ .gitignore 目录（绿色面板）在 tab 标签栏**上方**可见
3. ✅ tab 标签栏包含 "📁 排除目录" 和 "📄 排除扩展名" 两个按钮
4. ✅ 默认激活 "排除目录" tab
5. ✅ 点击 "排除扩展名" tab → 目录区消失，扩展名区显示，且 input/select/+ 添加按钮在**表格上方**
6. ✅ 添加按钮功能不变：输入 → 点击 + 添加 → 输入框清空、表格新增一行、显示 toast
7. ✅ 切 tab 不重置 `_skipRulesDraft`（编辑中数据保留）
8. ✅ 头部 5 个按钮（刷新/Finder/恢复默认/保存/关闭）位置和功能不变
9. ✅ Chrome 实测：1280×500 和 1581×814 两个视口下，添加区始终在视口内可见

## 5. 改动文件清单

| 文件 | 改动量 | 备注 |
|------|--------|------|
| `frontend/tabs/code-repos.html` | ~30 行（HTML 重组 + ~10 行 JS） | 主体结构调整 + 新增 `switchSkipTab` |

后端、其他 tab、API 路由、`.env` 配置：**全部不动**。

## 6. 风险与回退

- **风险**：tab 切换后，扩展名区"加扩展名"的 input 框可能跟目录区"加目录"的 input 视觉类似，误操作概率略升
  - **缓解**：input 的 `placeholder` 已经区分（"目录名, 如 node_modules" vs "扩展名, 如 .lock"），且两个 tab 不会同时显示
- **回退**：`git revert` 单次提交即可，整体改动 30 行内
- **测试**：仅前端，无后端回归风险

## 7. 不做的事（YAGNI）

- ❌ 不加 tab 切换动画（用 `hidden` 即可）
- ❌ 不持久化 tab 位置（每次开弹窗默认第一个，简单）
- ❌ 不重命名 `#skip-dir-input` / `#skip-ext-input`（保持 id 稳定，避免破坏现有 `addSkipRule` 函数）
- ❌ 不改 renderSkipTable 函数（数据结构不变）
- ❌ 不加键盘快捷键（如 Cmd+1/2 切 tab）— 不是核心需求
- ❌ 不加 swipe 手势（桌面应用，不需要）
