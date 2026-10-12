import asyncio
import os
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from mcp import StdioServerParameters

from paper_research_agent.agent.mcp_client import MCPClient
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.config import PROJECT_ROOT, Settings, load_settings
from test_agent import call, response
from test_pdf import make_pdf


def test_client_production_discovery():
    async def check():
        client = MCPClient(timeout=10)
        async with client.connect():
            assert set(client.tools) == {"search_arxiv", "read_pdf"}
            assert {t["function"]["name"] for t in client.function_tools} == set(client.tools)
            assert (await client.call_tool("read_pdf", {"source_type":"arxiv","arxiv_id":"bad"}))["error"]["code"] == "invalid_arxiv_id"
        assert client.session is None
    asyncio.run(check())


def test_mock_llm_real_stdio(tmp_path):
    (tmp_path / "fixture.pdf").write_bytes(make_pdf())
    client = MCPClient(StdioServerParameters(command=sys.executable,
        args=[str(PROJECT_ROOT / "tests" / "mcp_fixture_server.py"), str(tmp_path)], cwd=str(PROJECT_ROOT)), timeout=10)
    llm = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=[
        response([call(), call("read_pdf", '{"source_type":"local","file_path":"fixture.pdf"}', "pdf1")]), response()]))))
    result = asyncio.run(PaperAgent(Settings(), llm=llm, mcp=client).run("Search and read my PDF"))
    assert result.success and len(result.tool_trace) == 2
    assert all(trace["success"] for trace in result.tool_trace)
    assert "Research methods" in result.messages[-2]["content"]
    assert client.session is None


def test_server_exits_during_tool(tmp_path):
    script = tmp_path / "crash_server.py"
    script.write_text('import os\nfrom mcp.server.fastmcp import FastMCP\ns=FastMCP("crash")\n@s.tool()\ndef crash() -> dict:\n    os._exit(7)\ns.run(transport="stdio")\n', encoding="utf-8")
    async def check():
        client = MCPClient(StdioServerParameters(command=sys.executable,args=[str(script)]),timeout=2)
        async with client.connect():
            result = await client.call_tool("crash", {})
            assert result["error"]["code"] == "mcp_disconnected"
        assert client.session is None
    asyncio.run(check())


def test_task_timeout_closes_real_stdio(tmp_path):
    script = tmp_path / "slow_server.py"
    script.write_text('import asyncio\nfrom mcp.server.fastmcp import FastMCP\ns=FastMCP("slow")\n@s.tool()\nasync def slow() -> dict:\n    await asyncio.sleep(60)\n    return {}\ns.run(transport="stdio")\n', encoding="utf-8")
    client = MCPClient(StdioServerParameters(command=sys.executable,args=[str(script)]),timeout=10)
    llm = NS(chat=NS(completions=NS(create=AsyncMock(return_value=response([call("slow", "{}")])))))
    result = asyncio.run(PaperAgent(Settings(agent_task_timeout_seconds=1), llm=llm, mcp=client).run("Wait"))
    assert result.error["code"] == "task_timeout" and client.session is None


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_MCP") != "1", reason="Explicit real arXiv through production stdio opt-in")
def test_live_mcp_network():
    paper_id = os.getenv("LIVE_ARXIV_ID")
    assert paper_id, "Set LIVE_ARXIV_ID for the real MCP search + PDF smoke test."
    async def check():
        async with MCPClient(timeout=120).connect() as client:
            search = await client.call_tool("search_arxiv", {"query":f"id:{paper_id}", "max_results":1})
            assert search["success"] and search["papers"], search
            pdf = await client.call_tool("read_pdf", {"source_type":"arxiv", "arxiv_id":paper_id})
            assert pdf["success"] and pdf["full_text"], pdf.get("error")
    asyncio.run(check())


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_AGENT") != "1", reason="Explicit paid OpenAI + arXiv E2E opt-in")
def test_live_agent_end_to_end():
    settings = load_settings()
    settings.require_openai_api_key()
    request = os.getenv("LIVE_AGENT_REQUEST")
    assert request, "Set LIVE_AGENT_REQUEST to a request requiring arXiv search AND PDF reading."
    result = asyncio.run(PaperAgent(settings).run(request))
    assert result.success, result.error
    assert {"search_arxiv", "read_pdf"} <= {t["name"] for t in result.tool_trace if t["success"]}
    assert result.answer
