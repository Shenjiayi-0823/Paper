"""Local single-user library, separate from task history and model execution."""
from sqlalchemy import select, delete, func
from .models import Paper, PaperAnalysis, LibraryEntry, QueryHistory, utcnow
from .repository import Repository
from .service import sanitize
from paper_research_agent.analysis.models import PaperAnalysis as Report


class LibraryService:
    def __init__(self, history):
        self.history = history
        self.database = history.database

    def ensure_paper(self, data, content_hash=None):
        secret = self.history.settings.openai_api_key
        data = sanitize(data, secret.get_secret_value() if secret else None)
        with self.database.transaction() as session:
            return Repository(session).paper(data, content_hash).id

    def get_paper(self, paper_id):
        with self.database.transaction() as session:
            row = session.get(Paper, paper_id)
            if row is None:
                return None
            return {'paper_id': row.id, 'arxiv_id': row.arxiv_id, 'title': row.title,
                'authors': row.authors_json, 'abstract': row.abstract, 'published': row.published_at,
                'pdf_url': row.pdf_url, 'content_hash': row.content_hash}

    def favorite(self, paper_id, enabled=True):
        with self.database.transaction() as session:
            if session.get(Paper, paper_id) is None:
                raise ValueError('Paper not found')
            row = session.scalar(select(LibraryEntry).where(LibraryEntry.paper_id == paper_id))
            if enabled and row is None:
                session.add(LibraryEntry(paper_id=paper_id))
            elif not enabled and row:
                session.delete(row)

    def get_entry(self, paper_id):
        with self.database.transaction() as session:
            return session.scalar(select(LibraryEntry).where(LibraryEntry.paper_id == paper_id))

    def set_reading_status(self, paper_id, status):
        if status not in {'to_read', 'reading', 'read'}:
            raise ValueError('Invalid reading status')
        with self.database.transaction() as session:
            row = session.scalar(select(LibraryEntry).where(LibraryEntry.paper_id == paper_id))
            if row is None:
                raise ValueError('Favorite the paper first')
            row.reading_status, row.updated_at = status, utcnow()

    def list_papers(self, title='', status=None, page=0, page_size=20):
        if page < 0 or not 1 <= page_size <= 100:
            raise ValueError('Invalid pagination')
        with self.database.transaction() as session:
            statement = select(Paper, LibraryEntry).join(LibraryEntry, Paper.id == LibraryEntry.paper_id)
            if title:
                statement = statement.where(Paper.title.contains(title, autoescape=True))
            if status:
                statement = statement.where(LibraryEntry.reading_status == status)
            rows = session.execute(statement.order_by(LibraryEntry.updated_at.desc(), LibraryEntry.id.desc())
                                   .offset(page * page_size).limit(page_size))
            return [{'paper_id': paper.id, 'title': paper.title, 'arxiv_id': paper.arxiv_id,
                     'reading_status': entry.reading_status} for paper, entry in rows]

    def latest_analysis(self, paper_id, arxiv_id=None):
        # Viewing is allowed across model versions; it is NOT a new-task cache seed.
        with self.database.transaction() as session:
            statement = select(PaperAnalysis).where(PaperAnalysis.paper_id == paper_id)
            for row in session.scalars(statement.order_by(PaperAnalysis.id.desc())):
                try:
                    report = Report.model_validate(row.analysis_json)
                    if arxiv_id and report.document_id != arxiv_id:
                        continue
                    return {'analysis': report.model_dump(), 'query_id': row.query_id,
                            'model_name': row.model_name, 'prompt_version': row.prompt_version}
                except ValueError:
                    continue
        return None

    def overview(self):
        with self.database.transaction() as session:
            counts = dict(session.execute(select(LibraryEntry.reading_status, func.count())
                                           .group_by(LibraryEntry.reading_status)).all())
            return {'library': sum(counts.values()), 'to_read': counts.get('to_read', 0),
                    'read': counts.get('read', 0),
                    'analyses': session.scalar(select(func.count(func.distinct(PaperAnalysis.paper_id)))
                        .where(PaperAnalysis.analysis_json['complete'].as_boolean().is_(True))),
                    'tasks': session.scalar(select(func.count()).select_from(QueryHistory))}
