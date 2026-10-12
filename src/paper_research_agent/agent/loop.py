"""Bounded multi-round OpenAI Function Calling over MCP."""

import asyncio
from collections import Counter
from copy import deepcopy
import json

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from paper_research_agent.config import Settings
from .mcp_client import MCPClient, failure
from .prompts import SYSTEM_PROMPT
from .budget import BudgetedLLM, ResourceError, find_resource_error
from .progress import report
from paper_research_agent.analysis.service import ResearchService, OPERATIONS


class AgentResult(BaseModel):
    success: bool = False
    answer: str = ""
    error: dict | None = None
    messages: list[dict] = Field(default_factory=list)
    tool_trace: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


def bounded_result(data: dict, limit: int) -> str:
    """Preserve valid JSON; oversized results are explicitly untrusted excerpts."""
    try:
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raw = json.dumps(failure("serialization_error", "Tool result is not JSON serializable."))
    envelope = {"untrusted_tool_data": True, "truncated": False, "data": json.loads(raw)}
    text = json.dumps(envelope, ensure_ascii=False)
    if len(text) <= limit:
        return text
    envelope = {"untrusted_tool_data": True, "truncated": True,
                "original_chars": len(raw),
                "warning": "Result excerpt only; full-paper analysis is not supported by this evidence.",
                "excerpt": ""}
    # JSON escaping makes slicing the encoded result unsafe; shorten the value.
    available = max(0, limit - len(json.dumps(envelope, ensure_ascii=False)))
    envelope["excerpt"] = raw[:available]
    text = json.dumps(envelope, ensure_ascii=False)
    while len(text) > limit and envelope["excerpt"]:
        envelope["excerpt"] = envelope["excerpt"][:max(0, len(envelope["excerpt"]) - (len(text) - limit))]
        text = json.dumps(envelope, ensure_ascii=False)
    return text


class PaperAgent:
    def __init__(self, settings: Settings, llm=None, mcp: MCPClient | None = None, progress=None):
        self.settings = settings
        # Injection allows offline tests with no key. No API call is made here.
        self.llm = llm
        self.mcp = mcp or MCPClient(timeout=settings.agent_tool_timeout_seconds)
        self.progress = progress

    async def run(self, request: str) -> AgentResult:
        result = AgentResult(messages=[{"role": "system", "content": SYSTEM_PROMPT +
            f"\nDefault search count when unspecified: {self.settings.arxiv_max_results}."},
            {"role": "user", "content": request}])
        if not request.strip() or len(request) > 10000:
            result.error = failure("invalid_request", "Request must be 1–10000 characters.")["error"]
            return result
        owned_llm = self.llm is None
        llm = self.llm
        budgeted = None
        report(self.progress, f"任务启动（总时限 {self.settings.agent_task_timeout_seconds:g} 秒），正在连接 MCP Server")
        try:
            async with asyncio.timeout(self.settings.agent_task_timeout_seconds):
                if owned_llm:
                    llm = AsyncOpenAI(api_key=self.settings.require_openai_api_key(),
                                      base_url=self.settings.openai_base_url,
                                      timeout=self.settings.request_timeout_seconds, max_retries=0)
                async with self.mcp.connect():
                    report(self.progress, "MCP 已连接，开始模型决策")
                    budgeted = BudgetedLLM(llm, self.settings, self.progress)
                    await self._loop(budgeted, result)
        except ResourceError as exc:
            result.error = failure(exc.code, exc.message)["error"]
        except TimeoutError:
            result.error = failure("task_timeout", "The task exceeded its total time limit.")["error"]
        except Exception as exc:
            # Do not expose SDK exception strings, headers, arguments or API keys.
            specific = find_resource_error(exc)
            if specific is not None:
                result.error = failure(specific.code, specific.message)["error"]
            else:
                result.error = failure("agent_error", "LLM request or MCP connection failed; check credentials, model, network and server.")["error"]
        finally:
            report(self.progress, "任务处理结束，释放连接资源")
            if budgeted is not None:
                result.usage = {"llm_calls":budgeted.calls, "accounted_tokens":budgeted.reserved_tokens,
                    "provider_usage_calls":budgeted.reported_usage_calls,
                    "estimated_usage_calls":budgeted.calls - budgeted.reported_usage_calls}
            if owned_llm and llm is not None:
                await llm.close()
        if result.error:
            result.success = False
            if result.error["code"] in {"token_budget", "llm_call_budget", "context_budget", "task_timeout"}:
                prior = next((t["error"] for t in result.tool_trace if t["name"] in OPERATIONS and t.get("error")), None)
                if prior and prior["code"] != result.error["code"]:
                    result.error = {**prior, "secondary_error":result.error}
                    result.answer = "论文分析/推荐未完成。最初失败原因：" + prior["message"] + " 后续请求达到资源预算或时间上限。"
        return result

    async def _loop(self, llm, result: AgentResult):
        research = ResearchService(self.mcp, llm, self.settings, result.tool_trace)
        counts = Counter()
        used_chars = 0
        rounds = 0
        seen_ids = set()
        while True:
            reserve = 300 * self.settings.agent_max_calls_per_round
            exhausted = rounds >= self.settings.agent_max_tool_rounds or self.settings.agent_max_task_result_chars - used_chars < reserve
            tools = self.mcp.function_tools + research.function_tools
            routing_messages = deepcopy(result.messages)
            while len(json.dumps({"messages":routing_messages,"tools":tools},ensure_ascii=False).encode("utf-8")) + self.settings.agent_output_tokens + 1500 > self.settings.agent_context_budget:
                candidates = [m for m in routing_messages if m["role"] == "tool" and len(m["content"]) > 500]
                if not candidates:
                    raise ResourceError("context_budget", "Routing context cannot fit even after explicitly marked tool excerpts.")
                message = max(candidates, key=lambda m:len(m["content"]))
                message["content"] = bounded_result(json.loads(message["content"]),max(400,len(message["content"]) // 2))
            response = await llm.chat.completions.create(
                model=self.settings.openai_model, messages=routing_messages,
                tools=tools, tool_choice="none" if exhausted else "auto")
            choice = response.choices[0]
            message = choice.message
            calls = message.tool_calls or []
            if calls:
                if exhausted:
                    result.error = failure("round_limit", "LLM requested tools after the resource limit.")["error"]
                    return
                if len(calls) > self.settings.agent_max_calls_per_round:
                    result.error = failure("call_limit", "Too many tool calls in one LLM response.")["error"]
                    return
                if any(c.type != "function" or not c.id or c.id in seen_ids for c in calls) or len({c.id for c in calls}) != len(calls):
                    result.error = failure("invalid_llm_response", "Invalid or duplicate tool call IDs.")["error"]
                    return
                rounds += 1
                result.messages.append({"role": "assistant", "content": message.content,
                    "tool_calls": [{"id": c.id, "type": "function", "function": {
                        "name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
                for index, call in enumerate(calls):
                    seen_ids.add(call.id)
                    try:
                        if len(call.function.arguments) > 10000:
                            raise ValueError("Argument size limit")
                        args = json.loads(call.function.arguments, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        if not isinstance(args, dict):
                            raise ValueError("Arguments must be object")
                        key = (call.function.name, json.dumps(args, sort_keys=True, allow_nan=False))
                        counts[key] += 1
                        if index >= self.settings.agent_max_calls_per_round:
                            data = failure("call_limit", "Too many tool calls in one round.")
                        elif counts[key] > self.settings.agent_max_repeated_calls:
                            data = failure("repeat_limit", "Repeated identical tool call blocked.")
                        elif used_chars >= self.settings.agent_max_task_result_chars:
                            data = failure("result_budget", "Task tool result budget exhausted.")
                        else:
                            if call.function.name in OPERATIONS:
                                data = await research.execute(call.function.name, args)
                                if data.get("success"):
                                    result.artifacts.append({"operation":call.function.name, "data":data})
                            else:
                                data = await research.tool_call(call.function.name, args, internal=False)
                    except (ValueError, TypeError):
                        data = failure("invalid_arguments", "LLM tool arguments must be a valid JSON object.")
                    result.tool_trace.append({"tool_call_id": call.id, "name": call.function.name,
                        "success": data.get("success"), "error": data.get("error")})
                    remaining = self.settings.agent_max_task_result_chars - used_chars
                    text = bounded_result(data, min(self.settings.agent_max_result_chars,
                        remaining - 300 * (len(calls) - index - 1)))
                    used_chars += len(text)
                    result.messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
                if rounds >= self.settings.agent_max_tool_rounds or used_chars >= self.settings.agent_max_task_result_chars:
                    result.messages.append({"role": "system", "content": "Resource limit reached. Make no further tool calls. Answer from available evidence and explicitly state limits/errors."})
                continue
            if choice.finish_reason not in ("stop", None) or not message.content:
                result.error = failure("incomplete_answer", "LLM did not return a complete answer.")["error"]
                return
            result.messages.append({"role": "assistant", "content": message.content})
            result.answer = message.content
            failed_research = [t for t in result.tool_trace if t["name"] in OPERATIONS and t.get("error")]
            if failed_research and not result.artifacts:
                result.error = failed_research[0]["error"]
                if result.error["code"] in {"invalid_structured_output", "invalid_evidence", "invalid_title", "context_budget", "token_budget", "llm_call_budget"}:
                    read_ok = any(t["name"] == "read_pdf" and t.get("success") for t in result.tool_trace)
                    if result.error["code"] in {"context_budget", "token_budget", "llm_call_budget"}:
                        prefix = "PDF 已成功读取，但论文分析/汇总达到资源限制。" if read_ok else "论文分析/汇总达到资源限制。"
                    else:
                        prefix = "PDF 已成功读取，但模型的结构化分析或证据校验失败。" if read_ok else "论文结构化分析或证据校验失败。"
                    result.answer = prefix + "未生成有效报告或推荐结果。具体原因：" + result.error["message"]
                return
            result.success = True
            return
