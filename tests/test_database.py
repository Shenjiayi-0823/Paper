"""Temporary SQLite only; mock business tasks never call a paid API."""
from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace
import copy

import pytest
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError

from paper_research_agent.config import Settings
from paper_research_agent.database.connection import Database
from paper_research_agent.database.models import QueryHistory, QueryResult, Paper, PaperAnalysis, Recommendation, utcnow
from paper_research_agent.database.repository import Repository
from paper_research_agent.database.service import HistoryService, parameters, pdf_hash, sanitize, valid_snapshot, PersistentBackend
from paper_research_agent.ui.backend import TaskOutcome
from paper_research_agent.ui.uploads import UploadStore
from paper_research_agent.ui.state import initialize, start_job, poll_job
from test_analysis import analyze, paper, topic, ranked
from test_pdf import make_pdf


@pytest.fixture
def history(tmp_path):
    service = HistoryService(Settings(database_path=tmp_path / 'db' / 'history.db', openai_api_key='test-secret-value'))
    yield service
    service.database.close()


@pytest.fixture
def backend(tmp_path):
    store = UploadStore(root=tmp_path / 'uploads')
    store.save('paper.pdf', make_pdf(), Settings())
    class FakeBackend:
        uploads = store
        calls = 0
        outcome = TaskOutcome(success=True, data={'papers': [{**paper('1706.00001'),
            'published': '2017-06-01T00:00:00Z', 'updated': '2017-06-01T00:00:00Z'}]})
        def run(self, *args):
            self.calls += 1
            return copy.deepcopy(self.outcome)
    yield FakeBackend()
    store.cleanup()


def create(repo, **kwargs):
    return repo.create_query(session_id='session', query_type='search', query_text='energy',
                             parameters_json={}, cache_key='key', **kwargs)


def local_args(backend):
    record = next(iter(backend.uploads.files.values()))
    return {'source_type': 'local', 'file_path': record.relative_path, 'language': '中文'}


def test_initialization_pragmas(history):
    with history.database.engine.connect() as connection:
        assert connection.scalar(text('PRAGMA foreign_keys')) == 1
        assert connection.scalar(text('PRAGMA busy_timeout')) == 10000
        assert connection.scalar(text('PRAGMA journal_mode')) == 'wal'


def test_create_update_and_utc(history):
    with history.database.transaction() as session:
        repo = Repository(session)
        ident = create(repo).id
        repo.update_query_status(ident, 'running')
        repo.update_query_status(ident, 'failed', 'network failed')
    row = history.get_query_by_id(ident)
    assert row.status == 'failed' and row.error_message == 'network failed'
    assert row.completed_at and row.created_at <= row.completed_at


def test_sort_filter_pagination(history):
    with history.database.transaction() as session:
        repo = Repository(session)
        first = create(repo).id
        second = create(repo).id
        third = repo.create_query(session_id='s', query_type='analysis', query_text='pdf', parameters_json={}, cache_key='x').id
    assert [row.id for row in history.list_query_history()] == [third, second, first]
    assert [row.id for row in history.list_query_history('search', 1, 1)] == [first]
    with pytest.raises(ValueError):
        history.list_query_history(page=-1)


def test_search_snapshot_survives_reopen(history, backend):
    result = history.execute(backend, 'search', {'query': 'energy'})
    ident = result.data['history_query_id']
    other = HistoryService(history.settings)
    assert other.get_query_result(ident)['data']['papers'][0]['title'] == paper('1706.00001')['title']
    other.database.close()


def test_analysis_round_trip_and_hash_identity(history, backend):
    args = local_args(backend)
    report = analyze().model_copy(update={'document_id': args['file_path']})
    backend.outcome = TaskOutcome(success=True, data={'analysis': report.model_dump()})
    result = history.execute(backend, 'analyze_paper', args)
    snapshot = history.get_query_result(result.data['history_query_id'])
    from paper_research_agent.analysis.models import PaperAnalysis as Report
    assert Report.model_validate(snapshot['data']['analysis']) == report
    with history.database.transaction() as session:
        row = session.scalar(select(PaperAnalysis))
        assert row.analysis_json['evidence'][0]['page_number'] == 1
        assert session.scalar(select(Paper)).content_hash == next(iter(backend.uploads.files))


def test_recommendation_and_candidate_snapshot(history, backend):
    args = local_args(backend)
    report = analyze().model_copy(update={'document_id': args['file_path']}).model_dump()
    recommendations = {'source_document_id': args['file_path'], 'theme': topic(), 'queries': ['all:"energy"'],
        'papers': [{**ranked('1706.00001'), **paper('1706.00001')}], 'warnings': []}
    backend.outcome = TaskOutcome(success=True, data={'analysis': report, 'recommendations': recommendations,
        'candidate_searches': [{'parameters': {'query': 'energy'}, 'result': {'papers': [paper('1706.00001')]}}]})
    result = history.execute(backend, 'recommend_related', args)
    saved = history.get_query_result(result.data['history_query_id'])
    assert saved['data']['recommendations'] == recommendations
    assert saved['data']['candidate_searches']
    with history.database.transaction() as session:
        row = session.scalar(select(Recommendation))
        assert row.rank == 1 and row.similarity_score == .8 and row.reason == 'method similarity'


def test_delete_cascades_but_preserves_shared_papers(history, backend):
    a = history.execute(backend, 'search', {'query': 'a'}).data['history_query_id']
    b = history.execute(backend, 'search', {'query': 'b'}).data['history_query_id']
    history.delete_query(a)
    assert history.get_query_result(a) is None and history.get_query_result(b)
    with history.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Paper)) == 1


def test_foreign_key_and_transaction_rollback(history):
    with pytest.raises(IntegrityError):
        with history.database.transaction() as session:
            create(Repository(session))
            session.add(QueryResult(query_id=999999, result_json={}, result_type='search'))
    assert history.list_query_history() == []


def test_invalid_status_rollback(history):
    with pytest.raises(IntegrityError):
        with history.database.transaction() as session:
            create(Repository(session), status='invented')
    assert not history.list_query_history()


def test_deduplicate_ids_not_titles(history):
    with history.database.transaction() as session:
        repo = Repository(session)
        a = repo.paper(paper('1706.00001v1'))
        b = repo.paper(paper('1706.00001v2'))
        c = repo.paper({**paper('1706.00002'), 'title': a.title})
        assert a.id == b.id and a.id != c.id


def test_cache_hit_normalization_and_force(history, backend):
    first = history.execute(backend, 'search', {'query': 'energy'})
    second = history.execute(backend, 'search', {'query': '  energy  ', 'max_results': 5, 'sort_by': 'submittedDate'})
    assert backend.calls == 1
    assert second.data['cache']['source_query_id'] == first.data['history_query_id']
    assert second.usage == {} and second.trace[0]['name'] == 'history_cache'
    history.execute(backend, 'search', {'query': 'energy'}, force=True)
    assert backend.calls == 2


def test_search_ttl_expiry(history, backend):
    history.settings = history.settings.model_copy(update={'search_cache_seconds': 0})
    history.execute(backend, 'search', {'query': 'energy'})
    history.execute(backend, 'search', {'query': 'energy'})
    assert backend.calls == 2


@pytest.mark.parametrize('field,value', [('openai_model', 'different'), ('openai_base_url', 'https://other.example/v1')])
def test_model_provider_invalidate(history, backend, field, value):
    first = parameters('analyze_paper', local_args(backend), history.settings, backend.uploads)[1]
    changed = history.settings.model_copy(update={field: value})
    assert parameters('analyze_paper', local_args(backend), changed, backend.uploads)[1] != first


def test_prompt_version_invalidate(history, backend, monkeypatch):
    import paper_research_agent.database.service as module
    first = parameters('analyze_paper', local_args(backend), history.settings, backend.uploads)[1]
    monkeypatch.setattr(module, 'prompt_version', lambda: 'changed')
    assert parameters('analyze_paper', local_args(backend), history.settings, backend.uploads)[1] != first


def test_hash_identical_and_cross_session_cache(history, backend, tmp_path):
    args = local_args(backend)
    record = next(iter(backend.uploads.files.values()))
    assert pdf_hash(backend.uploads.base / record.relative_path) == record.digest
    backend.outcome = TaskOutcome(success=True, data={'analysis': analyze().model_copy(update={'document_id': args['file_path']}).model_dump()})
    history.execute(backend, 'analyze_paper', args)
    other_store = UploadStore(root=tmp_path / 'other')
    other_record = other_store.save('renamed.pdf', (backend.uploads.base / record.relative_path).read_bytes(), history.settings)
    backend.uploads = other_store
    result = history.execute(backend, 'analyze_paper', local_args(backend))
    assert backend.calls == 1 and result.data['analysis']['document_id'] == other_record.relative_path
    other_store.cleanup()


@pytest.mark.parametrize('outcome,status', [
    (TaskOutcome(error={'code': 'api_error', 'message': 'failed'}), 'failed'),
    (TaskOutcome(error={'code': 'task_timeout', 'message': 'timeout'}), 'timeout'),
    (TaskOutcome(success=True, data={'analysis': analyze().model_copy(update={'complete': False}).model_dump()}), 'partial'),
])
def test_failed_partial_timeout_not_cached(history, backend, outcome, status):
    backend.outcome = outcome
    operation = 'analyze_paper' if outcome.data else 'search'
    args = local_args(backend) if outcome.data else {'query': 'energy'}
    first = history.execute(backend, operation, args)
    assert history.get_query_by_id(first.data['history_query_id']).status == status
    history.execute(backend, operation, args)
    assert backend.calls == 2


def test_corrupt_cache_is_not_reused(history, backend):
    first = history.execute(backend, 'search', {'query': 'energy'})
    with history.database.transaction() as session:
        row = session.scalar(select(QueryResult))
        row.result_json = {'success': True, 'data': {'papers': [{}]}}
    history.execute(backend, 'search', {'query': 'energy'})
    assert backend.calls == 2


def test_interrupted_recovery_and_active_task_protection(history):
    with history.database.transaction() as session:
        repo = Repository(session)
        old = create(repo, status='running')
        old.updated_at = utcnow() - timedelta(days=1)
        old_id = old.id
        current = create(repo, status='running').id
    history.recover_interrupted()
    assert history.get_query_by_id(old_id).status == 'failed'
    assert history.get_query_result(old_id)['error']['code'] == 'interrupted'
    assert history.get_query_by_id(current).status == 'running'
    with pytest.raises(ValueError):
        history.delete_query(current)


def test_save_error_preserves_business_data(history, backend, monkeypatch):
    def fail(*args):
        raise RuntimeError('private details')
    monkeypatch.setattr(Repository, 'save_search_results', fail)
    result = history.execute(backend, 'search', {'query': 'energy'})
    assert not result.success and result.error['code'] == 'database_error' and result.data['papers']
    assert history.list_query_history()[0].status == 'partial'
    assert 'private details' not in str(asdict(result))


def test_database_read_error_does_not_execute(history, backend, monkeypatch):
    monkeypatch.setattr(history, 'cached', lambda *args: (_ for _ in ()).throw(RuntimeError()))
    result = history.execute(backend, 'search', {'query': 'energy'})
    assert result.error['code'] == 'database_error' and backend.calls == 0


def test_secret_redaction(history, backend):
    backend.outcome.trace = [{'name': 'tool', 'authorization': 'Bearer dangerous', 'error': {'message': 'test-secret-value'}}]
    result = history.execute(backend, 'search', {'query': 'test-secret-value'})
    row = history.get_query_by_id(result.data['history_query_id'])
    snapshot = history.get_query_result(row.id)
    assert 'test-secret-value' not in str(snapshot) and 'authorization' not in str(snapshot)
    assert 'test-secret-value' not in str(row.parameters_json)
    assert 'test-secret-value' not in row.query_text


def test_recommendation_reuses_persisted_analysis(history, backend):
    args = local_args(backend)
    backend.outcome = TaskOutcome(success=True, data={'analysis': analyze().model_copy(update={'document_id': args['file_path']}).model_dump()})
    history.execute(backend, 'analyze_paper', args)
    captured = []
    def run(operation, args, progress, analysis):
        captured.append(analysis)
        return TaskOutcome(error={'code': 'api_error', 'message': 'Mock failure'}, data={'analysis': analysis})
    backend.run = run
    result = history.execute(backend, 'recommend_related', args)
    assert captured[0]['document_id'] == args['file_path'] and result.data['analysis']


def test_force_does_not_seed_old_analysis(history, backend):
    captured = []
    def run(operation, args, progress, analysis):
        captured.append(analysis)
        return TaskOutcome(error={'code': 'api_error', 'message': 'Mock'})
    backend.run = run
    PersistentBackend(backend, history, force=True).run('recommend_related', local_args(backend), analysis=analyze().model_dump())
    assert captured == [None]


def test_database_initialization_error(tmp_path):
    path = tmp_path / 'broken.db'
    path.write_bytes(b'not a SQLite database')
    with pytest.raises(Exception):
        HistoryService(Settings(database_path=path))


def test_history_page_view_and_delete(tmp_path, monkeypatch):
    import paper_research_agent.ui.app as app
    from streamlit.testing.v1 import AppTest
    from paper_research_agent.config import PROJECT_ROOT
    service = HistoryService(Settings(database_path=tmp_path / 'history.db'))
    with service.database.transaction() as session:
        repo = Repository(session)
        row = create(repo, status='success')
        ident = row.id
        repo.save_result(ident, asdict(TaskOutcome(success=True, data={'papers': [paper('1706.00001')]})), 'search')
    monkeypatch.setattr(app, 'HistoryService', lambda settings: service)
    at = AppTest.from_file(str(PROJECT_ROOT / 'app.py'), default_timeout=10).run()
    assert not at.exception
    at.button(key='nav_' + 'History').click().run()
    at.button(key=f'history_view_{ident}').click().run()
    assert not at.exception and at.session_state['pra']['history_selected'] == ident
    assert any('Related Paper' in item.value for item in at.text)
    at.run()
    assert len(service.list_query_history()) == 1
    at.button(key=f'history_delete_{ident}').click().run()
    assert not at.exception and service.list_query_history() == []
    at.session_state['pra']['uploads'].cleanup()
    service.database.close()


def test_rerun_does_not_write_twice(history, backend):
    state = initialize({})
    wrapped = PersistentBackend(backend, history)
    runner = lambda progress: wrapped.run('search', {'query': 'energy'}, progress)
    assert start_job(state, 'key', 'search', None, runner)
    state['job'].future.result(timeout=5)
    assert poll_job(state)
    assert not start_job(state, 'key', 'search', None, runner)
    assert not poll_job(state)
    assert len(history.list_query_history()) == 1 and backend.calls == 1
    state['uploads'].cleanup()
