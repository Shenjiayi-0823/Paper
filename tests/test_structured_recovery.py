import asyncio
import json

import pytest

from paper_research_agent.analysis.structured import structured_call
from paper_research_agent.analysis.models import AnalysisContent
from paper_research_agent.analysis.service import ResearchService
from paper_research_agent.agent.budget import BudgetedLLM, ResourceError
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.config import Settings
from test_analysis import MCP, llm_for, notes
from test_research_agent import llm, json_response, ResearchMCP
from test_agent import response, call
from paper_research_agent.analysis.analyzer import PaperAnalyzer


def test_one_format_repair_then_validated_output():
    settings = Settings()
    raw = llm_for([{"methodology":"wrong shape"}, notes()])
    budget = BudgetedLLM(raw, settings)
    result = asyncio.run(structured_call(budget,settings,AnalysisContent,"Analyze the provided data",{}))
    assert result.methodology[0].evidence_ids == ["e1"]
    assert budget.calls == 2
    repair = raw.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert "methodology: list_type" in repair


def test_markdown_json_compatibility_without_extra_request():
    raw = llm([response(text='```json\n'+json.dumps(notes())+'\n```')])
    result = asyncio.run(structured_call(BudgetedLLM(raw,Settings()),Settings(),AnalysisContent,"Analyze",{}))
    assert result.title == "Research Paper" and raw.chat.completions.create.call_count == 1


def test_failed_repair_does_not_leak_invalid_output():
    settings = Settings()
    bad = {"methodology":"sensitive-raw-text"}
    with pytest.raises(ResourceError) as caught:
        asyncio.run(structured_call(BudgetedLLM(llm_for([bad,bad]),settings),settings,AnalysisContent,"Analyze",{}))
    assert caught.value.code == "invalid_structured_output"
    assert "methodology: list_type" in str(caught.value)
    assert "sensitive-raw-text" not in str(caught.value)


def test_failed_analysis_reuses_pdf_without_repeating_llm():
    async def check():
        settings = Settings(analysis_format_retries=0)
        mcp = MCP()
        raw = llm_for([{"methodology":"bad"}])
        service = ResearchService(mcp,BudgetedLLM(raw,settings),settings,[])
        source = {"source_type":"local","file_path":"source.pdf"}
        first = await service.execute("analyze_paper",source)
        second = await service.execute("recommend_related",source)
        pdf = await service.tool_call("read_pdf",source)
        assert first["error"]["code"] == second["error"]["code"] == "invalid_structured_output"
        assert pdf["success"] and len(mcp.calls) == 1
        assert raw.chat.completions.create.call_count == 1
    asyncio.run(check())


def test_agent_reports_research_failure_despite_final_conversation_answer():
    settings = Settings(analysis_format_retries=0)
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}')]),
        json_response({"methodology":"bad"}),response(text="The model could not produce a valid report.")])
    result = asyncio.run(PaperAgent(settings,raw,ResearchMCP()).run("Analyze source.pdf"))
    assert not result.success and result.error["code"] == "invalid_structured_output"
    assert not result.artifacts


def test_evidence_page_is_repaired_within_shared_limit():
    settings = Settings()
    bad = notes()
    bad["evidence"][0]["page_number"] = 99
    raw = llm_for([bad,notes()])
    budget = BudgetedLLM(raw,settings)
    report = asyncio.run(PaperAnalyzer(MCP(),budget,settings).analyze("local","source.pdf"))
    assert report.complete and report.evidence[0].page_number == 1
    assert budget.calls == 2
    assert "page not present" in raw.chat.completions.create.call_args.kwargs["messages"][-1]["content"]


def test_long_quote_is_repaired_without_changing_schema():
    settings = Settings()
    bad = notes()
    bad["evidence"][0]["quote"] = "x" * 351
    raw = llm_for([bad,notes()])
    report = asyncio.run(PaperAnalyzer(MCP(),BudgetedLLM(raw,settings),settings).analyze("local","source.pdf"))
    assert report.evidence[0].quote == "We use scheduling."
    assert raw.chat.completions.create.call_count == 2


def test_json_and_evidence_repair_share_one_retry():
    settings = Settings()
    bad = notes()
    bad["evidence"][0]["quote"] = "invented-sensitive-excerpt"
    raw = llm_for([{"methodology":"bad"},bad])
    with pytest.raises(ResourceError) as caught:
        asyncio.run(PaperAnalyzer(MCP(),BudgetedLLM(raw,settings),settings).analyze("local","source.pdf"))
    assert caught.value.code == "invalid_evidence"
    assert raw.chat.completions.create.call_count == 2
    assert "invented-sensitive-excerpt" not in str(caught.value)


def test_evidence_failure_cached_and_no_false_file_error():
    settings = Settings(analysis_format_retries=0)
    bad = notes()
    bad["evidence"][0]["quote"] = "invented quotation"
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}'),
        call("recommend_related",'{"source_type":"local","file_path":"source.pdf"}',"call2")]),
        json_response(bad),response(text="Please reupload the missing file")])
    mcp = ResearchMCP()
    result = asyncio.run(PaperAgent(settings,raw,mcp).run("分析并推荐"))
    assert result.error["code"] == "invalid_evidence"
    assert result.answer.startswith("PDF 已成功读取")
    assert "reupload" not in result.answer
    assert len(mcp.calls) == 1
