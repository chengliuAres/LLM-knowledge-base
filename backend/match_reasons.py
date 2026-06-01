"""搜索结果归因 - 解释每条结果为什么被匹配上"""

import re
from typing import Optional

CN_CHAR = re.compile(r"[\u4e00-\u9fa5]+")
EN_TOKEN = re.compile(r"[a-zA-Z0-9]+")


def tokenize(query: str) -> list[str]:
    """混合分词：英文按 \\W+ 切（≥2字符），中文取 2-gram；不引入 jieba"""
    tokens: list[str] = []
    for m in EN_TOKEN.findall(query):
        if len(m) >= 2:
            tokens.append(m.lower())
    for chunk in CN_CHAR.findall(query):
        for i in range(len(chunk) - 1):
            tokens.append(chunk[i:i + 2])
    return list(dict.fromkeys(tokens))


def explain_match(
    query: str,
    content: str,
    score: float,
    metadata: Optional[dict] = None,
) -> dict:
    """归因一条搜索结果。返回 {reasons:[{type,label,color}], hit_keywords:[...]}

    - reasons 用于前端 badge 渲染
    - hit_keywords 用于前端 content 高亮（不含整句的精确匹配，避免与 token 高亮重复）
    """
    metadata = metadata or {}
    q = (query or "").strip()
    q_lower = q.lower()
    c_lower = (content or "").lower()

    reasons: list[dict] = []
    hit_keywords: list[str] = []

    if q_lower and q_lower in c_lower:
        reasons.append({"type": "exact_match", "label": "完全包含", "color": "red"})
        hit_keywords.append(q)

    tokens = tokenize(q)
    if tokens:
        hits = [t for t in tokens if t in c_lower]
        if hits:
            reasons.append({
                "type": "keyword_hit",
                "label": f"关键词 {len(hits)}/{len(tokens)}",
                "color": "amber",
            })
            hit_keywords.extend(hits)

    if score >= 0.7:
        reasons.append({"type": "semantic_strong", "label": "强语义相似", "color": "blue"})
    elif score >= 0.5:
        reasons.append({"type": "semantic_medium", "label": "中度语义相似", "color": "indigo"})
    elif score >= 0.3:
        reasons.append({"type": "semantic_weak", "label": "弱语义相似", "color": "slate"})

    if isinstance(metadata, dict):
        subject = str(metadata.get("subject") or "").lower()
        sender_name = str(metadata.get("sender_name") or "").lower()
        sender = str(metadata.get("sender") or "").lower()
        if q_lower:
            if subject and q_lower in subject:
                reasons.append({"type": "subject_match", "label": "标题命中", "color": "purple"})
            if (sender_name and q_lower in sender_name) or (sender and q_lower in sender):
                reasons.append({"type": "sender_match", "label": "发件人命中", "color": "green"})

    seen, dedup_kw = set(), []
    for kw in hit_keywords:
        k = kw.lower()
        if k and k not in seen:
            seen.add(k)
            dedup_kw.append(kw)

    return {"reasons": reasons, "hit_keywords": dedup_kw}


def annotate_results(query: str, results: list[dict]) -> list[dict]:
    """批量给一组搜索结果附加 match_reasons + hit_keywords，原地修改并返回"""
    for r in results:
        explanation = explain_match(
            query=query,
            content=r.get("content", ""),
            score=r.get("score", 0.0),
            metadata=r.get("metadata", {}),
        )
        r["match_reasons"] = explanation["reasons"]
        r["hit_keywords"] = explanation["hit_keywords"]
    return results
