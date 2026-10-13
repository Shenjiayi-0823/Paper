"""Recommendations for the shared current paper, without repeated uploads."""
from .i18n import st, translate
from .components import launch, show_outcome, show_paper
from .workflow import source_available, select_paper, navigate, favorite_control
from .formatters import recommendation_view


def render(state, backend, settings):
    st.header('相关研究')
    current = state.get('current_paper')
    if not current:
        st.info('请先在 Discover 或 Paper Reader 中选择一篇论文。')
        return
    st.subheader(current['paper'].get('title', 'Not specified'))
    favorite_control(state, state['history'], 'related_favorite_' + str(current['paper_id']))
    source = current['source_key']
    key = 'recommend_' + source
    if not source_available(state):
        st.info('请在 Paper Reader 中重新上传相同 PDF；已有分析和推荐仍可查看。')
    if st.button('查找相关论文', key='recommend_upload_button', disabled=state['job'] is not None or not settings.openai_api_key or not source_available(state)):
        state['tasks'].pop(key, None)
        launch(state, key, 'recommend_related', source, backend, current['args'])
    st.caption('最多 5 篇；依据真实候选标题和摘要，不是候选全文评审。评分为后端模型判断。')
    if key in state['tasks']:
        show_outcome(state['tasks'][key])
    data = state['recommendations'].get(source)
    if data:
        result, _ = recommendation_view(data)
        st.subheader('研究主题')
        st.text(result.theme.research_theme)
        st.write('关键词：' + ', '.join(result.theme.english_keywords))
        with st.expander('技术方法与实际检索查询'):
            st.text(', '.join(result.theme.technical_methods))
            for query in result.queries:
                st.code(query, language=None)
        for warning in result.warnings:
            st.caption(warning)
        if not result.papers:
            st.info('没有符合条件的候选论文。')
        for index, candidate in enumerate(result.papers):
            with st.container(border=True):
                paper = candidate.model_dump()
                show_paper(paper)
                st.caption(f'相关性 {candidate.score:.2f} · 依据：标题与摘要')
                st.text(translate('推荐理由：') + candidate.reason)
                st.text(translate('研究联系：') + candidate.connection)
                st.text(translate('主要差异：') + candidate.differences)
                if st.button('阅读此论文', key='related_open_' + candidate.arxiv_id):
                    try:
                        select_paper(state, state['history'], paper)
                        navigate(state, 'Paper Reader')
                    except Exception:
                        st.error('无法打开候选论文。')
    if st.button('返回论文阅读', key='related_back'):
        navigate(state, 'Paper Reader')
