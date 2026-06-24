"""代码 Embedding - bge-small-en-v1.5

bge-small-en-v1.5: 33M，384-dim，512-token，英文通用模型。
配合 query_translator 中文→英文翻译层，实现中文查询搜索英文代码。
"""

import os
import torch
import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "config", "models")

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DIMENSION = 384
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# bge 模型 passage 侧不加前缀，只在 query 侧加
# e5-small token 上限 512；英文代码 ~3 chars/token，1100 chars 在安全域内
_MAX_CHARS = 1100

_model = None


def _load_model() -> SentenceTransformer:
    """模型加载（单例，MPS + fp16 加速）"""
    global _model

    if _model is not None:
        return _model

    os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
    print(f"正在加载 Embedding 模型: {_MODEL_NAME} ...")
    print(f"模型缓存目录: {MODEL_CACHE_DIR}")

    _model = SentenceTransformer(
        _MODEL_NAME,
        cache_folder=MODEL_CACHE_DIR,
        model_kwargs={"torch_dtype": "float16"},
    )

    # MPS 加速
    if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        try:
            _model = _model.to('mps')
            print("Embedding 模型已移至 MPS (Apple Silicon GPU)")
        except Exception:
            pass

    print(f"模型加载完成!")
    return _model


def get_model() -> SentenceTransformer:
    """获取模型实例（单例）"""
    return _load_model()


def embed_text(text: str) -> list[float]:
    """passage embedding（索引阶段用，不加前缀）"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"文本过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(safe_text, normalize_embeddings=True)
    return embedding.tolist()


def embed_query(text: str) -> list[float]:
    """query embedding（搜索阶段用，加 bge 前缀）"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"查询过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(_QUERY_PREFIX + safe_text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding（索引阶段用，不加前缀）"""
    model = get_model()
    truncated = sum(1 for t in texts if len(t) > _MAX_CHARS)
    if truncated:
        log.warning(f"批量 embedding: {truncated}/{len(texts)} 条文本过长，已截断")
    safe_texts = [(t[:_MAX_CHARS] if len(t) > _MAX_CHARS else t) for t in texts]
    embeddings = model.encode(safe_texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return _DIMENSION


# ── 兼容旧接口 ────────────────────────────────────────────────────

embed_code_batch = embed_batch


def check_model_available() -> tuple[bool, str]:
    """检查代码 embedding 模型是否可用，返回 (ok, message)"""
    from pathlib import Path

    # 检查 HuggingFace 缓存目录
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir_pattern = hf_cache / "models--nomic-ai--CodeRankEmbed"
    if model_dir_pattern.is_dir():
        # 检查是否有 snapshots 且包含模型文件
        snapshots = model_dir_pattern / "snapshots"
        if snapshots.is_dir():
            for snap in snapshots.iterdir():
                if snap.is_dir() and any(snap.glob("*.safetensors")):
                    return True, "模型已就绪"

    # 检查项目 models 目录（HF 格式缓存）
    local_model = Path(MODEL_CACHE_DIR)
    if local_model.is_dir():
        # HF cache 格式: models/models--nomic-ai--CodeRankEmbed/snapshots/<hash>/*.safetensors
        for safetensor in local_model.rglob("*.safetensors"):
            return True, "模型已就绪（本地缓存）"

    return False, (
        f"代码 Embedding 模型 {_model_name} 未下载。"
        f"请先运行: python3 -c \"from sentence_transformers import SentenceTransformer; "
        f"SentenceTransformer('{_model_name}', trust_remote_code=True, "
        f"cache_folder='{MODEL_CACHE_DIR}')\""
    )


def get_code_model_info() -> dict:
    return {
        "model_name": _MODEL_NAME,
        "dimension": _DIMENSION,
        "cache_dir": MODEL_CACHE_DIR,
    }
