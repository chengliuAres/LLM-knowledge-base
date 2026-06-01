# Benchmark - 性能压测工具链

> 用于 email-wiki-demo 的性能基线测量与对比实验

## 用途

1. **基线测量** — 跑一次基线产出当前性能快照入库 `metrics.db.baselines`
2. **回归对比** — 修改实现后跑同一基线，看 P50/P95 是否改善/退化
3. **维度实验** — 切换 embedding 模型 / chunk size / top_k，做 A/B 对比
4. **大数据量压测** — 灌 1k/1万/10万 chunks 验证 LanceDB 的扩展性

## 目录结构

```
benchmark/
├── config.py                 # 实验配置矩阵（模型/chunk_size/top_k）
├── fixtures/
│   └── queries.json          # 30 条固定测试查询（中英/类型多样化）
├── results/                  # 历次结果存档（gitignore 推荐）
├── generate_data.py          # 合成 N 个 chunk 灌入 LanceDB
├── benchmark_search.py       # 搜索压测：固定查询集 × N 次
├── benchmark_insert.py       # 插入压测
└── run_baseline.py           # 一键基线：跑全套压测 → 写 baselines 表
```

## 怎么跑

### 前置条件

```bash
# 服务依赖：embedder / db / metrics_db 已就绪
cd backend && source venv/bin/activate
```

### 跑一次基线

```bash
cd benchmark
python3 run_baseline.py --label "v1_minilm_chunk500_top5" --notes "初始基线"
```

产出：
- 控制台打印 P50/P95/avg
- `results/{timestamp}.json` 落盘
- `metrics.db.baselines` 入库一行

### 单独跑搜索压测

```bash
python3 benchmark_search.py --runs 30 --top-k 5
```

### 单独跑插入压测

```bash
python3 benchmark_insert.py --doc-count 100
```

### 灌大数据量（看 LanceDB 在不同规模下的搜索性能）

```bash
python3 generate_data.py --scale small    # 1k chunks
python3 generate_data.py --scale medium   # 10k chunks
python3 generate_data.py --scale large    # 100k chunks
```

> ⚠️ 大数据量会显著膨胀 `data/lancedb/`，跑完记得清理或备份

## 怎么解读结果

`results/{timestamp}.json` 结构：

```json
{
  "label": "v1_minilm_chunk500_top5",
  "timestamp": "2026-05-29T16:00:00",
  "config": { ... },
  "summary": {
    "search": { "count": 30, "avg_ms": 120, "p50_ms": 100, "p95_ms": 250, ... },
    "insert": { "file_count": 100, "avg_per_file_ms": ..., "avg_per_chunk_ms": ... },
    "step_breakdown": [ ... ]
  }
}
```

关键看：
- **search.p95_ms** — 长尾慢请求耗时（通常是冷启动 / GC / 大 chunk）
- **search.avg_ms** — 平均水平
- **step_breakdown** — 哪一步占大头（embed_query? lancedb_search?）
- **insert.avg_per_chunk_ms** — 平摊每个 chunk 的插入开销
- **lancedb_disk_bytes** — 数据膨胀率
