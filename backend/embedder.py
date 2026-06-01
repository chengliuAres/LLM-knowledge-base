"""Embedding 封装 - 基于 sentence-transformers"""

import os
from sentence_transformers import SentenceTransformer

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 模型缓存目录（项目内）
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "models")

# 全局模型实例（懒加载）
_model = None
_model_name = "paraphrase-multilingual-MiniLM-L12-v2"  # 多语言模型，支持中文


def get_model() -> SentenceTransformer:
    """获取模型实例（单例模式）"""
    global _model
    if _model is None:
        # 确保缓存目录存在
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        
        print(f"正在加载 Embedding 模型: {_model_name} ...")
        print(f"模型缓存目录: {MODEL_CACHE_DIR}")
        
        # 从项目目录加载或下载模型
        _model = SentenceTransformer(
            _model_name,
            cache_folder=MODEL_CACHE_DIR
        )
        print("模型加载完成!")
    return _model


def embed_text(text: str) -> list[float]:
    """单条文本 embedding"""
    model = get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding（更高效）"""
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return 384


def get_model_info() -> dict:
    """获取模型信息"""
    return {
        "model_name": _model_name,
        "dimension": get_dimension(),
        "cache_dir": MODEL_CACHE_DIR,
        "model_size_mb": get_dir_size(MODEL_CACHE_DIR) / (1024 * 1024)
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
