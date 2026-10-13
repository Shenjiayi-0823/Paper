"""Native workspace shell and real-data research context."""
from .i18n import st
from paper_research_agent.database.library import LibraryService
from .workflow import navigate

NAVIGATION = {
    'Dashboard': ('研究概览', ':material/dashboard:'),
    'Discover': ('文献发现', ':material/search:'),
    'Paper Reader': ('论文阅读', ':material/menu_book:'),
    'Related Research': ('相关研究', ':material/hub:'),
    'Library': ('我的文献库', ':material/local_library:'),
    'History': ('历史记录', ':material/history:'),
    'Settings': ('设置与诊断', ':material/settings:'),
}


def theme_css():
    values = {'bg':'#F8FAFC','surface':'#FFFFFF','text':'#18212F','muted':'#596579','border':'#D5DDE7','selected':'#DFE8F1'}
    variables = ';'.join('--pra-' + key + ':' + value for key, value in values.items())
    return ':root {' + variables + ';}' + '''
      .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stHeader"] {
        background:var(--pra-bg)!important; color:var(--pra-text)!important;
      }
      [data-testid="stSidebar"] {background:var(--pra-surface)!important; border-right:1px solid var(--pra-border);}
      h1,h2,h3,h4,p,label,[data-testid="stText"], [data-testid="stMetricValue"] {color:var(--pra-text)!important;}
      [data-testid="stCaptionContainer"] p {color:var(--pra-muted)!important;}
      input,textarea,[data-baseweb="select"]>div,[data-baseweb="input"],
      [role="listbox"],[data-baseweb="popover"],[data-baseweb="menu"],
      [data-testid="stFileUploaderDropzone"] {
        background:var(--pra-surface)!important; color:var(--pra-text)!important;
      }
      [data-baseweb="select"] span,[role="option"] {color:var(--pra-text)!important;}
      [role="option"] {background:var(--pra-surface)!important;}
      [role="option"]:hover {background:var(--pra-selected)!important;}
      [data-testid^="stBaseButton-"] {color:var(--pra-text)!important; border-color:var(--pra-border)!important;}
      [data-testid="stBaseButton-secondary"] {background:var(--pra-surface)!important;}
      [data-testid="stBaseButton-primary"] {background:var(--pra-selected)!important;}
      [data-testid^="stBaseButton-"]:disabled {opacity:.45;}
      [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {background:var(--pra-selected)!important;}
      [data-testid="stExpander"] details, [data-testid="stVerticalBlockBorderWrapper"] {
        border-color:var(--pra-border)!important;
      }
      [data-testid="stAlert"] {background:var(--pra-surface)!important; border:1px solid var(--pra-border);}
      pre,code {background:var(--pra-surface)!important; color:var(--pra-text)!important;}
      .paper-card-abstract {color:var(--pra-muted)!important;}
    '''


def style():
    # Only presentation styling; native widgets retain accessibility and events.
    st.html('<style>' + theme_css() + '''
      .stMainBlockContainer {padding-top:2rem; max-width:1600px;}
      [data-testid="stSidebar"] button {justify-content:flex-start; min-height:3rem; border:0;}
      [data-testid="stVerticalBlockBorderWrapper"] {border-radius:12px;}
      h1, h2, h3 {letter-spacing:-0.025em;}
      .paper-card-title {font-size:1.2rem; font-weight:600; padding:0; margin:0 0 .6rem;}
      .paper-card-abstract {font-size:.95rem; line-height:1.6; margin:.5rem 0;}
      [class*="st-key-history_row_"] button {justify-content:flex-start; text-align:left; font-weight:600;}
      [data-testid="stMetricValue"] {font-size:2rem;}
      @media (max-width:900px) {
        .stMainBlockContainer {padding:1rem;}
      }
    </style>''')


def navigation(state):
    with st.sidebar:
        st.caption('PAPER RESEARCH WORKSPACE')
        for group, names in [('WORKSPACE', list(NAVIGATION)[:4]), ('LIBRARY', ['Library', 'History']), ('', ['Settings'])]:
            if group:
                st.caption(group)
            for name in names:
                label, icon = NAVIGATION[name]
                if st.button(label, icon=icon, key='nav_' + name, width='stretch',
                             type='primary' if state['page'] == name else 'tertiary'):
                    navigate(state, name)
            st.divider()
        st.caption('本地单用户模式')


def research_context(state):
    st.subheader('研究上下文')
    current = state.get('current_paper')
    theme = state.get('search_query') or '尚未开始检索'
    if current:
        recommendation = state['recommendations'].get(current['source_key'], {})
        theme = recommendation.get('theme', {}).get('research_theme') or current['paper'].get('title', theme)
    st.caption('当前研究主题')
    st.write(theme)
    st.divider()
    try:
        counts = LibraryService(state['history']).overview()
        st.metric('已收藏论文', counts['library'])
        st.metric('已完成分析', counts['analyses'])
        st.divider()
        st.subheader('最近任务')
        labels = {'search': '论文检索', 'analysis': '论文分析', 'recommendation': '相关推荐'}
        for row in state['history'].list_query_history(page_size=3):
            st.caption(labels.get(row.query_type, row.query_type) + ' · ' + row.status)
            if st.button('查看任务 #' + str(row.id), key='context_history_' + str(row.id), type='tertiary'):
                state['history_selected'] = row.id
                navigate(state, 'History')
    except Exception:
        st.warning('研究统计暂不可用。')
