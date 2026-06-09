"""代码 Embedding - bge-small-en-v1.5 (主) + CodeRankEmbed (备)

bge-small-en-v1.5: 33M，384-dim，512-token，英文通用模型。
配合 query_translator 中文→英文翻译层，实现中文查询搜索英文代码。
CodeRankEmbed: 137M，768-dim，8192-token，代码专用模型（保留备用）。
"""

import os
import torch
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "models")

# ── bge-small-en (主模型) ─────────────────────────────────────────
_BGE_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_BGE_DIMENSION = 384
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_bge_model = None

# ── CodeRankEmbed (备用) ─────────────────────────────────────────
_CODE_MODEL_NAME = "nomic-ai/CodeRankEmbed"
_CODE_DIMENSION = 768
_CODE_QUERY_PREFIX = "Represent this query for searching relevant code: "
_CODE_MAX_CHARS = 2000

_code_model = None


def _load_model(model_name: str, model_attr: str, trust_remote: bool = False) -> SentenceTransformer:
    """通用模型加载（单例 + MPS 加速）"""
    import gc
    global _bge_model, _code_model

    current = globals()[model_attr]
    if current is not None:
        return current

    os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
    print(f"正在加载 Embedding 模型: {model_name} ...")
    print(f"模型缓存目录: {MODEL_CACHE_DIR}")

    kwargs = {}
    if trust_remote:
        kwargs["trust_remote_code"] = True
        kwargs["model_kwargs"] = {"torch_dtype": "float16"}

    current = SentenceTransformer(model_name, cache_folder=MODEL_CACHE_DIR, **kwargs)

    # bge-small-en 在 MPS 上可能不稳定，跳过 MPS 加速
    if "bge-small" not in model_name:
        if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            try:
                current = current.to('mps')
                print(f"模型已移至 MPS (Apple Silicon GPU)")
            except Exception:
                pass

    globals()[model_attr] = current
    print(f"模型加载完成!")
    return current


# ── bge-small-en 接口 (主) ────────────────────────────────────────

def get_model() -> SentenceTransformer:
    """获取 bge-small-en 模型（单例）"""
    return _load_model(_BGE_MODEL_NAME, "_bge_model")


def embed_text(text: str) -> list[float]:
    """passage embedding（索引阶段用，不加前缀）"""
    model = get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_query(text: str) -> list[float]:
    """query embedding（搜索阶段用，加 bge 前缀）"""
    model = get_model()
    embedding = model.encode(_BGE_QUERY_PREFIX + text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding（索引阶段用）"""
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return _BGE_DIMENSION


# ── CodeRankEmbed 接口 (备用) ─────────────────────────────────────

def get_code_model() -> SentenceTransformer:
    """获取 CodeRankEmbed 模型（单例，按需加载）"""
    return _load_model(_CODE_MODEL_NAME, "_code_model", trust_remote=True)


def embed_code_query(text: str) -> list[float]:
    """CodeRankEmbed 查询 embedding（带代码查询前缀）"""
    model = get_code_model()
    safe_text = text[:_CODE_MAX_CHARS] if len(text) > _CODE_MAX_CHARS else text
    embedding = model.encode(_CODE_QUERY_PREFIX + safe_text, normalize_embeddings=True)
    return embedding.tolist()


def get_code_dimension() -> int:
    """返回 CodeRankEmbed 维度"""
    return _CODE_DIMENSION


# ── 兼容旧接口 ────────────────────────────────────────────────────

# 旧代码调用的别名
embed_code_batch = embed_batch
get_code_dimension = get_dimension

def get_code_model_info() -> dict:
    return {
        "primary_model": _BGE_MODEL_NAME,
        "primary_dimension": _BGE_DIMENSION,
        "fallback_model": _CODE_MODEL_NAME,
        "fallback_dimension": _CODE_DIMENSION,
        "cache_dir": MODEL_CACHE_DIR,
    }
