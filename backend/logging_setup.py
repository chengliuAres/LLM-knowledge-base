"""日志系统 SSOT —— 唯一初始化入口，幂等。

- configure_logging(): 启动时调一次，可重复调不重复加 handler
- get_logger(name): 各模块取 logger 用
- request_id_var: 跨协程的 request_id 存储（middleware 写入）
- RequestIdFilter: 给每条 LogRecord 注入 req_id 字段
"""

import contextvars
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s [req:%(req_id)s]"
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARKER: str = "__kb_logging_setup__"

# 跨协程 request_id 存储（middleware 写入）
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    """给每条日志记录注入当前 request_id（默认 '-'）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.req_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """幂等：重复调直接 return。挂 file/stream 两个 handler，注入 request_id filter。"""
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_MARKER, False) for h in root.handlers):
        return  # 已初始化

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    req_filter = RequestIdFilter()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=3,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.addFilter(req_filter)
    setattr(file_handler, _HANDLER_MARKER, True)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(req_filter)
    setattr(stream_handler, _HANDLER_MARKER, True)
    root.addHandler(stream_handler)

    # 静默第三方库噪音（与原 main.py:14-16 行为一致）
    for noisy in ("jieba", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """各模块用 `from logging_setup import get_logger; log = get_logger("upload")`。"""
    return logging.getLogger(name)
