"""Application operations selected by the Agent, using the existing MCP client."""

from typing import Literal
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from paper_research_agent.agent.budget import ResourceError
from paper_research_agent.agent.mcp_client import failure
from .analyzer import PaperAnalyzer
from .recommender import PaperRecommender
from paper_research_agent.agent.progress import report


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_type: Literal["local", "arxiv"]
    file_path: str | None = None
    arxiv_id: str | None = None
    language: str = Field(default="中文", min_length=1, max_length=40)

    @model_validator(mode="after")
    def valid_source(self):
        if self.source_type == "local" and (not self.file_path or self.arxiv_id is not None):
            raise ValueError("Local source requires only file_path")
        if self.source_type == "arxiv" and (not self.arxiv_id or self.file_path is not None):
            raise ValueError("arXiv source requires only arxiv_id")
        return self


OPERATIONS = {
    "analyze_paper": "Produce a validated structured analysis of a PDF, processing every extractable page in chunks and preserving evidence and provenance. Calls read_pdf through MCP internally. Use for structured/deep paper analysis, not generic paper search. Set language to match the user's language.",
    "recommend_related": "Read and analyze the source PDF, extract English topic keywords, retrieve real arXiv candidates through MCP, rank and recommend up to 5. Uses read_pdf and search_arxiv internally. Candidates are evaluated by title and abstract only. Set language to match the user's language.",
}


class ResearchService:
    def __init__(self, mcp, llm, settings, trace):
        self.mcp, self.llm, self.settings, self.trace = mcp, llm, settings, trace
        self.counts = {}
        self.calls = 0
        self.cache = {}
        self.pdf_cache = {}
        self.analysis_failures = {}

    @property
    def function_tools(self):
        return [{"type":"function", "function":{"name":name, "description":description,
            "parameters":SourceRequest.model_json_schema(), "strict":False}} for name, description in OPERATIONS.items()]

    def seed_analysis(self,args,analysis):
        """Reuse a validated same-source report, e.g. within one Web session."""
        source = SourceRequest.model_validate(args)
        from .models import PaperAnalysis
        analysis = PaperAnalysis.model_validate(analysis)
        expected = source.file_path if source.source_type == 'local' else source.arxiv_id
        if analysis.document_id != expected:
            raise ValueError('Cached analysis belongs to another source')
        self.cache[(source.source_type,source.file_path,source.arxiv_id,source.language)] = analysis

    async def tool_call(self, name, args, internal=True):
        import json
        key = (name, json.dumps(args, sort_keys=True))
        if name == "read_pdf" and key in self.pdf_cache:
            report(getattr(self.llm, "progress", None), "复用已读取的 PDF")
            if internal:
                self.trace.append({"name":name,"internal":True,"cached":True,"success":True,"error":None})
            return deepcopy(self.pdf_cache[key])
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] > self.settings.agent_max_repeated_calls:
            return failure("repeat_limit", "Repeated internal MCP call blocked.")
        if self.calls >= self.settings.agent_max_tool_rounds * self.settings.agent_max_calls_per_round:
            return failure("call_limit", "Task internal MCP call budget exhausted.")
        self.calls += 1
        report(getattr(self.llm, "progress", None), "正在调用 MCP 工具")
        data = await self.mcp.call_tool(name, args)
        report(getattr(self.llm, "progress", None), "MCP 工具调用完成" if data.get("success") else "MCP 工具返回错误")
        if name == "read_pdf" and data.get("success"):
            self.pdf_cache[key] = deepcopy(data)
        if internal:
            self.trace.append({"name":name, "internal":True, "success":data.get("success"), "error":data.get("error")})
        return data

    async def execute(self, name, args):
        if name not in OPERATIONS:
            return failure("unknown_tool", "Unknown research operation.")
        try:
            source = SourceRequest.model_validate(args)
        except ValidationError:
            return failure("invalid_arguments", "Invalid analysis/recommendation source parameters.")
        try:
            cache_key = (source.source_type, source.file_path, source.arxiv_id, source.language)
            if cache_key in self.analysis_failures:
                code, message = self.analysis_failures[cache_key]
                return failure(code, message + " Previous analysis failed in this task; do not reread the successfully retrieved PDF to fix JSON format.")
            if cache_key not in self.cache:
                analyzer = PaperAnalyzer(self.mcp, self.llm, self.settings, self.tool_call)
                self.cache[cache_key] = await analyzer.analyze(**source.model_dump())
            analysis = self.cache[cache_key]
            data = {"success":True, "analysis":analysis.model_dump()}
            if name == "recommend_related":
                recommender = PaperRecommender(self.mcp, self.llm, self.settings, self.tool_call)
                recommendations = await recommender.recommend(analysis, source.arxiv_id, source.language)
                data["recommendations"] = recommendations.model_dump()
            return data
        except ValidationError:
            return failure("invalid_structured_output", "Analysis or recommendation failed final model validation.")
        except ResourceError as exc:
            if exc.code in {"invalid_structured_output", "invalid_evidence", "invalid_title", "incomplete_structured_output", "structured_output_limit", "unexpected_structured_tool", "context_budget", "token_budget", "llm_call_budget"} and cache_key not in self.cache:
                self.analysis_failures[cache_key] = (exc.code, exc.message)
            return failure(exc.code, exc.message)
        except Exception:
            return failure("research_error", "Research operation failed; check model, network and MCP service. No raw credentials or exceptions are exposed.")
