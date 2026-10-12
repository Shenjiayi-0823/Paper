"""Code-owned quotations: the LLM selects source IDs instead of rewriting text."""

from paper_research_agent.agent.budget import ResourceError
from .models import Evidence, CLAIM_FIELDS


def build_catalog(chunk):
    records = {}
    for span in chunk.spans:
        start = 0
        while start < len(span.text):
            end = min(start + 180, len(span.text))
            newline = span.text.rfind("\n", start, end)
            if end < len(span.text) and newline > start + 90:
                end = newline + 1
            quote = span.text[start:end].strip()
            start = end
            if not quote:
                continue
            ident = f"c{chunk.id}-s{len(records) + 1}"
            records[ident] = Evidence(id=ident, page_number=span.page_number, quote=quote)
    return records


def select_evidence(content, catalog, validate_legacy):
    used = list(dict.fromkeys(i for name in CLAIM_FIELDS for claim in getattr(content, name) for i in claim.evidence_ids))
    if all(ident in catalog for ident in used):
        content.evidence = [catalog[ident].model_copy(deep=True) for ident in used]
        return
    # Compatibility with previously valid full-evidence JSON. Unknown IDs are
    # accepted only with genuinely matching original quotes, never fabricated.
    legacy = {e.id for e in content.evidence}
    if content.evidence and all(ident in legacy for ident in used):
        validate_legacy(content)
        return
    raise ResourceError("invalid_evidence", "Unknown evidence ID. Select only IDs from evidence_catalog; do not generate quotes or page numbers.")
