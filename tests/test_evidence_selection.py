import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from paper_research_agent.analysis.analyzer import PaperAnalyzer
from paper_research_agent.analysis.chunking import chunk_pages
from paper_research_agent.analysis.evidence import build_catalog
from paper_research_agent.analysis.models import AnalysisSelection
from paper_research_agent.agent.budget import BudgetedLLM, ResourceError
from paper_research_agent.config import Settings
from test_analysis import MCP, document, llm_for
from test_agent import response


def test_catalog_quotes_are_short_and_page_grounded():
    text = "PDF ligature ﬁ,\n中文原文。\n" * 100
    pages = [{"page_number":3,"text":text}]
    chunks = chunk_pages(pages,12000,24)
    catalog = build_catalog(chunks[0])
    assert catalog and len({e.id for e in catalog.values()}) == len(catalog)
    assert all(e.page_number == 3 and len(e.quote) <= 180 and e.quote in text for e in catalog.values())
    schema = AnalysisSelection.model_json_schema()
    assert "evidence" not in schema["properties"]
    assert "Evidence" not in schema.get("$defs",{})


def test_llm_selects_ids_code_restores_quotes_and_pages():
    settings = Settings()
    expected = build_catalog(chunk_pages(document()["pages"],12000,24)[0])["c1-s1"]
    data = {"methodology":[{"text":"模型推断", "provenance":"inference", "evidence_ids":["c1-s1"]}]}
    result = asyncio.run(PaperAnalyzer(MCP(),BudgetedLLM(llm_for([data]),settings),settings).analyze("local","source.pdf"))
    assert result.evidence[0].quote == expected.quote
    assert result.evidence[0].page_number == expected.page_number
    assert result.methodology[0].evidence_ids == [result.evidence[0].id]


def test_unknown_selected_id_is_not_filled_with_invented_evidence():
    settings = Settings(analysis_format_retries=0)
    data = {"results":[{"text":"claim", "provenance":"author_stated","evidence_ids":["invented-id"]}]}
    with pytest.raises(ResourceError) as exc:
        asyncio.run(PaperAnalyzer(MCP(),BudgetedLLM(llm_for([data]),settings),settings).analyze("local","source.pdf"))
    assert exc.value.code == "invalid_evidence" and "Unknown evidence ID" in str(exc.value)


def test_hierarchy_uses_only_ids_not_model_generated_quotes():
    settings = Settings(analysis_chunk_bytes=256)
    async def generated(**kwargs):
        payload = json.loads(kwargs["messages"][-1]["content"])
        assert "evidence_catalog" in payload
        assert '"Evidence"' not in kwargs["messages"][0]["content"]
        ident = payload["evidence_catalog"][0]["id"]
        return response(text=json.dumps({"methodology":[{"text":"Supported note","provenance":"inference","evidence_ids":[ident]}]}))
    raw = NS(chat=NS(completions=NS(create=generated)))
    pdf = document("Methods\n" + "Exact original sentence.\n" * 30)
    result = asyncio.run(PaperAnalyzer(MCP(pdf),BudgetedLLM(raw,settings),settings).analyze("local","source.pdf"))
    assert result.chunk_count > 1 and result.complete
    assert all(e.quote in pdf["pages"][0]["text"] for e in result.evidence)
