import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from paper_research_agent.analysis.models import AnalysisContent, Claim, TopicPlan, PaperAnalysis
from paper_research_agent.analysis.chunking import chunk_pages
from paper_research_agent.analysis.analyzer import PaperAnalyzer
from paper_research_agent.analysis.recommender import PaperRecommender, build_queries
from paper_research_agent.analysis.service import ResearchService
from paper_research_agent.agent.budget import BudgetedLLM, ResourceError
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.config import Settings
from test_agent import response, call


TEXT = "Research Paper\n1 Methods\nWe use scheduling.\n2 Results\nWe improve energy by 10%.\n3 Limitations\nSingle site only."


def document(text=TEXT, page_count=1):
    return {"success":True,"source_type":"local","document_id":"source.pdf", "total_pages":page_count,
        "pages":[{"page_number":i + 1,"text":text} for i in range(page_count)],
        "full_text":text, "warnings":[], "error":None}


def notes():
    return {"title":"Research Paper", "methodology":[{"text":"使用 scheduling", "provenance":"author_stated", "evidence_ids":["e1"]}],
        "results":[{"text":"作者报告能耗改善 10%", "provenance":"author_stated", "evidence_ids":["e2"]}],
        "evidence":[{"id":"e1","page_number":1,"quote":"We use scheduling."}, {"id":"e2","page_number":1,"quote":"We improve energy by 10%."}], "keywords":["scheduling","energy management"]}


def llm_for(items):
    return NS(chat=NS(completions=NS(create=AsyncMock(side_effect=[response(text=json.dumps(i,ensure_ascii=False)) for i in items]))))


class MCP:
    def __init__(self, pdf=None, papers=None):
        self.pdf = pdf if pdf is not None else document()
        self.papers = papers or []
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return deepcopy(self.pdf if name == "read_pdf" else {"success":True,"papers":self.papers,"warnings":[]})


def analyze(items=None, pdf=None, **config):
    settings = Settings(**config)
    llm = BudgetedLLM(llm_for(items or [notes()]), settings)
    return asyncio.run(PaperAnalyzer(MCP(pdf), llm, settings).analyze("local", file_path="source.pdf"))


def test_short_analysis_and_missing_fields():
    report = analyze()
    assert isinstance(report, PaperAnalysis) and report.complete
    assert report.methodology[0].provenance == "author_stated"
    assert report.experiments[0].text == "Not specified"
    assert report.evidence[0].page_number == 1 and report.evidence[0].id == "c1-e1"
    assert report.methodology[0].evidence_ids == ["c1-e1"]
    assert report.keywords == ["scheduling", "energy management"]
    assert "Methods" in report.sections[0]


@pytest.mark.parametrize("data", [{"text":"Invented fact"}, {"text":"Not specified","provenance":"author_stated"}, {"text":"fact","provenance":"inference","evidence_ids":[]}])
def test_claim_model_validation(data):
    with pytest.raises(ValidationError):
        Claim.model_validate(data)


def test_incomplete_pdf():
    data = document()
    data["total_pages"] = 3
    data["pages"].append({"page_number":2,"text":""})
    data["warnings"] = ["Page 2 is scanned"]
    report = analyze(pdf=data)
    assert not report.complete and report.missing_pages == [2,3]
    assert report.analyzed_pages == [1] and any("incomplete" in w for w in report.warnings)


def test_lossless_long_chunking():
    text = ("1 Methods\n" + "中文数据 and English.\n" * 100 + "2 Results\nFINAL RESULT 42")
    pages = [{"page_number":1,"text":text}, {"page_number":2,"text":"3 Conclusion\nLast page evidence"}]
    chunks = chunk_pages(pages, 256, 100)
    assert len(chunks) > 2
    for page in pages:
        spans = [s for c in chunks for s in c.spans if s.page_number == page["page_number"]]
        assert "".join(s.text for s in spans) == page["text"]
        assert all(s.text == page["text"][s.start:s.end] for s in spans)
        assert all(a.end == b.start for a,b in zip(spans, spans[1:]))
    assert all(sum(len(s.text.encode("utf-8")) for s in c.spans) <= 256 for c in chunks)
    assert any("FINAL RESULT" in s.text for c in chunks for s in c.spans)


def test_hierarchical_analysis_no_citation_omission():
    settings = Settings(analysis_chunk_bytes=256)
    pdf = document("1 Methods\n" + "we use scheduling.\n" * 40 + "2 Results\nFinal result: 42.")
    calls = []
    async def generated(**kwargs):
        payload = json.loads(kwargs["messages"][-1]["content"])
        calls.append(payload)
        if "spans" in payload:
            span = payload["evidence_catalog"][0]
            output = {"methodology":[{"text":f"Chunk {payload['chunk_id']} finding", "provenance":"author_stated", "evidence_ids":["e"]}],
                "evidence":[{"id":"e", "page_number":span["page_number"], "quote":span["quote"][:20]}]}
        else:
            # Deliberately omit everything: reducer must retain original claims.
            output = {}
        return response(text=json.dumps(output))
    raw_llm = NS(chat=NS(completions=NS(create=generated)))
    report = asyncio.run(PaperAnalyzer(MCP(pdf), BudgetedLLM(raw_llm,settings),settings).analyze("local","source.pdf"))
    assert report.complete and report.chunk_count > 1
    assert len(calls) == report.chunk_count * 2 - 1
    assert len(report.methodology) == report.chunk_count
    assert len(report.chunk_analyses) == report.chunk_count
    assert len(report.evidence) == report.chunk_count
    assert all(claim.evidence_ids for claim in report.methodology)


@pytest.mark.parametrize("change,code", [(lambda n:n["evidence"][0].update(page_number=2), "invalid_evidence"), (lambda n:n["evidence"][0].update(quote="fabricated quote"), "invalid_evidence"), (lambda n:n["methodology"][0].update(evidence_ids=["unknown"]), "invalid_evidence")])
def test_invalid_evidence(change, code):
    data = notes()
    change(data)
    with pytest.raises(ResourceError) as exc:
        analyze(items=[data], analysis_format_retries=0)
    assert exc.value.code == code


def test_invalid_structured_json():
    with pytest.raises(ResourceError) as exc:
        analyze(items=[{"unknown":"field"}], analysis_format_retries=0)
    assert exc.value.code == "invalid_structured_output"


@pytest.mark.parametrize("pdf,code", [({"success":False,"error":{"code":"file_not_found"}}, "pdf_tool_error"), ({**document(),"truncated":True}, "truncated_pdf"), ({**document(),"pages":[{"page_number":8,"text":"text"}]}, "invalid_pdf_result")])
def test_pdf_tool_errors(pdf, code):
    with pytest.raises(ResourceError) as exc:
        analyze(pdf=pdf)
    assert exc.value.code == code


def test_chunk_budget_and_empty_pages():
    with pytest.raises(ResourceError) as exc:
        analyze(pdf=document("text " * 1000),analysis_chunk_bytes=256,analysis_max_chunks=1)
    assert exc.value.code == "chunk_budget"
    with pytest.raises(ResourceError) as exc:
        analyze(pdf=document(""))
    assert exc.value.code == "no_text"


def topic():
    return {"research_theme":"energy scheduling", "technical_methods":["scheduling"], "english_keywords":["energy management", "data center"]}


def paper(ident, title="Related Paper"):
    return {"arxiv_id":ident,"title":title,"authors":["Actual Author"],"abstract":"Actual scheduling abstract", "pdf_url":f"https://arxiv.org/pdf/{ident}","entry_url":f"https://arxiv.org/abs/{ident}"}


def ranked(ident, score=0.8):
    return {"arxiv_id":ident,"score":score,"reason":"method similarity","connection":"energy scheduling","differences":"Not specified"}


def recommend(papers=None, ranking=None, original_id=None):
    settings = Settings()
    mcp = MCP(papers=papers)
    outputs = [topic()] + ([{"candidates":ranking or []}] if papers else [])
    report = analyze()
    return asyncio.run(PaperRecommender(mcp,BudgetedLLM(llm_for(outputs),settings),settings).recommend(report,original_id)), mcp


def test_keywords_and_english_queries():
    assert build_queries(TopicPlan(**topic())) == ['all:"energy management" OR all:"data center"']
    with pytest.raises(ResourceError):
        build_queries(TopicPlan(research_theme="theme",english_keywords=['中文关键词']))


def test_ranking_dedup_and_original_filter():
    pool = [paper("1706.00001v1","Original title"),paper("1706.00001v2","Original title"),
        paper("1706.00002","Research Paper"), paper("1706.00003","Related A"), paper("1706.00003v2","Related A"),paper("1706.00004","Related B")]
    result, mcp = recommend(pool,[ranked("1706.00003",0.5), ranked("1706.00004",0.9)],"1706.00001")
    assert [p.arxiv_id for p in result.papers] == ["1706.00004","1706.00003"]
    assert result.papers[0].authors == ["Actual Author"]
    assert result.papers[0].evidence_basis == "title_and_abstract"
    assert mcp.calls[0][0] == "search_arxiv" and mcp.calls[0][1]["sort_by"] == "relevance"


def test_no_search_results():
    result, _ = recommend()
    assert result.papers == [] and any("No eligible" in w for w in result.warnings)


def test_filter_all_original_without_rank_call():
    settings = Settings()
    raw = llm_for([topic()])
    result = asyncio.run(PaperRecommender(MCP(papers=[paper("1706.00001","Research Paper")]),BudgetedLLM(raw,settings),settings).recommend(analyze()))
    assert not result.papers and raw.chat.completions.create.call_count == 1


def test_hallucinated_recommendation_id():
    with pytest.raises(ResourceError) as exc:
        recommend([paper("1706.00003")],[ranked("9999.99999")])
    assert exc.value.code == "invalid_ranking"


def test_search_tool_failure():
    mcp = MCP()
    mcp.call_tool = AsyncMock(return_value={"success":False,"error":{"code":"api_error"}})
    settings = Settings()
    with pytest.raises(ResourceError) as exc:
        asyncio.run(PaperRecommender(mcp,BudgetedLLM(llm_for([topic()]),settings),settings).recommend(analyze()))
    assert exc.value.code == "search_tool_error"


def test_unified_budget_and_llm_timeout():
    async def check():
        settings = Settings(agent_max_llm_calls=1)
        budget = BudgetedLLM(llm_for([{},{}]),settings)
        await budget.create(messages=[])
        with pytest.raises(ResourceError, match="call budget"):
            await budget.create(messages=[])
        with pytest.raises(ResourceError, match="token budget"):
            await BudgetedLLM(llm_for([{}]),Settings(agent_token_budget=1000)).create(messages=[])
        async def slow(**kwargs):
            await asyncio.sleep(1)
        with pytest.raises(ResourceError, match="timed out"):
            await BudgetedLLM(NS(chat=NS(completions=NS(create=slow))),Settings(request_timeout_seconds=0.02)).create(messages=[])
    asyncio.run(check())


def test_service_analysis_cache_and_errors():
    async def check():
        settings = Settings()
        trace = []
        service = ResearchService(MCP(),BudgetedLLM(llm_for([notes()]),settings),settings,trace)
        for _ in range(2):
            result = await service.execute("analyze_paper",{"source_type":"local","file_path":"source.pdf"})
            assert result["success"]
        assert len(trace) == 1 and trace[0]["name"] == "read_pdf"
        assert not (await service.execute("analyze_paper",{"source_type":"local"}))["success"]
    asyncio.run(check())


def test_inference_and_empty_field_preserved():
    data = notes()
    data["methodology"][0]["provenance"] = "inference"
    data["experiments"] = []
    result = analyze(items=[data])
    assert result.methodology[0].provenance == "inference"
    assert result.experiments[0].text == "Not specified"


def test_unknown_source_identity_rejects_recommendation():
    report = analyze(items=[{}])
    settings = Settings()
    with pytest.raises(ResourceError) as exc:
        asyncio.run(PaperRecommender(MCP(),BudgetedLLM(llm_for([topic()]),settings),settings).recommend(report))
    assert exc.value.code == "source_identity_unknown"


def test_context_budget():
    with pytest.raises(ResourceError) as exc:
        analyze(agent_context_budget=1000)
    assert exc.value.code == "context_budget"
