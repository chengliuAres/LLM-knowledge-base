"""翻译缓存层 - 持久化缓存翻译结果，支持自动扩充词典

缓存策略：
1. LLM/MyMemory 翻译成功后写入缓存
2. 下次查询直接从缓存读取（0ms）
3. 支持过期清理（默认 30 天）
4. 支持手动扩充词典

存储路径：data/translation_cache.json
"""

import json
import os
import time
from typing import Optional
from dataclasses import dataclass, asdict

# 缓存文件路径
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")
CACHE_FILE = os.path.join(CACHE_DIR, "translation_cache.json")

# 过期时间（秒）
DEFAULT_TTL = 30 * 24 * 3600  # 30 天

@dataclass
class CacheEntry:
    """缓存条目"""
    keywords: list[str]
    method: str  # "llm" / "mymemory" / "dict"
    confidence: float
    timestamp: float
    auto_added: bool = False  # 是否自动扩充到词典


class TranslationCache:
    """翻译缓存管理器"""
    
    def __init__(self, cache_file: str = CACHE_FILE, ttl: int = DEFAULT_TTL):
        self.cache_file = cache_file
        self.ttl = ttl
        self.cache: dict[str, CacheEntry] = {}
        self._load()
    
    def _load(self):
        """从文件加载缓存"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for query, entry in data.items():
                        self.cache[query] = CacheEntry(**entry)
        except Exception as e:
            print(f"[cache] 加载缓存失败: {e}")
            self.cache = {}
    
    def _save(self):
        """保存缓存到文件（原子写入：先写临时文件，再 replace）"""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            data = {query: asdict(entry) for query, entry in self.cache.items()}
            tmp_file = self.cache_file + '.tmp'
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.cache_file)
        except Exception as e:
            print(f"[cache] 保存缓存失败: {e}")
    
    def get(self, query: str) -> Optional[CacheEntry]:
        """获取缓存（检查过期）"""
        if query not in self.cache:
            return None
        
        entry = self.cache[query]
        if time.time() - entry.timestamp > self.ttl:
            # 过期，删除
            del self.cache[query]
            self._save()
            return None
        
        return entry
    
    def set(self, query: str, keywords: list[str], method: str, confidence: float, auto_added: bool = False):
        """写入缓存"""
        self.cache[query] = CacheEntry(
            keywords=keywords,
            method=method,
            confidence=confidence,
            timestamp=time.time(),
            auto_added=auto_added,
        )
        self._save()
    
    def add_to_dict(self, query: str, keywords: list[str]):
        """将缓存结果扩充到本地词典（TERM_MAP）"""
        from query_translator import TERM_MAP
        
        if query not in TERM_MAP:
            TERM_MAP[query] = keywords
            # 标记为自动扩充
            if query in self.cache:
                self.cache[query].auto_added = True
                self._save()
            print(f"[cache] 自动扩充词典: {query} -> {keywords}")
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        total = len(self.cache)
        auto_added = sum(1 for e in self.cache.values() if e.auto_added)
        return {
            "total": total,
            "auto_added": auto_added,
            "cache_file": self.cache_file,
        }
    
    def cleanup(self):
        """清理过期缓存"""
        now = time.time()
        expired = [q for q, e in self.cache.items() if now - e.timestamp > self.ttl]
        for q in expired:
            del self.cache[q]
        if expired:
            self._save()
            print(f"[cache] 清理过期缓存: {len(expired)} 条")


# 全局单例
_cache_instance: Optional[TranslationCache] = None

def get_cache() -> TranslationCache:
    """获取缓存单例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TranslationCache()
    return _cache_instance
