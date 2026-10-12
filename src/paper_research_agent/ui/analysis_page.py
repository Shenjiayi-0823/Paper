import math
import streamlit as st
from .components import launch, show_outcome, show_report, retry_button


def upload_control(state,settings,key):
    file = st.file_uploader('上传本地 PDF',type=['pdf'],max_upload_size=max(1,math.ceil(settings.pdf_max_bytes/1024/1024)),key=key+'_'+state['uploads'].session_id,
        disabled=state['job'] is not None)
    if file is None:
        return None
    try:
        record = state['uploads'].save(file.name,file.getvalue(),settings)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.caption(f'{record.name} · {record.pages} 页 · {record.size/1024/1024:.2f} MiB')
    return record


def render(state,backend,settings):
    st.subheader('PDF Analysis')
    st.caption('文件仅在本会话可访问。分析会将预算内论文内容发送给 .env 配置的模型平台。')
    record = upload_control(state,settings,'analysis_upload')
    if record is None:
        return
    source_key = 'local:'+record.digest
    task_key = 'analysis_'+source_key
    if st.button('结构化分析',key='analyze_upload',disabled=state['job'] is not None or not settings.openai_api_key or task_key in state['tasks'] or source_key in state['analyses']):
        launch(state,task_key,'analyze_paper',source_key,backend,{'source_type':'local','file_path':record.relative_path,'language':'中文'})
    if task_key in state['tasks']:
        show_outcome(state['tasks'][task_key])
        retry_button(state,task_key)
    if source_key in state['analyses']:
        st.caption('复用本会话已完成的有效分析。')
        show_report(state['analyses'][source_key],'download_local_'+record.digest)
