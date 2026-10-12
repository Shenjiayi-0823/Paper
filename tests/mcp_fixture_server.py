"""Test-only subprocess: real production server, mocked arXiv transport."""
from types import SimpleNamespace
from paper_research_agent.mcp_server.tools import arxiv_tool, pdf_tool
from paper_research_agent.mcp_server.server import main
from pathlib import Path
import sys

pdf_tool.UPLOADS_DIR = Path(sys.argv[1])


def results(search):
    if search.query == "raise-error":
        raise RuntimeError("Simulated unexpected backend failure")
    return iter([])


arxiv_tool._get_client = lambda _: SimpleNamespace(results=results)
main()
