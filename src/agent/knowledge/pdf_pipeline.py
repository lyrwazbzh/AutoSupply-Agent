"""PDF 入库完整链：抽取（含 OCR 降级）→ 分段结构化 → 去重 → 入库。"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .dedup import check_duplicate
from .ingest import _doc_id, structurize_text
from .store import KnowledgeDoc, KnowledgeStore, get_default_store

logger = logging.getLogger(__name__)
_MAX_CHARS = 12000


@dataclass
class PdfIngestReport:
    ok: bool
    docs: list[dict[str, Any]] = field(default_factory=list)
    skipped_duplicates: list[dict[str, Any]] = field(default_factory=list)
    extract_method: str = ""
    page_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_pdf_text(path: Path | str) -> tuple[str, str, int]:
    """返回 (text, method, page_count)。method=pdfplumber|pypdf|ocr|empty。"""
    path = Path(path)
    text, method, pages = _extract_native(path)
    if text.strip():
        return text[:_MAX_CHARS], method, pages
    ocr_text, ocr_pages = _extract_ocr(path)
    if ocr_text.strip():
        return ocr_text[:_MAX_CHARS], "ocr", ocr_pages or pages
    return "", "empty", pages


def _extract_native(path: Path) -> tuple[str, str, int]:
    try:
        import pdfplumber  # type: ignore

        parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
            n = len(pdf.pages)
        return "\n".join(parts), "pdfplumber", n
    except ImportError:
        pass
    except Exception as e:
        logger.warning("pdfplumber 失败: %s", e)

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return "", "empty", 0
    try:
        reader = PdfReader(str(path))
        parts = [(p.extract_text() or "") for p in reader.pages]
        return "\n".join(parts), "pypdf", len(reader.pages)
    except Exception as e:
        logger.warning("pypdf 失败: %s", e)
        return "", "empty", 0


def _extract_ocr(path: Path) -> tuple[str, int]:
    """可选 OCR：优先 rapidocr_onnxruntime，其次 pytesseract+pdf2image。"""
    try:
        import pdfplumber  # type: ignore
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        engine = RapidOCR()
        parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                img = page.to_image(resolution=150).original
                result, _ = engine(img)
                if result:
                    parts.append("\n".join(row[1] for row in result if len(row) > 1))
            return "\n".join(parts), len(pdf.pages)
    except Exception as e:
        logger.info("RapidOCR 不可用: %s", e)

    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore

        images = convert_from_path(str(path), dpi=150)
        parts = [pytesseract.image_to_string(img, lang="chi_sim+eng") for img in images]
        return "\n".join(parts), len(images)
    except Exception as e:
        logger.info("pytesseract OCR 不可用: %s", e)
        return "", 0


def split_sections(text: str, *, title_hint: str = "") -> list[tuple[str, str]]:
    """按 Markdown/中文章标题分段；无标题则整篇一条。"""
    text = (text or "").strip()
    if not text:
        return []
    # # 标题 或 一、二、 或 第X章
    pattern = re.compile(
        r"(?m)^(#{1,3}\s+.+$|[一二三四五六七八九十]+[、.．]\s*.+$|第[一二三四五六七八九十\d]+[章节条款].*$)"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return [(title_hint or "全文", text)]

    sections: list[tuple[str, str]] = []
    # 前言
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append((title_hint or "前言", preamble))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        title = m.group(0).lstrip("#").strip()[:80]
        body = block[len(m.group(0)) :].strip() or block
        sections.append((title, body))
    return sections


def ingest_pdf(
    path: Path | str,
    *,
    domain: Optional[str] = None,
    source: Optional[str] = None,
    version: str = "v1",
    store: Optional[KnowledgeStore] = None,
    split: bool = True,
    overwrite: bool = False,
) -> PdfIngestReport:
    path = Path(path)
    if not path.exists():
        return PdfIngestReport(ok=False, error=f"文件不存在: {path}")

    text, method, pages = extract_pdf_text(path)
    if not text.strip():
        return PdfIngestReport(
            ok=False,
            extract_method=method,
            page_count=pages,
            error="PDF 未能提取到文本（可安装 rapidocr_onnxruntime 或 pytesseract 启用 OCR）",
        )

    store = store or get_default_store()
    src = source or path.name
    chunks = split_sections(text, title_hint=path.stem) if split else [(path.stem, text)]

    docs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for title, body in chunks:
        structured = structurize_text(
            body, title=title, domain=domain, source=src, version=version
        )
        doc_id = _doc_id(structured.title, structured.source)
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
        if decision.is_duplicate and decision.reason != "same_source_title":
            skipped.append(decision.to_dict())
            continue
        if decision.is_duplicate and decision.reason == "same_source_title" and not overwrite:
            skipped.append({**decision.to_dict(), "note": "same_key_skip"})
            continue

        doc = KnowledgeDoc(
            id=doc_id,
            title=structured.title,
            content=structured.content,
            domain=structured.domain,
            source=structured.source,
            version=structured.version,
            tags=structured.tags + ["pdf", method],
            part_codes=structured.part_codes,
            supplier_codes=structured.supplier_codes,
        )
        store.upsert(doc)
        docs.append(doc.to_dict())

    return PdfIngestReport(
        ok=bool(docs),
        docs=docs,
        skipped_duplicates=skipped,
        extract_method=method,
        page_count=pages,
        error=None if docs else ("全部被去重跳过" if skipped else "无有效分段"),
    )
