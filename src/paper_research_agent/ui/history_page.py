"""History presentation only; all database access stays in the service layer."""
import uuid
import logging
from datetime import timezone, timedelta
from pathlib import PurePosixPath
from .i18n import st, translate
from .backend import TaskOutcome
from .components import show_outcome, show_paper, show_report, show_recommendations, launch
from paper_research_agent.database.service import OPERATIONS, PersistentBackend
from .workflow import open_query_paper, navigate

logger = logging.getLogger(__name__)


def page(state, backend, settings):
    if state.get('history_selected') is not None:
        render(state, state['history'], backend, settings)
        return
    heading, order = st.columns([3, 1])
    heading.header('研究历史')
    order.caption('按最近执行排序')
    list_records(state, state['history'])


TYPES = {'search':'文献检索', 'analysis':'论文分析', 'recommendation':'文献推荐'}
STATES = {'pending':'等待执行', 'running':'执行中', 'success':'成功', 'partial':'部分完成', 'failed':'失败', 'timeout':'超时'}
ICONS = {'search':':material/search:', 'analysis':':material/article:', 'recommendation':':material/hub:'}


def record_title(row):
    if row.query_type == 'search':
        return translate('检索：') + row.query_text
    title = getattr(row, 'display_title', None)
    if title and title != 'Not specified':
        return title + ' · ' + translate(TYPES[row.query_type])
    source = row.parameters_json.get('arxiv_id') or PurePosixPath(row.query_text.replace('\\','/')).name
    return translate('查找相关研究' if row.query_type == 'recommendation' else '论文分析') + ((' · ' + source) if source else '')


def list_records(state, history):
    search_column, type_column = st.columns([4, 1])
    search = search_column.text_input('搜索论文标题或查询关键词', key='history_search', max_chars=300,
                                      value=state.get('history_search_value',''), autocomplete='off',
                                      placeholder='搜索论文标题或查询关键词', label_visibility='collapsed')
    kind = type_column.selectbox('历史类型', ['全部', 'search', 'analysis', 'recommendation'],
                                index=['全部','search','analysis','recommendation'].index(state.get('history_type_value','全部')),
                                format_func=lambda value: '全部类型' if value == '全部' else TYPES[value],
                                key='history_type', label_visibility='collapsed')
    query_type = None if kind == '全部' else kind
    criteria = (query_type, search.strip())
    state['history_search_value'], state['history_type_value'] = search, kind
    if state.get('history_filters') != criteria:
        state['history_filters'] = criteria
        st.session_state['history_page'] = 1
        state['history_page_value'] = 1
    try:
        total = history.count_query_history(query_type, search)
        last_page = max(1, (total + 19) // 20)
        if state.get('history_page_value', 1) > last_page:
            st.session_state['history_page'] = last_page
            state['history_page_value'] = last_page
        page = int(st.number_input('历史页码', min_value=1, max_value=last_page, value=state.get('history_page_value',1), step=1, key='history_page'))
        state['history_page_value'] = page
        rows = history.list_query_history(query_type, page - 1, search=search)
        st.caption(translate('匹配记录：') + str(total))
        if not rows:
            st.info('没有匹配的历史记录。')
        for row in rows:
            with st.container(border=False, key=f'history_row_{row.id}'):
                item, status = st.columns([5, 1])
                with item:
                    if st.button(record_title(row), icon=ICONS[row.query_type], key=f'history_view_{row.id}',
                                 type='tertiary', width='stretch'):
                        state['history_selected'] = row.id
                        st.rerun()
                    date = row.created_at.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))
                    shown_date = date.strftime('%m/%d %H:%M') if state.get('ui_language') == 'en' else f'{date.month}月{date.day}日 {date:%H:%M}'
                    st.caption(translate(TYPES[row.query_type]) + ' · ' + shown_date + ' UTC+8')
                with status:
                    label = translate(STATES.get(row.status, row.status))
                    color = {'success':'green','partial':'orange','failed':'red','timeout':'orange'}.get(row.status, 'gray')
                    st.markdown(f':{color}[{label}]')
            st.divider()
        st.caption('记录从 SQLite 加载。打开结果不调用模型；重新运行需主动点击。')
    except Exception:
        st.error('历史数据库读取或删除失败，请检查数据库权限。')


def render(state, history, backend, settings):
    ident = state.get('history_selected')
    if ident is None:
        return
    st.subheader(f'历史记录 #{ident}')
    if st.button('返回研究历史', key='history_close_detail', type='tertiary', icon=':material/arrow_back:'):
        state.pop('history_selected', None)
        st.rerun()
    try:
        row = history.get_query_by_id(ident)
        snapshot = history.get_query_result(ident)
        if row is None:
            st.warning('记录已删除。')
            return
        st.caption(f'{row.query_type} · {row.status} · {row.created_at.isoformat()} UTC')
        if st.button('删除记录', key=f'history_delete_{ident}', disabled=state['job'] is not None or row.status in {'pending','running'}):
            history.delete_query(ident)
            state.pop('history_selected', None)
            st.rerun()
        if snapshot:
            outcome = TaskOutcome(**snapshot)
            state['last'] = outcome
            show_outcome(outcome)
            for index, paper in enumerate(outcome.data.get('papers', [])):
                show_paper(paper)
            if outcome.data.get('analysis'):
                show_report(outcome.data['analysis'], f'history_report_{ident}')
            if outcome.data.get('recommendations'):
                show_recommendations(outcome.data['recommendations'])
            if outcome.data.get('analysis') and st.button('在 Paper Reader 中打开', key=f'history_reader_{ident}'):
                open_query_paper(state, history, ident)
                navigate(state, 'Paper Reader')
            if row.query_type == 'search' and st.button('在 Discover 中查看结果', key=f'history_discover_{ident}'):
                state['search'] = outcome.data.get('papers', [])
                state['search_query'] = row.query_text
                navigate(state, 'Discover')
        else:
            st.info('任务尚未完成或正在等待中断恢复。')
        operation = next(name for name, kind in OPERATIONS.items() if kind == row.query_type)
        args = {key: value for key, value in row.parameters_json.items() if key != 'pdf_sha256'}
        if args.get('source_type') == 'local':
            # Former session files are never accessed by a new session.
            digest = row.parameters_json.get('pdf_sha256')
            upload = state['uploads'].files.get(digest)
            if upload:
                args['file_path'] = upload.relative_path
            else:
                st.info('重新执行本地论文任务前，请在 PDF 页面重新上传相同内容的文件。历史报告无需原文件即可查看。')
                return
        if st.button('重新执行历史任务（忽略缓存，可能产生费用）', key=f'history_rerun_{ident}',
                     disabled=state['job'] is not None or row.status in {'pending','running'} or (operation != 'search' and not settings.openai_api_key)):
            fresh = PersistentBackend(backend.backend, history, force=True)
            source = 'local:' + row.parameters_json['pdf_sha256'] if args.get('source_type') == 'local' else 'arxiv:' + args.get('arxiv_id', '')
            launch(state, 'history_reexecute_' + uuid.uuid4().hex, operation, source, fresh, args)
    except Exception as exc:
        logger.warning('History record %s could not be displayed (%s)', ident, type(exc).__name__)
        st.error('无法读取历史结果，记录可能损坏或数据库不可用。')
