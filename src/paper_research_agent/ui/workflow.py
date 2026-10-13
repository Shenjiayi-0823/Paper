"""Paper context and navigation; viewing never starts a model or MCP task."""
from .i18n import st
from .backend import TaskOutcome
from paper_research_agent.database.library import LibraryService

PAGES = ['Dashboard', 'Discover', 'Paper Reader', 'Related Research', 'Library', 'History', 'Settings']
READING = {'to_read': '待读', 'reading': '阅读中', 'read': '已读'}


def navigate(state, page):
    state['page'] = page
    state['navigate_to'] = page
    st.rerun()


def select_paper(state, history, paper, content_hash=None, args=None, analysis=None, query_id=None):
    library = LibraryService(history)
    paper_id = paper.get('paper_id') or library.ensure_paper(paper, content_hash)
    content_hash = content_hash or paper.get('content_hash')
    if args is None:
        if paper.get('arxiv_id'):
            args = {'source_type': 'arxiv', 'arxiv_id': paper['arxiv_id'], 'language': '中文'}
        else:
            upload = state['uploads'].files.get(content_hash)
            args = {'source_type': 'local', 'file_path': upload.relative_path if upload else None, 'language': '中文'}
    source_key = 'arxiv:' + args['arxiv_id'] if args['source_type'] == 'arxiv' else 'local:' + (content_hash or str(paper_id))
    state['current_paper'] = {'paper_id': paper_id, 'paper': dict(paper), 'content_hash': content_hash,
        'source_key': source_key, 'args': dict(args), 'analysis_query_id': query_id}
    if analysis is None:
        stored = library.latest_analysis(paper_id, args.get('arxiv_id'))
        if stored:
            analysis, query_id = stored['analysis'], stored['query_id']
            state['current_paper']['analysis_query_id'] = query_id
            state['current_paper']['analysis_origin'] = stored
    if analysis is not None:
        state['analyses'][source_key] = analysis
    return state['current_paper']


def source_available(state):
    current = state.get('current_paper')
    if not current:
        return False
    args = current['args']
    if args['source_type'] == 'arxiv':
        return True
    upload = state['uploads'].files.get(current.get('content_hash'))
    if upload and state['uploads'].owns(upload.relative_path):
        args['file_path'] = upload.relative_path
        return True
    return False


def favorite_control(state, history, key):
    current = state.get('current_paper')
    if not current:
        return
    try:
        library = LibraryService(history)
        entry = library.get_entry(current['paper_id'])
        if st.button('取消收藏' if entry else '收藏论文', key=key):
            library.favorite(current['paper_id'], not bool(entry))
            st.rerun()
        if entry:
            value = st.selectbox('阅读状态', list(READING), index=list(READING).index(entry.reading_status),
                                 format_func=READING.get, key=key + '_reading')
            if value != entry.reading_status:
                library.set_reading_status(current['paper_id'], value)
                st.rerun()
    except Exception:
        st.error('文献库读写失败，未更改收藏状态。')


def open_query_paper(state, history, query_id):
    row = history.get_query_by_id(query_id)
    snapshot = history.get_query_result(query_id)
    if row is None or not snapshot or not snapshot.get('data', {}).get('analysis'):
        raise ValueError('No saved analysis')
    data = snapshot['data']
    params = row.parameters_json
    args = {key: params.get(key) for key in ('source_type', 'file_path', 'arxiv_id', 'language') if params.get(key) is not None}
    if args['source_type'] == 'local':
        upload = state['uploads'].files.get(params.get('pdf_sha256'))
        args['file_path'] = upload.relative_path if upload else None
    current = select_paper(state, history, {'title': data['analysis']['title'], 'arxiv_id': args.get('arxiv_id')},
                           params.get('pdf_sha256'), args, data['analysis'], query_id)
    if data.get('recommendations'):
        state['recommendations'][current['source_key']] = data['recommendations']
    state['last'] = TaskOutcome(**snapshot)
    return current
