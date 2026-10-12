import streamlit as st
import json
from dataclasses import asdict
from paper_research_agent.config import load_settings
from .backend import WebBackend, task_status
from .state import initialize
from .components import monitor, launch
from . import search_page, analysis_page, recommend_page


def main():
    st.set_page_config(page_title='Paper Research Agent',page_icon='📚',layout='wide')
    st.title('Paper Research Agent')
    st.caption('AI-Powered Academic Paper Reading Assistant')
    try:
        settings = load_settings()
    except Exception:
        st.error('配置校验失败，请检查 .env；页面不显示配置原值或密钥。')
        st.stop()
    state = initialize(st.session_state)
    backend = WebBackend(settings,state['uploads'])
    with st.sidebar:
        st.header('科研论文阅读助手')
        st.write('通过 MCP 检索和读取真实论文，生成带页码证据的分析与相关推荐。')
        st.caption('当前模型')
        st.text(settings.openai_model)
        st.caption('后端连接状态：'+state['connection'])
        if st.button('检测 MCP 连接',disabled=state['job'] is not None):
            state['tasks'].pop('connection_check',None)
            launch(state,'connection_check','check',None,backend,{})
        if not settings.openai_api_key:
            st.warning('未配置模型密钥：检索可用，分析和推荐需先配置 .env。')
        st.caption(f'上传上限 {settings.pdf_max_bytes/1024/1024:.0f} MiB / {settings.pdf_max_pages} 页；任务时限 {settings.agent_task_timeout_seconds:g} 秒。')
        with st.expander('使用说明',expanded=True):
            st.write('1. 检索或上传 PDF。\n2. 点击按钮启动任务。\n3. 查看状态、原文证据和执行记录。\n4. 下载 Markdown 报告。')
            st.caption('分析/推荐会消耗模型平台额度。切换 Tab 不重复执行；同内容仅在本会话去重。')
        with st.expander('Agent Execution Trace'):
            st.caption('这是工具执行记录，不是 LLM 隐藏推理。MCP 工具耗时是实测；父操作耗时包含子调用，不能相加。')
            if state['last']:
                st.write('最终状态：'+task_status(state['last']))
                rows = [{'顺序':i+1,'工具':t['name'],'状态':'success' if t.get('success') else 'failed',
                    '耗时(秒)':t.get('elapsed_seconds'),'错误':(t.get('error') or {}).get('code',''),
                    '错误信息':(t.get('error') or {}).get('message','')} for i,t in enumerate(state['last'].trace)]
                for row in rows:
                    st.text(f"{row['顺序']}. {row['工具']} · {row['状态']} · {row['耗时(秒)']} 秒")
                    if row['错误']:
                        st.caption('错误：'+row['错误'])
                        st.text(row['错误信息'])
                st.json(state['last'].usage,expanded=False)
                st.download_button('下载完整任务结果 JSON',json.dumps({**asdict(state['last']),'status':task_status(state['last'])},ensure_ascii=False,indent=2),
                    file_name='paper-agent-task.json',mime='application/json',key='download_task_result')
            for elapsed,message in state['events']:
                st.text(f'[{elapsed:.1f}s] {message}')
        if st.button('清除本会话结果与上传文件',disabled=state['job'] is not None):
            state['uploads'].cleanup()
            del st.session_state['pra']
            st.rerun()
    monitor(state)
    tabs = st.tabs(['Paper Search','PDF Analysis','Related Papers'])
    with tabs[0]:
        search_page.render(state,backend,settings)
    with tabs[1]:
        analysis_page.render(state,backend,settings)
    with tabs[2]:
        recommend_page.render(state,backend,settings)


if __name__ == '__main__':
    main()
