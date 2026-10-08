"""检索前的问题改写：用上文把指代收成可检索的短句。

规则改写始终可用（零模型调用）。配置打开 ``query_rewrite_llm`` 时，
再尝试一次短提示改写，失败则回落到规则结果。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

_ANAPHORA = re.compile(
    r"那家|那个|那几家|这家|这票|他们|它的|上次|之前|刚才|同上"
)
_ENTITY_RE = re.compile(
    r"[\u4e00-\u9fff]{2,12}(?:机械|电子|科技|实业|集团|公司|厂)?"
)


def entities_from_context(context: str) -> list[str]:
    """从上文抽出可能的实体名（厂商/物料称呼），供规则替换「那家」等。"""
    text = context or ""
    found: list[str] = []
    seen: set[str] = set()
    for match in _ENTITY_RE.finditer(text):
        name = match.group(0)
        if name in seen or len(name) < 2:
            continue
        if name in ("近期任务", "图表类型", "输出格式", "计价货币", "回复语言"):
            continue
        seen.add(name)
        found.append(name)
    return found


def rewrite_retrieval_query(
    query: str,
    context: str = "",
    *,
    llm_fn: Optional[Callable[[str, str], str]] = None,
) -> str:
    """把带指代的检索句改写成带实体的检索句。

    有指代且有上文时：优先 ``llm_fn``；否则把上文实体填进原句，
    或把上文片段接到查询后面（查询扩展）。
    """
    q = re.sub(r"\s+", " ", (query or "")).strip()
    ctx = re.sub(r"\s+", " ", (context or "")).strip()
    if not q:
        return ""

    if llm_fn and ctx:
        try:
            out = (llm_fn(q, ctx) or "").strip()
            if out:
                return re.sub(r"\s+", " ", out)
        except Exception:
            pass

    if ctx and _ANAPHORA.search(q):
        rewritten = q
        for name in entities_from_context(ctx)[:4]:
            if name in rewritten:
                continue
            if "那家" in rewritten:
                rewritten = rewritten.replace("那家", name, 1)
                continue
            if "那个" in rewritten:
                rewritten = rewritten.replace("那个", name, 1)
                continue
            if "这家" in rewritten:
                rewritten = rewritten.replace("这家", name, 1)
                continue
            rewritten = f"{rewritten} {name}"
            break
        if rewritten == q:
            rewritten = f"{q} {ctx[:120]}"
        return rewritten.strip()
    return q


def llm_rewrite_query(query: str, context: str) -> str:
    """用主模型做一句检索改写；调用方捕获异常。"""
    from ..config import get_llm

    llm = get_llm(thinking=False)
    prompt = (
        "你把用户的检索问句改写成不依赖指代、可独立检索的一句中文。"
        "保留原意，补全「那家/上次/这票」等所指对象。只输出改写后的问句。\n"
        f"上文：{context[:800]}\n"
        f"问句：{query}"
    )
    message = llm.invoke(prompt)
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = " ".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content).strip().strip('"“”')
