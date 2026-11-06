"""知识入库：Markdown/纯文本/PDF → 轻量结构化 → 去重 → KnowledgeStore。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .dedup import check_duplicate
from .store import KnowledgeDoc, KnowledgeStore, get_default_store

_MAX_PDF_CHARS = 12000

_DOMAIN_HINTS = [
    (r"准入|信用|AVL|供应商等级", "avl"),
    (r"SOP|作业指导|补货|审批", "procurement_sop"),
    (r"规格|技术要求|电极|摩擦|验收", "material_spec"),
    (r"延期|异常|台账|处置", "exception"),
]


def _doc_id(title: str, source: str) -> str:
    digest = hashlib.sha1(f"{source}:{title}".encode("utf-8")).hexdigest()[:10]
    return f"ing-{digest}"


@dataclass
class StructuredDoc:
    title: str
    content: str
    domain: str
    source: str
    version: str = "v1"
    tags: list[str] = field(default_factory=list)
    part_codes: list[str] = field(default_factory=list)
    supplier_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def structurize_text(
    text: str,
    *,
    title: Optional[str] = None,
    domain: Optional[str] = None,
    source: str = "upload",
    version: str = "v1",
) -> StructuredDoc:
    """规则结构化：抽编码、推断 domain、截取正文（采购域 schema）。"""
    raw = (text or "").strip()
    if len(raw) > _MAX_PDF_CHARS:
        raw = raw[:_MAX_PDF_CHARS] + "\n…[截断]"

    part_codes = list(dict.fromkeys(re.findall(r"P-[A-Z]{2}-\d{4}", raw, re.I)))
    part_codes = [c.upper() for c in part_codes]
    supplier_codes = list(dict.fromkeys(re.findall(r"SUP\d{4}", raw, re.I)))
    supplier_codes = [c.upper() for c in supplier_codes]

    inferred = domain
    if not inferred:
        for pat, dom in _DOMAIN_HINTS:
            if re.search(pat, raw):
                inferred = dom
                break
    inferred = inferred or "procurement_sop"

    # 标题：参数 > 首行短标题 > stem
    if title:
        t = title.strip()
    else:
        first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "未命名知识")
        t = first[:80]

    tags: list[str] = []
    for kw in ("准入", "SOP", "规格", "延期", "审批", "补货"):
        if kw in raw:
            tags.append(kw)

    return StructuredDoc(
        title=t,
        content=raw,
        domain=inferred,
        source=source,
        version=version,
        tags=tags,
        part_codes=part_codes,
        supplier_codes=supplier_codes,
    )


def ingest_text(
    text: str,
    *,
    title: str,
    domain: str,
    source: str,
    version: str = "v1",
    part_codes: Optional[list[str]] = None,
    supplier_codes: Optional[list[str]] = None,
    store: Optional[KnowledgeStore] = None,
    overwrite: bool = True,
    check_dedup: bool = True,
) -> KnowledgeDoc | dict[str, Any]:
    """入库。check_dedup=True 且非 overwrite 命中真重复时返回 {ok:False, dedup:...}。"""
    store = store or get_default_store()
    structured = structurize_text(
        text, title=title, domain=domain, source=source, version=version
    )
    if part_codes:
        structured.part_codes = list(dict.fromkeys(part_codes + structured.part_codes))
    if supplier_codes:
        structured.supplier_codes = list(
            dict.fromkeys(supplier_codes + structured.supplier_codes)
        )

    doc_id = _doc_id(structured.title, structured.source)
    if check_dedup:
        decision = check_duplicate(
            title=structured.title,
            content=structured.content,
            source=structured.source,
            domain=structured.domain,
            part_codes=structured.part_codes,
            supplier_codes=structured.supplier_codes,
            store=store,
            exact_id=doc_id if store.get(doc_id) else None,
        )
        # same_source_title → 允许覆盖
        if decision.is_duplicate and decision.reason != "same_source_title":
            if not overwrite:
                return {
                    "ok": False,
                    "error": "duplicate",
                    "dedup": decision.to_dict(),
                }
            # overwrite=True 但对内容级重复：仍拒绝自动新建，避免污染库
            if decision.reason in ("vector_similarity", "code_and_title"):
                return {
                    "ok": False,
                    "error": "duplicate",
                    "dedup": decision.to_dict(),
                }

    doc = KnowledgeDoc(
        id=doc_id,
        title=structured.title,
        content=structured.content,
        domain=structured.domain,
        source=structured.source,
        version=structured.version,
        tags=structured.tags,
        part_codes=structured.part_codes,
        supplier_codes=structured.supplier_codes,
    )
    store.upsert(doc)
    return doc


def ingest_file(
    path: Path | str,
    *,
    domain: Optional[str] = None,
    source: Optional[str] = None,
    version: str = "v1",
    store: Optional[KnowledgeStore] = None,
    overwrite: bool = True,
    check_dedup: bool = True,
) -> KnowledgeDoc | dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from .pdf_pipeline import ingest_pdf

        report = ingest_pdf(
            path,
            domain=domain,
            source=source,
            version=version,
            store=store,
            split=True,
            overwrite=overwrite,
        )
        if report.docs:
            # 兼容旧返回：取首条 KnowledgeDoc
            row = report.docs[0]
            return KnowledgeDoc(**{k: row[k] for k in KnowledgeDoc.__dataclass_fields__})
        return {"ok": False, "error": report.error, "report": report.to_dict()}

    text = _read_file_text(path)
    structured = structurize_text(
        text,
        title=path.stem,
        domain=domain,
        source=source or path.name,
        version=version,
    )
    return ingest_text(
        structured.content,
        title=structured.title,
        domain=structured.domain,
        source=structured.source,
        version=structured.version,
        part_codes=structured.part_codes,
        supplier_codes=structured.supplier_codes,
        store=store,
        overwrite=overwrite,
        check_dedup=check_dedup,
    )


def _read_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        from .pdf_pipeline import extract_pdf_text

        text, _, _ = extract_pdf_text(path)
        if not text:
            raise RuntimeError("PDF 未能提取到文本")
        return text
    raise ValueError(f"不支持的文件类型: {suffix}")
