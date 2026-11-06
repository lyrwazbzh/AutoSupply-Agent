"""业务知识混合检索单测（Smart-Repair 级：BM25 + vector + RRF + 精排降级）。"""

from __future__ import annotations

import unittest

from src.agent.knowledge.bm25 import get_bm25_index
from src.agent.knowledge.bounded_react import bounded_retrieve, rewrite_query
from src.agent.knowledge.dedup import check_duplicate
from src.agent.knowledge.evidence import assess_evidence
from src.agent.knowledge.ingest import ingest_text, structurize_text
from src.agent.knowledge.retrieval_flow import (
    evaluate_retrieval_quality,
    filter_rerank,
    retrieve_hybrid,
)
from src.agent.knowledge.retrieve import hybrid_retrieve, rrf_merge
from src.agent.knowledge.store import KnowledgeDoc, KnowledgeStore, get_default_store


class HybridRetrieveTests(unittest.TestCase):
    def setUp(self):
        # 种子可能在进程内已缓存；用文件重载保证条数断言稳定
        store = get_default_store()
        if len(store.all()) < 8:
            from src.agent.knowledge.store import SEED_PATH

            store.load_json(SEED_PATH)
        self.store = store

    def test_seed_loaded(self):
        self.assertGreaterEqual(len(self.store.all()), 8)

    def test_avl_query_has_source(self):
        result = hybrid_retrieve("供应商准入信用等级要求", domain="avl", store=self.store)
        self.assertTrue(result["hits"])
        hit = result["hits"][0]
        self.assertTrue(hit.get("source"))
        self.assertTrue(hit.get("version"))
        self.assertIn("bm25", result["methods"])
        assessment = assess_evidence(result)
        self.assertTrue(assessment.sufficient)

    def test_exact_part_code(self):
        result = hybrid_retrieve("P-EN-0001 规格", store=self.store)
        ids = [h["id"] for h in result["hits"]]
        self.assertIn("spec-spark-001", ids)
        self.assertIn("exact", result["methods"])

    def test_exact_supplier_code(self):
        result = hybrid_retrieve("SUP0001 准入信用", store=self.store)
        ids = [h["id"] for h in result["hits"]]
        self.assertTrue(any(i in ids for i in ("avl-sup0001", "sop-avl-001")))

    def test_bm25_index_ranks_title(self):
        idx = get_bm25_index(self.store.all())
        hits = idx.search("采购补货 SOP", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].id, "sop-po-002")

    def test_rrf_merge_dedup(self):
        a = [{"id": "1", "_dedup_key": "K:1", "score": 0.9, "method": "a"}]
        b = [{"id": "1", "_dedup_key": "K:1", "score": 0.5, "method": "b"}]
        merged = rrf_merge([a, b], top_n=3)
        self.assertEqual(len(merged), 1)
        self.assertGreater(merged[0]["rrf_score"], 0)

    def test_rerank_rules_fallback(self):
        result = retrieve_hybrid(
            "制动片延期异常怎么处理",
            store=self.store,
            enable_vector=True,
            enable_rerank=True,
        )
        self.assertTrue(result["hits"])
        self.assertIn(result["rerank_mode"], {"rules", "http", "skip"})
        ids = [h["id"] for h in result["hits"]]
        self.assertTrue(
            any(i in ids for i in ("exc-delay-001", "spec-brake-001")),
            msg=ids,
        )

    def test_vector_disabled_degrades_to_bm25(self):
        result = retrieve_hybrid(
            "供应商信用等级 A",
            domain="avl",
            store=self.store,
            enable_vector=False,
        )
        self.assertIn("bm25", result["methods"])
        self.assertNotIn("vector", result["methods"])
        self.assertTrue(result["hits"])

    def test_filter_rerank_empty(self):
        hits, mode = filter_rerank([], "anything")
        self.assertEqual(hits, [])
        self.assertEqual(mode, "empty")

    def test_evaluate_quality(self):
        q = evaluate_retrieval_quality([])
        self.assertFalse(q["sufficient"])
        q2 = evaluate_retrieval_quality(
            [{"score": 0.8, "rrf_score": 0.02}, {"rerank_score": 0.7}]
        )
        self.assertTrue(q2["sufficient"])

    def test_assess_evidence_empty(self):
        assessment = assess_evidence({"hits": []})
        self.assertFalse(assessment.sufficient)
        self.assertTrue(assessment.suggest_react)

    def test_ingest_overwrite_same_key(self):
        store = KnowledgeStore()
        d1 = ingest_text(
            "测试内容准入",
            title="测试制度",
            domain="avl",
            source="unit-test",
            store=store,
            overwrite=True,
        )
        self.assertIsInstance(d1, KnowledgeDoc)
        d2 = ingest_text(
            "更新后的内容",
            title="测试制度",
            domain="avl",
            source="unit-test",
            store=store,
            overwrite=True,
        )
        self.assertIsInstance(d2, KnowledgeDoc)
        self.assertEqual(d1.id, d2.id)
        self.assertEqual(len(store.all()), 1)
        self.assertIn("更新", store.get(d1.id).content)

    def test_structurize_extracts_codes(self):
        s = structurize_text(
            "零件编码 P-EN-0001 由供应商 SUP0005 供货，技术规格要点如下。",
            title="规格草稿",
        )
        self.assertEqual(s.domain, "material_spec")
        self.assertIn("P-EN-0001", s.part_codes)
        self.assertIn("SUP0005", s.supplier_codes)

    def test_dedup_code_and_title(self):
        store = KnowledgeStore()
        store.upsert(
            KnowledgeDoc(
                id="x1",
                title="火花塞规格",
                content="P-EN-0001 铱金",
                domain="material_spec",
                source="a",
                version="v1",
                part_codes=["P-EN-0001"],
            )
        )
        d = check_duplicate(
            title="火花塞规格要点",
            content="另一种写法",
            source="b",
            domain="material_spec",
            part_codes=["P-EN-0001"],
            store=store,
        )
        self.assertTrue(d.is_duplicate)
        self.assertEqual(d.reason, "code_and_title")

    def test_bounded_react_rewrite(self):
        q = rewrite_query("供应商准入信用", 0, [])
        self.assertIn("AVL", q)

    def test_bounded_retrieve_runs(self):
        result = bounded_retrieve(
            "供应商准入信用等级要求",
            domain="avl",
            top_k=3,
            store=self.store,
            max_rounds=1,
        )
        self.assertTrue(result.get("hits"))
        self.assertIn("evidence_assessment", result)
        # 首轮充分则无需补搜
        if result["evidence_assessment"].get("sufficient"):
            self.assertEqual(result.get("react_rounds"), [])

    def test_pdf_section_split_and_ingest_text_as_pdf_body(self):
        from src.agent.knowledge.pdf_pipeline import split_sections

        sections = split_sections(
            "# 准入制度\n信用 A/B 可量产\n# 异常处置\n延期须人工审批\n",
            title_hint="手册",
        )
        self.assertGreaterEqual(len(sections), 2)
        # 无真实 PDF 时用文本管道等价验证分段入库
        store = KnowledgeStore()
        # 直接走 structurize+dedup 路径：模拟 pdf 分段结果
        from src.agent.knowledge.ingest import ingest_text

        for title, body in sections:
            out = ingest_text(
                body,
                title=title,
                domain="avl",
                source="pdf-demo.pdf",
                store=store,
                overwrite=True,
            )
            self.assertTrue(hasattr(out, "id") or isinstance(out, dict))
        self.assertGreaterEqual(len(store.all()), 2)


if __name__ == "__main__":
    unittest.main()
