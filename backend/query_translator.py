"""查询翻译层 — 中文查询 → 英文代码关键词

优先级: LLM 翻译 > 本地词典 > jieba 分词降级
用于代码搜索场景：用户输入中文"登录"，翻译成 "login, signin, auth" 等英文符号关键词。
"""

import re
import os
import asyncio
from typing import Optional
from dataclasses import dataclass, field

# ── 数据结构 ──────────────────────────────────────────────────────

@dataclass
class TranslationResult:
    """翻译结果"""
    original: str                     # 原始查询 "用户登录"
    translated: list[str]             # 翻译结果 ["user", "login", "signin"]
    method: str = "none"              # "llm" / "dict" / "none"
    confidence: float = 0.0           # 置信度 0-1


# ── 中文检测 ──────────────────────────────────────────────────────

_CN_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]+')


def has_chinese(text: str) -> bool:
    return bool(_CN_PATTERN.search(text)) if text else False


# ── 本地词典 ──────────────────────────────────────────────────────

# 高频中文 → 英文代码词根映射（邮箱大师场景优化）
TERM_MAP: dict[str, list[str]] = {
    # 认证/账号
    "登录": ["login", "signin", "sign_in", "auth", "authenticate"],
    "注册": ["register", "signup", "sign_up"],
    "登出": ["logout", "signout", "sign_out"],
    "密码": ["password", "passwd", "pwd"],
    "账号": ["account"],
    "验证": ["verify", "validation", "auth"],
    "授权": ["authorize", "auth", "oauth"],
    "令牌": ["token"],
    # 邮件核心
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
    # 操作
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
    # UI
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
    "标题": ["title", "header"],
    # 网络/存储
    "网络": ["network", "http", "api"],
    "请求": ["request"],
    "响应": ["response"],
    "缓存": ["cache"],
    "数据库": ["database", "db"],
    "存储": ["storage", "store"],
    # 状态
    "加载中": ["loading"],
    "错误": ["error", "err"],
    "成功": ["success"],
    "失败": ["fail", "failure"],
    "取消": ["cancel"],
    "确认": ["confirm", "ok"],
    "重试": ["retry"],
    # 其他
    "用户": ["user"],
    "联系人": ["contact"],
    "文件夹": ["folder", "directory"],
    "签名": ["signature"],
    "模板": ["template"],
    "日志": ["log"],
    "版本": ["version"],
    "更新": ["update"],
    "帮助": ["help"],
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


# ── 主入口 ────────────────────────────────────────────────────────

async def translate_query_async(
    query: str,
    use_llm: bool = True,
    timeout: float = 3.0,
) -> TranslationResult:
    """异步翻译入口

    Args:
        query: 原始查询（可能含中文）
        use_llm: 是否尝试 LLM 翻译
        timeout: LLM 调用超时秒数
    """
    query = query.strip()
    if not query or not has_chinese(query):
        return TranslationResult(
            original=query,
            translated=[query],
            method="none",
            confidence=1.0,
        )

    # 1. 尝试 LLM 翻译
    if use_llm:
        try:
            keywords, confidence = await asyncio.wait_for(
                _llm_translate(query),
                timeout=timeout,
            )
            if keywords:
                return TranslationResult(
                    original=query,
                    translated=keywords,
                    method="llm",
                    confidence=confidence,
                )
        except asyncio.TimeoutError:
            print(f"[query_translator] LLM 翻译超时 ({timeout}s)，降级到词典")
        except Exception as e:
            print(f"[query_translator] LLM 翻译异常: {e}，降级到词典")

    # 2. 降级到本地词典
    keywords, confidence = _dict_translate(query)
    if keywords:
        return TranslationResult(
            original=query,
            translated=keywords,
            method="dict",
            confidence=confidence,
        )

    # 3. 最终降级：返回原查询
    return TranslationResult(
        original=query,
        translated=[query],
        method="none",
        confidence=0.0,
    )


def translate_query_sync(query: str, use_llm: bool = True, timeout: float = 3.0) -> TranslationResult:
    """同步包装（给非 async 上下文用）"""
    try:
        return asyncio.run(
            translate_query_async(query, use_llm=use_llm, timeout=timeout)
        )
    except RuntimeError:
        # 已有 event loop 的情况（FastAPI 内），降级到纯词典
        keywords, confidence = _dict_translate(query)
        return TranslationResult(
            original=query,
            translated=keywords or [query],
            method="dict",
            confidence=confidence,
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

    # LLM 翻译
    result = translate_query_sync(q, use_llm=True, timeout=5.0)
    print(f"最终结果: {result}")
