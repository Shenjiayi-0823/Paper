"""One LLM budget shared by routing, chunk analysis, synthesis and ranking."""

import asyncio
import json
import socket
import ssl
import httpx
from types import SimpleNamespace
import openai
from .progress import report


class ResourceError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def find_resource_error(exc):
    """AnyIO task-group cleanup can wrap a sanitized error in ExceptionGroup."""
    if isinstance(exc, ResourceError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = find_resource_error(child)
            if found is not None:
                return found
    return None


def api_failure(exc):
    """Classify SDK errors without exposing response bodies or credentials."""
    if isinstance(exc, openai.AuthenticationError):
        return "llm_authentication", "OpenAI authentication failed (401). Check the API key and its provider."
    if isinstance(exc, openai.PermissionDeniedError):
        return "llm_permission", "OpenAI denied access (403). Check account, region and project/model permissions."
    if isinstance(exc, openai.NotFoundError):
        return "llm_model_not_found", "OpenAI model or endpoint was not found (404). Check OPENAI_MODEL and API provider."
    if isinstance(exc, openai.RateLimitError):
        if getattr(exc, "code", None) == "insufficient_quota":
            return "llm_quota", "OpenAI API quota is insufficient (429). Check API billing and project limits."
        return "llm_rate_limit", "OpenAI rate limit reached (429). Retry later or reduce requests."
    if isinstance(exc, openai.APITimeoutError):
        return "llm_timeout", "OpenAI request timed out. Check network or request timeout settings."
    if isinstance(exc, openai.APIConnectionError):
        current, seen = exc, set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ssl.SSLCertVerificationError):
                return "llm_tls_certificate", "Provider TLS certificate verification failed. Check trusted CA configuration; certificate verification remains enabled."
            if isinstance(current, socket.gaierror):
                return "llm_dns", "Provider hostname could not be resolved. Check OPENAI_BASE_URL and DNS."
            if isinstance(current, httpx.ProxyError):
                return "llm_proxy", "Connection through the configured proxy failed. Check proxy settings."
            if isinstance(current, httpx.LocalProtocolError):
                return "llm_request_headers", "Invalid HTTP request headers. Check the key for internal whitespace or invalid characters."
            if isinstance(current, httpx.ConnectTimeout):
                return "llm_connect_timeout", "Connection to the provider timed out. Check network and firewall."
            current = current.__cause__ or current.__context__
        return "llm_connection", "Cannot connect to the configured API provider. Check network, proxy, firewall and TLS certificates."
    if isinstance(exc, openai.BadRequestError):
        return "llm_bad_request", "OpenAI rejected the request (400). Check model support for tools/JSON mode and request parameters."
    return "llm_api_error", "OpenAI API request failed. Check service availability and configured provider."


class BudgetedLLM:
    def __init__(self, llm, settings, progress=None):
        self.llm, self.settings = llm, settings
        self.calls = 0
        self.reserved_tokens = 0
        self.reported_usage_calls = 0
        self.progress = progress
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        # Conservative UTF-8 byte estimate, NOT exact model tokenization. Include
        # schema/tools and reserve the full maximum output before every request.
        estimate = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 512
        output_limit = kwargs.get(self.settings.openai_token_parameter, self.settings.agent_output_tokens)
        if type(output_limit) is not int or not 100 <= output_limit <= max(self.settings.agent_output_tokens,self.settings.analysis_output_tokens):
            raise ResourceError("output_budget", "Requested output exceeds the configured limit.")
        reserve = estimate + output_limit
        if self.calls >= self.settings.agent_max_llm_calls:
            raise ResourceError("llm_call_budget", "LLM call budget exhausted.")
        if reserve > self.settings.agent_context_budget:
            raise ResourceError("context_budget", "Request exceeds the conservative context budget; no input was truncated.")
        if self.reserved_tokens + reserve > self.settings.agent_token_budget:
            raise ResourceError("token_budget", "Conservative task token budget exhausted.")
        self.calls += 1
        self.reserved_tokens += reserve
        kwargs[self.settings.openai_token_parameter] = output_limit
        report(self.progress, f"模型请求 {self.calls}：等待响应（单次时限 {self.settings.request_timeout_seconds:g} 秒）")
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                response = await self.llm.chat.completions.create(**kwargs)
            report(self.progress, f"模型请求 {self.calls}：已收到响应")
            usage = getattr(response, "usage", None)
            total = getattr(usage, "total_tokens", None)
            if type(total) is int and total > 0:
                self.reserved_tokens += total - reserve
                self.reported_usage_calls += 1
                if self.reserved_tokens > self.settings.agent_token_budget:
                    raise ResourceError("token_budget", "Provider-reported task token usage exceeds its budget.")
            return response
        except TimeoutError as exc:
            raise ResourceError("llm_timeout", "Single LLM request timed out.") from exc
        except openai.APIError as exc:
            code, message = api_failure(exc)
            raise ResourceError(code, message) from exc
