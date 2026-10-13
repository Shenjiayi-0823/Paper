"""Theme and UI language changes never mutate reports or trigger paid requests."""
import copy
import pytest
from paper_research_agent.ui.i18n import translate
from paper_research_agent.ui.workspace import theme_css
from test_workflow import app_setup, history, state, saved_report
from paper_research_agent.ui.workflow import open_query_paper


@pytest.mark.parametrize('source,expected', [
    ('文献发现','Discover'), ('阅读状态','Reading status'), ('最近 5 年','Last 5 years'),
    ('定位 PDF 第 2 页','Go to PDF page 2'), ('论文分析 · success','Paper analysis · success'),
    ('关键词：energy','Keywords: energy'), ('item · 待读','item · To read'),
])
def test_translations(source, expected):
    assert translate(source, 'en') == expected
    assert translate(source, 'zh') == source


def test_source_text_is_not_translated():
    assert translate('Unrecognized original scientific text', 'en') == 'Unrecognized original scientific text'


def test_fixed_light_palette():
    assert '--pra-bg:#F8FAFC' in theme_css()
    assert '--pra-text:#18212F' in theme_css()
    assert '#090909' not in theme_css()


def test_switch_preferences_preserves_report_and_tasks(monkeypatch, history, state):
    ident, record, report = saved_report(history, state)
    at, calls = app_setup(monkeypatch, history)
    ui = at.session_state['pra']
    ui['uploads'].cleanup()
    ui['uploads'] = state['uploads']
    open_query_paper(ui, history, ident)
    before = copy.deepcopy(ui['analyses'])
    current_id = ui['current_paper']['paper_id']
    assert all(item.key != 'ui_theme_choice' for item in at.selectbox)
    at.selectbox(key='ui_language_choice').set_value('en').run()
    assert not at.exception
    assert at.button(key='nav_Discover').label == 'Discover'
    at.button(key='nav_Paper Reader').click().run()
    assert not at.exception
    assert 'ui_theme' not in ui and ui['ui_language'] == 'en'
    assert ui['analyses'] == before and ui['current_paper']['paper_id'] == current_id
    assert at.button(key='analyze_upload').label == 'Analyze paper'
    assert any(item.label == 'PDF pages' for item in at.metric)
    assert calls == [] and len(history.list_query_history()) == 1
    at.selectbox(key='ui_language_choice').set_value('zh').run()
    assert at.button(key='nav_Discover').label == '文献发现'
    assert ui['analyses'] == before and calls == []


def test_english_search_options_keep_backend_values(monkeypatch, history):
    at, calls = app_setup(monkeypatch, history)
    at.selectbox(key='ui_language_choice').set_value('en').run()
    at.button(key='nav_Discover').click().run()
    assert not at.exception
    assert at.selectbox(key='search_years').options == ['Any year', 'Last 5 years', 'Last year']
    assert at.selectbox(key='search_years').value == 0
    assert at.text_input(key='search_keywords').label == 'Keywords or arXiv query'
    assert calls == []
    at.session_state['pra']['uploads'].cleanup()
