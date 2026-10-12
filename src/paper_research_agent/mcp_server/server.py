"""Run with python -m paper_research_agent.mcp_server.server (stdio only)."""

import logging
import sys

from mcp.server.fastmcp import FastMCP
from .tools.arxiv_tool import search_arxiv
from .tools.pdf_tool import read_pdf


def create_server() -> FastMCP:
    server = FastMCP("Paper Research Agent", log_level="WARNING")
    server.tool(name="search_arxiv", description="Search the real arXiv API. query: English keywords or arXiv expression; max_results: 1–20; sort_by: submittedDate or relevance. Returns success, query, papers, warnings and error.")(search_arxiv)
    server.tool(name="read_pdf", description="Extract real PDF text. source_type: local (file_path relative to uploads, or an absolute path inside uploads) or arxiv (arxiv_id only, no URLs). Returns success, source_type, document_id, total_pages, pages, full_text, warnings and error. Blank pages are explicitly warned; size/page/text limits fail without silent truncation.")(read_pdf)
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
