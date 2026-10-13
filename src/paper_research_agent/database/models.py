"""SQLAlchemy 2 typed models. JSON snapshots preserve the public result schema."""
from datetime import datetime, timezone
from sqlalchemy import ForeignKey, JSON, String, DateTime, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class QueryHistory(Base):
    __tablename__ = 'query_history'
    __table_args__ = (CheckConstraint("status IN ('pending','running','success','partial','failed','timeout')"),
                      CheckConstraint("query_type IN ('search','analysis','recommendation')"))
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64))
    query_type: Mapped[str] = mapped_column(String(20), index=True)
    query_text: Mapped[str] = mapped_column(default='')
    parameters_json: Mapped[dict] = mapped_column(JSON)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    error_message: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Paper(Base):
    __tablename__ = 'paper'
    id: Mapped[int] = mapped_column(primary_key=True)
    arxiv_id: Mapped[str | None] = mapped_column(unique=True)
    content_hash: Mapped[str | None] = mapped_column(unique=True)
    title: Mapped[str] = mapped_column(default='Not specified')
    authors_json: Mapped[list] = mapped_column(JSON, default=list)
    abstract: Mapped[str] = mapped_column(default='')
    published_at: Mapped[str | None]
    pdf_url: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaperAnalysis(Base):
    __tablename__ = 'paper_analysis'
    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey('query_history.id', ondelete='CASCADE'), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('paper.id'))
    analysis_json: Mapped[dict] = mapped_column(JSON)
    model_name: Mapped[str]
    prompt_version: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = 'recommendation'
    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey('query_history.id', ondelete='CASCADE'), index=True)
    source_paper_id: Mapped[int] = mapped_column(ForeignKey('paper.id'))
    recommended_paper_id: Mapped[int] = mapped_column(ForeignKey('paper.id'))
    rank: Mapped[int]
    reason: Mapped[str]
    similarity_score: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueryResult(Base):
    __tablename__ = 'query_result'
    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey('query_history.id', ondelete='CASCADE'), unique=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    result_type: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LibraryEntry(Base):
    """Additive table: initialization creates it without altering old tables."""
    __tablename__ = 'library_entry'
    __table_args__ = (CheckConstraint("reading_status IN ('to_read','reading','read')"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('paper.id'), unique=True)
    reading_status: Mapped[str] = mapped_column(String(16), default='to_read', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
