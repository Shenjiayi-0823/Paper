"""Parameterized ORM operations; callers own the transaction."""
import re
from sqlalchemy import select, delete, or_, func
from .models import QueryHistory, QueryResult, Paper, PaperAnalysis, Recommendation, utcnow
from paper_research_agent.analysis.models import PaperAnalysis as AnalysisModel, Recommendations


class Repository:
    def __init__(self, session):
        self.session = session

    def create_query(self, **values):
        row = QueryHistory(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def get_query_by_id(self, query_id):
        return self.session.get(QueryHistory, query_id)

    def update_query_status(self, query_id, status, error_message=None):
        row = self.get_query_by_id(query_id)
        if row is None:
            raise ValueError('Query does not exist')
        row.status, row.error_message, row.updated_at = status, error_message, utcnow()
        if status not in {'pending', 'running'}:
            row.completed_at = utcnow()
        self.session.flush()

    def history_filters(self, query_type=None, search=''):
        filters = []
        if query_type:
            filters.append(QueryHistory.query_type == query_type)
        term = search.strip()
        if term:
            # SQLite JSON extraction decodes Unicode titles before comparison.
            source_titles = select(PaperAnalysis.id).join(Paper, Paper.id == PaperAnalysis.paper_id).where(
                PaperAnalysis.query_id == QueryHistory.id,
                or_(Paper.title.contains(term, autoescape=True),
                    PaperAnalysis.analysis_json['title'].as_string().contains(term, autoescape=True))).correlate(QueryHistory).exists()
            candidates = []
            for path in ('$.data.papers', '$.data.recommendations.papers'):
                items = func.json_each(QueryResult.result_json, path).table_valued('value', joins_implicitly=True)
                candidates.append(select(QueryResult.id).select_from(QueryResult, items).where(
                    QueryResult.query_id == QueryHistory.id,
                    func.json_extract(items.c.value, '$.title').contains(term, autoescape=True)
                ).correlate(QueryHistory).exists())
            filters.append(or_(QueryHistory.query_text.contains(term, autoescape=True), source_titles, *candidates))
        return filters

    def count_query_history(self, query_type=None, search=''):
        return self.session.scalar(select(func.count(QueryHistory.id)).where(*self.history_filters(query_type, search)))

    def list_query_history(self, query_type=None, page=0, page_size=20, search=''):
        if page < 0 or not 1 <= page_size <= 100:
            raise ValueError('Invalid pagination')
        statement = select(QueryHistory).where(*self.history_filters(query_type, search))
        rows = list(self.session.scalars(statement.order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc())
                                        .offset(page * page_size).limit(page_size)))
        # Fetch only title columns, not every full report in the list.
        titles = {}
        if rows:
            for query_id, title, fallback in self.session.execute(select(PaperAnalysis.query_id,
                PaperAnalysis.analysis_json['title'].as_string(), Paper.title).join(Paper, Paper.id == PaperAnalysis.paper_id)
                .where(PaperAnalysis.query_id.in_([row.id for row in rows])).order_by(PaperAnalysis.id)):
                titles[query_id] = title if title and title != 'Not specified' else fallback
        for row in rows:
            row.display_title = titles.get(row.id)
        # Failed/running analysis can still refer to metadata saved by a search.
        arxiv_ids = {re.sub(r'v\d+$','',row.parameters_json.get('arxiv_id') or '') for row in rows}
        hashes = {row.parameters_json.get('pdf_sha256') for row in rows if row.parameters_json.get('pdf_sha256')}
        metadata = self.session.execute(select(Paper.arxiv_id, Paper.content_hash, Paper.title).where(
            or_(Paper.arxiv_id.in_(arxiv_ids - {''}), Paper.content_hash.in_(hashes))))
        by_id, by_hash = {}, {}
        for ident, digest, title in metadata:
            if ident:
                by_id[ident] = title
            if digest:
                by_hash[digest] = title
        for row in rows:
            if not row.display_title or row.display_title == 'Not specified':
                ident = re.sub(r'v\d+$','',row.parameters_json.get('arxiv_id') or '')
                row.display_title = by_id.get(ident) or by_hash.get(row.parameters_json.get('pdf_sha256'))
        return rows

    def get_query_result(self, query_id):
        row = self.session.scalar(select(QueryResult).where(QueryResult.query_id == query_id))
        return row.result_json if row else None

    def delete_query(self, query_id):
        self.session.execute(delete(QueryHistory).where(QueryHistory.id == query_id))

    def paper(self, data, content_hash=None):
        # arXiv versions identify the same paper; never merge by similar titles.
        ident = re.sub(r'v\d+$', '', data.get('arxiv_id') or '') or None
        row = None
        if ident:
            row = self.session.scalar(select(Paper).where(Paper.arxiv_id == ident))
        elif content_hash:
            row = self.session.scalar(select(Paper).where(Paper.content_hash == content_hash))
        if row is None:
            row = Paper(arxiv_id=ident, content_hash=content_hash, title=data.get('title', 'Not specified'),
                        authors_json=data.get('authors', []), abstract=data.get('abstract', ''),
                        published_at=data.get('published'), pdf_url=data.get('pdf_url'))
            self.session.add(row)
            self.session.flush()
        return row

    def save_search_results(self, papers):
        return [self.paper(paper) for paper in papers]

    def save_analysis(self, query_id, data, source, model_name, prompt_version):
        report = AnalysisModel.model_validate(data)
        paper = self.paper({'title': report.title, 'arxiv_id': source.get('arxiv_id')}, source.get('pdf_sha256'))
        if not paper.arxiv_id and report.title != 'Not specified':
            paper.title = report.title
        self.session.add(PaperAnalysis(query_id=query_id, paper_id=paper.id,
            analysis_json=report.model_dump(mode='json'), model_name=model_name, prompt_version=prompt_version))
        return paper

    def save_recommendations(self, query_id, data, source_paper):
        result = Recommendations.model_validate(data)
        for rank, item in enumerate(result.papers, 1):
            paper = self.paper(item.model_dump(mode='json'))
            self.session.add(Recommendation(query_id=query_id, source_paper_id=source_paper.id,
                recommended_paper_id=paper.id, rank=rank, reason=item.reason, similarity_score=item.score))

    def save_result(self, query_id, result, result_type):
        self.session.add(QueryResult(query_id=query_id, result_json=result, result_type=result_type))
