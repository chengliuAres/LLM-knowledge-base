# Android 开发学习报告：我的页面设置区改造

> 基于 `feature/mine_func_entry` 分支实战代码，梳理业务逻辑与 Android 开发技术要点。
> 生成日期：2026-05-15

---

## 一、业务概览

### 1.1 做了什么

将「我的」Tab 页中的**设置区**从**单列平铺**改造为 **5 分组布局**，新增 **7 个 Flutter 功能入口**，并扩展后端 Handler 支持。

### 1.2 5 个分组

| 分组 | 包含功能 |
|------|---------|
| 通知 | 通知管理、重要邮件提醒 |
| 邮件查看 | 邮件列表显示、标签管理、邮件聚合、黑白名单、小组件、更多查看设置 |
| 邮件发送 | 邮件追踪 |
| 皮肤外观 | 自定义皮肤、自定义启动页、自定义图标、语言文字 |
| 更多设置 | 待办设置、设置 |

### 1.3 核心路由：Native ↔ Flutter 混合架构

本项目是 **Native（Android）+ Flutter 混合开发** 的邮件客户端。设置区的大多数入口跳转到 Flutter 页面，少数跳转原生页面或 H5。

```
┌─────────────────────────────────────────────────────┐
│  Android Native (Kotlin/Java)                      │
│  ┌───────────────────────────────────────────────┐ │
│  │  MineFuncListAdapter (RecyclerView)           │ │
│  │  ├─ SettingGroup 1..5                         │ │
│  │  │  ├─ GroupTitle (ViewType=1)                │ │
│  │  │  └─ SettingItem (ViewType=0)               │ │
│  │  │     └─ SettingAction                       │ │
│  │  │        ├─ Router → ARouter → Flutter Page  │ │
│  │  │        └─ Method → Native Activity / H5    │ │
│  └───────────────────────────────────────────────┘ │
│                         │                          │
│                    ARouter 路由                      │
│                         │                          │
│  ┌───────────────────────────────────────────────┐ │
│  │  Flutter 引擎                                  │ │
│  │  ├─ setting/blackAndWhitePage                 │ │
│  │  ├─ setting/LanguageTextPage                  │ │
│  │  ├─ setting/MailAggregationSettingPage         │ │
│  │  └─ ... 更多 Flutter 页面                     │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 二、Android 开发技术要点

### 2.1 RecyclerView 多 ViewType 模式

这是本次改造最核心的 Android 技术点。

**改造前**：所有 Cell 共用一种布局 (`item_mine_page_func`)，设置项平铺。

**改造后**：引入分组标题 Cell + 普通设置项 Cell，通过 `getItemViewType()` 区分。

```kotlin
// 1. 定义 ViewType 常量
companion object {
    private const val VIEW_TYPE_NORMAL = 0      // 普通设置项
    private const val VIEW_TYPE_GROUP_TITLE = 1  // 分组标题
}

// 2. 按 position 计算 ViewType
override fun getItemViewType(position: Int): Int {
    if (!isSettingsMode()) return VIEW_TYPE_NORMAL
    var p = position
    for (group in groups) {
        if (p == 0) return VIEW_TYPE_GROUP_TITLE  // 每组第一个是标题
        p--
        if (p < group.items.size) return VIEW_TYPE_NORMAL
        p -= group.items.size
    }
    return VIEW_TYPE_NORMAL
}

// 3. 按 ViewType 创建不同的 ViewHolder
override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
    return if (viewType == VIEW_TYPE_GROUP_TITLE) {
        GroupTitleViewHolder(inflater.inflate(R.layout.item_mine_group_title, parent, false))
    } else {
        ViewHolder(inflater.inflate(R.layout.item_mine_page_func, parent, false))
    }
}

// 4. 绑定也分流
override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
    if (isSettingsMode()) {
        bindSettingsItem(holder, position)  // 设置区有自己的绑定逻辑
    } else {
        bindFuncItem(holder as ViewHolder, position)  // 功能区走原来的
    }
}
```

**关键学习点**：
- `getItemViewType()` 必须覆盖所有 position，返回值决定 `onCreateViewHolder` 用哪个布局
- Adapter 泛型从 `RecyclerView.Adapter<ViewHolder>` 变为 `RecyclerView.Adapter<RecyclerView.ViewHolder>`，因为现在有**两种 ViewHolder 类型**
- 分组标题和内容项通过 position → (groupIndex, itemIndex) 的映射来关联数据

### 2.2 分组数据模型设计（Kotlin data class + sealed class）

```kotlin
// 分组模型
private data class SettingGroup(
    val title: String,        // 分组标题（如"通知"）
    val items: List<SettingItem>
)

// 设置项模型
private data class SettingItem(
    val type: SettingItemType,  // 枚举：区分业务类型
    val title: String,          // 显示标题
    val icon: Int,              // 图标资源 ID
    val action: SettingAction   // 点击行为
)

// 点击行为：用 sealed class 实现「路由跳转」和「纯方法执行」两个分支
private sealed class SettingAction {
    data class Router(
        val route: String,                    // Flutter 路由
        val extraAction: (() -> Unit)? = null // 附带操作（如埋点）
    ) : SettingAction()

    data class Method(
        val action: () -> Unit  // 纯方法（跳转原生页面、打开H5等）
    ) : SettingAction()
}
```

**关键学习点**：
- `sealed class` 是 Kotlin 的「受限继承」——所有子类必须在**同一个文件**内声明，编译器能穷举，配合 `when` 表达式可以做到**无遗漏分支检查**
- `data class` 自动生成 `equals()/hashCode()/toString()/copy()`，适合做数据容器
- 把点击行为抽象为 `SettingAction`，让数据生成和 UI 绑定解耦

### 2.3 卡片圆角连续背景实现

设置区是一个**连续的白色卡片**，只有顶部和底部有圆角，中间每组有标题分隔。实现方式：

```kotlin
// position → (groupIndex, itemIndex) 映射
private fun resolveSettingsPosition(groups: List<SettingGroup>, position: Int): Pair<Int, Int>? {
    var p = position
    for ((gi, group) in groups.withIndex()) {
        if (p == 0) return gi to -1   // itemIndex=-1 表示是标题
        p--
        if (p < group.items.size) return gi to p
        p -= group.items.size
    }
    return null
}

// 绑定圆角逻辑
if (itemIndex == -1) {
    // 标题行：只有第一个有顶部圆角
    if (position == 0) {
        titleHolder.fl_root.setSpecialCorner(radius, radius, 0, 0)
    } else {
        titleHolder.fl_root.setSpecialCorner(0, 0, 0, 0)
    }
    titleHolder.fl_root.setShadowHiddenBottom(true)  // 隐藏底部阴影，视觉连续
} else {
    // 内容行：只有最后一个有底部圆角
    if (isLastOverall) {
        viewHolder.fl_root.setSpecialCorner(0, 0, radius, radius)
        viewHolder.fl_root.setShadowHiddenBottom(false)
    } else {
        viewHolder.fl_root.setSpecialCorner(0, 0, 0, 0)
        viewHolder.fl_root.setShadowHiddenBottom(true)
    }
}
```

**关键学习点**：
- `ShadowLayout` 是项目自定义的阴影容器，支持单独控制四个角的圆角 (`setSpecialCorner(topLeft, topRight, bottomRight, bottomLeft)`)
- `setShadowHiddenBottom(true)` 隐藏中间 Cell 的底部阴影，让视觉上各组连续不断开
- `12.dp` — 项目用 Kotlin 扩展属性把 dp 值转 px：`val Int.dp: Int get() = ...`

### 2.4 Kotlin 扩展函数/属性的使用

项目中大量用 Kotlin 扩展简化代码：

```kotlin
// dp 转换扩展
val radius = 12.dp              // Int.dp 扩展属性
setTitleLp(viewHolder.tv_title, 16f.dp)  // Float.dp 扩展属性

// View 可见性扩展函数
viewHolder.tv_tag.visible()     // 等价于 visibility = View.VISIBLE
viewHolder.tv_sub_title.gone()  // 等价于 visibility = View.GONE
viewHolder.tv_tag.isVisible     // 等价于 visibility == View.VISIBLE
```

**关键学习点**：Kotlin 扩展函数/属性可以给已有类（包括 Android SDK 类）添加新方法，语法简洁，不影响原有类结构。这是 Kotlin 相比 Java 的显著优势。

### 2.5 ARouter 路由：Native 跳转 Flutter

Native 跳转 Flutter 的统一方式：

```kotlin
// FlutterRouterPath.Page 中定义路由常量
interface Page {
    String PATH = "/flutter"
    String KEY_ROUTE = "route"
    String KEY_PARAM = "params"

    String PAGE_blackAndWhitePage = "setting/blackAndWhitePage"
    String PAGE_LanguageTextPage = "setting/LanguageTextPage"
    String PAGE_MailAggregationSettingPage = "setting/MailAggregationSettingPage"
}

// 执行跳转
ARouter.getInstance().build(FlutterRouterPath.Page.PATH)
    .withString(FlutterRouterPath.Page.KEY_ROUTE, action.route)
    .navigation(context)
```

**关键学习点**：
- ARouter 是阿里开源的路由框架，用于组件化解耦
- 所有 Flutter 页面通过统一的 `/flutter` 路径进入，具体页面由 `KEY_ROUTE` 参数区分
- 路由常量集中定义在 `FlutterRouterPath.Page` 接口中，方便 Flutter 端同步

### 2.6 Flutter Channel Handler 模式（Native ↔ Flutter 双向通信）

Flutter 页面需要调用 Native 能力时，通过 Method Channel 发消息，Native 侧由 Handler 处理：

```java
// 注册 Handler
handler.RegisterSubHandler(
    "MailAggregationSettingPage",          // Flutter 页面名
    new FlutterCallHandlerAggregation()    // 对应的 Handler
);

// Handler 中处理 Flutter 调用
public boolean onMethodCall(MethodCall methodCall, FlutterCallResult result) {
    switch (methodCall.method) {
        case "allSenderAggregationSwitch":
            setAllSenderAggregationSwitch(params, result);
            return true;
        case "showAggregationAboutView":
            showAggregationAboutView();
            result.success("{}");
            return true;
    }
}
```

**关键学习点**：
- Flutter 和 Native 通过 Method Channel 通信，`method` 字段区分操作
- 每个 Flutter 页面对应一个 Handler 实例，一个 Handler 可以处理多个 method
- 返回结果通过 `result.success(jsonString)` 回传给 Flutter
- 同一个 Handler 类可以注册到多个页面（`FlutterCallHandlerAggregation` 被注册到两个不同的 PAGE_NAME）

### 2.7 条件渲染与 AB 测试

```kotlin
// 按条件展示
if (supportedTagAccounts.isNotEmpty()) { /* 显示标签管理 */ }
if (blackListAction != null) { /* 显示黑白名单 */ }
if (ABTestManager.getInstance().shouldEnableDesktopWidget()) { /* 显示小组件 */ }
```

**关键学习点**：
- `ABTestManager` 是项目内部的 AB 测试/灰度开关管理器
- 黑白名单的「智能路由」：有网易系账号时走 Flutter 统一账号列表页，没有则不展示入口

### 2.8 埋点统计模式

每个设置项的**曝光**和**点击**都记录埋点：

```kotlin
// 首次曝光埋点（只报一次）
if (!isShownSetting) {
    isShownSetting = true
    MinePageStatisticsHelper.recordMineSettingDisplay()
}

// 点击埋点（按 funcType 区分）
val funcType = when (settingItem.type) {
    SettingItemType.MAIL_GATHER -> "mail_gather"
    SettingItemType.BLACKLIST -> "blacklist"
    // ...
}
MinePageStatisticsHelper.recordMineSettingClick(funcType)
```

**关键学习点**：用 `isShownSetting` 标记防止重复曝光；点击埋点按业务类型枚举值映射到字符串标识。

---

## 三、项目架构模式

### 3.1 组件化模块结构

```
biz_core/           ← 核心路由、基础服务定义
master/             ← 主工程（UI、业务实现）
master-design/      ← UI 组件库（ShadowLayout 等）
```

`FlutterRouterPath` 放在 `biz_core`（路由常量），`MineFuncListAdapter` 放在 `master`（具体 UI），体现了基础层和业务层的分离。

### 3.2 改造原则（实际执行中体现的）

| 原则 | 体现 |
|------|------|
| **不改数据源** | `funcList` 结构不变，Adapter 内部做分组转换 |
| **保留旧逻辑** | SKIN_CUSTOM 的「来个好彩头」tag、WIDGET 的「NEW」角标逻辑完整保留 |
| **扩展而非重写** | 新增 `bindSettingsItem()` 方法处理设置区，原有的 `bindFuncItem()` 不动 |
| **缓存避免重复计算** | `settingGroups` 缓存，`setList()` 时清空 |

---

## 四、涉及的核心文件

| 文件 | 改动类型 | 关键内容 |
|------|---------|---------|
| `MineFuncListAdapter.kt` | 重构 | 多 ViewType、分组数据模型、圆角逻辑 |
| `FlutterRouterPath.java` | 新增 3 行 | 路由常量定义 |
| `FlutterCallHandlerAggregation.java` | 新增 ~50 行 | Flutter Method Channel Handler |
| `FlutterServiceImpl.java` | 新增 3 行 | Handler 注册 |
| `item_mine_group_title.xml` | 新建 | 分组标题布局 |
| `strings.xml` | 新增 14 条 | 分组标题、入口名称 |
| 30+ 图标资源 | 新增/替换 | 按密度分布（hdpi~xxxhdpi + night） |

---

## 五、总结：这次能学到的 Android 技能清单

| 技能 | 难度 | 说明 |
|------|------|------|
| RecyclerView 多 ViewType | ⭐⭐⭐ | 分组列表的核心实现方式 |
| Kotlin sealed class | ⭐⭐ | 类型安全的穷举，替代 enum + 分支 |
| Kotlin data class | ⭐ | 数据容器的标准写法 |
| Kotlin 扩展函数/属性 | ⭐ | 简化 Android SDK 调用 |
| ARouter 路由 | ⭐⭐ | 组件化跳转 |
| Flutter-Native 混合通信 | ⭐⭐⭐ | Method Channel + Handler 模式 |
| ShadowLayout 圆角卡片 | ⭐ | 自定义 View 的圆角阴影控制 |
| 埋点统计模式 | ⭐ | 曝光去重 + 点击枚举映射 |
| AB 测试开关 | ⭐ | 灰度发布基础设施 |
| dp 密度适配 | ⭐ | 资源按 hdpi/xhdpi/xxhdpi/xxxhdpi 分布 |
