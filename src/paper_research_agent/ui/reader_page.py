"""PDF originals alongside provenance-aware analysis; no fake highlighting."""
import pymupdf
from .i18n import st
from .analysis_page import upload_control
from .components import launch, show_outcome, show_report
from .workflow import select_paper, source_available, favorite_control, navigate
from .pdf_preview import pdf_address, load_online_preview
from .state import start_job

READER_PANEL_HEIGHT = 780


def render_pdf_page(store, relative_path, page):
    if not store.owns(relative_path):
        raise ValueError('Upload not owned')
    with pymupdf.open(store.base / relative_path) as document:
        if not 1 <= page <= document.page_count:
            raise ValueError('Page out of range')
        source = document[page - 1]
        # Bound image dimensions for unusual PDF page sizes.
        scale = min(1.5, 1600 / max(source.rect.width, source.rect.height))
        return source.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png')


def jump_to_page(state, source_key, page):
    state['reader_pages'][source_key] = page


def render(state, backend, settings):
    st.header('论文阅读')
    with st.expander('上传或切换本地 PDF', expanded=not bool(state.get('current_paper'))):
        record = upload_control(state, settings, 'analysis_upload')
        if record:
            current = state.get('current_paper')
            if current is None or current.get('content_hash') != record.digest:
                if current is None or st.button('切换到此 PDF', key='switch_uploaded'):
                    try:
                        select_paper(state, state['history'], {'title': record.name}, record.digest,
                                     {'source_type': 'local', 'file_path': record.relative_path, 'language': '中文'})
                    except Exception:
                        st.error('无法建立本地论文上下文。')
    current = state.get('current_paper')
    if current is None:
        st.info('在 Discover 中选择论文，或在此上传 PDF。')
        return
    source = current['source_key']
    report = state['analyses'].get(source)
    st.subheader(current['paper'].get('title', 'Not specified'))
    st.caption('当前来源：' + (current['args'].get('arxiv_id') or '本地 PDF'))
    favorite_control(state, state['history'], 'reader_favorite_' + str(current['paper_id']))
    if current.get('analysis_origin'):
        origin = current['analysis_origin']
        st.caption(f"已打开历史分析 #{origin['query_id']} · 模型 {origin['model_name']}。查看不会调用 LLM；新任务仍校验模型与提示词缓存版本。")
    single = st.checkbox('单栏阅读（适合窄窗口）', key='reader_single_column')
    left, right = (st.container(), st.container()) if single else st.columns([1, 1], gap='large')
    available = source_available(state)
    with left:
        with st.container(height=READER_PANEL_HEIGHT, border=True, key="reader_pdf_panel"):
            st.subheader('PDF 原文')
            upload = state['uploads'].files.get(current.get('content_hash'))
            if current['args']['source_type'] == 'arxiv':
                preview = state['pdf_previews'].get(source, {})
                upload = state['uploads'].files.get(preview.get('digest'))
            total = upload.pages if upload else (report or {}).get('total_pages', settings.pdf_max_pages)
            if not upload and not report:
                st.caption('尚未确认总页数；页码输入上限采用 PDF 安全配置。')
            page = min(max(1, state['reader_pages'].get(source, 1)), max(1, total))
            chosen = int(st.number_input('PDF 页码', min_value=1, max_value=max(1, total), value=page,
                                         key=f'pdf_page_{source}_{page}'))
            state['reader_pages'][source] = chosen
            if current['args']['source_type'] == 'local':
                if available:
                    try:
                        st.image(render_pdf_page(state['uploads'], current['args']['file_path'], chosen), width='stretch')
                        st.caption(f'实际 PDF 第 {chosen} 页；引用页码采用 PDF 页序号。')
                        st.download_button('下载原 PDF', (state['uploads'].base / current['args']['file_path']).read_bytes(),
                                           file_name='paper.pdf', mime='application/pdf', key='reader_download_pdf')
                    except Exception:
                        st.warning('PDF 预览失败，已完成的分析仍保留。')
                else:
                    st.info('历史报告可直接查看。预览或重新执行前，请上传相同内容的 PDF。')
            else:
                try:
                    address = pdf_address(current['args']['arxiv_id'], chosen)
                    preview_key = 'preview_' + source
                    if upload and state['uploads'].owns(upload.relative_path):
                        try:
                            st.image(render_pdf_page(state['uploads'], upload.relative_path, chosen), width='stretch')
                            st.caption(f'实际 PDF 第 {chosen} 页；引用页码采用 PDF 页序号。')
                        except Exception:
                            st.warning('PDF 预览失败，已完成的分析仍保留。')
                    else:
                        st.info('在线 PDF 按页显示，不依赖浏览器 PDF 插件。点击加载后下载官方原文，不调用 LLM。')
                        if st.button('加载 PDF 原文', key='load_online_pdf', disabled=state['job'] is not None):
                            state['tasks'].pop(preview_key, None)
                            if start_job(state, preview_key, 'pdf_preview', source,
                                         lambda progress: load_online_preview(current['args']['arxiv_id'], state['uploads'], settings, progress)):
                                st.rerun()
                    if preview_key in state['tasks'] and not state['tasks'][preview_key].success:
                        show_outcome(state['tasks'][preview_key])
                    st.link_button(f'新窗口打开 PDF · 第 {chosen} 页', address)
                    st.caption('预览只用于显示原文，分析仍通过 MCP 读取同一 arXiv 论文。')
                except ValueError:
                    st.error('在线论文编号无效，不能预览。')
    with right:
        with st.container(height=READER_PANEL_HEIGHT, border=True, key="reader_analysis_panel"):
            st.subheader('结构化 AI 分析')
            task_key = 'analysis_' + source
            if st.button('结构化分析', key='analyze_upload', disabled=state['job'] is not None or not settings.openai_api_key or not available):
                state['tasks'].pop(task_key, None)
                launch(state, task_key, 'analyze_paper', source, backend, current['args'])
            st.caption('分析会向配置的模型平台发送论文内容；默认优先复用有效缓存。')
            if task_key in state['tasks']:
                show_outcome(state['tasks'][task_key])
            if report:
                show_report(report, 'reader_report_' + source,
                            on_page=lambda page: jump_to_page(state, source, page))
            else:
                st.info('尚无分析。点击按钮后才执行模型请求。')
            if st.button('查找相关研究', key='reader_related'):
                navigate(state, 'Related Research')
