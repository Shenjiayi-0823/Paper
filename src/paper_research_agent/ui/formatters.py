"""Data conversion and Markdown export; no fabricated facts or scores."""

from urllib.parse import urlsplit
from paper_research_agent.analysis.models import PaperAnalysis, Recommendations, CLAIM_FIELDS

LABELS = dict(zip(CLAIM_FIELDS,['Research Problem','Background','Methodology','Contributions','Experiments','Results','Limitations']))
PROVENANCE = {'author_stated':'作者陈述','inference':'模型推断','not_specified':'未说明'}


def safe_link(value):
    if not isinstance(value,str):
        return None
    parts = urlsplit(value)
    if parts.scheme in {'http','https'} and parts.hostname in {'arxiv.org','www.arxiv.org','export.arxiv.org'} and not parts.username and not parts.password:
        return value
    return None


def paper_view(data):
    return {'title':str(data.get('title','Not specified')),'authors':', '.join(data.get('authors',[])),
        'published':str(data.get('published','Not specified'))[:10],'arxiv_id':str(data.get('arxiv_id','')),
        'abstract':str(data.get('abstract','')),'pdf_url':safe_link(data.get('pdf_url'))}


def report_view(data):
    report = PaperAnalysis.model_validate(data)
    return {'report':report,'fields':[(LABELS[name],getattr(report,name)) for name in CLAIM_FIELDS],
        'evidence':{e.id:e for e in report.evidence}}


def recommendation_view(data):
    result = Recommendations.model_validate(data)
    return result, [{**paper_view(p.model_dump()),'score':p.score,'reason':p.reason,'connection':p.connection,
        'differences':p.differences,'evidence_basis':p.evidence_basis} for p in result.papers]


def markdown_report(data):
    view = report_view(data)
    report = view['report']
    lines = ['# '+report.title,'',f'PDF pages: {report.total_pages}',f'Coverage complete: {report.complete}','']
    for warning in report.warnings:
        lines.extend(['Warning: '+warning,''])
    for label,claims in view['fields']:
        lines.extend(['## '+label,''])
        for claim in claims:
            lines.append(f'- [{PROVENANCE[claim.provenance]}] {claim.text} (evidence: {", ".join(claim.evidence_ids) or "none"})')
        lines.append('')
    lines.extend(['## Keywords','',', '.join(report.keywords),'','## Evidence',''])
    for e in report.evidence:
        lines.extend([f'### {e.id} — page {e.page_number}','',e.quote,''])
    return '\n'.join(lines)
