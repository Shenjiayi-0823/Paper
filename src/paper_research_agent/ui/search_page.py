import hashlib
import streamlit as st
from .components import launch, show_outcome, show_paper, show_report, retry_button


def render(state,backend,settings):
    st.subheader('Paper Search')
    st.caption('真实 arXiv 检索，经 MCP 执行；检索本身不调用 LLM。')
    with st.form('paper_search'):
        query = st.text_input('研究关键词或 arXiv 检索表达式',max_chars=1000)
        count = st.slider('论文数量',1,20,5)
        sort = st.selectbox('排序',['relevance','submittedDate'])
        submitted = st.form_submit_button('检索论文',disabled=state['job'] is not None)
    key = 'search_'+hashlib.sha256(f'{query.strip()}|{count}|{sort}'.encode()).hexdigest()
    if submitted:
        if not query.strip():
            st.warning('请输入研究关键词。')
        elif key in state['tasks']:
            st.info('此检索已执行，复用当前会话结果。')
            outcome = state['tasks'][key]
            if outcome.success:
                state['search'] = outcome.data.get('papers',[])
                state['search_query'] = outcome.data.get('query',query.strip())
            state['last'] = outcome
        else:
            launch(state,key,'search',None,backend,{'query':query.strip(),'max_results':count,'sort_by':sort})
    if key in state['tasks']:
        show_outcome(state['tasks'][key])
        retry_button(state,key)
    if not state['search']:
        if key in state['tasks'] and state['tasks'][key].success and not state['tasks'][key].data.get('papers'):
            st.info('检索成功，但未找到匹配论文。可调整英文关键词或检索表达式。')
        else:
            st.info('输入关键词后点击检索；请求失败与没有匹配结果是不同状态。')
    else:
        st.caption('以下为当前保留的成功检索结果：'+state['search_query'])
    for paper in state['search']:
        st.divider()
        show_paper(paper)
        ident = paper['arxiv_id']
        source_key = 'arxiv:'+ident
        task_key = 'analysis_'+source_key
        if st.button('深度分析',key='deep_'+ident,disabled=state['job'] is not None or not settings.openai_api_key or task_key in state['tasks']):
            state['selected'] = ident
            launch(state,task_key,'analyze_paper',source_key,backend,{'source_type':'arxiv','arxiv_id':ident,'language':'中文'})
        if task_key in state['tasks']:
            show_outcome(state['tasks'][task_key])
            retry_button(state,task_key)
        if source_key in state['analyses']:
            show_report(state['analyses'][source_key],'download_'+ident)
