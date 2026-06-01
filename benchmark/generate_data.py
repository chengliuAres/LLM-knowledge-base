"""合成测试数据灌入 LanceDB（1k/1万/10万 chunks，固定种子可复现）"""

import os
import sys
import argparse
import random
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from embedder import embed_batch
from db import insert_documents
from config import DATA_GEN

TOPICS = [
    "机器学习", "深度学习", "向量数据库", "向量检索", "embedding 模型",
    "Transformer", "注意力机制", "RAG 检索增强生成", "微服务架构", "分布式系统",
    "数据库优化", "Redis 缓存", "Kubernetes", "Docker 容器", "前端性能",
    "React 状态管理", "TypeScript 类型系统", "Python 装饰器", "Go 并发", "Rust 所有权",
    "API 设计", "RESTful", "GraphQL", "gRPC", "WebSocket",
    "邮件协议", "IMAP", "SMTP", "邮件分类", "垃圾邮件过滤",
    "搜索引擎", "倒排索引", "BM25", "语义搜索", "混合检索",
]

ACTIONS = [
    "实现", "优化", "调试", "重构", "迁移", "部署", "压测", "监控",
    "理解", "学习", "对比", "分析", "设计", "评估",
]

CONTEXTS = [
    "在生产环境中", "对于大规模数据", "在边缘场景下", "针对高并发场景",
    "考虑成本约束", "在低延迟要求下", "对于初学者", "在团队协作中",
]

DETAILS = [
    "需要权衡一致性与可用性，CAP 定理告诉我们三者只能选其二，实际工程中通常牺牲强一致性。",
    "性能瓶颈往往出现在 IO 而非 CPU，profiling 工具是定位热点的关键。",
    "缓存策略的选择取决于读写比例：读多写少适合 Cache-Aside，写多读少适合 Write-Through。",
    "异步化是提升吞吐量的核心手段，但带来复杂的错误处理与重试机制。",
    "可观测性的三大支柱：日志、指标、链路追踪，缺一不可。",
    "良好的错误信息应包含上下文：发生了什么、影响范围、建议的修复方向。",
    "技术债务不可避免，但要有意识地管理，定期偿还。",
    "代码评审不是找茬，而是知识传播与质量保证的双向过程。",
    "测试金字塔：单元测试多、集成测试中、E2E 测试少。",
    "命名是软件工程最难的两件事之一，另一件是缓存失效。",
]


def generate_chunk_content(seed_idx: int) -> str:
    """合成一段约 200-500 字符的中文文本"""
    rnd = random.Random(seed_idx)
    topic = rnd.choice(TOPICS)
    action = rnd.choice(ACTIONS)
    context = rnd.choice(CONTEXTS)
    detail = rnd.choice(DETAILS)
    extra = " ".join(rnd.choices(DETAILS, k=rnd.randint(1, 3)))

    return f"关于 {topic} 的笔记 #{seed_idx}\n\n{context}{action} {topic} 时,{detail} {extra}"


def generate_chunks(count: int, prefix: str = "synthetic") -> list:
    """生成 count 个 chunk dict（不带 vector，留给调用方批量 embed）"""
    chunks = []
    for i in range(count):
        chunks.append({
            "filename": f"{prefix}_{i // 100}.txt",
            "chunk_index": i % 100,
            "content": generate_chunk_content(i),
            "file_type": ".synthetic",
            "metadata": {"synthetic": True, "seed": i},
        })
    return chunks


def insert_in_batches(chunks: list, batch_size: int = 200):
    """分批 embed + insert，避免一次内存爆炸"""
    total = len(chunks)
    elapsed_total = 0.0
    embed_total = 0.0

    for start in range(0, total, batch_size):
        batch = chunks[start:start + batch_size]
        contents = [c["content"] for c in batch]

        t0 = time.time()
        vectors = embed_batch(contents)
        embed_dt = time.time() - t0
        embed_total += embed_dt

        for c, v in zip(batch, vectors):
            c["vector"] = v

        t1 = time.time()
        insert_documents(batch)
        insert_dt = time.time() - t1

        elapsed_total += embed_dt + insert_dt
        progress = min(start + batch_size, total)
        print(f"  [{progress}/{total}] embed={embed_dt*1000:.0f}ms insert={insert_dt*1000:.0f}ms")

    print(f"\n✅ {total} chunks 完成")
    print(f"   总耗时: {elapsed_total:.2f}s (embed {embed_total:.2f}s + insert {elapsed_total - embed_total:.2f}s)")
    print(f"   平均: {elapsed_total/total*1000:.2f} ms/chunk")
    return {
        "total_chunks": total,
        "total_seconds": round(elapsed_total, 2),
        "embed_seconds": round(embed_total, 2),
        "insert_seconds": round(elapsed_total - embed_total, 2),
        "avg_ms_per_chunk": round(elapsed_total / total * 1000, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="合成测试数据灌入 LanceDB")
    parser.add_argument("--scale", choices=list(DATA_GEN["scales"].keys()), default=DATA_GEN["default_scale"],
                        help="规模: small=1k / medium=1万 / large=10万")
    parser.add_argument("--count", type=int, help="自定义数量（覆盖 scale）")
    parser.add_argument("--prefix", default="synthetic", help="文件名前缀，便于后续清理")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    count = args.count if args.count else DATA_GEN["scales"][args.scale]
    print(f"🌱 准备合成 {count} 个 chunks (prefix={args.prefix}, batch_size={args.batch_size})")

    t0 = time.time()
    chunks = generate_chunks(count, prefix=args.prefix)
    print(f"📝 文本生成完毕: {time.time() - t0:.2f}s")

    summary = insert_in_batches(chunks, batch_size=args.batch_size)
    print(f"\n{summary}")


if __name__ == "__main__":
    main()
