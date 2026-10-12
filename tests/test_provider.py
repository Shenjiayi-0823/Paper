import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
from openai import AsyncOpenAI
import pytest
from pydantic import ValidationError

from paper_research_agent.config import Settings, load_settings
from paper_research_agent.agent.budget import BudgetedLLM


@pytest.mark.parametrize("url,expected", [
    ("https://gateway.example/v1/", "https://gateway.example/v1"),
    ("https://gateway.example/v1/chat/completions", "https://gateway.example/v1"),
    ("https://gateway.example/api/chat/completions/", "https://gateway.example/api"),
])
def test_provider_url(url,expected):
    assert Settings(openai_base_url=url).openai_base_url == expected


@pytest.mark.parametrize("url", ["", "http://gateway.example/v1", "https://user:secret@gateway.example/v1", "https://gateway.example/v1?api_key=secret"])
def test_invalid_provider_url(url):
    with pytest.raises(ValidationError):
        Settings(openai_base_url=url)


def test_provider_dotenv(tmp_path,monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(),raising=False)
    env = tmp_path / ".env"
    env.write_text('OPENAI_BASE_URL=https://gateway.example/v1\nOPENAI_MODEL=provider-model\nOPENAI_TOKEN_PARAMETER=max_tokens\n',encoding="utf-8")
    config = load_settings(env)
    assert config.openai_base_url == "https://gateway.example/v1" and config.openai_model == "provider-model"
    assert config.openai_token_parameter == "max_tokens"


def test_sdk_sends_tools_to_provider_without_network():
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200,json={"id":"test","object":"chat.completion","created":0,"model":"provider-model", "choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}]})
    async def check():
        settings = Settings(openai_base_url="https://gateway.example/v1/chat/completions",openai_token_parameter="max_tokens")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with AsyncOpenAI(api_key="test-only-key",base_url=settings.openai_base_url,http_client=http) as sdk:
                await BudgetedLLM(sdk,settings).create(model="provider-model", messages=[{"role":"user","content":"hello"}],
                    tools=[{"type":"function","function":{"name":"test","parameters":{"type":"object"}}}])
    asyncio.run(check())
    req = captured[0]
    assert str(req.url) == "https://gateway.example/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer test-only-key"
    body = json.loads(req.content)
    assert body["tools"] and body["max_tokens"] == 3000
    assert "max_completion_tokens" not in body
