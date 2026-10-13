"""Research workflow navigation; only the selected page is rendered."""
from .i18n import st, preference_controls
from paper_research_agent.config import load_settings
from paper_research_agent.database.service import HistoryService, PersistentBackend
from .backend import WebBackend
from .state import initialize
from .components import monitor
from .workspace import style, navigation, compact_navigation
from . import search_page, reader_page, recommend_page, dashboard_page, library_page, history_page, settings_page


def main():
    st.set_page_config(page_title='Paper Research Agent', page_icon='📚', layout='wide')
    try:
        settings = load_settings()
    except Exception:
        st.error('配置校验失败，请检查 .env。页面不显示配置原值或密钥。')
        st.stop()
    state = initialize(st.session_state)
    try:
        if 'history' not in state:
            state['history'] = HistoryService(settings)
        history = state['history']
    except Exception:
        st.error('历史数据库初始化失败，请检查路径、权限和磁盘空间。')
        st.stop()
    raw = WebBackend(settings, state['uploads'])
    raw.uploads = state['uploads']
    if state.get('navigate_to'):
        state['page'] = state.pop('navigate_to')
    preference_controls(state)
    style()
    navigation(state)
    compact_navigation(state)
    with st.container(key='workspace_heading'):
        st.title('Paper Research Workspace')
    st.caption('')
    st.divider()
    page = state['page']
    backend = PersistentBackend(raw, history, state.get('force_execution', False))
    monitor(state)
    pages = {'Dashboard': dashboard_page.render, 'Discover': search_page.render,
             'Paper Reader': reader_page.render, 'Related Research': recommend_page.render,
             'Library': library_page.render, 'History': history_page.page, 'Settings': settings_page.render}
    pages[page](state, backend, settings)


if __name__ == '__main__':
    main()
