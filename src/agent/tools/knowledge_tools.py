"""业务知识检索工具。"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from ..knowledge.bounded_react import run_bounded_search_tool
from ..knowledge.evidence import BOUNDED_REACT_POLICY
from ..knowledge.ingest import ingest_text
from ..knowledge.store import KnowledgeDoc, get_default_store


@tool
def search_business_knowledge(
    query: str,
    domain: str = "",
    top_k: int = 5,
    auto_rescue: bool = True,
) -> str:
    """检索采购业务知识（SOP / 准入 / 物料规格 / 异常案例）。

    管道：精确编码 + BM25 + 向量 → RRF → 粗筛精排；
    证据不足时自动有界 ReAct 补搜（改写查询、限轮次、只读）。
    用于制度、规格、准入与作业指导等非结构化采购知识检索。

    Args:
        query: 自然语言或物料号/供应商代码
        domain: 可选 procurement_sop | avl | material_spec | exception；空=全库
        top_k: 返回条数，默认 5
        auto_rescue: 证据不足时是否自动补搜，默认 true
    """
    result = run_bounded_search_tool(
        query,
        domain=domain or None,
        top_k=max(1, min(int(top_k or 5), 10)),
        auto_rescue=bool(auto_rescue),
    )
    assessment = result.get("evidence_assessment") or {}
    if result.get("bounded_react_policy") is None and assessment.get("suggest_react"):
        result["bounded_react_policy"] = BOUNDED_REACT_POLICY
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def ingest_pdf_knowledge(
    file_path: str,
    domain: str = "",
    source: str = "",
    version: str = "v1",
    split_sections: bool = True,
    overwrite: bool = False,
) -> str:
    """PDF 入库：抽取（OCR 降级）→ 分段结构化 → 去重 → 写入知识库。

    Args:
        file_path: 本地 PDF 路径
        domain: 可选 procurement_sop|avl|material_spec|exception；空则规则推断
        source: 来源名，默认文件名
        version: 版本号
        split_sections: 是否按标题分段入库
        overwrite: 同 source+title 是否覆盖
    """
    from ..knowledge.pdf_pipeline import ingest_pdf

    report = ingest_pdf(
        file_path,
        domain=domain or None,
        source=source or None,
        version=version,
        store=get_default_store(),
        split=bool(split_sections),
        overwrite=bool(overwrite),
    )
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


@tool
def ingest_business_knowledge(
    title: str,
    content: str,
    domain: str,
    source: str,
    version: str = "v1",
    overwrite: bool = False,
) -> str:
    """将文本知识条目入库（去重：source+title / 编码+标题 / 向量相似）。

    用于 SOP/规格草稿发布。内容级重复默认拒绝；同 source+title 可覆盖。

    Args:
        title: 标题
        content: 正文
        domain: procurement_sop | avl | material_spec | exception
        source: 来源说明（制度名/文件名）
        version: 版本号
        overwrite: 仅对 same_source_title 覆盖；内容级重复仍拒绝
    """
    allowed = {"procurement_sop", "avl", "material_spec", "exception"}
    if domain not in allowed:
        return json.dumps(
            {"ok": False, "error": f"domain 须为 {sorted(allowed)}"},
            ensure_ascii=False,
        )
    out = ingest_text(
        content,
        title=title,
        domain=domain,
        source=source,
        version=version,
        store=get_default_store(),
        overwrite=bool(overwrite),
        check_dedup=True,
    )
    if isinstance(out, KnowledgeDoc):
        return json.dumps({"ok": True, "data": out.to_dict()}, ensure_ascii=False, indent=2)
    return json.dumps(out, ensure_ascii=False, indent=2)
