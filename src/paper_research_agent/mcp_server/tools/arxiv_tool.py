"""Real arXiv searches with bounded inputs, timeouts and SDK retries."""

from functools import lru_cache
import logging
import threading

import arxiv
import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from typing import Literal

from paper_research_agent.config import load_settings
from .models import Paper, SearchResult, ToolError

logger = logging.getLogger(__name__)
_search_lock = threading.Lock()


class SearchInput(BaseModel):
    model_config = ConfigDict(strict=True)
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=5, ge=1, le=20)
    sort_by: Literal["submittedDate", "relevance"] = "submittedDate"

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value):
        return value.strip() if isinstance(value, str) else value


class TimeoutSession(requests.Session):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        try:
            return super().get(url, **kwargs)
        except requests.Timeout as exc:
            # arxiv.Client retries ConnectionError but not Timeout.
            raise requests.ConnectionError("arXiv request timed out") from exc


@lru_cache(maxsize=4)
def _get_client(timeout: float) -> arxiv.Client:
    client = arxiv.Client(page_size=20, delay_seconds=3, num_retries=2)
    # SDK 2.x has no public session/timeout constructor argument.
    client._session.close()
    client._session = TimeoutSession(timeout)
    return client


def search_arxiv(query: str, max_results: int = 5,
                 sort_by: str = "submittedDate") -> SearchResult:
    result = SearchResult(query=query if isinstance(query, str) else "")
    try:
        params = SearchInput(query=query, max_results=max_results, sort_by=sort_by)
    except ValidationError:
        result.error = ToolError(code="invalid_input", message="query must be nonempty (max 1000 chars); max_results must be 1–20; sort_by must be submittedDate or relevance.")
        return result
    result.query = params.query
    try:
        client = _get_client(load_settings().request_timeout_seconds)
        search = arxiv.Search(query=params.query, max_results=params.max_results,
                              sort_by=arxiv.SortCriterion(params.sort_by),
                              sort_order=arxiv.SortOrder.Descending)
        # Shared client preserves arXiv's three-second spacing across tool calls.
        with _search_lock:
            papers = list(client.results(search))
        result.papers = [Paper(
            arxiv_id=p.get_short_id(), title=p.title,
            authors=[a.name for a in p.authors], abstract=p.summary,
            published=p.published.isoformat(), updated=p.updated.isoformat(),
            pdf_url=p.pdf_url, entry_url=p.entry_id,
        ) for p in papers]
        result.success = True
        if not papers:
            result.warnings.append("No matching arXiv papers were returned.")
    except (requests.RequestException, arxiv.ArxivError) as exc:
        # Do not expose raw request/proxy exceptions. Detect permission denial
        # even when requests wraps the underlying Windows socket error.
        if '10013' in str(exc) or 'permission denied' in str(exc).lower():
            result.error = ToolError(code="api_network_permission", message="arXiv connection was blocked by network permissions (Windows 10013). Start Streamlit from your own VS Code terminal outside the restricted agent execution environment.")
        elif isinstance(exc, requests.exceptions.SSLError):
            result.error = ToolError(code="api_tls_error", message="arXiv TLS certificate verification failed. Check trusted CA settings; certificate verification remains enabled.")
        elif isinstance(exc, requests.exceptions.ProxyError):
            result.error = ToolError(code="api_proxy_error", message="arXiv request failed through the configured proxy. Check the Streamlit process proxy environment.")
        elif isinstance(exc, arxiv.HTTPError):
            status = exc.status
            code = 'api_rate_limit' if status == 429 else 'api_service_unavailable' if status >= 500 else 'api_invalid_query' if status == 400 else 'api_http_error'
            result.error = ToolError(code=code,message=f'arXiv returned HTTP {status} after retries. This is an HTTP/API failure, not an empty search result.')
        elif isinstance(exc, arxiv.UnexpectedEmptyPageError):
            result.error = ToolError(code='api_response_error',message='arXiv returned an unexpectedly empty API page after retries. This differs from a valid search with zero matches.')
        elif isinstance(exc, requests.Timeout) or isinstance(exc.__cause__, requests.Timeout):
            result.error = ToolError(code='api_timeout',message='arXiv network request timed out after retries. Check connectivity to export.arxiv.org.')
        elif isinstance(exc, requests.ConnectionError):
            result.error = ToolError(code='api_error',message='Cannot establish an arXiv API connection after retries; no HTTP response was received. Check DNS, network and proxy connectivity to export.arxiv.org.')
        else:
            result.error = ToolError(code="api_error", message="arXiv API request failed or timed out after retries.")
        logger.warning('search_arxiv failed [%s] (%s): %s',result.error.code,type(exc).__name__,result.error.message)
    except Exception:
        logger.exception("Unexpected arXiv tool error")
        result.error = ToolError(code="internal_error", message="Unable to process the arXiv response.")
    return result
