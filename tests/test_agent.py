import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool, CallToolResult, TextContent

from paper_research_agent.agent.loop import PaperAgent, bounded_result
from paper_research_agent.agent.mcp_client import MCPClient, decode_result, function_schema
from paper_research_agent.config import Settings


def call(name="search_arxiv", args='{"query":"attention"}', ident="call1"):
    return NS(type="function", id=ident, function=NS(name=name, arguments=args))


def response(calls=None, text="Final answer", finish="stop"):
    return NS(choices=[NS(message=NS(tool_calls=calls, content=None if calls else text), finish_reason=finish)])


def tool():
    return Tool(name="search_arxiv", description="Search", inputSchema={"type": "object",
        "properties": {"query": {"type": "string"}}, "required": ["query"]})


class FakeMCP(MCPClient):
    def __init__(self, data=None, delay=0):
        super().__init__()
        self.tools = {"search_arxiv": tool(), "read_pdf": Tool(name="read_pdf", inputSchema={"type":"object", "properties": {
            "source_type":{"type":"string"}, "arxiv_id":{"type":"string"}}})}
        self.data = data or {"success": True, "papers": []}
        self.delay = delay
        self.calls = []
        self.closed = False

    @asynccontextmanager
    async def connect(self):
        try:
            yield self
        finally:
            self.closed = True

    async def call_tool(self, name, arguments):
        error = self.validate_arguments(name, arguments)
        if error:
            return error
        self.calls.append((name, arguments))
        await asyncio.sleep(self.delay)
        return deepcopy(self.data)


def run(responses, mcp=None, **config):
    llm = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=responses))))
    mcp = mcp or FakeMCP()
    result = asyncio.run(PaperAgent(Settings(**config), llm=llm, mcp=mcp).run("Research request"))
    return result, llm.chat.completions.create, mcp


def test_schema_conversion():
    source = tool()
    converted = function_schema(source)
    assert converted["function"]["parameters"] == source.inputSchema
    assert converted["function"]["strict"] is False
    converted["function"]["parameters"]["required"].append("other")
    assert source.inputSchema["required"] == ["query"]


def test_one_tool_then_final():
    result, llm, mcp = run([response([call()]), response()])
    assert result.success and result.answer == "Final answer" and mcp.closed
    assert mcp.calls == [("search_arxiv", {"query": "attention"})]
    messages = llm.call_args_list[1].kwargs["messages"]
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "call1"
    assert json.loads(messages[-1]["content"])["data"]["success"]


def test_two_rounds():
    result, llm, mcp = run([response([call()]), response([call("read_pdf", '{"source_type":"arxiv","arxiv_id":"1706.03762"}', "call2")]), response()])
    assert result.success and len(mcp.calls) == 2 and llm.call_count == 3
    assert [m["tool_call_id"] for m in result.messages if m["role"] == "tool"] == ["call1", "call2"]


def test_multiple_calls_same_round():
    result, llm, mcp = run([response([call(), call("read_pdf", '{}', "call2")]), response()])
    assert result.success and len(mcp.calls) == 2
    assert [m["tool_call_id"] for m in llm.call_args_list[1].kwargs["messages"] if m["role"] == "tool"] == ["call1", "call2"]


def test_direct_answer():
    result, llm, mcp = run([response(text="Hello")])
    assert result.success and result.answer == "Hello" and not mcp.calls
    assert llm.call_args.kwargs["tool_choice"] == "auto"


@pytest.mark.parametrize("name,args,code", [("undeclared", '{}', "unknown_tool"), ("search_arxiv", 'broken', "invalid_arguments"), ("search_arxiv", '[]', "invalid_arguments"), ("search_arxiv", '{"query":12}', "invalid_arguments"), ("search_arxiv", '{"query":"a","extra":1}', "invalid_arguments"), ("search_arxiv", '{"query":NaN}', "invalid_arguments")])
def test_bad_arguments(name, args, code):
    result, _, mcp = run([response([call(name, args)]), response(text="The tool failed")])
    assert result.success and not mcp.calls
    assert result.tool_trace[0]["error"]["code"] == code


def test_business_error_to_llm():
    result, llm, _ = run([response([call()]), response()], FakeMCP({"success":False,"error":{"code":"api_error","message":"offline"}}))
    assert result.tool_trace[0]["error"]["code"] == "api_error"
    assert "api_error" in llm.call_args_list[1].kwargs["messages"][-1]["content"]


def test_round_limit_and_final_synthesis():
    result, llm, _ = run([response([call()]), response()], agent_max_tool_rounds=1)
    assert result.success and llm.call_args.kwargs["tool_choice"] == "none"
    result, _, _ = run([response([call()]), response([call(ident="call2")])], agent_max_tool_rounds=1)
    assert result.error["code"] == "round_limit"


def test_repeat_limit():
    result, _, mcp = run([response([call(ident=f"call{i}")]) for i in range(3)] + [response()])
    assert result.success and len(mcp.calls) == 2
    assert result.tool_trace[-1]["error"]["code"] == "repeat_limit"


def test_total_timeout():
    mcp = FakeMCP(delay=1)
    result, _, _ = run([response([call()])], mcp, agent_task_timeout_seconds=0.05)
    assert result.error["code"] == "task_timeout" and mcp.closed


def test_truncation_and_task_budget():
    result, _, _ = run([response([call(), call(ident="call2")]), response()],
        FakeMCP({"success":True,"full_text":'"\\' * 10000}),
        agent_max_result_chars=1000, agent_max_task_result_chars=2000)
    contents = [m["content"] for m in result.messages if m["role"] == "tool"]
    assert result.success and sum(map(len, contents)) <= 2000
    assert all(json.loads(c)["truncated"] for c in contents)
    assert "full-paper" in contents[0]


def test_serialization_error():
    data = json.loads(bounded_result({"bad": object()}, 1000))
    assert data["data"]["error"]["code"] == "serialization_error"


def test_decode_structured_and_text():
    result = CallToolResult(structuredContent={"success":True}, content=[TextContent(type="text", text="ignored")])
    assert decode_result(result) == {"success":True}
    assert decode_result(CallToolResult(content=[TextContent(type="text",text='{"success":true}')])) == {"success":True}
    assert decode_result(CallToolResult(isError=True, content=[TextContent(type="text", text="failed")]))["error"]["code"] == "mcp_tool_error"
    malformed = NS(structuredContent={"bad":object()}, content=[], isError=False)
    assert decode_result(malformed)["error"]["code"] == "serialization_error"


def test_single_tool_timeout_and_disconnect():
    async def check():
        client = MCPClient(timeout=0.02)
        client.tools = {"search_arxiv":tool()}
        async def slow(*args):
            await asyncio.sleep(1)
        client.session = NS(call_tool=slow)
        assert (await client.call_tool("search_arxiv", {"query":"x"}))["error"]["code"] == "tool_timeout"
        assert (await client.call_tool("search_arxiv", {"query":"x"}))["error"]["code"] == "mcp_disconnected"
    asyncio.run(check())


def test_no_secret_in_error():
    result, _, _ = run([RuntimeError("sk-secret")])
    assert not result.success and "sk-secret" not in result.model_dump_json()


def test_invalid_call_ids_and_batch_limit():
    result, _, _ = run([response([call(), call()])])
    assert result.error["code"] == "invalid_llm_response"
    result, _, _ = run([response([call(ident=f"id{i}") for i in range(5)])])
    assert result.error["code"] == "call_limit"


def test_llm_timeout_and_missing_key():
    async def slow(**kwargs):
        await asyncio.sleep(1)
    llm = NS(chat=NS(completions=NS(create=slow)))
    result = asyncio.run(PaperAgent(Settings(agent_task_timeout_seconds=0.02), llm=llm, mcp=FakeMCP()).run("Hello"))
    assert result.error["code"] == "task_timeout"
    result = asyncio.run(PaperAgent(Settings(openai_api_key=None), mcp=FakeMCP()).run("Hello"))
    assert result.error["code"] == "agent_error"


def test_sdk_timeout_classification():
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData
    async def check():
        client = MCPClient()
        client.tools = {"search_arxiv":tool()}
        client.session = NS(call_tool=AsyncMock(side_effect=McpError(ErrorData(code=408,message="timeout"))))
        assert (await client.call_tool("search_arxiv", {"query":"x"}))["error"]["code"] == "tool_timeout"
    asyncio.run(check())
