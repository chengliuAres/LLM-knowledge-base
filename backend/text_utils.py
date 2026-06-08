"""中文文本处理工具 — jieba 分词 + FTS5 查询适配

用于修复 FTS5 unicode61 tokenizer 无法正确分词中文的问题。
unicode61 将连续中文视为单个 token（"用户登录页面" 是一个 token），
导致搜索"登录"无法匹配。使用 jieba 分词后在中文间插入空格，
让 unicode61 tokenizer 能正确切出独立的中文词。
"""

import re
import jieba

# 中文字符范围（含 CJK 统一表意文字 + 扩展区）
_CN_CHAR = re.compile(r'[一-龥㐀-䶿豈-﫿]+')


def segment_for_fts(text: str) -> str:
    """对中文内容进行 jieba 分词，在词之间插入空格。

    让 FTS5 unicode61 tokenizer 将每个中文词作为独立 token 索引。
    非中文部分（英文、代码等）原样保留。

    Example:
        "用户登录页面控制器" → "用户 登录 页面 控制器"
        "func login() { /* 登录 */ }" → "func login() { /* 登录 */ }"
    """
    if not text:
        return text

    def _segment(m: re.Match) -> str:
        cn_block = m.group(0)
        return ' '.join(jieba.cut(cn_block))

    return _CN_CHAR.sub(_segment, text)


def segment_query_for_match(query: str) -> str:
    """为 FTS5 MATCH 准备中文查询。

    对中文查询：jieba 分词 → 每个词加双引号 → OR 连接。
    纯英文/代码查询原样返回。

    Example:
        "登录" → '"登录"'
        "用户登录" → '"用户" OR "登录"'
        "GHMailListCellModel" → "GHMailListCellModel"
    """
    if not query or not query.strip():
        return query

    has_cn = bool(_CN_CHAR.search(query))
    if not has_cn:
        return query

    tokens = list(jieba.cut(query))
    terms = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if _CN_CHAR.search(t):
            terms.append(f'"{t}"')
        else:
            terms.append(t)

    return ' OR '.join(terms) if terms else query


def has_chinese(text: str) -> bool:
    """检查文本是否包含中文字符"""
    if not text:
        return False
    return bool(_CN_CHAR.search(text))
