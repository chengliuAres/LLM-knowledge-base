"""步骤追踪器 - 记录执行过程中的每一步操作，并可选地持久化到 metrics.db"""

import time
import uuid
from typing import List, Optional
from dataclasses import dataclass, field, asdict

from metrics_db import record_operations_batch


@dataclass
class Step:
    """单个步骤"""
    name: str
    description: str
    status: str = "pending"
    start_time: float = 0
    end_time: float = 0
    duration_ms: float = 0
    details: dict = field(default_factory=dict)
    error: Optional[str] = None

    def start(self):
        self.status = "running"
        self.start_time = time.time()

    def complete(self, details: dict = None):
        self.status = "completed"
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        if details:
            self.details.update(details)

    def fail(self, error: str):
        self.status = "error"
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.error = error

    def to_dict(self) -> dict:
        return asdict(self)


class StepTracker:
    """步骤追踪器

    operation_type 不为 None 时，flush() 会把所有 step 持久化到 metrics.db。
    保留无参构造的向后兼容性。
    """

    def __init__(self, operation_type: Optional[str] = None, request_id: Optional[str] = None):
        self.steps: List[Step] = []
        self.start_time = time.time()
        self.operation_type = operation_type
        self.request_id = request_id or str(uuid.uuid4())
        self.extra: dict = {}

    def add_step(self, name: str, description: str) -> Step:
        """添加一个新步骤"""
        step = Step(name=name, description=description)
        self.steps.append(step)
        return step

    def set_extra(self, **kwargs):
        """设置请求级元信息（如 filename/chunk_count/query），flush 时写入主记录的 extra"""
        self.extra.update(kwargs)

    def get_total_duration(self) -> float:
        """获取总耗时（毫秒）"""
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "total_duration_ms": self.get_total_duration(),
            "request_id": self.request_id,
        }

    def to_list(self) -> list:
        """转换为列表（兼容旧格式）"""
        return [s.to_dict() for s in self.steps]

    def flush(self, status: Optional[str] = None):
        """把所有步骤持久化到 metrics.db。

        operation_type 未设置时为 no-op（向后兼容）。
        每个请求会写入：1 条主记录（step_name=NULL，代表请求总耗时）+ N 条 step 子记录。
        """
        if not self.operation_type:
            return

        if status is None:
            status = "error" if any(s.status == "error" for s in self.steps) else "completed"

        records = [{
            "request_id": self.request_id,
            "operation_type": self.operation_type,
            "step_name": None,
            "duration_ms": self.get_total_duration(),
            "status": status,
            "extra": self.extra,
        }]

        for s in self.steps:
            step_extra = dict(s.details) if s.details else {}
            if s.error:
                step_extra["error"] = s.error
            records.append({
                "request_id": self.request_id,
                "operation_type": self.operation_type,
                "step_name": s.name,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "extra": step_extra,
            })

        try:
            record_operations_batch(records)
        except Exception as e:
            print(f"[metrics] flush failed: {e}")
