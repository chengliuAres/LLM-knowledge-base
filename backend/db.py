"""LanceDB 数据库操作封装"""

import lancedb
import os
import json
import math
from datetime import datetime
from embedder import get_dimension

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lancedb")
TABLE_NAME = "documents"

# 全局连接（单例）
_db = None
_table = None


def get_db() -> lancedb.DBConnection:
    """获取数据库连接"""
    global _db
    if _db is None:
        os.makedirs(DB_PATH, exist_ok=True)
        _db = lancedb.connect(DB_PATH)
    return _db


def get_table():
    """获取表（不存在则创建，维度不匹配则自动迁移）"""
    global _table
    if _table is None:
        db = get_db()
        dim = get_dimension()
        try:
            _table = db.open_table(TABLE_NAME)
            # 检查维度是否匹配
            schema = _table.schema
            for field in schema:
                if field.name == 'vector' and hasattr(field.type, 'list_size'):
                    existing_dim = field.type.list_size
                    if existing_dim != dim:
                        # 维度不匹配 → 抛显式错误，不静默删数据
                        msg = (f"LanceDB 向量维度不匹配！现存={existing_dim}维, 当前={dim}维。"
                               f"请手动清除 data/lancedb/ 目录后重新导入。")
                        print(f"[db] {msg}")
                        raise RuntimeError(msg)
        except Exception:
            _table = None

        if _table is None:
            placeholder = [{
                "id": "__placeholder__",
                "filename": "__placeholder__",
                "chunk_index": 0,
                "content": "__placeholder__",
                "vector": [0.0] * dim,
                "file_type": ".txt",
                "uploaded_at": datetime.now().isoformat(),
                "metadata": "{}",  # JSON 字符串存储元数据
            }]
            _table = db.create_table(TABLE_NAME, data=placeholder)
            # 删除占位数据
            _table.delete("id = '__placeholder__'")
    return _table


def cosine_distance_to_similarity(distance: float) -> float:
    """
    将余弦距离转换为相似度分数 [0, 1]
    
    LanceDB 返回的是余弦距离 (1 - cosine_similarity)
    cosine_similarity = 1 - distance
    similarity = (cosine_similarity + 1) / 2  # 归一化到 [0, 1]
    """
    cosine_similarity = 1.0 - distance
    return (cosine_similarity + 1.0) / 2.0


def insert_documents(documents: list[dict]):
    """
    批量插入文档分块
    
    documents: [{
        "filename": "xxx.pdf",
        "chunk_index": 0,
        "content": "...",
        "vector": [...],
        "file_type": ".pdf",
        "metadata": {...}  # 可选，邮件元数据
    }]
    """
    table = get_table()
    
    # 生成 ID 和时间戳
    now = datetime.now().isoformat()
    for doc in documents:
        doc["id"] = f"{doc['filename']}_{doc['chunk_index']}"
        doc["uploaded_at"] = now
        # 将 metadata 转为 JSON 字符串
        if "metadata" in doc and isinstance(doc["metadata"], dict):
            doc["metadata"] = json.dumps(doc["metadata"], ensure_ascii=False)
        else:
            doc.setdefault("metadata", "{}")
    
    table.add(documents)


def search_similar(query_vector: list[float], top_k: int = 5, filter_expr: str = None) -> list[dict]:
    """
    向量相似度搜索（使用余弦相似度）
    
    filter_expr: 可选的过滤表达式，如 "file_type = '.eml'"
    """
    table = get_table()
    
    # 使用余弦相似度（更适合归一化向量）
    query = table.search(query_vector).metric("cosine")
    
    if filter_expr:
        query = query.where(filter_expr)
    
    results = query.limit(top_k).to_list()
    
    # 整理返回格式
    formatted = []
    for r in results:
        # 计算相似度分数
        distance = r.get("_distance", 0)
        score = cosine_distance_to_similarity(distance)
        
        item = {
            "id": r["id"],
            "filename": r["filename"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "file_type": r["file_type"],
            "score": score,
            "distance": distance,  # 保留原始距离供参考
        }
        
        # 解析元数据
        try:
            metadata = json.loads(r.get("metadata", "{}"))
            item["metadata"] = metadata
        except:
            item["metadata"] = {}
        
        formatted.append(item)
    
    return formatted


def list_documents(file_type: str = None) -> list[dict]:
    """列出所有已上传的文档（按文件名聚合）"""
    table = get_table()
    all_data = table.to_pandas()
    
    if all_data.empty:
        return []
    
    # 过滤类型
    if file_type:
        all_data = all_data[all_data['file_type'] == file_type]
    
    # 按文件名聚合
    grouped = all_data.groupby('filename').agg({
        'chunk_index': 'count',
        'uploaded_at': 'first',
        'file_type': 'first'
    }).reset_index()
    
    grouped.columns = ['filename', 'chunk_count', 'uploaded_at', 'file_type']
    
    return grouped.to_dict('records')


def delete_document(filename: str) -> int:
    """删除指定文档的所有分块，返回删除数量"""
    table = get_table()
    
    # 查询要删除的记录数
    df = table.to_pandas()
    count = len(df[df['filename'] == filename])
    
    if count > 0:
        table.delete(f"filename = '{filename}'")
    
    return count


def get_stats() -> dict:
    """获取数据库统计信息"""
    table = get_table()
    df = table.to_pandas()
    
    if df.empty:
        return {
            "total_chunks": 0,
            "total_documents": 0,
            "by_type": {}
        }
    
    # 按类型统计
    type_stats = df.groupby('file_type').size().to_dict()
    
    return {
        "total_chunks": len(df),
        "total_documents": df['filename'].nunique(),
        "by_type": type_stats
    }
