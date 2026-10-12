"""Read complete MCP data, analyze every chunk, then reduce notes in a tree."""

import json
from pydantic import BaseModel, Field, ValidationError

from paper_research_agent.agent.budget import ResourceError
from .chunking import chunk_pages
from .models import AnalysisContent, AnalysisSelection, SummarySelection, PaperAnalysis, CLAIM_FIELDS, Claim
from .evidence import build_catalog, select_evidence
from paper_research_agent.agent.progress import report
from .structured import structured_call


class Page(BaseModel):
    page_number: int = Field(ge=1)
    text: str


class Document(BaseModel):
    document_id: str
    total_pages: int = Field(ge=1)
    pages: list[Page] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


def normalize(text):
    return " ".join(text.split())


def check_claims(content: AnalysisContent):
    ids = {e.id for e in content.evidence}
    if len(ids) != len(content.evidence):
        raise ResourceError("invalid_evidence", "Duplicate evidence identifiers.")
    for name in CLAIM_FIELDS:
        for claim in getattr(content, name):
            if not set(claim.evidence_ids) <= ids:
                raise ResourceError("invalid_evidence", "A conclusion references unavailable evidence.")


def validate_quotes(content, source_pages, title_pages=None):
    if content.title != "Not specified" and normalize(content.title).casefold() not in normalize("\n".join((title_pages or source_pages).values())).casefold():
        raise ResourceError("invalid_title", "Analysis title is not present in the supplied original text; retain the source title or Not specified.")
    for index, evidence in enumerate(content.evidence):
        text = source_pages.get(evidence.page_number, "")
        if not normalize(evidence.quote) or normalize(evidence.quote) not in normalize(text):
            reason = "page not present in this chunk" if evidence.page_number not in source_pages else "quote is not a contiguous original-text match"
            raise ResourceError("invalid_evidence", f"evidence.{index} on page {evidence.page_number}: {reason}. Copy a short snippet verbatim; do not translate or insert ellipses.")
    check_claims(content)


def deduplicate_claims(content):
    for field in CLAIM_FIELDS:
        values = getattr(content, field)
        specified = [c for c in values if c.provenance != "not_specified"]
        seen = {}
        for claim in specified:
            key = (normalize(claim.text).casefold(), claim.provenance)
            if key in seen:
                seen[key].evidence_ids = list(dict.fromkeys(seen[key].evidence_ids + claim.evidence_ids))[:10]
            else:
                seen[key] = claim.model_copy(deep=True)
        setattr(content, field, list(seen.values()) or values[:1] or [Claim()])
    content.keywords = list(dict.fromkeys(k.strip() for k in content.keywords if k.strip()))
    return content


class PaperAnalyzer:
    def __init__(self, mcp, llm, settings, tool_call=None):
        self.mcp, self.llm, self.settings = mcp, llm, settings
        self.tool_call = tool_call or mcp.call_tool

    async def analyze(self, source_type, file_path=None, arxiv_id=None, language="中文") -> PaperAnalysis:
        args = {"source_type": source_type}
        if file_path is not None:
            args["file_path"] = file_path
        if arxiv_id is not None:
            args["arxiv_id"] = arxiv_id
        data = await self.tool_call("read_pdf", args)
        if not data.get("success"):
            raise ResourceError("pdf_tool_error", "MCP read_pdf failed: " + str((data.get("error") or {}).get("code", "unknown")))
        if data.get("truncated"):
            raise ResourceError("truncated_pdf", "Analysis requires untruncated MCP page data.")
        try:
            doc = Document.model_validate(data)
        except ValidationError as exc:
            raise ResourceError("invalid_pdf_result", "MCP PDF result has invalid page data.") from exc
        numbers = [p.page_number for p in doc.pages]
        if len(set(numbers)) != len(numbers) or any(p > doc.total_pages for p in numbers):
            raise ResourceError("invalid_pdf_result", "Duplicate or out-of-range PDF page numbers.")
        pages = [p.model_dump() for p in sorted(doc.pages, key=lambda p: p.page_number)]
        original = {p["page_number"]: p["text"] for p in pages}
        missing = [n for n in range(1, doc.total_pages + 1) if not original.get(n, "").strip()]
        schema_bytes = len(json.dumps(AnalysisContent.model_json_schema(), ensure_ascii=False).encode("utf-8"))
        available = self.settings.agent_context_budget - schema_bytes - self.settings.analysis_output_tokens - 3000
        if available < 256:
            raise ResourceError("context_budget", "Context budget is too small for analysis schema, prompt and output reserve.")
        # Source text and code-owned snippet catalogue are both in the prompt.
        chunks = chunk_pages(pages, min(self.settings.analysis_chunk_bytes, available // 2), self.settings.analysis_max_chunks)
        if hasattr(self.llm, "calls") and self.llm.calls + 2 * len(chunks) - 1 > self.settings.agent_max_llm_calls:
            raise ResourceError("llm_call_budget", "Remaining LLM calls cannot cover every chunk and the reduction tree.")
        if not chunks:
            raise ResourceError("no_text", "No extracted PDF text is available.")
        progress = getattr(self.llm, "progress", None)
        report(progress, f"PDF 已读取：{doc.total_pages} 页，{len(chunks)} 个文本块")
        leaves = []
        title_warnings = []
        def ground_title(parsed):
            if parsed.title != "Not specified" and normalize(parsed.title).casefold() not in normalize("\n".join(original.values())).casefold():
                parsed.title = "Not specified"
                if not title_warnings:
                    title_warnings.append("Model-generated title could not be verified against PDF text; replaced with Not specified. No title was fabricated.")
        for chunk in chunks:
            report(progress, f"分块分析 {chunk.id}/{len(chunks)}")
            source = {}
            for span in chunk.spans:
                source[span.page_number] = source.get(span.page_number, "") + span.text
            catalog = build_catalog(chunk)
            def validate_selection(parsed):
                SummarySelection.model_validate(parsed.model_dump(exclude={"evidence"}))
                ground_title(parsed)
                select_evidence(parsed, catalog, lambda value: validate_quotes(value, source, original))
                validate_quotes(parsed, source, original)
            content = await structured_call(self.llm, self.settings, AnalysisContent,
                f"Analyze this PDF chunk in {language}, preserving English technical terms. Copy the title verbatim from source text or use Not specified; do not translate the title. Focus on methods, experiments, quantitative results and limitations. Missing facts MUST be Not specified. Label author_stated vs inference. Give at most 3 claims per field, each at most 180 characters. Select at most 2 supporting IDs per claim and at most 10 short keywords. DO NOT output an evidence array or write quotes/page numbers. Quote text and pages are filled by code. Do not infer missing datasets/results. Use only this chunk's text.",
                {"chunk_id":chunk.id, "spans":[{"page_number":s.page_number,"start":s.start,"end":s.end,"section":s.section} for s in chunk.spans],
                 "evidence_catalog":[e.model_dump() for e in catalog.values()]},
                validator=validate_selection, schema_model=SummarySelection)
            # Canonical IDs prevent collisions across independent chunk calls.
            mapping = {e.id: f"c{chunk.id}-e{i + 1}" for i, e in enumerate(content.evidence)}
            for evidence in content.evidence:
                evidence.id = mapping[evidence.id]
            for name in CLAIM_FIELDS:
                for claim in getattr(content, name):
                    claim.evidence_ids = [mapping[i] for i in claim.evidence_ids]
            leaves.append(deduplicate_claims(content))
        level = leaves
        layer = 0
        while len(level) > 1:
            layer += 1
            reduced = []
            for index in range(0, len(level), 2):
                group = level[index:index + 2]
                if len(group) == 1:
                    reduced.append(group[0])
                    continue
                report(progress, f"分层汇总：第 {layer} 层，第 {index // 2 + 1}/{len(level) // 2} 组")
                referenced = {i for c in group for name in CLAIM_FIELDS for claim in getattr(c,name) for i in claim.evidence_ids}
                allowed = {e.id: e for c in group for e in c.evidence if e.id in referenced}
                def validate_merge(parsed):
                    SummarySelection.model_validate(parsed.model_dump(exclude={"evidence"}))
                    ground_title(parsed)
                    select_evidence(parsed, allowed, lambda value: check_claims(value))
                    if any(e.id not in allowed or e != allowed[e.id] for e in parsed.evidence):
                        raise ResourceError("invalid_evidence", "Synthesis changed original evidence.")
                    check_claims(parsed)
                merged = await structured_call(self.llm, self.settings, AnalysisContent,
                    f"Merge these notes in {language} into a SHORT intermediate summary: at most 3 claims per field, 180 characters per claim, 2 supporting IDs per claim, and 10 keywords of at most 60 characters. Consolidate methods, experiments, results and limitations. Do not reproduce every source claim: detailed leaf notes are separately preserved in the final report. Preserve author/inference labels. Select ONLY existing evidence IDs. Do not output evidence records, quotes or page numbers. Code fills those. Do not add facts. Missing information is Not specified.",
                    {"notes": [c.model_dump(exclude={"evidence"}) for c in group], "evidence_catalog":[{"id":e.id,"page_number":e.page_number} for e in allowed.values()]},
                    validator=validate_merge, schema_model=SummarySelection)
                if any(e.id not in allowed or e != allowed[e.id] for e in merged.evidence):
                    raise ResourceError("invalid_evidence", "Synthesis changed original evidence.")
                check_claims(merged)
                if merged.title == "Not specified":
                    merged.title = next((c.title for c in group if c.title != "Not specified"), "Not specified")
                reduced.append(deduplicate_claims(merged))
            level = reduced
        # Retain verified leaf evidence and notes even if synthesis omits details.
        final = level[0].model_copy(deep=True)
        # Restore detail ONCE in the final artifact, never in intermediate
        # requests: otherwise every tree level grows toward the entire paper.
        for name in CLAIM_FIELDS:
            for leaf in leaves:
                for claim in getattr(leaf,name):
                    if claim.provenance != "not_specified":
                        getattr(final,name).append(claim.model_copy(deep=True))
        final = deduplicate_claims(final)
        all_evidence = {e.id: e for leaf in leaves for e in leaf.evidence}
        final.evidence = list(all_evidence.values())
        validate_quotes(final, original)
        warnings = list(doc.warnings) + title_warnings
        warnings.append("Intermediate summaries are bounded; full verified chunk notes and citations are preserved separately in chunk_analyses.")
        if missing:
            warnings.append(f"Unextractable/missing pages: {missing}; analysis is incomplete, no OCR performed.")
        warnings.append("Coverage means all extractable spans were processed, not that every scientific claim was verified.")
        return PaperAnalysis(**final.model_dump(), document_id=doc.document_id,
            total_pages=doc.total_pages, analyzed_pages=sorted(n for n in numbers if n not in missing),
            missing_pages=missing, complete=not missing and not doc.warnings,
            warnings=warnings, sections=list(dict.fromkeys(s.section for c in chunks for s in c.spans)),
            chunk_count=len(chunks), chunk_analyses=leaves,
            summary=AnalysisSelection.model_validate(level[0].model_dump(exclude={"evidence"})))
