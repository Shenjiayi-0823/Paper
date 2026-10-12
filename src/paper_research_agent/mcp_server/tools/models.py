"""Stable JSON result schemas for the tools."""

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str


class Paper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    pdf_url: str | None
    entry_url: str


class SearchResult(BaseModel):
    success: bool = False
    query: str
    papers: list[Paper] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None


class PDFPage(BaseModel):
    page_number: int
    text: str


class PDFResult(BaseModel):
    success: bool = False
    source_type: str
    document_id: str | None = None
    total_pages: int = 0
    pages: list[PDFPage] = Field(default_factory=list)
    full_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None
