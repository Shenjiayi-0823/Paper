import json
from dataclasses import asdict
from .i18n import st
from .backend import task_status
from .components import launch, show_outcome


def render(state, backend, settings):
    st.header('设置与诊断')
    st.caption('当前模型：' + settings.openai_model)
    st.caption(f'单任务 {settings.agent_task_timeout_seconds:g} 秒 · 单请求 {settings.request_timeout_seconds:g} 秒 · 上传 {settings.pdf_max_bytes/1024/1024:g} MiB / {settings.pdf_max_pages} 页')
    st.caption('修改超时、模型和预算请编辑 .env 后重启服务；不在界面展示密钥。')
    if not settings.openai_api_key:
        st.warning('未配置模型密钥；检索可用，分析和推荐需先配置。')
    state['force_execution'] = st.checkbox('重新执行：忽略历史缓存', value=state.get('force_execution', False),
                                           key='force_history_cache', disabled=state['job'] is not None)
    st.caption('开启后，下一次分析或推荐不复用源论文报告，可能产生平台费用。')
    st.caption('后端连接：' + state['connection'])
    if st.button('检测 MCP 连接', key='settings_check', disabled=state['job'] is not None):
        state['tasks'].pop('connection_check', None)
        launch(state, 'connection_check', 'check', None, backend, {})
    with st.expander('Agent Execution Trace / 完整任务诊断'):
        st.caption('工具执行记录，不是隐藏推理。父操作耗时包含子调用，不能相加。')
        outcome = state['last']
        if outcome:
            show_outcome(outcome)
            for index, item in enumerate(outcome.trace, 1):
                st.text(f"{index}. {item.get('name')} · {'success' if item.get('success') else 'failed'} · {item.get('elapsed_seconds')} 秒")
                if item.get('error'):
                    st.text(item['error'].get('message', ''))
            st.json(outcome.usage, expanded=False)
            st.download_button('下载完整任务结果 JSON', json.dumps({**asdict(outcome), 'status': task_status(outcome)}, ensure_ascii=False, indent=2),
                               file_name='paper-agent-task.json', mime='application/json', key='download_task_result')
        for elapsed, message in state['events']:
            st.text(f'[{elapsed:.1f}s] {message}')
    st.caption('本地单用户模式。清除会话不会删除 SQLite 历史或收藏。')
    if st.button('清除本会话结果与上传文件', disabled=state['job'] is not None):
        state['uploads'].cleanup()
        state['history'].database.close()
        del st.session_state['pra']
        st.rerun()
