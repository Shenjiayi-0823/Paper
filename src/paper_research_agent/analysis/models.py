"""Validated, provenance-aware analysis and recommendation schemas."""

from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Model):
    id: str
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=350)


class Claim(Model):
    text: str = Field(default="Not specified", min_length=1, max_length=600)
    provenance: Literal["author_stated", "inference", "not_specified"] = "not_specified"
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def check_missing(self):
        if self.provenance == "not_specified":
            if self.text != "Not specified" or self.evidence_ids:
                raise PydanticCustomError('claim_missing_mismatch','not_specified requires text=Not specified and empty evidence_ids')
        elif self.text == "Not specified":
            raise PydanticCustomError('claim_missing_label','Not specified text requires provenance=not_specified')
        elif not self.evidence_ids:
            raise PydanticCustomError('claim_evidence_required','Specified claims require nonempty evidence_ids from the supplied catalogue')
        return self


def missing():
    return [Claim()]


class AnalysisSelection(Model):
    title: str = Field(default="Not specified", min_length=1, max_length=300)
    research_problem: list[Claim] = Field(default_factory=missing, max_length=200)
    background: list[Claim] = Field(default_factory=missing, max_length=200)
    methodology: list[Claim] = Field(default_factory=missing, max_length=200)
    contributions: list[Claim] = Field(default_factory=missing, max_length=200)
    experiments: list[Claim] = Field(default_factory=missing, max_length=200)
    results: list[Claim] = Field(default_factory=missing, max_length=200)
    limitations: list[Claim] = Field(default_factory=missing, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class AnalysisContent(AnalysisSelection):
    evidence: list[Evidence] = Field(default_factory=list, max_length=1000)


class SummaryClaim(Claim):
    text: str = Field(default="Not specified", min_length=1, max_length=180)
    evidence_ids: list[str] = Field(default_factory=list, max_length=2)


class SummarySelection(AnalysisSelection):
    research_problem: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    background: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    methodology: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    contributions: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    experiments: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    results: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    limitations: list[SummaryClaim] = Field(default_factory=missing, max_length=3)
    keywords: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=10)


CLAIM_FIELDS = ("research_problem", "background", "methodology", "contributions", "experiments", "results", "limitations")


class PaperAnalysis(AnalysisContent):
    document_id: str
    total_pages: int
    analyzed_pages: list[int]
    missing_pages: list[int]
    complete: bool
    warnings: list[str]
    sections: list[str]
    chunk_count: int
    # Leaf notes retained so synthesis cannot silently erase extracted findings.
    chunk_analyses: list[AnalysisContent]
    summary: AnalysisSelection | None = None


class TopicPlan(Model):
    research_theme: str = Field(min_length=1, max_length=500)
    technical_methods: list[str] = Field(default_factory=list, max_length=10)
    english_keywords: list[str] = Field(min_length=1, max_length=8)


class RankedCandidate(Model):
    arxiv_id: str
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=600)
    connection: str = Field(min_length=1, max_length=600)
    differences: str = Field(min_length=1, max_length=600)


class Ranking(Model):
    candidates: list[RankedCandidate] = Field(default_factory=list, max_length=5)


class RelatedPaper(RankedCandidate):
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str | None
    entry_url: str
    evidence_basis: Literal["title_and_abstract"] = "title_and_abstract"


class Recommendations(Model):
    source_document_id: str
    theme: TopicPlan
    queries: list[str]
    papers: list[RelatedPaper] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list)
