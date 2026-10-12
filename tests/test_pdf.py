from pathlib import Path
from unittest.mock import Mock
import os

import pymupdf
import pytest
import requests

from paper_research_agent.config import Settings
from paper_research_agent.mcp_server.tools import pdf_tool as tool


def make_pdf(text="Research methods and results", pages=1, encrypted=False):
    with pymupdf.open() as doc:
        for _ in range(pages):
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        if encrypted:
            return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
        return doc.tobytes()


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(tool, "UPLOADS_DIR", root)
    monkeypatch.setattr(tool, "load_settings", lambda: Settings())
    return root


def test_local(uploads):
    path = uploads / "paper.pdf"
    path.write_bytes(make_pdf())
    result = tool.read_pdf("local", "paper.pdf")
    assert result.success and result.total_pages == 1
    assert result.document_id == "paper.pdf"
    assert result.pages[0].page_number == 1
    assert "Research methods" in result.full_text
    assert tool.read_pdf("local", str(path)).success


def test_missing(uploads):
    assert tool.read_pdf("local", "absent.pdf").error.code == "file_not_found"


@pytest.mark.parametrize("path", ["../outside.pdf", "nested/../../outside.pdf"])
def test_traversal(uploads, path):
    assert tool.read_pdf("local", path).error.code == "path_not_allowed"


def test_absolute_outside(uploads):
    assert tool.read_pdf("local", str(uploads.parent / "outside.pdf")).error.code == "path_not_allowed"


@pytest.mark.parametrize("content,code", [(b"%PDF-broken", "corrupt_pdf"), (b"hello", "not_pdf")])
def test_corrupt(uploads, content, code):
    (uploads / "broken.pdf").write_bytes(content)
    assert tool.read_pdf("local", "broken.pdf").error.code == code


def test_scanned_and_encrypted(uploads):
    (uploads / "scan.pdf").write_bytes(make_pdf(text=""))
    result = tool.read_pdf("local", "scan.pdf")
    assert not result.success and result.error.code == "no_text" and result.warnings
    (uploads / "locked.pdf").write_bytes(make_pdf(encrypted=True))
    assert tool.read_pdf("local", "locked.pdf").error.code == "encrypted_pdf"


@pytest.mark.parametrize("value", ["bad", "https://arxiv.org/pdf/1706.03762", "1713.00001", "1706.03762/../../x", "1706.03762v0"])
def test_invalid_id(value):
    assert tool.read_pdf("arxiv", arxiv_id=value).error.code == "invalid_arxiv_id"


def test_download_failure(monkeypatch):
    monkeypatch.setattr(tool, "_download_pdf", Mock(side_effect=requests.Timeout()))
    assert tool.read_pdf("arxiv", arxiv_id="1706.03762").error.code == "download_failed"


def test_online_parse(monkeypatch):
    monkeypatch.setattr(tool, "_download_pdf", lambda *_: make_pdf())
    assert tool.read_pdf("arxiv", arxiv_id="1706.03762").success


@pytest.mark.parametrize("config,code", [(dict(pdf_max_bytes=10), "size_limit"), (dict(pdf_max_pages=1), "page_limit"), (dict(pdf_max_text_chars=2), "text_limit")])
def test_limits(uploads, monkeypatch, config, code):
    (uploads / "paper.pdf").write_bytes(make_pdf(pages=2))
    monkeypatch.setattr(tool, "load_settings", lambda: Settings(**config))
    result = tool.read_pdf("local", "paper.pdf")
    assert not result.success and result.error.code == code
    assert result.pages == [] and result.full_text == ""


def test_invalid_modes():
    assert tool.read_pdf("url").error.code == "invalid_input"
    assert tool.read_pdf("local", "a.pdf", "1706.03762").error.code == "invalid_input"


def response(status=200, headers=None, content=b"%PDF-test"):
    obj = Mock()
    obj.status_code = status
    obj.headers = headers or {"Content-Type": "application/pdf"}
    obj.iter_content.return_value = iter([content])
    obj.__enter__ = Mock(return_value=obj)
    obj.__exit__ = Mock(return_value=False)
    return obj


def mock_session(monkeypatch, responses):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.side_effect = responses
    monkeypatch.setattr(tool.requests, "Session", lambda: session)
    return session


def test_redirect_blocked_before_request(monkeypatch):
    session = mock_session(monkeypatch, [response(302, {"Location": "http://127.0.0.1/private"})])
    result = tool.read_pdf("arxiv", arxiv_id="1706.03762")
    assert result.error.code == "unsafe_redirect"
    assert session.get.call_count == 1


def test_allowed_redirect(monkeypatch):
    session = mock_session(monkeypatch, [response(302, {"Location": "https://export.arxiv.org/pdf/1706.03762"}), response(content=make_pdf())])
    assert tool.read_pdf("arxiv", arxiv_id="1706.03762").success
    assert session.get.call_count == 2
    assert session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("headers,content,config,code", [({"Content-Type": "text/html"}, b"html", {}, "not_pdf"), ({"Content-Type": "application/pdf", "Content-Length": "99"}, b"x", {"pdf_max_bytes": 10}, "size_limit"), ({"Content-Type": "application/pdf"}, b"x" * 11, {"pdf_max_bytes": 10}, "size_limit")])
def test_download_limits(monkeypatch, headers, content, config, code):
    mock_session(monkeypatch, [response(headers=headers, content=content)])
    monkeypatch.setattr(tool, "load_settings", lambda: Settings(**config))
    assert tool.read_pdf("arxiv", arxiv_id="1706.03762").error.code == code


@pytest.mark.parametrize("url", ["https://arxiv.org.evil.example/pdf/x", "https://arxiv.org@evil.example/x", "https://arxiv.org:444/x", "http://arxiv.org/x", "https://user:secret@arxiv.org/x"])
def test_untrusted_targets(url):
    with pytest.raises(tool.PDFError, match="allowed HTTPS"):
        tool._validate_url(url)


def test_partial_text_warning(uploads):
    with pymupdf.open(stream=make_pdf(), filetype="pdf") as doc:
        doc.new_page()
        (uploads / "partial.pdf").write_bytes(doc.tobytes())
    result = tool.read_pdf("local", "partial.pdf")
    assert result.success and result.total_pages == 2
    assert result.pages[1].text == ""
    assert any("incomplete" in warning for warning in result.warnings)


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_PDF") != "1", reason="Opt-in real arXiv PDF download")
def test_live_pdf():
    result = tool.read_pdf("arxiv", arxiv_id="1706.03762")
    assert result.success, result.error
    assert result.total_pages > 0 and "Attention" in result.full_text
