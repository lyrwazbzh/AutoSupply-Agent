"""Harness 审查用文本、规则开关与句向量选型。

审查开关与任务类型分开判定。Store/Mongo 不参与本模块。
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from .memory.embeddings import cosine
from .memory.rewrite import rewrite_retrieval_query

_FOLLOW_MARKERS = re.compile(
    r"再|也来|还是|那个|那家|那几家|上次|同上|这票|这几家|继续"
)

_DEFAULT_TRIVIAL_PATTERNS = (
    re.compile(
        r"^(?:你好|您好|嗨|哈喽|hello|hi|hey|早上好|晚上好|晚安|谢谢|感谢|多谢|"
        r"在吗|你是谁|再见|拜拜|好的|好哒|收到|明白|了解|ok|okay|行|嗯|嗯嗯)"
        r"[!！。,.，、\s~～]*$",
        re.IGNORECASE,
    ),
)

_DEFINITION_PATTERN = re.compile(
    r"^(?:什么是|什么叫|何为|如何理解|请解释|解释一下).*"
    r"[？?。.!！\s]*$|.*(?:是什么|什么意思|含义|定义)[？?。.!！\s]*$",
    re.IGNORECASE,
)

_COMPOUND_ACTIONS = (
    "列出", "查询", "统计", "分析", "对比", "生成", "导出",
    "缺料", "下单", "帮我", "并给", "并列出",
)

_ENTITY_RE = re.compile(
    r"(?:SKU[-_]?|物料|料号|零件号)[\w-]{2,}|"
    r"(?:订单号?|PO|SO)[-_]?\d{3,}|"
    r"工厂[\w\u4e00-\u9fff]{1,12}",
    re.IGNORECASE,
)

_DEFAULT_REVIEW_TRIGGER_KEYWORDS = (
    "查询", "搜索", "获取", "列出", "统计", "分析", "对比", "比较", "评估",
    "报表", "报告", "图表", "下单", "采购", "订单", "审批", "创建", "修改", "删除",
    "库存", "入库", "出库", "盘点", "预警", "供应商", "供货", "价格", "报价",
    "生成", "导出", "下载", "上传", "安装", "配置", "执行", "调用", "脚本", "代码",
    "文件", "批量", "验证", "检查", "审查", "复核", "评审", "验收", "完整", "详细", "请帮我做",
)


def _message_text(msg: Any) -> str:
    content = getattr(msg, "content", "") or ""
    if isinstance(content, list):
        content = " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return re.sub(r"\s+", " ", str(content)).strip()


def human_texts(messages: list[Any] | None) -> list[str]:
    texts: list[str] = []
    for msg in messages or []:
        if getattr(msg, "type", "") != "human":
            continue
        text = _message_text(msg)
        if text:
            texts.append(text)
    return texts


def latest_human_text(messages: list[Any] | None) -> str:
    texts = human_texts(messages)
    return texts[-1] if texts else ""


def review_text(messages: list[Any] | None) -> str:
    """一句审查用文本：跟进句用上一轮用户话填槽。"""
    texts = human_texts(messages)
    if not texts:
        return ""
    current = texts[-1]
    if len(texts) >= 2 and _FOLLOW_MARKERS.search(current):
        return rewrite_retrieval_query(current, texts[-2])
    return current


def is_trivial_greeting(text: str) -> bool:
    if not text:
        return True
    return any(pattern.fullmatch(text) for pattern in _DEFAULT_TRIVIAL_PATTERNS)


def is_short_definition(text: str) -> bool:
    if not text or not _DEFINITION_PATTERN.fullmatch(text):
        return False
    return not has_compound_action(text)


def has_compound_action(text: str) -> bool:
    return any(token in text for token in _COMPOUND_ACTIONS)


def has_business_entity(text: str) -> bool:
    return bool(text and _ENTITY_RE.search(text))


def is_trivial_or_conceptual(text: str) -> bool:
    """问候整句或短单句定义（无第二业务动作）。"""
    if not text:
        return True
    if is_trivial_greeting(text):
        return True
    return is_short_definition(text)


def rule_grade_decision(text: str) -> bool | None:
    """规则层：True 审查 / False 跳过 / None 未决。"""
    if not text:
        return False
    if is_trivial_greeting(text):
        return False
    if _DEFINITION_PATTERN.fullmatch(text) and has_compound_action(text):
        return True
    if is_short_definition(text):
        return False
    if has_business_entity(text):
        return True
    return None


def _example_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _embed_one(embedder: Any, text: str) -> list[float] | None:
    if embedder is None or not text:
        return None
    try:
        vectors = embedder.embed_texts([text])
    except Exception:
        return None
    if not vectors or not vectors[0]:
        return None
    return [float(x) for x in vectors[0]]


def max_example_similarity(query_vec: Sequence[float] | None, examples: list[str], embedder: Any) -> float:
    if not query_vec or not examples or embedder is None:
        return 0.0
    best = 0.0
    for example in examples:
        vec = _embed_one(embedder, example)
        best = max(best, cosine(query_vec, vec))
    return best


def vector_should_grade(
    text: str,
    review_config: dict[str, Any],
    embedder: Any,
) -> bool | None:
    """句向量二分类。无法编码时返回 None。"""
    need = _example_list(review_config.get("examples_need_review"))
    skip = _example_list(review_config.get("examples_skip_review"))
    if embedder is None or (not need and not skip):
        return None
    query_vec = _embed_one(embedder, text)
    if query_vec is None:
        return None
    try:
        t_skip = float(review_config.get("t_skip", 0.55))
        t_grade = float(review_config.get("t_grade", 0.40))
    except (TypeError, ValueError):
        t_skip, t_grade = 0.55, 0.40
    sim_grade = max_example_similarity(query_vec, need, embedder)
    sim_skip = max_example_similarity(query_vec, skip, embedder)
    if sim_skip > t_skip and sim_skip > sim_grade:
        return False
    if sim_grade > t_grade:
        return True
    return True


def _trigger_keywords(review_config: dict[str, Any]) -> tuple[str, ...]:
    configured = review_config.get("trigger_keywords")
    if isinstance(configured, list):
        return tuple(str(item) for item in configured if item)
    return _DEFAULT_REVIEW_TRIGGER_KEYWORDS


def detect_task_type(
    messages: list[Any],
    config: dict[str, Any],
    embedder: Any = None,
    text: str | None = None,
) -> str:
    """选出 rubric 类型。关键词平局或向量平局时为 default。"""
    task_types = config.get("task_types", {}) if isinstance(config, dict) else {}
    if not task_types:
        return "default"
    resolved = (text if text is not None else review_text(messages)).strip()
    if not resolved:
        return "default"

    scored: list[tuple[str, int]] = []
    for task_type, spec in task_types.items():
        keywords = spec.get("keywords", []) if isinstance(spec, dict) else []
        score = sum(1 for kw in keywords if kw in resolved)
        scored.append((str(task_type), score))
    best_kw = max((s for _, s in scored), default=0)
    if best_kw > 0:
        winners = [name for name, s in scored if s == best_kw]
        if len(winners) == 1:
            return winners[0]
        return "default"

    if embedder is None:
        return "default"
    query_vec = _embed_one(embedder, resolved)
    if query_vec is None:
        return "default"
    try:
        t_type = float((config.get("review") or {}).get("t_type", 0.50))
    except (TypeError, ValueError):
        t_type = 0.50
    typed: list[tuple[str, float]] = []
    for task_type, spec in task_types.items():
        examples = _example_list(spec.get("examples") if isinstance(spec, dict) else None)
        sim = max_example_similarity(query_vec, examples, embedder)
        typed.append((str(task_type), sim))
    if not typed:
        return "default"
    best_sim = max(s for _, s in typed)
    if best_sim <= t_type:
        return "default"
    winners = [name for name, s in typed if s == best_sim]
    if len(winners) == 1:
        return winners[0]
    return "default"


def should_use_grader(
    messages: list[Any] | None,
    config: dict[str, Any],
    embedder: Any = None,
) -> bool:
    """是否往 state 写入 rubric。类型名不作为本开关的充分条件。"""
    review_config = config.get("review", {}) if isinstance(config, dict) else {}
    review_config = review_config if isinstance(review_config, dict) else {}
    mode = str(review_config.get("mode", "auto")).strip().lower()
    text = review_text(messages)

    if mode == "never":
        return False
    if mode == "always":
        return bool(text)
    if not text:
        return False

    decided = rule_grade_decision(text)
    if decided is not None:
        return decided

    vector = vector_should_grade(text, review_config, embedder)
    if vector is not None:
        return vector

    return any(keyword in text for keyword in _trigger_keywords(review_config))
