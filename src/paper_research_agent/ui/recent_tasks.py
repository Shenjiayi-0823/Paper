"""Shared compact recent tasks, backed by SQLite and opened without API calls."""
from pathlib import PurePosixPath
from .i18n import st, translate
from .history_page import STATES
from .workflow import navigate

RECENT_TASK_HEIGHT = 320


def recent_label(row):
    kind = translate({'search':'搜索','analysis':'分析','recommendation':'推荐'}.get(row.query_type,row.query_type))
    if row.query_type == 'search':
        title = row.query_text
    else:
        title = getattr(row,'display_title',None)
        if not title or title == 'Not specified':
            title = row.parameters_json.get('arxiv_id') or PurePosixPath(row.query_text.replace('\\','/')).name or 'Not specified'
    return f"{kind}：{title} · {translate(STATES.get(row.status,row.status))}"


def render_recent(state, key):
    st.subheader('最近任务')
    with st.container(height=RECENT_TASK_HEIGHT, border=True, key=key+'_panel'):
        rows = state['history'].list_query_history(page_size=20)
        if not rows:
            st.caption('暂无最近任务。')
        for row in rows:
            with st.container(border=False, key='recent_task_card_' + key + str(row.id)):
                if st.button(recent_label(row), key=key+str(row.id), type='secondary', width='stretch'):
                    state['history_selected'] = row.id
                    navigate(state,'History')
