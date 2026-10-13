"""Presentation-only localization. Widget values, keys and paper data stay intact."""
import re
import streamlit as native
from streamlit.delta_generator import DeltaGenerator

EN = {
    '搜索':'Search', '分析':'Analysis', '推荐':'Recommendation', '暂无最近任务。':'No recent tasks.',
    '研究历史':'Research history', '按最近执行排序':'Most recent first', '关闭详情':'Close details', '返回研究历史':'Back to research history',
    '搜索论文标题或查询关键词':'Search paper titles or query keywords', '全部类型':'All types',
    '文献检索':'Paper search', '文献推荐':'Recommendations', '等待执行':'Pending', '执行中':'Running',
    '成功':'Success', '部分完成':'Partial', '失败':'Failed', '超时':'Timeout',
    '没有匹配的历史记录。':'No matching history records.',
    '记录从 SQLite 加载。打开结果不调用模型；重新运行需主动点击。':'Records load from SQLite. Viewing does not call a model; reruns require an explicit click.',
    '加载 PDF 原文':'Load original PDF',
    '在线 PDF 按页显示，不依赖浏览器 PDF 插件。点击加载后下载官方原文，不调用 LLM。':'Online PDFs are displayed as page images without browser PDF plugins. Click Load to download the official PDF; no LLM call.',
    '预览只用于显示原文，分析仍通过 MCP 读取同一 arXiv 论文。':'Preview only displays the original; analysis still reads the same arXiv paper through MCP.',
    '研究概览':'Dashboard', '文献发现':'Discover', '论文阅读':'Paper Reader', '相关研究':'Related Research',
    '我的文献库':'Library', '历史记录':'History', '设置与诊断':'Settings',
    '从文献发现到研究积累的一体化工作台':'An integrated workspace for discovery and research',
    '本地单用户模式':'Local single-user mode', '研究上下文':'Research context', '当前研究主题':'Current research topic',
    '尚未开始检索':'No search yet', '已收藏论文':'Saved papers', '已完成分析':'Analyzed papers', '最近任务':'Recent tasks',
    '论文检索':'Paper search', '论文分析':'Paper analysis', '相关推荐':'Recommendations',
    '围绕一篇论文持续发现、阅读、分析与回顾。':'Discover, read, analyze and revisit research around a paper.',
    '我的文献':'Saved papers', '待读':'To read', '阅读中':'Reading', '已读':'Read', '继续阅读':'Continue reading',
    '打开当前论文':'Open current paper', '发现论文':'Discover papers', '回顾':'Review',
    '搜索、筛选并收集值得阅读的论文':'Search, filter and collect papers worth reading',
    '研究关键词或 arXiv 检索表达式':'Keywords or arXiv query', '例如：data center energy management':'e.g. data center energy management',
    '论文数量':'Number of papers', '排序':'Sort by', '发表时间':'Publication period', '不限年份':'Any year',
    '检索论文':'Search papers', '请输入研究关键词。':'Enter research keywords.',
    '检索成功，但未找到匹配论文。':'Search completed with no matching papers.',
    '输入关键词开始发现论文。失败与无匹配结果会分别显示。':'Enter keywords to discover papers. Errors are distinct from empty results.',
    '完整摘要与 PDF':'Full abstract and PDF', '收藏':'Save', '取消收藏':'Unsave', '收藏论文':'Save paper',
    '阅读分析 →':'Read and analyze →', '日期未提供':'Date unavailable',
    '收藏是长期阅读计划；任务历史另存于 History。':'Your reading collection; task records are stored separately in History.',
    '按标题筛选':'Filter by title', '阅读状态筛选':'Filter by reading status', '全部':'All', '阅读状态':'Reading status',
    '文献库页码':'Library page', '本地论文':'Local paper', '阅读 / 查看已有分析':'Read / view saved analysis',
    '没有符合条件的收藏。可以在 Paper Reader 中收藏论文。':'No matching saved papers. Save papers in Paper Reader.',
    '上传或切换本地 PDF':'Upload or switch local PDF', '上传本地 PDF':'Upload local PDF', '切换到此 PDF':'Switch to this PDF',
    '在 Discover 中选择论文，或在此上传 PDF。':'Select a paper in Discover or upload a PDF here.',
    '本地 PDF':'Local PDF', '单栏阅读（适合窄窗口）':'Single-column reading (narrow windows)', 'PDF 原文':'Original PDF',
    'PDF 页码':'PDF page', '尚未确认总页数；页码输入上限采用 PDF 安全配置。':'Page count is not confirmed; the input limit follows PDF safety settings.',
    '下载原 PDF':'Download original PDF', '历史报告可直接查看。预览或重新执行前，请上传相同内容的 PDF。':'Saved reports can be viewed now. Upload the same PDF to preview or rerun.',
    '结构化 AI 分析':'Structured AI analysis', '结构化分析':'Analyze paper',
    '分析会向配置的模型平台发送论文内容；默认优先复用有效缓存。':'Analysis sends paper content to your model provider; valid caches are preferred.',
    '尚无分析。点击按钮后才执行模型请求。':'No analysis yet. Model requests start only when you click Analyze.',
    '查找相关研究':'Find related research', '查找相关论文':'Find related papers', '返回论文阅读':'Back to reader',
    '请先在 Discover 或 Paper Reader 中选择一篇论文。':'Select a paper in Discover or Paper Reader first.',
    '请在 Paper Reader 中重新上传相同 PDF；已有分析和推荐仍可查看。':'Reupload the same PDF in Paper Reader. Saved analysis and recommendations remain available.',
    '最多 5 篇；依据真实候选标题和摘要，不是候选全文评审。评分为后端模型判断。':'Up to 5 papers, assessed using real titles and abstracts, not full texts. Scores come from the backend model.',
    '研究主题':'Research topic', '技术方法与实际检索查询':'Methods and actual search queries',
    '没有符合条件的候选论文。':'No qualifying candidates.', '阅读此论文':'Read this paper',
    '研究问题':'Research problem', '研究背景':'Background', '研究方法':'Methodology', '创新贡献':'Contributions',
    '实验设计':'Experiments', '实验结果':'Results', '研究局限':'Limitations', '作者陈述':'Author-stated', '模型推断':'Model inference', '未说明':'Not specified',
    'PDF 页数':'PDF pages', '分析文本块':'Analysis chunks', '缺失/空白页':'Missing / empty pages',
    '论文提取覆盖不完整，请结合缺页与警告阅读结论。':'Text coverage is incomplete. Review missing pages and warnings.',
    '显示完整分块结论':'Show full chunk findings', '当前展示分层汇总；完整结论与证据仍保留，可切换或导出。':'Showing the hierarchical summary. Full findings and evidence are retained for viewing and export.',
    '证据所在页':'Evidence page', 'Evidence · 原文证据与页码':'Evidence · original quotes and pages',
    '下载 Markdown 分析报告':'Download Markdown report',
    '历史类型':'Task type', '历史页码':'History page', '本页没有记录。':'No records on this page.', '查看结果':'View result', '删除记录':'Delete record',
    '在 Paper Reader 中打开':'Open in Paper Reader', '在 Discover 中查看结果':'View in Discover',
    '任务尚未完成或正在等待中断恢复。':'Task is unfinished or awaiting interruption recovery.',
    '重新执行历史任务（忽略缓存，可能产生费用）':'Rerun task (ignore cache; fees may apply)',
    '重新执行本地论文任务前，请在 PDF 页面重新上传相同内容的文件。历史报告无需原文件即可查看。':'Reupload the same local PDF before rerunning. Saved reports do not require the original file.',
    '记录已删除。':'Record deleted.', '检测 MCP 连接':'Check MCP connection',
    '重新执行：忽略历史缓存':'Rerun: ignore history cache', '开启后，下一次分析或推荐不复用源论文报告，可能产生平台费用。':'When enabled, analysis and recommendation do not reuse the source report; provider fees may apply.',
    '修改超时、模型和预算请编辑 .env 后重启服务；不在界面展示密钥。':'Edit .env and restart to change models, timeouts and budgets. Keys are not displayed.',
    '未配置模型密钥；检索可用，分析和推荐需先配置。':'No model key configured. Search works; analysis and recommendation require configuration.',
    'Agent Execution Trace / 完整任务诊断':'Agent execution trace / task diagnostics',
    '工具执行记录，不是隐藏推理。父操作耗时包含子调用，不能相加。':'Tool execution records, not hidden reasoning. Parent timings include child calls.',
    '下载完整任务结果 JSON':'Download full task JSON', '清除本会话结果与上传文件':'Clear session results and uploads',
    '本地单用户模式。清除会话不会删除 SQLite 历史或收藏。':'Local single-user mode. Clearing the session does not delete SQLite history or favorites.',
    '本地单用户模式：所有浏览器会话共享历史。session_id 不是身份认证。':'Local single-user mode: browser sessions share history. session_id is not authentication.',
    'success · 完整任务成功':'success · Task completed', 'partial · 有有效结果，任务或覆盖不完整':'partial · Valid results; task or coverage incomplete',
    'failed · 任务失败':'failed · Task failed', 'timeout · 超时，已有有效结果仍保留':'timeout · Timed out; valid results retained',
    '已有任务或缓存结果，未重复启动。':'An existing task or cached result prevents duplicate execution.',
    '任务在后台运行；切换页面不会再次启动。':'Task runs in the background; switching pages does not restart it.',
    '研究统计暂不可用。':'Research statistics are unavailable.', '无法读取研究概览，请检查数据库。':'Unable to load the overview; check the database.',
    '文献库操作失败，检索结果已保留。':'Library operation failed; search results are retained.',
    '文献库操作失败，请检查数据库；已有数据不会被清空。':'Library operation failed; check the database. Existing data is retained.',
    '文献库读写失败，未更改收藏状态。':'Library access failed; favorite status was not changed.',
    'PDF 预览失败，已完成的分析仍保留。':'PDF preview failed; completed analysis is retained.',
    '在线论文编号无效，不能预览。':'Invalid arXiv ID; preview is unavailable.', '无法建立本地论文上下文。':'Unable to create local paper context.',
    '历史数据库读取或删除失败，请检查数据库权限。':'History access or deletion failed; check database permissions.',
    '无法读取历史结果，记录可能损坏或数据库不可用。':'Unable to load history; the record may be invalid or the database unavailable.',
    '无法打开候选论文。':'Unable to open the candidate paper.',
    '配置校验失败，请检查 .env。页面不显示配置原值或密钥。':'Invalid configuration; check .env. Configuration values and keys are not displayed.',
    '历史数据库初始化失败，请检查路径、权限和磁盘空间。':'Database initialization failed; check path, permissions and disk space.',
    '在线预览依赖浏览器与 arXiv 网络。若浏览器忽略 #page，请在 PDF 阅读器中输入上述页码；不提供自动高亮。':'Online preview depends on the browser and arXiv network. If #page is ignored, enter the shown page manually. Automatic highlighting is unavailable.',
    '允许重试此任务（可能产生平台费用）':'Allow retry (provider fees may apply)',
    '后端没有返回符合条件的推荐论文。':'The backend returned no qualifying recommendations.',
    '实际 arXiv 检索查询':'Actual arXiv search queries',
    '请选择名称有效的 PDF 文件，不能包含路径。':'Choose a valid PDF filename without a path.',
    'PDF 为空或超过上传大小上限。':'PDF is empty or exceeds the upload size limit.',
    '文件内容不是 PDF。':'File content is not a PDF.', '暂不支持加密 PDF。':'Encrypted PDFs are not supported.',
    'PDF 损坏或超过页数上限。':'PDF is damaged or exceeds the page limit.',
    'PDF 无法打开，可能已损坏。':'Cannot open the PDF; it may be damaged.',
    '每个会话最多保留 5 个 PDF，请先清除会话文件。':'A session can retain up to 5 PDFs. Clear session files first.',
    '尚未检测':'Not checked', '最近任务已连接；连接现已释放':'Last task connected; connection released',
    '最近任务未确认连接':'Last task did not confirm a connection',
}

PREFIX = {'检索：':'Search: ', '匹配记录：':'Matching records: ', '保留的检索结果：':'Retained search results: ', '当前来源：':'Source: ', '当前模型：':'Model: ',
          '后端连接：':'Backend connection: ', '推荐理由：':'Reason: ', '研究联系：':'Connection: ',
          '主要差异：':'Differences: ', '关键词：':'Keywords: ', '方法：':'Methods: ', '提示：':'Warning: ', '依据：':'Evidence: '}


def translate(text, language=None):
    if not isinstance(text, str):
        return text
    language = language or native.session_state.get('pra', {}).get('ui_language', 'zh')
    if language != 'en':
        return text
    if text in EN:
        return EN[text]
    if text == '最近 1 年':
        return 'Last year'
    for prefix, replacement in PREFIX.items():
        if text.startswith(prefix):
            return replacement + translate(text[len(prefix):], 'en')
    match = re.fullmatch(r'(.*) · (待读|阅读中|已读)', text)
    if match:
        return match[1] + ' · ' + EN[match[2]]
    match = re.fullmatch(r'(论文检索|论文分析|相关推荐) · (.*)', text)
    if match:
        return EN[match[1]] + ' · ' + match[2]
    rules = [
        (r'最近 (\d+) 年', r'Last \1 years'), (r'查看任务 #(\d+)', r'View task #\1'),
        (r'历史记录 #(\d+)', r'History #\1'), (r'耗时 ([\d.]+) 秒', r'Elapsed: \1 s'),
        (r'定位 PDF 第 (\d+) 页', r'Go to PDF page \1'),
        (r'(.*) · PDF 第 (\d+) 页', r'\1 · PDF page \2'),
        (r'实际 PDF 第 (\d+) 页；引用页码采用 PDF 页序号。', r'Original PDF page \1; citations use PDF page order.'),
        (r'新窗口打开 PDF · 第 (\d+) 页', r'Open PDF in new window · page \1'),
        (r'(.*) · (\d+) 页 · ([\d.]+) MiB', r'\1 · \2 pages · \3 MiB'),
        (r'执行中 · (.*) · (\d+) 秒', r'Running · \1 · \2 s'),
        (r'历史缓存命中：来源记录 #(\d+)，本次未调用 LLM 或 MCP。', r'History cache hit: record #\1. No LLM or MCP call this time.'),
        (r'相关性 ([\d.]+) · 依据：标题与摘要', r'Relevance \1 · Basis: title and abstract'),
        (r'相关性评分：([\d.]+)（模型估计） · 依据：标题和摘要，未读取候选全文', r'Relevance: \1 (model estimate) · Basis: titles and abstracts, not full text'),
        (r'单任务 ([\d.]+) 秒 · 单请求 ([\d.]+) 秒 · 上传 ([\d.]+) MiB / (\d+) 页', r'Task \1 s · Request \2 s · Upload \3 MiB / \4 pages'),
        (r'已打开历史分析 #(\d+) · 模型 (.*)。查看不会调用 LLM；新任务仍校验模型与提示词缓存版本。', r'Saved analysis #\1 · Model \2. Viewing makes no LLM call; new tasks still validate model and prompt versions.'),
    ]
    for pattern, replacement in rules:
        if re.fullmatch(pattern, text):
            return re.sub(pattern, replacement, text)
    return text


class Localized:
    """Small facade over native components; data outputs are never translated."""
    labels = {'title','header','subheader','caption','button','checkbox','selectbox','slider',
              'number_input','text_input','file_uploader','form_submit_button','download_button',
              'link_button','expander','status','info','warning','error','success','metric'}

    def __init__(self, target):
        self.target = target

    def __enter__(self):
        self.target.__enter__()
        return self

    def __exit__(self, *args):
        return self.target.__exit__(*args)

    def __getattr__(self, name):
        value = getattr(self.target, name)
        if isinstance(value, DeltaGenerator):
            return Localized(value)
        if name not in self.labels | {'columns', 'container', 'form'}:
            return value
        def call(*args, **kwargs):
            if name in self.labels and args:
                args = (translate(args[0]), *args[1:])
            for key in ('label', 'help', 'placeholder'):
                if key in kwargs:
                    kwargs[key] = translate(kwargs[key])
            if name == 'selectbox':
                formatter = kwargs.get('format_func', str)
                kwargs['format_func'] = lambda option: translate(formatter(option))
            result = value(*args, **kwargs)
            if isinstance(result, DeltaGenerator):
                return Localized(result)
            if name == 'columns':
                return [Localized(column) for column in result]
            return result
        return call


st = Localized(native)


def preference_controls(state):
    with native.sidebar:
        state['ui_language'] = native.selectbox('语言 / Language', ['zh', 'en'],
            index=['zh','en'].index(state.get('ui_language','zh')),
            format_func=lambda value: {'zh':'中文','en':'English'}[value], key='ui_language_choice')
