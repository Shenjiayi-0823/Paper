import asyncio
import importlib
from pathlib import Path
import time
from types import SimpleNamespace as NS
from contextlib import asynccontextmanager

import pytest
from streamlit.testing.v1 import AppTest

from paper_research_agent.config import Settings, PROJECT_ROOT
from paper_research_agent.ui.backend import WebBackend, TaskOutcome, task_status
from paper_research_agent.ui.uploads import UploadStore, validate_pdf
from paper_research_agent.ui.state import initialize, start_job, poll_job
from paper_research_agent.ui.formatters import paper_view, report_view, recommendation_view, markdown_report, safe_link
from test_pdf import make_pdf
from test_analysis import analyze, topic, paper, ranked


@pytest.mark.parametrize('name',['app','components','search_page','analysis_page','recommend_page','state','formatters','uploads','backend'])
def test_ui_module_imports(name):
    assert importlib.import_module('paper_research_agent.ui.'+name)


def test_search_format_and_link_safety():
    data = {**paper('1706.00001'),'published':'2017-06-01T00:00:00Z'}
    view = paper_view(data)
    assert view['authors'] == 'Actual Author' and view['published'] == '2017-06-01'
    assert view['pdf_url'] == data['pdf_url']
    assert safe_link('javascript:alert(1)') is None
    assert safe_link('https://evil.example/pdf') is None


def test_report_conversion_and_export():
    data = analyze().model_dump()
    view = report_view(data)
    assert view['evidence']['c1-e1'].page_number == 1
    text = markdown_report(data)
    assert 'Research Problem' in text and 'page 1' in text
    assert 'We use scheduling.' in text and '作者陈述' in text


def test_recommendation_format_preserves_metadata_and_score():
    data = {'source_document_id':'source.pdf','theme':topic(),'queries':['all:"energy"'],
        'papers':[{**ranked('1706.00001'),**paper('1706.00001'),'evidence_basis':'title_and_abstract'}]}
    result,views = recommendation_view(data)
    assert result.queries == ['all:"energy"'] and views[0]['score'] == 0.8
    assert views[0]['reason'] == 'method similarity'


@pytest.mark.parametrize('outcome,status',[
    (TaskOutcome(success=True,data={'papers':[]}), 'success'),
    (TaskOutcome(success=False,data={'recommendations':{'papers':[{}]}},error={'code':'backend_error'}),'partial'),
    (TaskOutcome(error={'code':'backend_error'}),'failed'),
    (TaskOutcome(error={'code':'task_timeout'},data={'analysis':{'title':'valid'}}),'timeout'),
    (TaskOutcome(error={'code':'invalid_evidence','secondary_error':{'code':'task_timeout'}}),'timeout'),
    (TaskOutcome(success=True,data={'analysis':{'complete':False}}),'partial'),
])
def test_status_mapping(outcome,status):
    assert task_status(outcome) == status


@pytest.mark.parametrize('name,data,limit',[
    ('../paper.pdf',b'%PDF-',100),('C:\\paper.pdf',b'%PDF-',100),('file.txt',b'%PDF-',100),
    ('paper.pdf',b'not pdf',100),('paper.pdf',make_pdf(),10),('paper.pdf',b'%PDF-broken',100),
])
def test_invalid_uploads(name,data,limit):
    with pytest.raises(ValueError):
        validate_pdf(name,data,limit,50)


def test_upload_isolation_dedup_and_cleanup(tmp_path):
    settings = Settings()
    a,b = UploadStore(root=tmp_path),UploadStore(root=tmp_path)
    data = make_pdf()
    first = a.save('paper.pdf',data,settings)
    assert a.save('again.pdf',data,settings) == first
    other = b.save('paper.pdf',data,settings)
    assert first.relative_path != other.relative_path
    assert a.owns(first.relative_path) and not a.owns(other.relative_path)
    assert not a.owns('../outside.pdf')
    a.cleanup()
    assert b.owns(other.relative_path)
    b.cleanup()
    assert not list(tmp_path.iterdir())


def test_initial_state_and_job_dedup():
    mapping = {}
    state = initialize(mapping)
    assert initialize(mapping) is state and state['search'] == []
    calls = []
    def runner(progress):
        calls.append(1)
        progress('Mock progress')
        return TaskOutcome(success=True,data={'papers':[paper('1706.00001')]})
    assert start_job(state,'key','search',None,runner)
    assert not start_job(state,'key','search',None,runner)
    state['job'].future.result(timeout=2)
    assert poll_job(state) and len(calls) == 1
    assert state['search'][0]['arxiv_id'] == '1706.00001'
    assert not start_job(state,'key','search',None,runner)
    state['uploads'].cleanup()


def test_unexpected_job_exception_is_sanitized():
    state = initialize({})
    def runner(progress):
        raise RuntimeError('secret-key-should-not-be-shown')
    start_job(state,'bad','search',None,runner)
    state['job'].future.result(timeout=2)
    poll_job(state)
    assert task_status(state['last']) == 'failed'
    assert 'secret-key' not in str(state['last'].error)
    state['uploads'].cleanup()


class FakeClient:
    tools = {'search_arxiv':object(),'read_pdf':object()}
    def __init__(self):
        self.closed = False
    @asynccontextmanager
    async def connect(self):
        try:
            yield self
        finally:
            self.closed = True
    async def call_tool(self,name,args):
        return {'success':True,'papers':[paper('1706.00001')],'warnings':[]}


def test_backend_search_uses_mcp_without_llm(tmp_path):
    client = FakeClient()
    backend = WebBackend(Settings(),UploadStore(root=tmp_path),mcp_factory=lambda:client,
        llm_factory=lambda:pytest.fail('Search must not call LLM'))
    outcome = backend.run('search',{'query':'energy','max_results':5})
    assert outcome.success and client.closed
    assert outcome.trace[0]['name'] == 'search_arxiv' and outcome.trace[0]['elapsed_seconds'] >= 0


def test_backend_rejects_other_session_source(tmp_path):
    store = UploadStore(root=tmp_path)
    backend = WebBackend(Settings(),store,mcp_factory=lambda:pytest.fail('Must reject before MCP'))
    outcome = backend.run('analyze_paper',{'source_type':'local','file_path':'../paper.pdf'})
    assert outcome.error['code'] == 'upload_not_owned'


def test_backend_partial_recommendation_preserves_valid_analysis(tmp_path):
    store = UploadStore(root=tmp_path)
    upload = store.save('source.pdf',make_pdf(),Settings())
    cached = analyze().model_copy(update={'document_id':upload.relative_path}).model_dump()
    class BrokenLLM:
        def __init__(self):
            self.chat = NS(completions=NS(create=self.create))
            self.closed = False
        async def create(self,**kwargs):
            raise RuntimeError('private-key')
        async def close(self):
            self.closed = True
    sdk = BrokenLLM()
    backend = WebBackend(Settings(),store,mcp_factory=FakeClient,llm_factory=lambda:sdk)
    outcome = backend.run('recommend_related',{'source_type':'local','file_path':upload.relative_path,'language':'中文'},analysis=cached)
    assert task_status(outcome) == 'partial' and not outcome.success
    assert outcome.data['analysis']['document_id'] == upload.relative_path
    assert sdk.closed and 'private-key' not in str(outcome.error)
    store.cleanup()


def test_streamlit_app_and_search_click_does_not_repeat(monkeypatch):
    import paper_research_agent.ui.app as app
    calls = []
    class FakeBackend:
        def __init__(self,*args):
            pass
        def run(self,operation,args,progress=None,analysis=None):
            calls.append(operation)
            if progress:
                progress('Mock search')
            return TaskOutcome(success=True,connected=True,data={'papers':[paper('1706.00001')]})
    monkeypatch.setattr(app,'WebBackend',FakeBackend)
    at = AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=10).run()
    assert not at.exception
    assert [tab.label for tab in at.tabs] == ['Paper Search','PDF Analysis','Related Papers']
    at.text_input[0].set_value('energy')
    at.button(key='FormSubmitter:paper_search-检索论文').click().run()
    for _ in range(3):
        if at.session_state['pra']['job'] is None:
            break
        time.sleep(0.01)
        at.run()
    assert not at.exception and calls == ['search']
    assert at.session_state['pra']['search'][0]['arxiv_id'] == '1706.00001'
    at.run()
    assert calls == ['search'] and not at.exception
    at.session_state['pra']['uploads'].cleanup()


def test_upload_analysis_recommendation_and_failure_preserve_report(monkeypatch):
    import paper_research_agent.ui.app as app
    monkeypatch.setattr(app,'load_settings',lambda:Settings(openai_api_key='mock-only-key'))
    base_report = analyze().model_dump()
    calls = []
    class FakeBackend:
        def __init__(self,*args):
            pass
        def run(self,operation,args,progress=None,analysis=None):
            calls.append((operation,analysis is not None))
            report = {**base_report,'document_id':args['file_path']}
            return TaskOutcome(success=operation=='analyze_paper',connected=True,data={'analysis':report},
                error=None if operation=='analyze_paper' else {'code':'search_tool_error','message':'Mock search failed'})
    monkeypatch.setattr(app,'WebBackend',FakeBackend)
    at = AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=10).run()
    pdf_bytes = make_pdf()
    at.file_uploader[0].set_value(('source.pdf',pdf_bytes,'application/pdf')).run()
    assert not at.exception
    at.button(key='analyze_upload').click().run()
    for _ in range(3):
        at.run()
        if at.session_state['pra']['job'] is None:
            break
    assert not at.exception and len(at.session_state['pra']['analyses']) == 1
    assert calls == [('analyze_paper',False)]
    # The same content uploaded on a different tab reuses the session file/report.
    at.file_uploader[1].set_value(('renamed.pdf',pdf_bytes,'application/pdf')).run()
    assert len(at.session_state['pra']['uploads'].files) == 1
    at.button(key='recommend_upload_button').click().run()
    for _ in range(3):
        at.run()
        if at.session_state['pra']['job'] is None:
            break
    assert not at.exception and calls[-1] == ('recommend_related',True)
    assert task_status(at.session_state['pra']['last']) == 'partial'
    assert len(at.session_state['pra']['analyses']) == 1
    assert at.download_button
    at.session_state['pra']['uploads'].cleanup()


def test_web_adapter_real_stdio_local_pdf_with_mock_llm(tmp_path):
    import json
    import sys
    from mcp import StdioServerParameters
    from paper_research_agent.agent.mcp_client import MCPClient
    from test_agent import response
    store = UploadStore(root=tmp_path)
    record = store.save('paper.pdf',make_pdf(),Settings())
    class SDK:
        def __init__(self):
            self.closed = False
            self.chat = NS(completions=NS(create=self.create))
        async def create(self,**kwargs):
            data = json.loads(kwargs['messages'][-1]['content'])
            ident = data['evidence_catalog'][0]['id']
            return response(text=json.dumps({'methodology':[{'text':'Test inference','provenance':'inference','evidence_ids':[ident]}]}))
        async def close(self):
            self.closed = True
    sdk = SDK()
    factory = lambda:MCPClient(StdioServerParameters(command=sys.executable,
        args=[str(PROJECT_ROOT/'tests'/'mcp_fixture_server.py'),str(tmp_path)],cwd=str(PROJECT_ROOT)),timeout=10)
    backend = WebBackend(Settings(),store,mcp_factory=factory,llm_factory=lambda:sdk)
    outcome = backend.run('analyze_paper',{'source_type':'local','file_path':record.relative_path,'language':'中文'})
    assert outcome.success and outcome.connected and sdk.closed
    assert outcome.data['analysis']['document_id'] == record.relative_path
    assert 'Research methods' in outcome.data['analysis']['evidence'][0]['quote']
    assert outcome.trace[0]['name'] == 'read_pdf'
    store.cleanup()


def test_web_task_timeout_preserves_cached_source_and_closes_clients(tmp_path):
    store = UploadStore(root=tmp_path)
    record = store.save('source.pdf',make_pdf(),Settings())
    cached = analyze().model_copy(update={'document_id':record.relative_path}).model_dump()
    class SlowSDK:
        closed = False
        def __init__(self):
            self.chat = NS(completions=NS(create=self.create))
        async def create(self,**kwargs):
            await asyncio.sleep(1)
        async def close(self):
            self.closed = True
    sdk,client = SlowSDK(),FakeClient()
    backend = WebBackend(Settings(agent_task_timeout_seconds=0.03),store,mcp_factory=lambda:client,llm_factory=lambda:sdk)
    outcome = backend.run('recommend_related',{'source_type':'local','file_path':record.relative_path,'language':'中文'},analysis=cached)
    assert task_status(outcome) == 'timeout' and outcome.data['analysis']
    assert sdk.closed and client.closed
    store.cleanup()
