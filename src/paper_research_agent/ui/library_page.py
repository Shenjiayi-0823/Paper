from .i18n import st
from paper_research_agent.database.library import LibraryService
from .workflow import READING, select_paper, open_query_paper, navigate


def render(state, backend, settings):
    st.header('我的文献库')
    st.caption('收藏是长期阅读计划；任务历史另存于 History。')
    title = st.text_input('按标题筛选', key='library_title')
    status = st.selectbox('阅读状态筛选', ['all', *READING], format_func=lambda value: '全部' if value == 'all' else READING[value], key='library_filter')
    page = int(st.number_input('文献库页码', min_value=1, value=1, step=1, key='library_page'))
    try:
        library = LibraryService(state['history'])
        rows = library.list_papers(title, None if status == 'all' else status, page - 1)
        if not rows:
            st.info('没有符合条件的收藏。可以在 Paper Reader 中收藏论文。')
        for row in rows:
            with st.container(border=True):
                ident = row['paper_id']
                st.text(row['title'])
                st.caption((row['arxiv_id'] or '本地论文') + ' · ' + READING[row['reading_status']])
                chosen = st.selectbox('阅读状态', list(READING), index=list(READING).index(row['reading_status']),
                                     format_func=READING.get, key=f'library_status_{ident}')
                if chosen != row['reading_status']:
                    library.set_reading_status(ident, chosen)
                    st.rerun()
                stored = library.latest_analysis(ident)
                if st.button('阅读 / 查看已有分析', key=f'library_open_{ident}'):
                    if stored:
                        open_query_paper(state, state['history'], stored['query_id'])
                    else:
                        select_paper(state, state['history'], library.get_paper(ident))
                    navigate(state, 'Paper Reader')
                if st.button('取消收藏', key=f'library_remove_{ident}'):
                    library.favorite(ident, False)
                    st.rerun()
    except Exception:
        st.error('文献库操作失败，请检查数据库；已有数据不会被清空。')
