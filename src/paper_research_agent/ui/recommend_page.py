import streamlit as st
from .analysis_page import upload_control
from .components import launch, show_outcome, show_recommendations, show_report, retry_button


def render(state,backend,settings):
    st.subheader('Related Papers')
    st.caption('推荐最多 5 篇。依据候选标题和摘要；评分与理由来自后端，不代表全文评审。')
    record = upload_control(state,settings,'recommend_upload')
    if record is None:
        return
    source_key = 'local:'+record.digest
    task_key = 'recommend_'+source_key
    if source_key in state['analyses']:
        st.info('已有源论文分析，本次推荐将复用，避免重新分析。')
    if st.button('查找相关论文',key='recommend_upload_button',disabled=state['job'] is not None or not settings.openai_api_key or task_key in state['tasks']):
        launch(state,task_key,'recommend_related',source_key,backend,{'source_type':'local','file_path':record.relative_path,'language':'中文'})
    if task_key in state['tasks']:
        show_outcome(state['tasks'][task_key])
        retry_button(state,task_key)
    if source_key in state['recommendations']:
        show_recommendations(state['recommendations'][source_key])
    if source_key in state['analyses']:
        with st.expander('源论文分析（即使推荐失败也保留）'):
            show_report(state['analyses'][source_key],'download_source_'+record.digest)
