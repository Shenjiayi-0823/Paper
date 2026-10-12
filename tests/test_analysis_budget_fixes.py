import asyncio
import json
from types import SimpleNamespace as NS

from paper_research_agent.agent.budget import BudgetedLLM
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.analysis.analyzer import PaperAnalyzer
from paper_research_agent.config import Settings
from test_analysis import analyze, notes, MCP, document
from test_research_agent import llm, json_response, ResearchMCP
from test_agent import response, call


def test_unverifiable_title_is_missing_not_fatal():
    data = notes()
    data["title"] = "An invented translated title"
    report = analyze(items=[data])
    assert report.title == "Not specified" and report.methodology[0].evidence_ids
    assert any("title could not be verified" in w for w in report.warnings)


def test_global_title_can_appear_in_a_later_chunk():
    settings = Settings(analysis_chunk_bytes=256)
    captured = []
    async def create(**kwargs):
        payload = json.loads(kwargs["messages"][-1]["content"])
        captured.append(payload)
        assert all("text" not in span for span in payload.get("spans",[]))
        assert all("evidence" not in note for note in payload.get("notes",[]))
        return response(text=json.dumps({"title":"Actual Global Title"}))
    raw = NS(chat=NS(completions=NS(create=create)))
    pdf = document("Actual Global Title\n" + "Methods and results text.\n" * 40)
    report = asyncio.run(PaperAnalyzer(MCP(pdf),BudgetedLLM(raw,settings),settings).analyze("local","source.pdf"))
    assert report.title == "Actual Global Title" and report.chunk_count > 1
    assert all("evidence_catalog" in p for p in captured)
    assert all(p["evidence_catalog"] for p in captured if "chunk_id" in p)


def test_provider_usage_replaces_pessimistic_reservation():
    async def create(**kwargs):
        return NS(usage=NS(total_tokens=25))
    async def check():
        raw = NS(chat=NS(completions=NS(create=create)))
        budget = BudgetedLLM(raw,Settings())
        for _ in range(3):
            await budget.create(messages=[{"role":"user","content":"x" * 1000}])
        assert budget.reserved_tokens == 75 and budget.reported_usage_calls == 3
    asyncio.run(check())


def test_budget_failure_keeps_original_research_error():
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}')]),json_response({"methodology":"bad"})])
    result = asyncio.run(PaperAgent(Settings(agent_max_llm_calls=2,analysis_format_retries=0),raw,ResearchMCP()).run("Analyze"))
    assert result.error["code"] == "invalid_structured_output"
    assert result.error["secondary_error"]["code"] == "llm_call_budget"
    assert result.usage["llm_calls"] == 2 and result.usage["estimated_usage_calls"] == 2
