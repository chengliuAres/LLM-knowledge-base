# 代码知识库 — 可配置排除规则

## 目标

将扫描索引时的文件排除规则（skip_dirs / skip_exts）从硬编码改为用户可配置，通过 UI 管理，扫描时实时读取。

## 约束

- 全局一套规则，不做仓库级覆盖
- 分组表格 UI（目录和扩展名分开，带分类注释）
- 配置存储在独立文件 `data/code_skip_rules.json`，与仓库数据解耦
- 首次启动如果文件不存在，自动写入默认规则

## 配置格式

文件路径：`data/code_skip_rules.json`

```json
{
  "skip_dirs": [
    {"name": ".git", "category": "版本控制"},
    {"name": "node_modules", "category": "依赖"},
    {"name": "Pods", "category": "依赖"},
    {"name": "build", "category": "构建产物"},
    {"name": "DerivedData", "category": "构建产物"},
    {"name": ".idea", "category": "IDE"},
    {"name": "__pycache__", "category": "缓存"},
    {"name": "venv", "category": "虚拟环境"}
  ],
  "skip_exts": [
    {"name": ".png", "category": "图片"},
    {"name": ".jpg", "category": "图片"},
    {"name": ".json", "category": "配置/数据"},
    {"name": ".strings", "category": "iOS资源"},
    {"name": ".woff", "category": "字体"}
  ]
}
```

分类（category）用于 UI 分组展示，不影响扫描逻辑。

## 默认规则

从现有 `DEFAULT_SKIP_DIRS` / `DEFAULT_SKIP_EXTS` / `UNIVERSAL_SKIP_DIRS` 合并去重，不再按项目类型区分。具体列表见代码中 `build_default_skip_rules()` 函数。

### 默认排除目录

| 分类 | 目录 |
|------|------|
| 版本控制 | .git, .svn, .hg |
| 依赖 | node_modules, Pods, Carthage, .build, vendor, bundle, bower_components |
| 构建产物 | build, dist, DerivedData, target, out |
| IDE | .idea, .vscode, .xcodeproj, .xcworkspace |
| 资源 | .xcassets, Assets.xcassets, .lproj, Resource |
| 缓存 | __pycache__, .mypy_cache, .pytest_cache, .ruff_cache, .gradle, .dart_tool, .packages, .next, .nuxt, .cache, coverage, .nyc_output |
| 虚拟环境 | venv, .venv, virtualenv, env, .tox |
| 第三方 | third, third_party, lottie, keystore, gradleScripts, buildSrc, .ios, .android, ohosApp |

### 默认排除扩展名

| 分类 | 扩展名 |
|------|--------|
| 图片 | .png, .jpg, .jpeg, .gif, .ico, .svg |
| 字体 | .woff, .woff2, .ttf, .eot |
| iOS/Mac 资源 | .strings, .plist, .storyboard, .xib |
| Android 资源 | .xml, .pro |
| 配置/数据 | .json |

## 后端接口

### GET /api/code/skip-rules

读取当前规则。返回 `code_skip_rules.json` 内容。

### PUT /api/code/skip-rules

保存规则。请求体为完整规则 JSON，写入 `code_skip_rules.json`。

### POST /api/code/skip-rules/reset

恢复默认规则。用 `build_default_skip_rules()` 的结果覆盖文件。

## 后端实现

### 新增模块：`code_skip_rules.py`

职责：
- `get_skip_rules() -> dict`：读取 `code_skip_rules.json`，文件不存在则自动写入默认规则并返回
- `save_skip_rules(rules: dict) -> None`：写入文件
- `reset_skip_rules() -> dict`：恢复默认并写入，返回默认规则
- `build_default_skip_rules() -> dict`：构造默认规则（合并现有硬编码规则）
- `get_skip_dirs() -> set[str]`：返回 skip_dirs 的 name 集合（供扫描函数直接使用）
- `get_skip_exts() -> set[str]`：返回 skip_exts 的 name 集合

### 修改 `code_parser.py` — `scan_directory()`

移除 `DEFAULT_SKIP_DIRS`、`DEFAULT_SKIP_EXTS`、`UNIVERSAL_SKIP_DIRS` 三个硬编码字典。
改为调用 `code_skip_rules.get_skip_dirs()` 和 `code_skip_rules.get_skip_exts()` 获取排除集合。

函数签名不变，`skip_dirs` / `skip_extensions` 参数保留（作为额外追加），但默认值从配置文件读取。

### 新增路由：`code_routes.py`

三个接口的路由处理。

## 前端实现

### 代码知识库 Tab — 新增「仓库设置」按钮

在代码知识库 Tab 的操作区新增一个齿轮/设置图标按钮，点击打开设置面板。

### 设置面板（模态框或侧边栏）

两个表格区域：

**排除目录表格**

| 目录名 | 分类 | 操作 |
|--------|------|------|
| .git | 版本控制 | [删除] |
| node_modules | 依赖 | [删除] |
| ... | ... | ... |

- 底部：输入框（目录名）+ 分类下拉选择 + [添加] 按钮
- 分类选项：版本控制、依赖、构建产物、IDE、资源、缓存、虚拟环境、第三方、自定义

**排除扩展名表格**

| 扩展名 | 分类 | 操作 |
|--------|------|------|
| .png | 图片 | [删除] |
| .json | 配置/数据 | [删除] |
| ... | ... | ... |

- 底部：输入框（扩展名）+ 分类下拉选择 + [添加] 按钮
- 分类选项：图片、字体、iOS/Mac资源、Android资源、配置/数据、自定义

**操作按钮**

- [恢复默认] — 调用 reset 接口，刷新表格
- [保存] — 调用 PUT 接口，保存成功后提示

## 数据流

```
用户编辑规则 → PUT /api/code/skip-rules → code_skip_rules.json
用户点击扫描 → scan_directory() → get_skip_dirs() + get_skip_exts() → 读取 code_skip_rules.json → 过滤文件
```

## 验证方式

1. 启动服务，打开代码知识库 Tab，点击「仓库设置」
2. 确认默认规则与现有硬编码规则一致
3. 添加/删除规则，保存后刷新页面确认持久化
4. 点击「恢复默认」确认回到初始状态
5. 扫描一个仓库，确认被排除的目录/扩展名确实未被索引
