from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import os

import pytest
import requests

from paper_research_agent.mcp_server.tools import arxiv_tool as tool


def test_search_structure(monkeypatch):
    paper = SimpleNamespace(get_short_id=lambda: "1706.03762v7", title="Test paper",
        authors=[SimpleNamespace(name="Author")], summary="Real fixture summary",
        published=datetime(2017, 6, 12, tzinfo=timezone.utc),
        updated=datetime(2023, 8, 2, tzinfo=timezone.utc),
        pdf_url="https://arxiv.org/pdf/1706.03762v7", entry_id="https://arxiv.org/abs/1706.03762v7")
    client = Mock()
    client.results.return_value = iter([paper])
    monkeypatch.setattr(tool, "_get_client", lambda _: client)
    result = tool.search_arxiv(" attention ", 1, "relevance")
    assert result.success and result.query == "attention"
    assert set(result.papers[0].model_dump()) == {"arxiv_id", "title", "authors", "abstract", "published", "updated", "pdf_url", "entry_url"}
    assert result.papers[0].authors == ["Author"]
    assert client.results.call_args.args[0].sort_by.value == "relevance"
    assert '1706.03762v7' in result.model_dump_json()


def test_empty(monkeypatch):
    monkeypatch.setattr(tool, "_get_client", lambda _: SimpleNamespace(results=lambda _: iter([])))
    result = tool.search_arxiv("nothing")
    assert result.success and result.papers == [] and result.warnings


@pytest.mark.parametrize("args", [(" ",), ("x", 0), ("x", 21), ("x", True), ("x", 2, "wrong"), ("x" * 1001,)])
def test_invalid(args):
    assert tool.search_arxiv(*args).error.code == "invalid_input"


def test_api_failure(monkeypatch):
    client = Mock()
    client.results.side_effect = requests.ConnectionError("offline")
    monkeypatch.setattr(tool, "_get_client", lambda _: client)
    assert tool.search_arxiv("attention").error.code == "api_error"


@pytest.mark.parametrize('status,code',[(429,'api_rate_limit'),(503,'api_service_unavailable'),(400,'api_invalid_query'),(403,'api_http_error')])
def test_http_status_is_reported_without_query(monkeypatch,caplog,status,code):
    import arxiv
    client = Mock()
    client.results.side_effect = arxiv.HTTPError('https://export.arxiv.org/api/query?private-query',2,status)
    monkeypatch.setattr(tool,'_get_client',lambda _:client)
    result = tool.search_arxiv('large language models')
    assert result.error.code == code and str(status) in result.error.message
    assert 'private-query' not in result.error.message
    assert code in caplog.text and str(status) in caplog.text
    assert 'private-query' not in caplog.text


def test_wrapped_timeout_classification(monkeypatch):
    exc = requests.ConnectionError('timed out')
    exc.__cause__ = requests.Timeout('private-details')
    client = Mock()
    client.results.side_effect = exc
    monkeypatch.setattr(tool,'_get_client',lambda _:client)
    assert tool.search_arxiv('energy').error.code == 'api_timeout'


@pytest.mark.parametrize('exc,code',[(requests.ConnectionError('[WinError 10013] denied'),'api_network_permission'),
    (requests.exceptions.SSLError('private-proxy-info'),'api_tls_error'),
    (requests.exceptions.ProxyError('private-proxy-info'),'api_proxy_error')])
def test_safe_network_error_categories(monkeypatch,exc,code):
    client = Mock()
    client.results.side_effect = exc
    monkeypatch.setattr(tool,'_get_client',lambda _:client)
    result = tool.search_arxiv('attention')
    assert result.error.code == code
    assert 'private-proxy-info' not in result.error.message


def test_timeout_session(monkeypatch):
    original = Mock(side_effect=requests.Timeout())
    monkeypatch.setattr(requests.Session, "get", original)
    with pytest.raises(requests.ConnectionError):
        tool.TimeoutSession(4).get("https://export.arxiv.org/api/query")
    assert original.call_args.kwargs["timeout"] == 4


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_ARXIV") != "1", reason="Opt-in real arXiv API request")
def test_live_arxiv():
    result = tool.search_arxiv("id:1706.03762", 1, "relevance")
    assert result.success, result.error
    assert result.papers and result.papers[0].arxiv_id.startswith("1706.03762")
