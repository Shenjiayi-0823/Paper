import asyncio
from datetime import timedelta
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from paper_research_agent.config import PROJECT_ROOT
from test_pdf import make_pdf


async def run_session(params, local_pdf=False):
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
            await session.initialize()
            listing = await session.list_tools()
            assert {t.name for t in listing.tools} == {"search_arxiv", "read_pdf"}
            assert all(t.inputSchema and t.outputSchema for t in listing.tools)
            result = await session.call_tool("search_arxiv", {"query": "" if not local_pdf else "fixture"})
            assert not result.isError
            assert result.structuredContent["success"] is local_pdf
            pdf = await session.call_tool("read_pdf", {"source_type": "local", "file_path": "fixture.pdf"})
            assert not pdf.isError
            assert pdf.structuredContent["success"] is local_pdf
            if local_pdf:
                assert "Research methods" in pdf.structuredContent["full_text"]
                failed = await session.call_tool("search_arxiv", {"query": "raise-error"})
                assert failed.structuredContent["error"]["code"] == "internal_error"
            invalid = await session.call_tool("read_pdf", {"unexpected": "value"})
            assert invalid.isError
            assert len((await session.list_tools()).tools) == 2
            good = await session.call_tool("read_pdf", {"source_type": "arxiv", "arxiv_id": "bad"})
            assert good.structuredContent["error"]["code"] == "invalid_arxiv_id"


def test_production_server_stdio():
    asyncio.run(run_session(StdioServerParameters(command=sys.executable,
        args=["-m", "paper_research_agent.mcp_server.server"], cwd=str(PROJECT_ROOT))))


def test_stdio_tools_success_and_recovery(tmp_path):
    (tmp_path / "fixture.pdf").write_bytes(make_pdf())
    asyncio.run(run_session(StdioServerParameters(command=sys.executable,
        args=[str(PROJECT_ROOT / "tests" / "mcp_fixture_server.py"), str(tmp_path)],
        cwd=str(PROJECT_ROOT)), local_pdf=True))
