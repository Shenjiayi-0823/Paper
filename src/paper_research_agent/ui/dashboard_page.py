from .i18n import st
from paper_research_agent.database.library import LibraryService
from .workflow import navigate
from .recent_tasks import render_recent


def render(state, backend, settings):
    st.header('研究概览')
    st.caption('围绕一篇论文持续发现、阅读、分析与回顾。')
    try:
        counts = LibraryService(state['history']).overview()
        columns = st.columns(3)
        columns[0].metric('我的文献', counts['library'])
        columns[1].metric('待读', counts['to_read'])
        columns[2].metric('已读', counts['read'])
        current = state.get('current_paper')
        if current:
            st.subheader('继续阅读')
            st.text(current['paper'].get('title', 'Not specified'))
            if st.button('打开当前论文', key='dashboard_continue'):
                navigate(state, 'Paper Reader')
        else:
            if st.button('发现论文', key='dashboard_discover'):
                navigate(state, 'Discover')
        render_recent(state, 'dashboard_history_')
    except Exception:
        st.error('无法读取研究概览，请检查数据库。')
