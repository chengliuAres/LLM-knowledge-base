"""Embedding 封装 - 基于 sentence-transformers (BAAI/bge-base-zh-v1.5)

bge-base-zh-v1.5: 中文优化轻量模型，768-dim，512-token 上下文。
用于文档/邮件知识库的中文语义检索。
"""

import os
import torch
import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "config", "models")

_model = None
_model_name = "BAAI/bge-base-zh-v1.5"  # 中文优化，768-dim，512-token，102M
_MAX_CHARS = 1500  # 512 tokens ≈ 1500 字符，安全兜底（实际 chunk 上限 500 字符，正常不会触发）

# bge 系列查询前缀（可选，但能提升检索质量）
_QUERY_PROMPT = "为这个句子生成表示以用于检索相关文章："


def get_model() -> SentenceTransformer:
    """获取模型实例（单例，MPS + fp16）"""
    global _model
    if _model is None:
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        print(f"正在加载 Embedding 模型: {_model_name} ...")
        print(f"模型缓存目录: {MODEL_CACHE_DIR}")

        _model = SentenceTransformer(
            _model_name,
            cache_folder=MODEL_CACHE_DIR,
            model_kwargs={"torch_dtype": "float16"},  # fp16: MPS 上 ~2x 加速 + 省一半显存
        )
        # MPS 加速
        if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            try:
                _model = _model.to('mps')
                print("Embedding 模型已移至 MPS (Apple Silicon GPU)")
            except Exception:
                pass

        print(f"模型加载完成! 维度={get_dimension()}")
    return _model


def embed_text(text: str) -> list[float]:
    """单条文本 embedding (passage)"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"文本过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(safe_text, normalize_embeddings=True)
    return embedding.tolist()


def embed_query(text: str) -> list[float]:
    """查询 embedding (带查询前缀)"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"查询过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(
        _QUERY_PROMPT + safe_text,
        normalize_embeddings=True,
    )
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding（索引阶段用）"""
    model = get_model()
    truncated = sum(1 for t in texts if len(t) > _MAX_CHARS)
    if truncated:
        log.warning(f"批量 embedding: {truncated}/{len(texts)} 条文本过长，已截断")
    safe_texts = [t[:_MAX_CHARS] if len(t) > _MAX_CHARS else t for t in texts]
    embeddings = model.encode(safe_texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return 768


def get_model_info() -> dict:
    """获取模型信息"""
    return {
        "model_name": _model_name,
        "dimension": get_dimension(),
        "cache_dir": MODEL_CACHE_DIR,
    }


def get_dir_size(path: str) -> int:
    """获取目录大小（字节）"""
    total = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    return total
