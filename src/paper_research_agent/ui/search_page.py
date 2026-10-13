"""Compact discovery list; choosing a paper is separate from paid analysis."""
import hashlib
from datetime import datetime, timezone
from html import escape
from .i18n import st
from .components import launch, show_outcome, show_paper
from .workflow import select_paper, navigate
from paper_research_agent.database.library import LibraryService
from .workspace import research_context


def dated_query(query, years, now=None):
    if not years:
        return query.strip()
    now = now or datetime.now(timezone.utc)
    try:
        start = now.replace(year=now.year-years)
    except ValueError:
        start = now.replace(year=now.year-years, day=28)
    return f'({query.strip()}) AND submittedDate:[{start:%Y%m%d}0000 TO {now:%Y%m%d}2359]'


def render(state, backend, settings):
    main, context = st.columns([3, 1], gap='large')
    with main:
        render_results(state, backend, settings)
    with context:
        research_context(state)


def render_results(state, backend, settings):
    st.header('文献发现')
    st.caption('搜索、筛选并收集值得阅读的论文')
    with st.form('paper_search'):
        query = st.text_input('研究关键词或 arXiv 检索表达式', max_chars=1000,
                              placeholder='例如：data center energy management', key='search_keywords')
        a, b, c = st.columns(3)
        count = a.slider('论文数量', 1, 20, 5, key='search_count')
        sort = b.selectbox('排序', ['relevance', 'submittedDate'], key='search_sort')
        years = c.selectbox('发表时间', [0, 5, 1], format_func=lambda value: '不限年份' if not value else f'最近 {value} 年', key='search_years')
        submitted = st.form_submit_button('检索论文', disabled=state['job'] is not None)
    actual_query = dated_query(query, years)
    key = 'search_' + hashlib.sha256(f'{actual_query}|{count}|{sort}'.encode()).hexdigest()
    if submitted:
        if not query.strip():
            st.warning('请输入研究关键词。')
        elif key in state['tasks'] and not backend.force:
            outcome = state['tasks'][key]
            if outcome.success:
                state['search'], state['search_query'] = outcome.data.get('papers', []), outcome.data.get('query', query.strip())
            state['last'] = outcome
        else:
            state['tasks'].pop(key, None)
            launch(state, key, 'search', None, backend, {'query': actual_query, 'max_results': count, 'sort_by': sort})
    if key in state['tasks']:
        show_outcome(state['tasks'][key])
    if not state['search']:
        st.info('检索成功，但未找到匹配论文。' if key in state['tasks'] and state['tasks'][key].success else '输入关键词开始发现论文。失败与无匹配结果会分别显示。')
    else:
        st.caption('保留的检索结果：' + state['search_query'])
    for paper in state['search']:
        with st.container(border=True):
            st.html('<h3 class="paper-card-title">' + escape(paper['title']) + '</h3>')
            st.caption(', '.join(paper.get('authors', [])) + ' · ' + str(paper.get('published') or '日期未提供')[:10] + ' · ' + paper['arxiv_id'])
            abstract = paper.get('abstract', '')
            excerpt = abstract[:210] + ('…' if len(abstract) > 210 else '')
            st.html('<p class="paper-card-abstract">' + escape(excerpt) + '</p>')
            with st.expander('完整摘要与 PDF'):
                show_paper(paper)
            ident = paper['arxiv_id']
            try:
                library = LibraryService(state['history'])
                paper_id = library.ensure_paper(paper)
                saved = library.get_entry(paper_id)
                left, right = st.columns(2)
                with left:
                    if st.button('取消收藏' if saved else '收藏', icon=':material/bookmark:', key='discover_save_' + ident, type='tertiary'):
                        library.favorite(paper_id, not bool(saved))
                        st.rerun()
                with right:
                    opened = st.button('阅读分析 →', key='open_' + ident, width='stretch', type='tertiary')
                if opened:
                    select_paper(state, state['history'], paper)
                    navigate(state, 'Paper Reader')
            except Exception:
                st.error('文献库操作失败，检索结果已保留。')
