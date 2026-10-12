import asyncio
from types import SimpleNamespace as NS

import pytest

from paper_research_agent.agent.budget import BudgetedLLM, ResourceError
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.analysis.models import AnalysisContent
from paper_research_agent.analysis.structured import structured_call
from paper_research_agent.analysis.service import ResearchService
from paper_research_agent.config import Settings
from test_analysis import MCP
from test_agent import response, call
from test_research_agent import llm, ResearchMCP


@pytest.mark.parametrize("output,code", [(response(text='{"title":',finish="length"),"structured_output_limit"),
    (response(text="{}",finish=None),"incomplete_structured_output"),
    (response([call()]),"unexpected_structured_tool")])
def test_finish_reason_is_explicit_and_limit_is_forwarded(output,code):
    raw = llm([output])
    settings = Settings(openai_token_parameter="max_tokens")
    with pytest.raises(ResourceError) as caught:
        asyncio.run(structured_call(BudgetedLLM(raw,settings),settings,AnalysisContent,"Analyze",{}))
    assert caught.value.code == code
    assert raw.chat.completions.create.call_args.kwargs["max_tokens"] == 6000


def test_incomplete_analysis_not_restarted_by_recommendation():
    async def check():
        settings = Settings()
        raw = llm([response(text="{",finish="length")])
        mcp = MCP()
        service = ResearchService(mcp,BudgetedLLM(raw,settings),settings,[])
        args = {"source_type":"local","file_path":"source.pdf"}
        first = await service.execute("analyze_paper",args)
        second = await service.execute("recommend_related",args)
        assert first["error"]["code"] == second["error"]["code"] == "structured_output_limit"
        assert len(mcp.calls) == 1 and raw.chat.completions.create.call_count == 1
    asyncio.run(check())


def test_task_timeout_preserves_prior_output_failure():
    calls = 0
    async def create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}')])
        if calls == 2:
            return response(text="{",finish="length")
        await asyncio.sleep(1)
    raw = NS(chat=NS(completions=NS(create=create)))
    result = asyncio.run(PaperAgent(Settings(agent_task_timeout_seconds=0.05),raw,ResearchMCP()).run("Analyze"))
    assert result.error["code"] == "structured_output_limit"
    assert result.error["secondary_error"]["code"] == "task_timeout"
