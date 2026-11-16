"""从对话里抽取记忆。

默认走**确定性规则**（零 LLM 调用、零额外延迟），覆盖 UserPreferences 里
声明的全部维度——包括之前 README 写了但代码里没实现的 ``recent_suppliers``
和 ``recent_queries``。

可选的 LLM 抽取（``MEMORY_LLM_EXTRACTION=1``）作为增强，失败时自动回退到规则。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from .config import DEFAULT_MEMORY_CONFIG, MemoryConfig

# ---------------------------------------------------------------- 关键词表

CHART_KEYWORDS = {
    "饼图": "pie", "饼状图": "pie", "环形图": "donut", "圆环图": "donut",
    "柱状图": "bar", "柱图": "bar", "条形图": "bar",
    "折线图": "line", "趋势图": "line", "曲线图": "line",
    "散点图": "scatter", "雷达图": "radar", "热力图": "heatmap", "面积图": "area",
}

OUTPUT_KEYWORDS = {
    "表格": "table", "json": "json", "markdown": "markdown",
    "列表": "list", "图表": "chart",
}

CURRENCY_KEYWORDS = {
    "美元": "USD", "美金": "USD", "usd": "USD",
    "人民币": "CNY", "cny": "CNY", "rmb": "CNY", "元": "CNY",
}

LANGUAGE_KEYWORDS = {
    "英文": "en", "english": "en", "英语": "en",
    "中文": "zh", "汉语": "zh", "chinese": "zh",
}

# 明确的"这是一个长期偏好"的信号词
PREFERENCE_TRIGGERS = (
    "以后", "默认", "总是", "都用", "统一", "改成", "换成", "改为",
    "别用", "不要再用", "记住", "记住了", "prefer",
)

# 祈使/指令性语境，配合关键词即可判定为偏好
IMPERATIVE_HINTS = ("用", "输出", "展示", "生成", "画", "来", "给我", "按", "格式", "结算", "计价")

_TEMPORARY_MARKERS = ("这次", "本次", "临时", "仅此")
_CANCEL_MARKERS = (
    "不要", "别用", "不用", "不想", "不喜欢", "不再", "不能", "无需",
    "取消", "清除", "恢复默认", "不固定", "没有偏好", "don't", "do not",
)
_PREFERENCE_DOMAIN_HINTS = {
    "preferred_chart_type": ("图表类型", "图形", "图"),
    "preferred_output": ("输出格式", "固定格式", "格式"),
    "preferred_currency": ("计价货币", "货币", "币种", "计价"),
    "preferred_language": ("回复语言", "语言"),
}

_SUPPLIER_SPLIT_RE = re.compile(r"[，。；！？、,.;!?\s和及与()（）:：]+")
_SUPPLIER_NAME_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,12})(?:供应商|公司|厂家|集团)")
# "钱江摩托这两家供应商" 里的"这两家"是指示/量词，不是名字的一部分
_SUPPLIER_TRAILING_NOISE = "这两那的几家等了的"

_SUPPLIER_TOOLS = ("supplier_query", "supplier_get", "supplier_page")

# 任务类型关键词（与 harness_config.yaml 的 task_types 保持一致）
TASK_TYPE_KEYWORDS = {
    "analysis": ("分析", "对比", "统计", "趋势", "报表", "图表", "报告", "评估"),
    "order": ("下单", "采购", "订单", "新增", "修改", "审批", "创建"),
    "inventory": ("库存", "入库", "出库", "盘点", "预警"),
    "supplier": ("供应商", "供货", "信用"),
}


# ---------------------------------------------------------------- 消息工具

def _role_of(message: Any) -> str:
    role = getattr(message, "type", None)
    if isinstance(role, str) and role:
        return role
    role = getattr(message, "role", None)
    if isinstance(role, str) and role:
        return role
    return message.__class__.__name__.lower()


def _content_of(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return " ".join(parts)
    return ""


def _tool_calls_of(message: Any) -> List[dict]:
    calls = getattr(message, "tool_calls", None)
    if isinstance(calls, list):
        return [c for c in calls if isinstance(c, dict)]
    return []


def _tool_name_of(message: Any) -> str:
    name = getattr(message, "name", None)
    return str(name) if isinstance(name, str) else ""


def _tool_call_id_of(message: Any) -> str:
    value = getattr(message, "tool_call_id", None)
    return str(value) if value else ""


# ---------------------------------------------------------------- 偏好抽取

def _has_trigger(text: str) -> bool:
    return any(t in text for t in PREFERENCE_TRIGGERS)


def _has_imperative(text: str) -> bool:
    return any(h in text for h in IMPERATIVE_HINTS)


def _pick(text: str, table: Dict[str, str], *, require_trigger: bool) -> Optional[str]:
    """在一段文本里按关键词表取值。

    长键优先匹配（"饼状图" 要先于 "饼图"），避免子串误命中。
    """
    explicit = _has_trigger(text)
    if require_trigger and not explicit:
        return None
    if not explicit and not _has_imperative(text):
        return None
    selected = None
    # Prefer the last affirmative clause; do not turn a rejection into a
    # positive preference. Ambiguous / temporary instructions are not stored.
    for clause in re.split(r"[，。；！？,;!?]|改成|改为|换成", text):
        if re.search(r"不要|别用|不用|不想|不喜欢|不再|不能|无需|这次|本次|临时|仅此|don't|do not", clause):
            continue
        for keyword in sorted(table, key=len, reverse=True):
            if keyword in clause:
                selected = table[keyword]
                break
    return selected


def _cancels_preference(text: str, table: Dict[str, str], field: str) -> bool:
    """判断用户是否明确取消某类长期偏好，临时要求不改变长期记忆。"""
    if any(marker in text for marker in _TEMPORARY_MARKERS):
        return False
    if not any(marker in text for marker in _CANCEL_MARKERS):
        return False
    hints = tuple(table) + _PREFERENCE_DOMAIN_HINTS.get(field, ())
    return any(hint in text for hint in hints)


def _extract_supplier_names(text: str) -> List[str]:
    """从用户原话里回退式抽取供应商名。

    优先使用工具调用参数（见 ``_collect_tool_entities``），这里只在拿不到
    参数时兜底：先按分隔符切成片段，再匹配"X + 供应商/公司/厂家/集团"，
    最后剥掉"这两家"这类指示词。宁可少抽，也不抽出一长串废话。
    """
    names: List[str] = []
    for chunk in _SUPPLIER_SPLIT_RE.split(text or ""):
        if not chunk:
            continue
        for match in _SUPPLIER_NAME_RE.finditer(chunk):
            name = match.group(1).strip(_SUPPLIER_TRAILING_NOISE)
            if len(name) >= 2 and name not in names:
                names.append(name)
    return names


def _collect_tool_entities(messages: Sequence[Any]) -> Dict[str, List[str]]:
    """从工具调用参数里收集实体（供应商、零部件），比正则稳。

    判定规则（按优先级）：
    1. 工具名含 supplier / 参数名含 supplier → 供应商
    2. 工具名含 part / 参数名含 part → 零部件
    两者都命不上时忽略（比如 order_page 的 status 参数不是实体名）。
    """
    suppliers: List[str] = []
    parts: List[str] = []
    for message in messages:
        for call in _tool_calls_of(message):
            name = str(call.get("name") or "").lower()
            args = call.get("args")
            if not isinstance(args, dict):
                continue
            for arg_key, value in args.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                low = arg_key.lower()
                text = value.strip()
                if "supplier" in name or "supplier" in low:
                    if text not in suppliers:
                        suppliers.append(text)
                elif "part" in name or "part" in low:
                    if text not in parts:
                        parts.append(text)
    return {"suppliers": suppliers, "parts": parts}


def extract_preferences(
    messages: Sequence[Any],
    config: Optional[MemoryConfig] = None,
    max_messages: int = 30,
) -> Dict[str, Any]:
    """从最近的消息里抽取偏好增量，只返回**确实抽到**的字段。"""
    cfg = config or DEFAULT_MEMORY_CONFIG
    window = list(messages or [])[-max_messages:] if messages else []
    if not window:
        return {}

    updates: Dict[str, Any] = {}

    for message in window:
        role = _role_of(message)
        if role not in ("human", "user"):
            continue
        text = _content_of(message).strip()
        if not text:
            continue
        lowered = text.lower()

        for field, table in (
            ("preferred_chart_type", CHART_KEYWORDS),
            ("preferred_output", OUTPUT_KEYWORDS),
            ("preferred_currency", CURRENCY_KEYWORDS),
            ("preferred_language", LANGUAGE_KEYWORDS),
        ):
            selected = _pick(lowered, table, require_trigger=False)
            if selected:
                updates[field] = selected
            elif _cancels_preference(lowered, table, field):
                # None 是明确的删除语义，不是“没有抽取到”。后续同一 thread
                # 若再次出现肯定表达，按消息顺序自然覆盖该删除标记。
                updates[field] = None

    # 最近查询：用户原话（去重、截断）
    recent_queries: List[str] = []
    for message in reversed(window):
        if _role_of(message) not in ("human", "user"):
            continue
        text = _content_of(message).strip().replace("\n", " ")
        if not text or text in recent_queries:
            continue
        recent_queries.append(text[:60])
        if len(recent_queries) >= cfg.max_recent_queries:
            break
    if recent_queries:
        updates["recent_queries"] = recent_queries

    # 最近供应商：优先取工具调用参数，其次回落到正则
    entities = _collect_tool_entities(window)
    suppliers: List[str] = []
    for name in entities.get("suppliers", []):
        if name not in suppliers:
            suppliers.append(name)
    if not suppliers:
        for message in window:
            if _role_of(message) not in ("human", "user"):
                continue
            for name in _extract_supplier_names(_content_of(message)):
                if name not in suppliers:
                    suppliers.append(name)
    if suppliers:
        updates["recent_suppliers"] = suppliers[: cfg.max_recent_suppliers]

    return updates


# ---------------------------------------------------------------- 情节摘要

def _classify(text: str) -> str:
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        if any(k in text for k in keywords):
            return task_type
    return "general"


def summarize_episode(
    messages: Sequence[Any],
    config: Optional[MemoryConfig] = None,
    thread_id: str = "",
) -> Dict[str, Any]:
    """把 thread 压成可检索、可恢复采购上下文的结构化情节摘要。"""
    cfg = config or DEFAULT_MEMORY_CONFIG
    window = list(messages or [])
    if not window:
        return {}

    goal = ""
    for message in window:
        if _role_of(message) in ("human", "user"):
            goal = _content_of(message).strip().replace("\n", " ")
            break

    outcome = ""
    for message in reversed(window):
        if _role_of(message) in ("ai", "assistant"):
            text = _content_of(message).strip().replace("\n", " ")
            if text:
                outcome = text
                break

    tools: List[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, str]] = []
    completed_tool_names: list[str] = []
    call_names_by_id: dict[str, str] = {}
    for message in window:
        for call in _tool_calls_of(message):
            name = str(call.get("name") or "")
            if name and name not in tools:
                tools.append(name)
            tool_calls.append(call)
            call_id = str(call.get("id") or "")
            if call_id and name:
                call_names_by_id[call_id] = name
        standalone = _tool_name_of(message)
        if not standalone and _role_of(message) == "tool":
            standalone = call_names_by_id.get(_tool_call_id_of(message), "")
        if standalone and _role_of(message) == "tool" and standalone not in tools:
            tools.append(standalone)
        if standalone and _role_of(message) == "tool":
            result_text = _content_of(message).strip()
            failed = bool(re.search(
                r"失败|错误|无权限|超时|exception|traceback|\"ok\"\s*:\s*false",
                result_text,
                re.IGNORECASE,
            ))
            tool_results.append({
                "tool": standalone,
                "status": "failed" if failed else "succeeded",
                "tool_call_id": _tool_call_id_of(message),
            })
            completed_tool_names.append(standalone)

    structured = _extract_procurement_state(window, tool_calls, tool_results)
    protected_writes = {
        "order_create", "order_update", "order_update_status", "order_receive",
        "replenishment_create", "replenishment_inspect",
        "replenishment_create_order", "replenishment_complete",
        "replenishment_cancel", "purchase_return_create", "purchase_return_confirm",
    }
    remaining_results = list(completed_tool_names)
    pending_approvals: list[str] = []
    for call in tool_calls:
        name = str(call.get("name") or "")
        if name in remaining_results:
            remaining_results.remove(name)
        elif name in protected_writes:
            pending_approvals.append(name)
    structured["pending_approvals"] = pending_approvals
    structured["tool_results"] = tool_results

    limit = max(80, cfg.episode_summary_chars)
    summary_parts = []
    if goal:
        summary_parts.append(f"目标：{goal[:120]}")
    for label, key in (
        ("采购单", "order_numbers"),
        ("零件", "part_codes"),
        ("供应商", "supplier_codes"),
        ("状态", "statuses"),
    ):
        values = structured.get(key) or []
        if values:
            summary_parts.append(f"{label}：{', '.join(values[:5])}")
    if pending_approvals:
        summary_parts.append(f"待审批：{', '.join(pending_approvals)}")
    if outcome:
        summary_parts.append(f"结果：{outcome[:limit]}")
    summary = " ｜ ".join(summary_parts) or "（无有效内容）"
    summary = summary[:limit]

    task_type = _classify(f"{goal} {outcome}")
    tags = [task_type]
    if tools:
        tags.append("tools")

    return {
        "goal": goal[:200],
        "summary": summary,
        "task_type": task_type,
        "tags": tags,
        "tools": tools[:20],
        "entities": structured.pop("entities", []),
        "structured": structured,
        "turns": sum(1 for m in window if _role_of(m) in ("human", "user")),
        "thread_id": thread_id,
    }


_FIELD_ALIASES = {
    "ordernumber": "order_numbers", "orderno": "order_numbers",
    "purchaseordernumber": "order_numbers", "purchaseorderno": "order_numbers",
    "partcode": "part_codes", "materialcode": "part_codes",
    "suppliercode": "supplier_codes", "vendorcode": "supplier_codes",
    "operationid": "operation_ids", "idempotencykey": "idempotency_keys",
    "orderstatus": "statuses", "status": "statuses",
}
_CONSTRAINT_MARKERS = ("必须", "不要", "不能", "只要", "只需", "不需要", "保持", "至少", "最多", "固定")


def _append_unique(target: dict[str, list[str]], field: str, value: Any) -> None:
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        if text and len(text) <= 160 and text not in target.setdefault(field, []):
            target[field].append(text)


def _walk_named_values(value: Any, target: dict[str, list[str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            field = _FIELD_ALIASES.get(normalized)
            if field:
                if isinstance(child, list):
                    for item in child:
                        _append_unique(target, field, item)
                else:
                    _append_unique(target, field, child)
            _walk_named_values(child, target)
    elif isinstance(value, list):
        for child in value:
            _walk_named_values(child, target)


def _extract_procurement_state(
    messages: Sequence[Any],
    tool_calls: Sequence[dict[str, Any]],
    tool_results: Sequence[dict[str, str]],
) -> dict[str, Any]:
    values: dict[str, list[str]] = {
        "order_numbers": [], "part_codes": [], "supplier_codes": [],
        "operation_ids": [], "idempotency_keys": [], "statuses": [],
    }
    constraints: list[str] = []
    unfinished: list[str] = []

    for call in tool_calls:
        _walk_named_values(call.get("args") or {}, values)
        if str(call.get("name") or "") == "write_todos":
            todos = (call.get("args") or {}).get("todos", [])
            for todo in todos if isinstance(todos, list) else []:
                if isinstance(todo, dict) and todo.get("status") != "completed":
                    text = str(todo.get("content") or "").strip()
                    if text and text not in unfinished:
                        unfinished.append(text[:160])

    all_text: list[str] = []
    for message in messages:
        text = _content_of(message).strip()
        if not text:
            continue
        all_text.append(text)
        if _role_of(message) in ("human", "user"):
            for sentence in re.split(r"[。！？;；\n]", text):
                sentence = sentence.strip()
                if sentence and any(marker in sentence for marker in _CONSTRAINT_MARKERS):
                    clipped = sentence[:160]
                    if clipped not in constraints:
                        constraints.append(clipped)
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if payload is not None:
            _walk_named_values(payload, values)

    for text in all_text:
        for order_number in re.findall(r"\bPO\d{8,}\b", text, re.IGNORECASE):
            _append_unique(values, "order_numbers", order_number.upper())
        for operation_id in re.findall(
            r"\b(?:op|operation)[-_][A-Za-z0-9._:-]{4,}\b", text, re.IGNORECASE
        ):
            _append_unique(values, "operation_ids", operation_id)

    entities = [
        *(f"order:{value}" for value in values["order_numbers"]),
        *(f"part:{value}" for value in values["part_codes"]),
        *(f"supplier:{value}" for value in values["supplier_codes"]),
    ]
    return {
        **values,
        "confirmed_constraints": constraints[:10],
        "unfinished_tasks": unfinished[:20],
        "entities": entities,
    }


# ---------------------------------------------------------------- LLM 抽取（可选）

_LLM_EXTRACT_PROMPT = """你是记忆抽取器。从下面这段对话里抽取用户稳定偏好，只输出 JSON，不要解释。

可抽取字段（没有就不写）：
- preferred_chart_type: pie/bar/line/scatter/radar/donut/heatmap/area
- preferred_output: markdown/table/json/list/chart
- preferred_currency: CNY/USD
- preferred_language: zh/en
- recent_suppliers: 字符串数组
只抽取用户明确表达或反复体现的偏好，不要猜测。

对话：
{conversation}

输出 JSON："""


def llm_extract_preferences(messages: Sequence[Any], llm, max_messages: int = 20) -> Dict[str, Any]:
    """可选的 LLM 抽取；返回空 dict 表示失败，调用方回退到规则抽取。"""
    import json

    if llm is None:
        return {}
    window = list(messages or [])[-max_messages:]
    if not window:
        return {}
    transcript = []
    for message in window:
        role = _role_of(message)
        text = _content_of(message).strip()
        if role in ("human", "user", "ai", "assistant") and text:
            transcript.append(f"{role}: {text[:300]}")
    if not transcript:
        return {}

    try:
        response = llm.invoke(_LLM_EXTRACT_PROMPT.format(conversation="\n".join(transcript)))
        raw = getattr(response, "content", response)
        if not isinstance(raw, str):
            return {}
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        data = json.loads(raw[start:end + 1])
        if not isinstance(data, dict):
            return {}
        allowed = {
            "preferred_chart_type", "preferred_output",
            "preferred_currency", "preferred_language", "recent_suppliers",
        }
        return {k: v for k, v in data.items() if k in allowed and v}
    except Exception:
        return {}
