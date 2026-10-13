"""Search and history interactions use temporary SQLite; no live API calls."""
from dataclasses import asdict
import pytest
from paper_research_agent.database.repository import Repository
from paper_research_agent.ui.backend import TaskOutcome
from test_workflow import history, state, app_setup, saved_report
from test_analysis import paper


def add_search(history, query, title):
    with history.database.transaction() as session:
        repo = Repository(session)
        row = repo.create_query(session_id='s', query_type='search', query_text=query,
            parameters_json={'query':query, 'max_results':5, 'sort_by':'relevance'}, cache_key=query, status='success')
        repo.save_result(row.id, asdict(TaskOutcome(success=True, data={'papers':[paper('1706.00001',title)]})), 'search')
        return row.id


def test_query_and_unicode_result_title_search(history):
    a = add_search(history,'data center energy','数据中心能源优化')
    b = add_search(history,'language models','Other title')
    assert [row.id for row in history.list_query_history(search='  data center  ')] == [a]
    assert [row.id for row in history.list_query_history(search='能源优化')] == [a]
    assert history.count_query_history(search='能源优化') == 1
    assert history.count_query_history(search='no match') == 0
    assert [row.id for row in history.list_query_history()] == [b,a]


def test_source_title_filter_and_pagination(history,state):
    ident,record,report = saved_report(history,state)
    add_search(history,'energy','Another paper')
    rows = history.list_query_history(query_type='analysis',search=report.title)
    assert [row.id for row in rows] == [ident] and rows[0].display_title == report.title
    assert history.count_query_history(query_type='search',search=report.title) == 0
    assert len(history.list_query_history(page=1,page_size=1)) == 1


def test_wildcards_are_literal_and_not_sql_injection(history):
    ident = add_search(history,'100%_efficiency','Example')
    add_search(history,'ordinary','Normal')
    assert [row.id for row in history.list_query_history(search='%_')] == [ident]
    assert history.list_query_history(search="' OR 1=1 --") == []


def test_recommended_title_search_without_source_analysis(history):
    with history.database.transaction() as session:
        repo = Repository(session)
        row = repo.create_query(session_id='s',query_type='recommendation',query_text='source',
            parameters_json={},cache_key='key',status='partial')
        ident = row.id
        repo.save_result(ident,asdict(TaskOutcome(data={'recommendations':{'papers':[paper('1706.00001','候选能源论文')]}})), 'recommendation')
    assert [row.id for row in history.list_query_history(search='候选能源')] == [ident]


def test_history_search_open_no_cost_then_explicit_rerun(monkeypatch,history):
    ident = add_search(history,'data center energy','Energy paper')
    add_search(history,'language models','Other paper')
    at,calls = app_setup(monkeypatch,history)
    at.button(key='nav_History').click().run()
    assert not at.exception and calls == []
    at.text_input(key='history_search').set_value('data center').run()
    assert not at.exception
    assert len([button for button in at.button if button.key.startswith('history_view_')]) == 1
    at.button(key=f'history_view_{ident}').click().run()
    at.run()
    assert not at.exception and calls == [] and len(history.list_query_history()) == 2
    at.button(key=f'history_rerun_{ident}').click().run()
    for _ in range(4):
        at.run()
        if at.session_state['pra']['job'] is None:
            break
    assert not at.exception and calls == ['search']
    assert len(history.list_query_history()) == 3
    at.session_state['pra']['uploads'].cleanup()


def test_filter_resets_pagination_and_opens_saved_report(monkeypatch,history,state):
    ident,record,report = saved_report(history,state)
    for n in range(21):
        add_search(history,f'query {n}','Search result')
    at,calls = app_setup(monkeypatch,history)
    at.button(key='nav_History').click().run()
    at.number_input(key='history_page').set_value(2).run()
    at.selectbox(key='history_type').set_value('analysis').run()
    assert at.number_input(key='history_page').value == 1
    at.button(key=f'history_view_{ident}').click().run()
    assert not at.exception and at.download_button and calls == []
    assert at.session_state['pra']['history_selected'] == ident
    at.button(key=f'history_delete_{ident}').click().run()
    assert not at.exception and history.get_query_by_id(ident) is None and calls == []
    at.session_state['pra']['uploads'].cleanup()


def test_detail_replaces_list_and_return_restores_filters(monkeypatch,history):
    for n in range(21):
        add_search(history, f'query {n}', 'Stored result')
    at,calls = app_setup(monkeypatch,history)
    at.button(key='nav_History').click().run()
    assert at.text_input(key='history_search').proto.autocomplete == 'off'
    at.text_input(key='history_search').set_value('query').run()
    at.number_input(key='history_page').set_value(2).run()
    record = next(button for button in at.button if button.key.startswith('history_view_'))
    record.click().run()
    assert not at.exception
    assert all(item.key != 'history_search' for item in at.text_input)
    assert any('Stored result' in item.value for item in at.text)
    assert calls == [] and history.count_query_history() == 21
    at.button(key='history_close_detail').click().run()
    assert not at.exception
    assert at.text_input(key='history_search').value == 'query'
    assert at.number_input(key='history_page').value == 2
    assert calls == []
    at.session_state['pra']['uploads'].cleanup()


def test_failed_history_opens_error_without_running_task(monkeypatch,history):
    with history.database.transaction() as session:
        repo=Repository(session)
        row=repo.create_query(session_id='s',query_type='search',query_text='failed request',
            parameters_json={'query':'failed request'},cache_key='failed',status='failed')
        ident=row.id
        repo.save_result(ident,asdict(TaskOutcome(error={'code':'api_error','message':'Stored failure message'})), 'search')
    at,calls=app_setup(monkeypatch,history)
    at.button(key='nav_History').click().run()
    at.button(key=f'history_view_{ident}').click().run()
    assert not at.exception and any('Stored failure message' in item.value for item in at.error)
    assert calls == []
    at.session_state['pra']['uploads'].cleanup()


def test_failed_task_uses_saved_paper_title_in_recent_tasks(history):
    from paper_research_agent.ui.recent_tasks import recent_label
    with history.database.transaction() as session:
        repo=Repository(session)
        repo.paper(paper('2506.02752v1','Actual source paper title'))
        row=repo.create_query(session_id='s',query_type='analysis',query_text='2506.02752v1',
            parameters_json={'source_type':'arxiv','arxiv_id':'2506.02752v1'}, cache_key='key',status='failed')
    row=history.list_query_history()[0]
    assert row.display_title == 'Actual source paper title'
    assert 'Actual source paper title' in recent_label(row)
    assert recent_label(row) == '分析：Actual source paper title · 失败'


def test_recent_task_opens_history_without_api(monkeypatch,history):
    ident=add_search(history,'MIP','Search result')
    at,calls=app_setup(monkeypatch,history)
    label=at.button(key=f'dashboard_history_{ident}').label
    assert 'MIP' in label and '成功' in label
    at.button(key=f'dashboard_history_{ident}').click().run()
    assert not at.exception and at.session_state['pra']['history_selected'] == ident
    assert calls == []
    at.session_state['pra']['uploads'].cleanup()
