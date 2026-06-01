"""压测配置 - 实验维度矩阵 & 基线参数"""

import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

DEFAULT_CONFIG = {
    "embedding_model": "all-MiniLM-L6-v2",
    "vector_dim": 384,
    "chunk_size": 500,
    "chunk_overlap": 50,
    "top_k": 5,
    "score_threshold": 0.3,
    "distance_metric": "L2",
}

SEARCH_BENCHMARK = {
    "warmup_runs": 3,
    "measure_runs": 30,
    "queries_file": os.path.join(FIXTURES_DIR, "queries.json"),
}

INSERT_BENCHMARK = {
    "doc_sizes": [10, 100, 1000],
    "chunk_avg_size": 500,
    "warmup_runs": 1,
    "measure_runs": 3,
}

DATA_GEN = {
    "scales": {
        "small": 1000,
        "medium": 10_000,
        "large": 100_000,
    },
    "default_scale": "small",
}

EXPERIMENT_MATRIX = {
    "embedding_models": ["all-MiniLM-L6-v2"],
    "chunk_sizes": [300, 500, 800],
    "top_ks": [3, 5, 10, 20],
}
