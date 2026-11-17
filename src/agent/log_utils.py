"""
日志工具模块
结构化日志配置，按模块分 logger
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

from opentelemetry import trace


class JSONFormatter(logging.Formatter):
    """JSON 格式日志"""

    def format(self, record):
        log_entry = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "log.level": record.levelname,
            "service.name": os.getenv("OTEL_SERVICE_NAME", "erp-agent"),
            "log.logger": record.name,
            "message": record.getMessage(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            log_entry["trace.id"] = format(span_context.trace_id, "032x")
            log_entry["span.id"] = format(span_context.span_id, "016x")
        if record.exc_info:
            log_entry["error.stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_json_logging() -> None:
    """统一应用与依赖库的 stdout JSON 日志。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastmcp"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger


configure_json_logging()


# 预定义模块 logger 预定义 5 个模块 logger，各模块按需导入使用
agent_logger = get_logger("agent")        # Agent 核心逻辑
mcp_logger = get_logger("mcp")            # MCP 工具相关
sandbox_logger = get_logger("sandbox")    # 沙箱操作
web_logger = get_logger("web")            # Web API 层
middleware_logger = get_logger("middleware")  # 中间件
