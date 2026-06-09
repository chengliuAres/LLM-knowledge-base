"""代码 Embedding - bge-small-en-v1.5

bge-small-en-v1.5: 33M，384-dim，512-token，英文通用模型。
配合 query_translator 中文→英文翻译层，实现中文查询搜索英文代码。
"""

import os
import torch
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "models")

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DIMENSION = 384
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None


def _load_model() -> SentenceTransformer:
    """模型加载（单例）"""
    global _model

    if _model is not None:
        return _model

    os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
    print(f"正在加载 Embedding 模型: {_MODEL_NAME} ...")
    print(f"模型缓存目录: {MODEL_CACHE_DIR}")

    _model = SentenceTransformer(_MODEL_NAME, cache_folder=MODEL_CACHE_DIR)

    print(f"模型加载完成!")
    return _model


def get_model() -> SentenceTransformer:
    """获取模型实例（单例）"""
    return _load_model()


def embed_text(text: str) -> list[float]:
    """passage embedding（索引阶段用，不加前缀）"""
    model = get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_query(text: str) -> list[float]:
    """query embedding（搜索阶段用，加 bge 前缀）"""
    model = get_model()
    embedding = model.encode(_QUERY_PREFIX + text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[float]:
    """批量 embedding（索引阶段用）"""
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return _DIMENSION


# ── 兼容旧接口 ────────────────────────────────────────────────────

embed_code_batch = embed_batch


def get_code_model_info() -> dict:
    return {
        "model_name": _MODEL_NAME,
        "dimension": _DIMENSION,
        "cache_dir": MODEL_CACHE_DIR,
    }
