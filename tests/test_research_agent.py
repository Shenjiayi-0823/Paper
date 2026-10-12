import asyncio
import json
import os
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from mcp import StdioServerParameters

from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.agent.mcp_client import MCPClient
from paper_research_agent.config import Settings, PROJECT_ROOT, load_settings
from test_agent import FakeMCP, response, call
from test_analysis import document, notes, topic, ranked, paper
from test_pdf import make_pdf


class ResearchMCP(FakeMCP):
    async def call_tool(self, name, arguments):
        self.calls.append((name,arguments))
        return document() if name == "read_pdf" else {"success":True,"papers":[paper("1706.00003")],"warnings":[]}


def llm(responses):
    return NS(chat=NS(completions=NS(create=AsyncMock(side_effect=responses))))


def json_response(data):
    return response(text=json.dumps(data))


def test_agent_autonomously_analyzes_and_retains_artifact():
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}')]),json_response(notes()),response(text="基于原文的结构化分析")])
    result = asyncio.run(PaperAgent(Settings(agent_max_result_chars=1000),raw,ResearchMCP()).run("请结构化分析 source.pdf"))
    assert result.success and result.artifacts[0]["operation"] == "analyze_paper"
    report = result.artifacts[0]["data"]["analysis"]
    assert report["results"][0]["evidence_ids"] == ["c1-e2"]
    assert report["evidence"][1]["quote"] == "We improve energy by 10%."
    assert any(t.get("internal") and t["name"] == "read_pdf" for t in result.tool_trace)
    assert any(json.loads(m["content"])["truncated"] for m in result.messages if m["role"] == "tool")


def test_agent_recommendation_chain_uses_mcp():
    mcp = ResearchMCP()
    raw = llm([response([call("recommend_related",'{"source_type":"local","file_path":"source.pdf"}')]),
        json_response(notes()),json_response(topic()),json_response({"candidates":[ranked("1706.00003")]}),response(text="推荐来自真实检索结果")])
    result = asyncio.run(PaperAgent(Settings(),raw,mcp).run("根据 source.pdf 推荐相关论文"))
    assert result.success and [c[0] for c in mcp.calls] == ["read_pdf","search_arxiv"]
    assert result.artifacts[0]["data"]["recommendations"]["papers"][0]["title"] == "Related Paper"
    assert raw.chat.completions.create.call_count == 5


def test_agent_unified_llm_budget_exhaustion():
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"source.pdf"}')])])
    result = asyncio.run(PaperAgent(Settings(agent_max_llm_calls=1),raw,ResearchMCP()).run("Analyze"))
    assert not result.success and result.error["code"] == "llm_call_budget"
    assert result.tool_trace[-1]["error"]["code"] == "llm_call_budget"


def test_analysis_through_actual_stdio(tmp_path):
    (tmp_path / "fixture.pdf").write_bytes(make_pdf())
    client = MCPClient(StdioServerParameters(command=sys.executable,
        args=[str(PROJECT_ROOT / "tests" / "mcp_fixture_server.py"),str(tmp_path)],cwd=str(PROJECT_ROOT)),timeout=10)
    content = {"methodology":[{"text":"提取文本讨论研究方法与结果", "provenance":"inference", "evidence_ids":["e1"]}],
        "evidence":[{"id":"e1","page_number":1,"quote":"Research methods and results"}]}
    raw = llm([response([call("analyze_paper",'{"source_type":"local","file_path":"fixture.pdf"}')]), json_response(content),response()])
    result = asyncio.run(PaperAgent(Settings(),raw,client).run("分析本地 fixture.pdf"))
    assert result.success and result.artifacts[0]["data"]["analysis"]["complete"]
    assert client.session is None


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_RESEARCH") != "1",reason="Explicit authorized paid research E2E opt-in")
def test_live_research_end_to_end():
    settings = load_settings()
    settings.require_openai_api_key()
    request = os.getenv("LIVE_RESEARCH_REQUEST")
    assert request, "Set a real source PDF/ID and ask for structured analysis and recommendations."
    result = asyncio.run(PaperAgent(settings).run(request))
    assert result.success, result.error
    assert any(a["data"].get("analysis") for a in result.artifacts)
    assert any(a["data"].get("recommendations",{}).get("papers") for a in result.artifacts)
