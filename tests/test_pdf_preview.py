"""Mock HTTP preview tests; no real arXiv or model calls."""
import requests
import pytest
from paper_research_agent.config import Settings
from paper_research_agent.ui.uploads import UploadStore
from paper_research_agent.ui.pdf_preview import load_online_preview
from paper_research_agent.ui.reader_page import render_pdf_page
from test_pdf import make_pdf
from test_workflow import app_setup, history
from test_analysis import paper


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data = make_pdf() if data is None else data
        self.status_code = status
        self.headers = headers or {'Content-Type':'application/pdf'}
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)
    def iter_content(self,chunk_size):
        yield self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def store(tmp_path):
    value = UploadStore(root=tmp_path)
    yield value
    value.cleanup()


def test_preview_download_and_render(store):
    session = Session([Response()])
    outcome = load_online_preview('1706.03762v1',store,Settings(),session_factory=lambda:session)
    assert outcome.success and outcome.usage == {}
    upload = store.files[outcome.data['preview']['digest']]
    assert render_pdf_page(store,upload.relative_path,1).startswith(b'\x89PNG')
    assert session.calls[0][0] == 'https://arxiv.org/pdf/1706.03762v1'
    assert session.calls[0][1]['allow_redirects'] is False and session.trust_env is False


@pytest.mark.parametrize('location',['https://evil.example/pdf','http://arxiv.org/pdf/1706.03762','https://arxiv.org:8080/pdf/x'])
def test_redirect_is_validated_before_request(store,location):
    session = Session([Response(status=302,headers={'Location':location})])
    outcome = load_online_preview('1706.03762',store,Settings(),session_factory=lambda:session)
    assert outcome.error['code'] == 'unsafe_redirect' and len(session.calls) == 1
    assert not store.files


@pytest.mark.parametrize('response,settings,code',[
    (Response(headers={'Content-Type':'text/html'}),Settings(),'not_pdf'),
    (Response(data=b'not PDF'),Settings(),'invalid_preview'),
    (Response(),Settings(pdf_max_bytes=10),'size_limit'),
    (Response(headers={'Content-Type':'application/pdf','Content-Length':'99999999'}),Settings(),'size_limit'),
    (Response(status=429),Settings(),'download_failed'),
    (requests.Timeout('private details'),Settings(),'tool_timeout'),
])
def test_preview_failures_are_safe(store,response,settings,code):
    session = Session([response])
    outcome = load_online_preview('1706.03762',store,settings,session_factory=lambda:session)
    assert not outcome.success and outcome.error['code'] == code
    assert 'private details' not in str(outcome) and not store.files


def test_online_reader_preview_only_on_click(monkeypatch,history):
    from paper_research_agent.ui.workflow import select_paper
    import paper_research_agent.ui.reader_page as reader
    at,calls = app_setup(monkeypatch,history)
    state = at.session_state['pra']
    select_paper(state,history,paper('1706.00001'))
    preview_calls = []
    def download(ident,uploads,settings,progress):
        preview_calls.append(ident)
        session = Session([Response()])
        return load_online_preview(ident,uploads,settings,progress,session_factory=lambda:session)
    monkeypatch.setattr(reader,'load_online_preview',download)
    at.button(key='nav_Paper Reader').click().run()
    assert preview_calls == [] and calls == []
    at.button(key='load_online_pdf').click().run()
    for _ in range(4):
        at.run()
        if state['job'] is None:
            break
    assert not at.exception and preview_calls == ['1706.00001']
    assert state['pdf_previews']['arxiv:1706.00001']['pages'] == 1
    assert state['current_paper']['args']['source_type'] == 'arxiv'
    assert calls == [] and history.list_query_history() == []
    at.run()
    assert preview_calls == ['1706.00001']
    state['uploads'].cleanup()
