"""Native Streamlit displays; tool trace is not hidden LLM reasoning."""

import time
import streamlit as st
from .backend import task_status
from .formatters import paper_view, report_view, recommendation_view, markdown_report, PROVENANCE
from .state import start_job, poll_job


def launch(state,key,operation,source_key,backend,args):
    cached = state['analyses'].get(source_key)
    if start_job(state,key,operation,source_key,lambda progress:backend.run(operation,args,progress,cached)):
        st.rerun()
    else:
        st.info('已有任务或缓存结果，未重复启动。')


def show_outcome(outcome):
    if outcome is None:
        return
    status = task_status(outcome)
    labels = {'success':'success · 完整任务成功','partial':'partial · 有有效结果，任务或覆盖不完整',
        'failed':'failed · 任务失败','timeout':'timeout · 超时，已有有效结果仍保留'}
    display = st.success if status == 'success' else st.warning if status in {'partial','timeout'} else st.error
    display(labels[status])
    if outcome.error:
        st.error(f"{outcome.error.get('code','error')}：{outcome.error.get('message','任务失败')}")
    st.caption(f'总耗时 {outcome.elapsed:.2f} 秒；状态依据后端 success/error 与有效数据映射，不依据列表是否非空。')


def show_paper(data):
    paper = paper_view(data)
    st.subheader(paper['title'])
    st.caption(f"{paper['authors']} · {paper['published']} · arXiv {paper['arxiv_id']}")
    with st.expander('Abstract'):
        st.text(paper['abstract'])
    if paper['pdf_url']:
        st.link_button('Open PDF',paper['pdf_url'])


def show_report(data,key):
    view = report_view(data)
    report = view['report']
    st.subheader(report.title)
    a,b,c = st.columns(3)
    a.metric('PDF 页数',report.total_pages)
    b.metric('分析文本块',report.chunk_count)
    c.metric('缺失/空白页',len(report.missing_pages))
    if not report.complete:
        st.warning('论文提取覆盖不完整，请结合缺页与警告阅读结论。')
    for warning in report.warnings:
        st.caption('提示：'+warning)
    for label,claims in view['fields']:
        with st.expander(label,expanded=label in {'Research Problem','Methodology','Results'}):
            for claim in claims:
                st.caption(PROVENANCE[claim.provenance])
                st.text(claim.text)
                if claim.evidence_ids:
                    cited = [view['evidence'][i] for i in claim.evidence_ids if i in view['evidence']]
                    st.caption('依据：'+', '.join(f'{e.id} (p.{e.page_number})' for e in cited))
    st.write('Keywords：'+', '.join(report.keywords))
    with st.expander('Evidence · 原文证据与页码'):
        for evidence in report.evidence:
            st.caption(f'{evidence.id} · PDF 第 {evidence.page_number} 页')
            st.text(evidence.quote)
    st.download_button('下载 Markdown 分析报告',markdown_report(data),file_name='paper-analysis.md',mime='text/markdown',key=key)


def show_recommendations(data):
    result,papers = recommendation_view(data)
    st.subheader('研究主题')
    st.text(result.theme.research_theme)
    st.write('方法：'+', '.join(result.theme.technical_methods))
    st.write('English Keywords：'+', '.join(result.theme.english_keywords))
    with st.expander('实际 arXiv 检索查询',expanded=True):
        for query in result.queries:
            st.code(query,language=None)
    for warning in result.warnings:
        st.caption('提示：'+warning)
    if not papers:
        st.info('后端没有返回符合条件的推荐论文。')
    for paper in papers:
        st.divider()
        show_paper(paper)
        st.caption(f"相关性评分：{paper['score']:.2f}（模型估计） · 依据：标题和摘要，未读取候选全文")
        st.text('推荐理由：'+paper['reason'])
        st.text('研究联系：'+paper['connection'])
        st.text('主要差异：'+paper['differences'])


def retry_button(state,key):
    outcome = state['tasks'].get(key)
    if outcome and task_status(outcome) != 'success' and state['job'] is None:
        if st.button('允许重试此任务（可能产生平台费用）',key='retry_'+key):
            state['tasks'].pop(key,None)
            st.rerun()


@st.fragment(run_every=1)
def monitor(state):
    if state['job'] is None:
        return
    if poll_job(state):
        st.rerun()
    job = state['job']
    with st.status(f'执行中 · {job.operation} · {time.monotonic()-job.started:.0f} 秒',expanded=True):
        for elapsed,message in state['events'][-8:]:
            st.text(f'[{elapsed:.1f}s] {message}')
        st.caption('后台任务仍在运行。结果完成后自动刷新；切换页面不会再次启动。')
