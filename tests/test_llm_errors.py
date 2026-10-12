import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from paper_research_agent.agent.budget import BudgetedLLM, ResourceError
from paper_research_agent.config import Settings
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.agent.budget import api_failure
import ssl
import socket


@pytest.mark.parametrize("kind,status,body,code", [
    (openai.AuthenticationError,401,{},"llm_authentication"),
    (openai.PermissionDeniedError,403,{},"llm_permission"),
    (openai.NotFoundError,404,{},"llm_model_not_found"),
    (openai.RateLimitError,429,{"code":"insufficient_quota"},"llm_quota"),
    (openai.RateLimitError,429,{},"llm_rate_limit"),
    (openai.BadRequestError,400,{},"llm_bad_request"),
])
def test_safe_api_errors(kind,status,body,code):
    request = httpx.Request("POST","https://api.openai.com/v1/chat/completions")
    exc = kind("sensitive-test-secret", response=httpx.Response(status,request=request),body=body)
    llm = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=exc))))
    with pytest.raises(ResourceError) as caught:
        asyncio.run(BudgetedLLM(llm,Settings()).create(messages=[]))
    assert caught.value.code == code
    assert "sensitive-test-secret" not in str(caught.value)


def test_connection_error_classified():
    exc = openai.APIConnectionError(request=httpx.Request("POST","https://api.openai.com/v1/chat/completions"))
    llm = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=exc))))
    with pytest.raises(ResourceError) as caught:
        asyncio.run(BudgetedLLM(llm,Settings()).create(messages=[]))
    assert caught.value.code == "llm_connection"


def test_api_error_survives_real_mcp_cleanup():
    req = httpx.Request("POST","https://api.openai.com/v1/chat/completions")
    exc = openai.AuthenticationError("test-secret",response=httpx.Response(401,request=req),body={})
    llm = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=exc))))
    result = asyncio.run(PaperAgent(Settings(),llm=llm).run("Hello"))
    assert result.error["code"] == "llm_authentication"
    assert "test-secret" not in result.model_dump_json()


@pytest.mark.parametrize("cause,code", [
    (ssl.SSLCertVerificationError("test-secret"),"llm_tls_certificate"),
    (socket.gaierror("test-secret"),"llm_dns"),
    (httpx.ProxyError("test-secret"),"llm_proxy"),
    (httpx.LocalProtocolError("test-secret"),"llm_request_headers"),
    (httpx.ConnectTimeout("test-secret"),"llm_connect_timeout"),
])
def test_safe_connection_causes(cause,code):
    exc = openai.APIConnectionError(request=httpx.Request("POST","https://gateway.example/v1/chat/completions"))
    exc.__cause__ = cause
    actual,message = api_failure(exc)
    assert actual == code and "test-secret" not in message
