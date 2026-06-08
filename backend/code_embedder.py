"""代码 Embedding - 基于 nomic-ai/CodeRankEmbed

CodeRankEmbed: 代码专用检索模型，137M，768-dim，8192-token。
用于代码知识库的代码语义搜索，CSN MRR 77.9 (超过 OpenAI Ada-002)。
"""

import os
import torch
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "models")

_model = None
_model_name = "nomic-ai/CodeRankEmbed"  # 代码专用，768-dim，8192-token，137M

# CodeRankEmbed 要求查询加此前缀
_QUERY_PREFIX = "Represent this query for searching relevant code: "


def get_code_model() -> SentenceTransformer:
    """获取代码 embedding 模型（单例）"""
    global _model
    if _model is None:
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        print(f"正在加载代码 Embedding 模型: {_model_name} ...")
        print(f"模型缓存目录: {MODEL_CACHE_DIR}")

        _model = SentenceTransformer(
            _model_name,
            trust_remote_code=True,
        )
        # MPS 加速
        if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            try:
                _model = _model.to('mps')
                print("代码 Embedding 模型已移至 MPS (Apple Silicon GPU)")
            except Exception:
                pass

        print(f"代码模型加载完成! 维度={get_code_dimension()}")
    return _model


def embed_code(text: str) -> list[float]:
    """单条代码 embedding (passage，不加前缀)"""
    model = get_code_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_code_query(text: str) -> list[float]:
    """查询 embedding (带 CodeRankEmbed 查询前缀)"""
    model = get_code_model()
    embedding = model.encode(
        _QUERY_PREFIX + text,
        normalize_embeddings=True,
    )
    return embedding.tolist()


def embed_code_batch(texts: list[str]) -> list[list[float]]:
    """批量代码 embedding（索引阶段用）"""
    model = get_code_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()


def get_code_dimension() -> int:
    """返回代码 embedding 维度"""
    return 768


def get_code_model_info() -> dict:
    """获取代码模型信息"""
    return {
        "model_name": _model_name,
        "dimension": get_code_dimension(),
        "cache_dir": MODEL_CACHE_DIR,
    }
