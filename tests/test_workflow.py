"""Research workflow regression tests: temporary databases, no paid/network calls."""
from dataclasses import asdict
from types import SimpleNamespace
import sys
import pytest
import pymupdf
from sqlalchemy import create_engine, select, func
from streamlit.testing.v1 import AppTest

from paper_research_agent.config import Settings, PROJECT_ROOT
from paper_research_agent.database.service import HistoryService
from paper_research_agent.database.library import LibraryService
from paper_research_agent.database.models import Base, LibraryEntry, QueryHistory, Paper
from paper_research_agent.database.repository import Repository
from paper_research_agent.ui.state import initialize
from paper_research_agent.ui.workflow import select_paper, source_available, open_query_paper
from paper_research_agent.ui.reader_page import render_pdf_page, pdf_address, jump_to_page
from paper_research_agent.ui.backend import TaskOutcome
from test_analysis import paper, analyze
from test_pdf import make_pdf


@pytest.fixture
def history(tmp_path):
    result = HistoryService(Settings(database_path=tmp_path / 'history.db', openai_api_key='mock-only'))
    yield result
    result.database.close()


@pytest.fixture
def state():
    result = initialize({})
    yield result
    result['uploads'].cleanup()


def test_additive_migration_preserves_old_history(tmp_path):
    path = tmp_path / 'legacy.db'
    engine = create_engine('sqlite:///' + str(path))
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != 'library_entry'])
    from sqlalchemy.orm import Session
    with Session(engine) as session, session.begin():
        session.add(QueryHistory(session_id='old', query_type='search', query_text='preserve me',
            parameters_json={}, cache_key='old', status='failed'))
    engine.dispose()
    service = HistoryService(Settings(database_path=path))
    assert service.list_query_history()[0].query_text == 'preserve me'
    with service.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(LibraryEntry)) == 0
    service.database.close()


def test_favorites_reading_filters_and_persistence(history):
    library = LibraryService(history)
    a = library.ensure_paper(paper('1706.00001', 'Energy scheduling'))
    b = library.ensure_paper(paper('1706.00002', 'Different paper'))
    library.favorite(a)
    library.favorite(a)
    library.favorite(b)
    library.set_reading_status(a, 'reading')
    assert [row['paper_id'] for row in library.list_papers('Energy', 'reading')] == [a]
    assert len(library.list_papers(page=1, page_size=1)) == 1
    other = HistoryService(history.settings)
    assert LibraryService(other).get_entry(a).reading_status == 'reading'
    other.database.close()
    library.favorite(a, False)
    assert library.get_paper(a) and library.get_entry(a) is None
    with pytest.raises(ValueError):
        library.set_reading_status(b, 'invalid')


def saved_report(history, state, complete=True, pages=1):
    data = make_pdf()
    if pages == 2:
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            doc.new_page().insert_text((50, 50), 'We use scheduling.')
            data = doc.tobytes()
    record = state['uploads'].save('paper.pdf', data, history.settings)
    report = analyze().model_copy(update={'document_id': record.relative_path, 'complete': complete,
        'total_pages': pages, 'analyzed_pages': list(range(1, pages + 1))})
    if pages == 2:
        report = report.model_copy(update={'evidence': [e.model_copy(update={'page_number': 2}) for e in report.evidence]})
    with history.database.transaction() as session:
        repo = Repository(session)
        row = repo.create_query(session_id='s', query_type='analysis', query_text='paper',
            parameters_json={'source_type': 'local', 'file_path': record.relative_path, 'pdf_sha256': record.digest, 'language': '中文'},
            cache_key='saved', status='success' if complete else 'partial')
        repo.save_analysis(row.id, report.model_dump(), {'pdf_sha256': record.digest}, 'old-model', 'old-prompt')
        repo.save_result(row.id, asdict(TaskOutcome(success=True, data={'analysis': report.model_dump()})), 'analysis')
        ident = row.id
    return ident, record, report


def test_context_selection_reuses_history_without_task(history, state):
    ident, record, report = saved_report(history, state)
    current = select_paper(state, history, {'title': 'Uploaded'}, record.digest,
        {'source_type': 'local', 'file_path': record.relative_path, 'language': '中文'})
    assert current['analysis_query_id'] == ident
    assert state['analyses'][current['source_key']] == report.model_dump()
    assert state['job'] is None and len(history.list_query_history()) == 1
    state['page'] = 'Related Research'
    assert source_available(state) and state['current_paper'] is current


def test_history_context_survives_file_cleanup_and_reupload(history, state):
    ident, record, report = saved_report(history, state)
    original = (state['uploads'].base / record.relative_path).read_bytes()
    state['uploads'].cleanup()
    current = open_query_paper(state, history, ident)
    assert not source_available(state)
    assert state['analyses'][current['source_key']]['evidence']
    new = state['uploads'].save('renamed.pdf', original, history.settings)
    assert source_available(state) and current['args']['file_path'] == new.relative_path


def test_library_favorite_survives_history_deletion(history, state):
    ident, record, report = saved_report(history, state)
    current = open_query_paper(state, history, ident)
    library = LibraryService(history)
    library.favorite(current['paper_id'])
    history.delete_query(ident)
    assert library.get_entry(current['paper_id'])
    assert library.get_paper(current['paper_id'])
    assert library.latest_analysis(current['paper_id']) is None


def test_local_page_preview_and_bounds(history, state):
    doc = pymupdf.open()
    for text in ('PAGE ONE', 'PAGE TWO'):
        doc.new_page().insert_text((50, 50), text)
    data = doc.tobytes()
    doc.close()
    upload = state['uploads'].save('two.pdf', data, history.settings)
    first = render_pdf_page(state['uploads'], upload.relative_path, 1)
    second = render_pdf_page(state['uploads'], upload.relative_path, 2)
    assert first.startswith(b'\x89PNG') and second != first
    jump_to_page(state, 'local:' + upload.digest, 2)
    assert state['reader_pages']['local:' + upload.digest] == 2
    with pytest.raises(ValueError):
        render_pdf_page(state['uploads'], upload.relative_path, 3)
    with pytest.raises(ValueError):
        render_pdf_page(state['uploads'], '../outside.pdf', 1)


@pytest.mark.parametrize('ident', ['1706.03762v1', 'hep-th/9901001', 'math.GT/0309136'])
def test_official_pdf_page_links(ident):
    assert pdf_address(ident, 3) == f'https://arxiv.org/pdf/{ident}#page=3'


@pytest.mark.parametrize('ident', ['https://evil.example/x', '../file', '1706.03762?redirect=evil'])
def test_reject_arbitrary_preview_urls(ident):
    with pytest.raises(ValueError):
        pdf_address(ident)


def app_setup(monkeypatch, history):
    import paper_research_agent.ui.app as app
    calls = []
    class FakeBackend:
        def __init__(self, *args):
            pass
        def run(self, operation, args, progress=None, analysis=None):
            calls.append(operation)
            return TaskOutcome(success=True, data={'query': args.get('query', ''), 'papers': [paper('1706.00001')]})
    monkeypatch.setattr(app, 'HistoryService', lambda settings: history)
    monkeypatch.setattr(app, 'load_settings', lambda: history.settings)
    monkeypatch.setattr(app, 'WebBackend', FakeBackend)
    return AppTest.from_file(str(PROJECT_ROOT / 'app.py'), default_timeout=10).run(), calls


def test_all_pages_and_diagnostics_isolation(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    for name in ['Dashboard', 'Discover', 'Paper Reader', 'Related Research', 'Library', 'History', 'Settings']:
        at.button(key='nav_' + name).click().run()
        assert not at.exception
        keys = [item.key for item in at.button]
        assert ('settings_check' in keys) == (name == 'Settings')
    assert calls == []
    at.session_state['pra']['uploads'].cleanup()


def test_discover_select_reader_favorite_library_without_llm(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    state = at.session_state['pra']
    state['search'] = [paper('1706.00001')]
    at.button(key='nav_' + 'Discover').click().run()
    at.button(key='open_1706.00001').click().run()
    assert not at.exception and state['page'] == 'Paper Reader'
    current = state['current_paper']
    at.button(key='reader_favorite_' + str(current['paper_id'])).click().run()
    assert not at.exception
    at.button(key='nav_' + 'Library').click().run()
    assert len(LibraryService(history).list_papers()) == 1
    at.button(key='library_open_' + str(current['paper_id'])).click().run()
    assert not at.exception and state['current_paper']['paper_id'] == current['paper_id']
    at.button(key='reader_related').click().run()
    assert not at.exception and state['page'] == 'Related Research'
    assert calls == [] and state['job'] is None
    state['uploads'].cleanup()


def test_reader_history_evidence_jump_no_api(monkeypatch, history, state):
    ident, record, report = saved_report(history, state, pages=2)
    at, calls = app_setup(monkeypatch, history)
    ui_state = at.session_state['pra']
    # Transfer only this test's session-owned file store, not an arbitrary path.
    ui_state['uploads'].cleanup()
    ui_state['uploads'] = state['uploads']
    open_query_paper(ui_state, history, ident)
    at.button(key='nav_' + 'Paper Reader').click().run()
    assert not at.exception
    key = 'reader_report_' + ui_state['current_paper']['source_key']
    at.button(key=key+'_jump').click().run()
    assert not at.exception and ui_state['reader_pages'][ui_state['current_paper']['source_key']] == 2
    at.checkbox(key='reader_single_column').set_value(True).run()
    assert not at.exception and calls == [] and len(history.list_query_history()) == 1


def test_settings_force_option_survives_navigation(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    at.button(key='nav_' + 'Settings').click().run()
    at.checkbox(key='force_history_cache').set_value(True).run()
    at.button(key='nav_' + 'Discover').click().run()
    at.run()
    assert at.session_state['pra']['force_execution'] is True
    assert not at.exception and calls == []
    at.session_state['pra']['uploads'].cleanup()


def test_date_filter_uses_real_query_bounds():
    from datetime import datetime, timezone
    from paper_research_agent.ui.search_page import dated_query
    now = datetime(2024, 2, 29, tzinfo=timezone.utc)
    assert dated_query(' energy ', 0, now) == 'energy'
    assert dated_query('energy', 1, now) == '(energy) AND submittedDate:[202302280000 TO 202402292359]'


def test_discover_direct_favorite_and_actual_context_counts(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    state = at.session_state['pra']
    state['search'] = [paper('1706.00001')]
    at.button(key='nav_Discover').click().run()
    assert not at.exception
    at.button(key='discover_save_1706.00001').click().run()
    assert not at.exception and LibraryService(history).overview()['library'] == 1
    metrics = {item.label: item.value for item in at.metric}
    assert metrics['已收藏论文'] == '1' and metrics['已完成分析'] == '0'
    assert calls == [] and state['current_paper'] is None
    at.button(key='discover_save_1706.00001').click().run()
    assert LibraryService(history).overview()['library'] == 0
    state['uploads'].cleanup()


def test_compact_navigation_keeps_context_and_never_calls_backend(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    state = at.session_state['pra']
    select_paper(state, history, paper('1706.00001'))
    ident = state['current_paper']['paper_id']
    for name in ['Discover','Paper Reader','Related Research','Library','History','Settings','Dashboard']:
        at.button(key='compact_nav_' + name).click().run()
        assert not at.exception and state['page'] == name
        assert state['current_paper']['paper_id'] == ident
    assert calls == []
    state['uploads'].cleanup()
