"""Persistence boundary around existing Web tasks, with explicitly marked cache hits."""
from dataclasses import asdict
from datetime import timedelta, timezone
import hashlib
import json
import re
from sqlalchemy import select
from .connection import Database
from .models import QueryHistory, utcnow
from .repository import Repository
from paper_research_agent.config import PROJECT_ROOT
from paper_research_agent.ui.backend import TaskOutcome, task_status
from paper_research_agent.analysis.models import PaperAnalysis, Recommendations
from paper_research_agent.mcp_server.tools.models import Paper as SearchPaper

OPERATIONS = {'search': 'search', 'analyze_paper': 'analysis', 'recommend_related': 'recommendation'}


def prompt_version():
    # Include schema/analysis code as well as prompts: updates invalidate old results.
    digest = hashlib.sha256()
    for path in sorted((PROJECT_ROOT / 'src/paper_research_agent/analysis').glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def pdf_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sanitize(value, secret=None):
    if isinstance(value, dict):
        return {key: sanitize(item, secret) for key, item in value.items()
                if not any(word in key.lower() for word in ('api_key', 'authorization', 'password', 'secret'))}
    if isinstance(value, list):
        return [sanitize(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)Bearer\s+\S+|\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', value)
    return value


def parameters(operation, args, settings, uploads):
    params = dict(args)
    if operation == 'search':
        # Keep quoted expressions/case intact: only trim surrounding whitespace.
        params['query'] = params.get('query', '').strip()
        params.setdefault('max_results', 5)
        params.setdefault('sort_by', 'submittedDate')
    elif params.get('source_type') == 'local':
        if not uploads.owns(params.get('file_path')):
            raise ValueError('Upload not owned')
        params['pdf_sha256'] = pdf_hash(uploads.base / params['file_path'])
    if operation != 'search':
        params.setdefault('language', '中文')
    identity = {key: value for key, value in params.items() if key != 'file_path'}
    identity.update(operation=operation, model=settings.openai_model, provider=settings.openai_base_url,
                    prompt_version=prompt_version())
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return params, key


def valid_snapshot(snapshot, operation):
    try:
        outcome = TaskOutcome(**snapshot)
        if task_status(outcome) != 'success':
            return False
        if operation == 'search':
            for item in outcome.data['papers']:
                SearchPaper.model_validate(item)
        else:
            report = PaperAnalysis.model_validate(outcome.data['analysis'])
            if not report.complete:
                return False
            if operation == 'recommend_related':
                Recommendations.model_validate(outcome.data['recommendations'])
        return True
    except (ValueError, TypeError, KeyError):
        return False


class HistoryService:
    def __init__(self, settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.recover_interrupted()

    def recover_interrupted(self):
        # Do not mark another active Web session failed merely because a new one opens.
        cutoff = utcnow() - timedelta(seconds=self.settings.agent_task_timeout_seconds + 60)
        with self.database.transaction() as session:
            repo = Repository(session)
            rows = session.scalars(select(QueryHistory).where(QueryHistory.status.in_(['pending', 'running']),
                                                              QueryHistory.updated_at < cutoff))
            for row in rows:
                repo.update_query_status(row.id, 'failed', 'Interrupted task: no completion before its deadline.')
                repo.save_result(row.id, asdict(TaskOutcome(error={'code': 'interrupted',
                    'message': '任务中断且已超过恢复等待期限，请重新执行。'})), row.query_type)

    def list_query_history(self, query_type=None, page=0, page_size=20, search=''):
        self.recover_interrupted()
        with self.database.transaction() as session:
            return Repository(session).list_query_history(query_type, page, page_size, search)

    def count_query_history(self, query_type=None, search=''):
        with self.database.transaction() as session:
            return Repository(session).count_query_history(query_type, search)

    def get_query_by_id(self, query_id):
        with self.database.transaction() as session:
            return Repository(session).get_query_by_id(query_id)

    def get_query_result(self, query_id):
        with self.database.transaction() as session:
            return Repository(session).get_query_result(query_id)

    def delete_query(self, query_id):
        with self.database.transaction() as session:
            row = Repository(session).get_query_by_id(query_id)
            if row and row.status in {'pending', 'running'}:
                raise ValueError('Cannot delete an active task')
            Repository(session).delete_query(query_id)

    def cached(self, key, operation):
        with self.database.transaction() as session:
            rows = session.scalars(select(QueryHistory).where(QueryHistory.cache_key == key,
                QueryHistory.status == 'success').order_by(QueryHistory.id.desc()))
            for row in rows:
                completed = row.completed_at.replace(tzinfo=timezone.utc) if row.completed_at else row.created_at.replace(tzinfo=timezone.utc)
                if operation == 'search' and (utcnow() - completed).total_seconds() >= self.settings.search_cache_seconds:
                    continue
                snapshot = Repository(session).get_query_result(row.id)
                if snapshot and valid_snapshot(snapshot, operation):
                    return row.id, snapshot
        return None

    def execute(self, backend, operation, args, progress=None, analysis=None, force=False):
        if operation not in OPERATIONS:
            return backend.run(operation, args, progress, analysis)
        # A session report alone has no model/prompt provenance. Only a matching
        # complete history entry may seed a new persisted research task.
        analysis = None
        query_id = None
        secret = self.settings.openai_api_key.get_secret_value() if self.settings.openai_api_key else None
        try:
            params, key = parameters(operation, args, self.settings, backend.uploads)
            with self.database.transaction() as session:
                row = Repository(session).create_query(session_id=backend.uploads.session_id,
                    query_type=OPERATIONS[operation], query_text=sanitize(args.get('query') or args.get('arxiv_id') or args.get('file_path', ''), secret),
                    parameters_json=sanitize(params, secret), cache_key=key)
                query_id = row.id
            with self.database.transaction() as session:
                Repository(session).update_query_status(query_id, 'running')
            hit = None if force else self.cached(key, operation)
            if hit:
                original_id, snapshot = hit
                outcome = TaskOutcome(**snapshot)
                outcome.elapsed, outcome.usage, outcome.connected = 0, {}, False
                outcome.trace = [{'name': 'history_cache', 'success': True, 'error': None,
                                  'elapsed_seconds': 0, 'source_query_id': original_id}]
                outcome.data['cache'] = {'hit': True, 'source_query_id': original_id}
                # A local report's document ID belongs to its former upload path.
                # Rebind source identity only; preserve all scientific fields/citations.
                if args.get('source_type') == 'local':
                    new_id = args['file_path']
                    outcome.data['analysis']['document_id'] = new_id
                    if outcome.data.get('recommendations'):
                        outcome.data['recommendations']['source_document_id'] = new_id
                if progress:
                    progress('命中历史缓存，未调用 MCP 或 LLM')
            else:
                if operation == 'recommend_related' and analysis is None and not force:
                    _, analysis_key = parameters('analyze_paper', args, self.settings, backend.uploads)
                    saved_analysis = self.cached(analysis_key, 'analyze_paper')
                    if saved_analysis:
                        analysis = saved_analysis[1]['data']['analysis']
                        analysis['document_id'] = args.get('file_path') if args.get('source_type') == 'local' else args.get('arxiv_id')
                        if progress:
                            progress('复用历史中完整成功的源论文分析')
                try:
                    outcome = backend.run(operation, args, progress, analysis)
                except Exception:
                    outcome = TaskOutcome(error={'code': 'backend_error', 'message': '任务执行异常。'})
            outcome.data['history_query_id'] = query_id
            snapshot = sanitize(asdict(outcome), secret)
            # One atomic transaction for all result tables and final status.
            with self.database.transaction() as session:
                repo = Repository(session)
                repo.save_search_results(snapshot['data'].get('papers', []))
                source = None
                if snapshot['data'].get('analysis'):
                    source = repo.save_analysis(query_id, snapshot['data']['analysis'], params,
                                               self.settings.openai_model, prompt_version())
                if snapshot['data'].get('recommendations') and source:
                    repo.save_recommendations(query_id, snapshot['data']['recommendations'], source)
                repo.save_result(query_id, snapshot, OPERATIONS[operation])
                error = (snapshot.get('error') or {}).get('message')
                repo.update_query_status(query_id, task_status(outcome), error)
            return outcome
        except ValueError:
            error = {'code': 'persistence_validation', 'message': '输入或结果结构校验失败，未保存为成功记录。'}
        except Exception:
            error = {'code': 'database_error', 'message': '数据库读写失败；任务未标记为成功，请检查路径、权限和磁盘空间。'}
        # Preserve usable business results, but never pretend persistence succeeded.
        outcome = locals().get('outcome') or TaskOutcome()
        outcome.success, outcome.error = False, error
        if query_id is not None:
            try:
                with self.database.transaction() as session:
                    repo = Repository(session)
                    repo.update_query_status(query_id, task_status(outcome), error['message'])
                    repo.save_result(query_id, sanitize(asdict(outcome), secret), OPERATIONS[operation])
            except Exception:
                pass
        return outcome


class PersistentBackend:
    def __init__(self, backend, history, force=False):
        self.backend, self.history, self.force = backend, history, force

    def run(self, operation, args, progress=None, analysis=None):
        return self.history.execute(self.backend, operation, args, progress, None if self.force else analysis, self.force)
