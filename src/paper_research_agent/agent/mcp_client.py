"""Official MCP stdio client; no imports of the underlying tool functions."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from datetime import timedelta
import json
import sys

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from paper_research_agent.config import PROJECT_ROOT


def failure(code: str, message: str) -> dict:
    return {"success": False, "error": {"code": code, "message": message}}


def function_schema(tool) -> dict:
    """Preserve MCP defaults/nullable inputs; don't force incompatible strict mode."""
    return {"type": "function", "function": {
        "name": tool.name, "description": tool.description or "",
        "parameters": deepcopy(tool.inputSchema), "strict": False,
    }}


def decode_result(result) -> dict:
    if result.structuredContent is not None:
        data = result.structuredContent
    else:
        texts = [block.text for block in result.content if block.type == "text"]
        try:
            data = json.loads(texts[0]) if len(texts) == 1 else {"content": texts}
        except (ValueError, TypeError):
            data = {"content": texts}
    try:
        json.dumps(data, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        return failure("serialization_error", "MCP result cannot be serialized as JSON.")
    if result.isError:
        return {**failure("mcp_tool_error", "MCP reported a tool execution error."), "details": data}
    return data if isinstance(data, dict) else {"data": data}


class MCPClient:
    def __init__(self, server: StdioServerParameters | None = None, timeout: float = 90):
        self.server = server or StdioServerParameters(
            command=sys.executable, args=["-m", "paper_research_agent.mcp_server.server"],
            cwd=str(PROJECT_ROOT))
        self.timeout = timeout
        self.session = None
        self.tools = {}
        self.broken = False

    @property
    def function_tools(self) -> list[dict]:
        return [function_schema(tool) for tool in self.tools.values()]

    @asynccontextmanager
    async def connect(self):
        if self.session is not None:
            raise RuntimeError("MCP client is already connected")
        try:
            # Enter and exit SDK cancel scopes in the SAME task, in reverse order.
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(self.server))
                self.session = await stack.enter_async_context(ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=self.timeout)))
                async with asyncio.timeout(self.timeout):
                    await self.session.initialize()
                    self.tools = {}
                    cursor = None
                    while True:
                        listing = await self.session.list_tools(cursor=cursor)
                        for tool in listing.tools:
                            Draft202012Validator.check_schema(tool.inputSchema)
                            self.tools[tool.name] = tool
                        cursor = listing.nextCursor
                        if not cursor:
                            break
                self.broken = False
                yield self
        finally:
            self.session = None
            self.tools = {}

    def validate_arguments(self, name: str, arguments: dict) -> dict | None:
        if name not in self.tools:
            return failure("unknown_tool", "Tool was not declared by the connected MCP server.")
        if not isinstance(arguments, dict):
            return failure("invalid_arguments", "Tool arguments must be a JSON object.")
        schema = deepcopy(self.tools[name].inputSchema)
        schema.setdefault("additionalProperties", False)
        errors = list(Draft202012Validator(schema).iter_errors(arguments))
        if errors:
            return failure("invalid_arguments", "Tool arguments do not match the discovered MCP inputSchema.")
        return None

    async def call_tool(self, name: str, arguments: dict) -> dict:
        error = self.validate_arguments(name, arguments)
        if error:
            return error
        if self.session is None or self.broken:
            return failure("mcp_disconnected", "MCP connection is unavailable; start a new task to reconnect.")
        try:
            json.dumps(arguments, allow_nan=False)
            async with asyncio.timeout(self.timeout):
                result = await self.session.call_tool(name, arguments)
            return decode_result(result)
        except TimeoutError:
            self.broken = True
            return failure("tool_timeout", "MCP tool exceeded its time limit; connection will be closed.")
        except McpError as exc:
            if exc.error.code == 408:
                self.broken = True
                return failure("tool_timeout", "MCP tool exceeded its time limit; connection will be closed.")
            self.broken = True
            return failure("mcp_disconnected", "MCP request failed or the server disconnected.")
        except (ValueError, TypeError):
            return failure("serialization_error", "Tool arguments or results cannot be serialized.")
        except Exception:
            self.broken = True
            return failure("mcp_disconnected", "MCP request failed or the server disconnected.")
