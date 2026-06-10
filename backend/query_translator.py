"""查询翻译层 — 中文查询 → 英文代码关键词

优先级: 本地词典 > 缓存 > MyMemory API > LLM 翻译 > 完整查询回退
用于代码搜索场景：用户输入中文"登录"，翻译成 "login, signin, auth" 等英文符号关键词。

特性：
1. 缓存层：LLM/MyMemory 翻译结果持久化缓存（30天）
2. 自动扩充词典：翻译成功后自动添加到 TERM_MAP
3. 翻译流程展示：每步都有 Step 记录（方法、关键词、耗时）
"""

import re
import os
import asyncio
import requests
from typing import Optional
from dataclasses import dataclass, field

# ── 数据结构 ──────────────────────────────────────────────────────

@dataclass
class TranslationResult:
    """翻译结果"""
    original: str                     # 原始查询 "用户登录"
    translated: list[str]             # 翻译结果 ["user", "login", "signin"]
    method: str = "none"              # "cache" / "llm" / "mymemory" / "dict" / "none"
    confidence: float = 0.0           # 置信度 0-1
    duration_ms: float = 0.0          # 翻译耗时（毫秒）
    steps: list = field(default_factory=list)  # 翻译步骤详情
    suggestion: str = ""              # 建议（如 LLM 超时时建议走关键字搜索）


# ── 中文检测 ──────────────────────────────────────────────────────

_CN_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]+')


def has_chinese(text: str) -> bool:
    return bool(_CN_PATTERN.search(text)) if text else False


# ── 本地词典 ──────────────────────────────────────────────────────

# 高频中文 → 英文代码词根映射（邮箱大师场景优化）
TERM_MAP: dict[str, list[str]] = {
    # ── 认证/账号 ──
    "登录": ["login", "signin", "sign_in", "auth", "authenticate"],
    "注册": ["register", "signup", "sign_up"],
    "登出": ["logout", "signout", "sign_out"],
    "密码": ["password", "passwd", "pwd"],
    "账号": ["account"],
    "验证": ["verify", "validation", "auth"],
    "授权": ["authorize", "auth", "oauth"],
    "令牌": ["token"],
    # ── 邮件核心 ──
    "邮件": ["mail", "email", "message"],
    "收件": ["inbox", "receive"],
    "发件": ["send", "outbox", "sent"],
    "草稿": ["draft"],
    "附件": ["attachment", "attach"],
    "转发": ["forward"],
    "回复": ["reply"],
    "抄送": ["cc", "carbon_copy"],
    "密送": ["bcc"],
    "主题": ["subject"],
    "正文": ["body", "content"],
    "收件箱": ["inbox"],
    "已发送": ["sent", "outbox"],
    "草稿箱": ["drafts"],
    "未读": ["unread"],
    "已读": ["read"],
    "来信": ["incoming", "received"],
    "收信": ["receive", "fetch"],
    "发信": ["send", "compose"],
    "新邮件": ["new_mail", "new_message"],
    "退订": ["unsubscribe"],
    "订阅": ["subscribe", "subscription"],
    "通讯录": ["contacts", "address_book"],
    "待办": ["todo", "task"],
    # ── 操作 ──
    "下载": ["download"],
    "上传": ["upload"],
    "删除": ["delete", "remove"],
    "保存": ["save", "store"],
    "编辑": ["edit", "modify"],
    "搜索": ["search", "query"],
    "筛选": ["filter"],
    "排序": ["sort", "order"],
    "刷新": ["refresh", "reload"],
    "同步": ["sync", "synchronize"],
    "加载": ["load"],
    "推送": ["push", "notification"],
    "通知": ["notification", "notify"],
    "标记": ["flag", "mark", "tag"],
    "收藏": ["favorite", "bookmark", "star"],
    "归档": ["archive"],
    "移动": ["move"],
    "复制": ["copy"],
    "跳转": ["jump", "navigate", "redirect"],
    "切换": ["switch", "toggle"],
    "清除": ["clear", "reset"],
    "移除": ["remove", "delete"],
    "展开": ["expand", "unfold"],
    "折叠": ["collapse", "fold", "shrink"],
    "收起": ["collapse", "fold", "hide"],
    "置顶": ["pin", "sticky", "top"],
    "全选": ["select_all"],
    # ── UI 组件 ──
    "页面": ["page", "view", "screen"],
    "列表": ["list"],
    "详情": ["detail"],
    "设置": ["settings", "config", "preference"],
    "按钮": ["button", "btn"],
    "弹窗": ["dialog", "popup", "alert"],
    "菜单": ["menu"],
    "导航": ["nav", "navigation"],
    "标签": ["tab", "tag", "label"],
    "工具栏": ["toolbar"],
    "侧边栏": ["sidebar"],
    "状态栏": ["statusbar", "status_bar", "StatusBar", "statusBar"],
    "标题": ["title", "header"],
    "输入框": ["input", "textfield", "text_field", "TextInput"],
    "图标": ["icon", "Icon"],
    "图片": ["image", "img", "Image"],
    "头像": ["avatar", "Avatar"],
    "容器": ["container", "Container"],
    "面板": ["panel", "Panel"],
    "选择器": ["picker", "selector", "Picker", "Selector"],
    "卡片": ["card", "Card"],
    "角标": ["badge", "Badge"],
    "徽章": ["badge", "Badge"],
    "开关": ["switch", "toggle", "Switch", "Toggle"],
    "复选框": ["checkbox", "Checkbox"],
    "单选": ["radio", "Radio"],
    "分割线": ["divider", "separator", "Divider"],
    "提示条": ["toast", "snackbar", "Toast"],
    "进度条": ["progress", "Progress"],
    "滚动条": ["scrollbar", "Scrollbar"],
    "搜索栏": ["searchbar", "search_bar", "SearchBar"],
    "导航栏": ["navbar", "navigation_bar", "NavigationBar"],
    "底部栏": ["bottombar", "bottom_bar", "BottomBar"],
    "标签栏": ["tabbar", "tab_bar", "TabBar"],
    "浮动按钮": ["fab", "floating_action_button", "FloatingActionButton"],
    "网格": ["grid", "Grid"],
    "轮播": ["carousel", "swiper", "Carousel"],
    "抽屉": ["drawer", "Drawer"],
    "骨架屏": ["skeleton", "Skeleton"],
    "空状态": ["empty_state", "EmptyState"],
    "加载指示器": ["indicator", "spinner", "ActivityIndicator"],
    "下拉菜单": ["dropdown", "Dropdown"],
    "气泡": ["bubble", "tooltip", "Tooltip"],
    "遮罩": ["mask", "overlay", "Overlay"],
    # ── UI 属性/布局 ──
    "布局": ["layout", "Layout"],
    "圆角": ["border_radius", "cornerRadius", "BorderRadius"],
    "边距": ["margin", "Margin"],
    "间距": ["spacing", "gap", "Spacing"],
    "内边距": ["padding", "Padding"],
    "边框": ["border", "Border"],
    "阴影": ["shadow", "Shadow"],
    "透明": ["transparent", "opacity"],
    "透明度": ["opacity", "Opacity"],
    "背景色": ["background_color", "backgroundColor", "BackgroundColor"],
    "文字大小": ["font_size", "fontSize", "FontSize"],
    "字体": ["font", "font_family", "Font"],
    "高度": ["height", "Height"],
    "宽度": ["width", "Width"],
    "居中": ["center", "Center"],
    "对齐": ["align", "alignment", "Alignment"],
    "填充": ["fill", "padding", "Fill"],
    # ── UI 状态/交互 ──
    "焦点": ["focus", "Focus"],
    "选中": ["selected", "Selected"],
    "高亮": ["highlight", "Highlight"],
    "禁用": ["disabled", "Disabled"],
    "可见": ["visible", "Visible"],
    "隐藏": ["hidden", "Hidden"],
    "激活": ["active", "Active"],
    "动画": ["animation", "Animation"],
    "过渡": ["transition", "Transition"],
    "渐变": ["gradient", "Gradient"],
    "点击": ["click", "tap", "onTap"],
    "长按": ["long_press", "longPress", "onLongPress"],
    "滑动": ["swipe", "slide", "Swipe"],
    "拖拽": ["drag", "Drag"],
    "缩放": ["scale", "zoom", "Scale"],
    "键盘": ["keyboard", "Keyboard"],
    "返回": ["back", "return", "Back"],
    # ── 移动端 ──
    "沉浸式": ["immersive", "edge_to_edge"],
    "全屏": ["fullscreen", "FullScreen"],
    "横屏": ["landscape"],
    "竖屏": ["portrait"],
    "安全区": ["safe_area", "safeArea", "SafeArea"],
    "手势": ["gesture", "Gesture"],
    "系统栏": ["system_bars", "SystemChrome"],
    # ── 数据/状态 ──
    "数据": ["data", "Data"],
    "颜色": ["color", "Color"],
    "样式": ["style", "Style"],
    "皮肤": ["skin", "theme", "Theme"],
    "主题色": ["theme_color", "primary_color"],
    "模式": ["mode", "Mode"],
    "配置": ["config", "configuration", "Config"],
    "分页": ["pagination", "paging", "Pagination"],
    "占位": ["placeholder", "Placeholder"],
    "提示": ["hint", "tip", "Hint"],
    "提醒": ["alert", "reminder", "Alert"],
    "声音": ["sound", "Sound"],
    "振动": ["vibration", "haptic", "Haptic"],
    # ── 网络/存储 ──
    "网络": ["network", "http", "api"],
    "请求": ["request"],
    "响应": ["response"],
    "缓存": ["cache"],
    "数据库": ["database", "db"],
    "存储": ["storage", "store"],
    # ── 状态 ──
    "加载中": ["loading"],
    "错误": ["error", "err"],
    "成功": ["success"],
    "失败": ["fail", "failure"],
    "取消": ["cancel"],
    "确认": ["confirm", "ok"],
    "重试": ["retry"],
    "警告": ["warning", "warn"],
    # ── 其他 ──
    "用户": ["user"],
    "联系人": ["contact"],
    "文件夹": ["folder", "directory"],
    "签名": ["signature"],
    "模板": ["template"],
    "日志": ["log"],
    "版本": ["version"],
    "更新": ["update"],
    "帮助": ["help"],
    "管理": ["manage", "management", "Manage"],
    "权限": ["permission", "Permission"],
    "隐私": ["privacy", "Privacy"],
    "安全": ["security", "Security"],
    "会员": ["member", "vip", "Member"],
    "个性化": ["personalize", "customization"],
    "自定义": ["custom", "Custom"],
    "智能": ["smart", "intelligent"],
    "聚合": ["aggregate", "Aggregate"],
}


def _dict_translate(query: str) -> tuple[list[str], float]:
    """本地词典翻译

    策略：
    1. 整句匹配（"用户登录" → 精确匹配词典）
    2. jieba 分词后逐词匹配
    3. 未匹配的中文词跳过，已匹配的取英文词根
    """
    query = query.strip()
    if not query:
        return [], 0.0

    # 1. 整句精确匹配
    if query in TERM_MAP:
        return TERM_MAP[query], 0.9

    # 2. jieba 分词
    try:
        import jieba
        tokens = list(jieba.cut(query))
    except ImportError:
        # jieba 不可用，按字符拆分
        tokens = list(query)

    results = []
    matched_count = 0
    total_cn_words = 0

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if not has_chinese(token):
            # 非中文部分（英文、数字）直接保留
            results.append(token)
            matched_count += 1
            total_cn_words += 1
            continue

        total_cn_words += 1
        if token in TERM_MAP:
            results.extend(TERM_MAP[token])
            matched_count += 1
        else:
            # 子串回退：尝试把长词拆成词典里有的子词
            # 例如 "邮件附件" → "邮件" + "附件"
            sub_matches = _substring_match(token)
            if sub_matches:
                results.extend(sub_matches)
                matched_count += 1
            else:
                # 未匹配的中文词，保留原词（FTS5 还能搜中文 content）
                results.append(token)

    confidence = matched_count / max(total_cn_words, 1)
    # 如果没有匹配任何词典条目，返回空列表（让翻译流程继续走 MyMemory）
    if matched_count == 0:
        return [], 0.0
    return results, confidence


def _substring_match(text: str) -> list[str]:
    """对未匹配的中文词做子串回退匹配

    贪心最长匹配：从左到右，每次找词典里最长的匹配子串。
    例如 "邮件附件" → 先匹配 "邮件" (2字)，再匹配 "附件" (2字) → ["mail", "email", "attachment", "attach"]
    """
    results = []
    i = 0
    while i < len(text):
        best_match = None
        best_len = 0
        # 从当前位置开始，找最长的匹配子串
        for end in range(len(text), i, -1):
            substr = text[i:end]
            if substr in TERM_MAP:
                best_match = substr
                best_len = end - i
                break
        if best_match:
            results.extend(TERM_MAP[best_match])
            i += best_len
        else:
            i += 1  # 跳过未匹配的单字
    return results


# ── MyMemory API 翻译 ────────────────────────────────────────────

def _mymemory_translate(query: str) -> tuple[list[str], float]:
    """调用 MyMemory API 翻译中文查询

    免费额度：5000 字符/天（匿名）
    速度：~2 秒
    """
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": query,
            "langpair": "zh|en"
        }

        response = requests.get(url, params=params, timeout=2)
        if response.status_code != 200:
            return [], 0.0

        data = response.json()
        if data.get("responseStatus") != 200:
            return [], 0.0

        translated_text = data["responseData"]["translatedText"]
        if not translated_text:
            return [], 0.0

        # 解析翻译结果（逗号分隔或空格分隔）
        keywords = []
        for kw in re.split(r'[,，\s]+', translated_text):
            kw = kw.strip().strip('"').strip("'").strip("`")
            kw = re.sub(r'[^a-zA-Z0-9_]', '', kw)  # 只保留英文+数字+下划线
            if kw and len(kw) >= 2:
                keywords.append(kw.lower())

        return keywords[:5], 0.8 if keywords else 0.0

    except Exception as e:
        print(f"[query_translator] MyMemory 翻译失败: {e}")
        return [], 0.0


# ── LLM 翻译 ─────────────────────────────────────────────────────

_TRANSLATE_PROMPT = """你是一个代码搜索助手。把用户的中文查询翻译成代码中常见的英文符号名/关键词。

规则：
1. 返回逗号分隔的英文关键词，不要解释
2. 包含常见的类名/方法名词根
3. 最多返回 5 个关键词
4. 只返回英文，不要中文

示例：
输入：登录
输出：login, signin, auth, authenticate, account

输入：邮件附件下载
输出：attachment, download, mail, email, file

输入：{query}
输出："""


async def _llm_translate(query: str) -> tuple[list[str], float]:
    """调用 LLM 翻译中文查询"""
    try:
        from llm_client import get_llm_client
        client = get_llm_client()

        prompt = _TRANSLATE_PROMPT.format(query=query)
        messages = [{"role": "user", "content": prompt}]

        response = await client.chat(messages, stream=False)
        if not response:
            return [], 0.0

        # 解析逗号分隔的关键词
        keywords = []
        for kw in response.strip().split(","):
            kw = kw.strip().strip('"').strip("'").strip("`")
            kw = re.sub(r'[^a-zA-Z0-9_]', '', kw)  # 只保留英文+数字+下划线
            if kw and len(kw) >= 2:
                keywords.append(kw.lower())

        return keywords[:5], 0.95 if keywords else 0.0

    except Exception as e:
        print(f"[query_translator] LLM 翻译失败: {e}")
        return [], 0.0


# ── 主入口（带 StepTracker）──────────────────────────────────────

async def translate_query_async(
    query: str,
    use_llm: bool = True,
    timeout: float = 5.0,
    tracker=None,  # StepTracker 实例
) -> TranslationResult:
    """异步翻译入口（带步骤追踪）

    翻译流程顺序：
    1. 本地词典 + 缓存（快速路径）
    2. MyMemory API（第三方翻译）
    3. LLM 翻译（最后手段）
    4. 完整查询回退（FTS5 搜索中文）

    Args:
        query: 原始查询（可能含中文）
        use_llm: 是否尝试 LLM 翻译
        timeout: LLM 调用超时秒数
        tracker: StepTracker 实例，用于记录翻译步骤
    """
    import time
    start_time = time.time()

    query = query.strip()
    if not query or not has_chinese(query):
        return TranslationResult(
            original=query,
            translated=[query],
            method="none",
            confidence=1.0,
            duration_ms=0,
        )

    steps = []

    # ── Step 1: 本地词典 ──────────────────────────────────────
    step_dict = None
    if tracker:
        step_dict = tracker.add_step("dict_translate", "查询翻译: 本地词典")
        step_dict.start()

    dict_start = time.time()
    keywords, confidence = _dict_translate(query)
    dict_duration = (time.time() - dict_start) * 1000

    if keywords:
        step_info = {
            "method": "dict",
            "keywords": keywords,
            "confidence": confidence,
            "duration_ms": dict_duration,
        }
        steps.append(step_info)

        if tracker and step_dict:
            step_dict.complete(step_info)

        # 写入缓存
        from translation_cache import get_cache
        cache = get_cache()
        cache.set(query, keywords, "dict", confidence)

        duration_ms = (time.time() - start_time) * 1000
        return TranslationResult(
            original=query,
            translated=keywords,
            method="dict",
            confidence=confidence,
            duration_ms=duration_ms,
            steps=steps,
        )

    if tracker and step_dict:
        step_dict.complete({"keywords": [], "reason": "词典无匹配"})

    # ── Step 2: 检查缓存 ──────────────────────────────────────
    step_cache = None
    if tracker:
        step_cache = tracker.add_step("translation_cache", "查询翻译: 检查缓存")
        step_cache.start()

    from translation_cache import get_cache
    cache = get_cache()
    cached = cache.get(query)

    if cached:
        duration_ms = (time.time() - start_time) * 1000
        step_info = {
            "method": "cache",
            "keywords": cached.keywords,
            "confidence": cached.confidence,
            "duration_ms": duration_ms,
        }
        steps.append(step_info)

        if tracker and step_cache:
            step_cache.complete(step_info)

        return TranslationResult(
            original=query,
            translated=cached.keywords,
            method="cache",
            confidence=cached.confidence,
            duration_ms=duration_ms,
            steps=steps,
        )

    if tracker and step_cache:
        step_cache.complete({"hit": False})

    # ── Step 3: MyMemory API 翻译 ─────────────────────────────
    step_mymemory = None
    if tracker:
        step_mymemory = tracker.add_step("mymemory_translate", "查询翻译: MyMemory API")
        step_mymemory.start()

    try:
        mymemory_start = time.time()
        keywords, confidence = await asyncio.to_thread(_mymemory_translate, query)
        mymemory_duration = (time.time() - mymemory_start) * 1000

        if keywords:
            step_info = {
                "method": "mymemory",
                "keywords": keywords,
                "confidence": confidence,
                "duration_ms": mymemory_duration,
            }
            steps.append(step_info)

            if tracker and step_mymemory:
                step_mymemory.complete(step_info)

            # 写入缓存
            cache.set(query, keywords, "mymemory", confidence, auto_added=True)
            # 自动扩充词典
            cache.add_to_dict(query, keywords)

            duration_ms = (time.time() - start_time) * 1000
            return TranslationResult(
                original=query,
                translated=keywords,
                method="mymemory",
                confidence=confidence,
                duration_ms=duration_ms,
                steps=steps,
            )

        if tracker and step_mymemory:
            step_mymemory.complete({"keywords": [], "reason": "MyMemory 返回空"})

    except Exception as e:
        mymemory_duration = (time.time() - mymemory_start) * 1000
        step_info = {
            "method": "mymemory",
            "keywords": [],
            "confidence": 0.0,
            "duration_ms": mymemory_duration,
            "error": str(e),
        }
        steps.append(step_info)

        if tracker and step_mymemory:
            step_mymemory.fail(str(e))

    # ── Step 4: LLM 翻译 ──────────────────────────────────────
    step_llm = None
    if use_llm:
        if tracker:
            step_llm = tracker.add_step("llm_translate", "查询翻译: LLM 翻译 (MiMo)")
            step_llm.start()

        llm_start = time.time()
        try:
            llm_start = time.time()
            keywords, confidence = await asyncio.wait_for(
                _llm_translate(query),
                timeout=timeout,
            )
            llm_duration = (time.time() - llm_start) * 1000

            if keywords:
                step_info = {
                    "method": "llm",
                    "keywords": keywords,
                    "confidence": confidence,
                    "duration_ms": llm_duration,
                }
                steps.append(step_info)

                if tracker and step_llm:
                    step_llm.complete(step_info)

                # 写入缓存
                cache.set(query, keywords, "llm", confidence, auto_added=True)
                # 自动扩充词典
                cache.add_to_dict(query, keywords)

                duration_ms = (time.time() - start_time) * 1000
                return TranslationResult(
                    original=query,
                    translated=keywords,
                    method="llm",
                    confidence=confidence,
                    duration_ms=duration_ms,
                    steps=steps,
                )

            if tracker and step_llm:
                step_llm.complete({"keywords": [], "reason": "LLM 返回空"})

        except asyncio.TimeoutError:
            llm_duration = (time.time() - llm_start) * 1000
            step_info = {
                "method": "llm",
                "keywords": [],
                "confidence": 0.0,
                "duration_ms": llm_duration,
                "error": f"超时 ({timeout}s)",
                "suggestion": "英文语义匹配失败，建议走关键字搜索",
            }
            steps.append(step_info)

            if tracker and step_llm:
                step_llm.fail(f"超时 ({timeout}s)")

        except Exception as e:
            llm_duration = (time.time() - llm_start) * 1000
            step_info = {
                "method": "llm",
                "keywords": [],
                "confidence": 0.0,
                "duration_ms": llm_duration,
                "error": str(e),
            }
            steps.append(step_info)

            if tracker and step_llm:
                step_llm.fail(str(e))

    # ── Step 5: 最终降级：完整查询回退 ─────────────────────────
    step_fallback = None
    if tracker:
        step_fallback = tracker.add_step("fallback", "查询翻译: 完整查询回退")
        step_fallback.start()

    fallback_keywords = [query]  # 保留完整查询，让 FTS5 搜索中文 content
    fallback_duration = 0.0

    step_info = {
        "method": "fallback",
        "keywords": fallback_keywords,
        "confidence": 0.0,
        "duration_ms": fallback_duration,
        "suggestion": "英文语义匹配失败，建议走关键字搜索",
    }
    steps.append(step_info)

    if tracker and step_fallback:
        step_fallback.complete(step_info)

    duration_ms = (time.time() - start_time) * 1000
    return TranslationResult(
        original=query,
        translated=fallback_keywords,
        method="fallback",
        confidence=0.0,
        duration_ms=duration_ms,
        steps=steps,
        suggestion="英文语义匹配失败，建议走关键字搜索",
    )


def translate_query_sync(query: str, use_llm: bool = True, timeout: float = 5.0, tracker=None) -> TranslationResult:
    """同步包装（给非 async 上下文用）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已有 event loop（FastAPI 内），使用 nest_asyncio
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(
                translate_query_async(query, use_llm=use_llm, timeout=timeout, tracker=tracker)
            )
        else:
            # 没有 event loop，直接运行
            return asyncio.run(
                translate_query_async(query, use_llm=use_llm, timeout=timeout, tracker=tracker)
            )
    except RuntimeError:
        # 已有 event loop 的情况（FastAPI 内），降级到纯词典
        from translation_cache import get_cache
        cache = get_cache()

        # 检查缓存
        cached = cache.get(query)
        if cached:
            return TranslationResult(
                original=query,
                translated=cached.keywords,
                method="cache",
                confidence=cached.confidence,
                steps=[{"method": "cache", "keywords": cached.keywords, "confidence": cached.confidence, "duration_ms": 0}],
            )

        # 降级到词典
        keywords, confidence = _dict_translate(query)
        return TranslationResult(
            original=query,
            translated=keywords or [query],
            method="dict",
            confidence=confidence,
            steps=[{"method": "dict", "keywords": keywords or [query], "confidence": confidence, "duration_ms": 0}],
        )


# ── 快速测试 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "登录"
    print(f"查询: {q}")
    print(f"含中文: {has_chinese(q)}")

    # 词典翻译
    kw, conf = _dict_translate(q)
    print(f"词典翻译: {kw} (置信度: {conf:.2f})")

    # 完整翻译流程
    result = translate_query_sync(q, use_llm=True, timeout=5.0)
    print(f"最终结果: {result}")
