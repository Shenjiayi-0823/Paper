"""Bounded text extraction from uploads or official arXiv PDF URLs."""

import logging
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

import pymupdf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from paper_research_agent.config import PROJECT_ROOT, Settings, load_settings
from .models import PDFPage, PDFResult, ToolError

logger = logging.getLogger(__name__)
UPLOADS_DIR = PROJECT_ROOT / "uploads"
ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?:v[1-9]\d*)?", re.ASCII)
TRUSTED_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}


class PDFError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _validate_id(value: str | None) -> str:
    if not isinstance(value, str) or not ARXIV_ID.fullmatch(value):
        raise PDFError("invalid_arxiv_id", "Supply an arXiv ID, such as 1706.03762 or hep-th/9901001; URLs are not accepted.")
    number = value.split("v", 1)[0].split("/")[-1]
    month = int(number[2:4])
    if not 1 <= month <= 12:
        raise PDFError("invalid_arxiv_id", "The arXiv ID has an invalid month.")
    return value


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise PDFError("unsafe_redirect", "The PDF redirect target is not an allowed HTTPS arXiv host.")


def _download_pdf(arxiv_id: str, settings: Settings) -> bytes:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    with requests.Session() as session:
        session.trust_env = False  # Do not inherit ambient proxies or netrc credentials.
        retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"], respect_retry_after_header=False)
        session.mount("https://", HTTPAdapter(max_retries=retry))
        for _ in range(6):
            _validate_url(url)  # Check before sending each request, including redirects.
            with session.get(url, stream=True, allow_redirects=False,
                             timeout=settings.request_timeout_seconds) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise PDFError("download_failed", "Redirect response has no Location header.")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if mime not in ("application/pdf", "application/octet-stream"):
                    raise PDFError("not_pdf", "arXiv returned a non-PDF content type.")
                length = response.headers.get("Content-Length")
                if length and int(length) > settings.pdf_max_bytes:
                    raise PDFError("size_limit", "PDF exceeds PDF_MAX_BYTES.")
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > settings.pdf_max_bytes:
                        raise PDFError("size_limit", "PDF exceeds PDF_MAX_BYTES during download.")
                return bytes(content)
        raise PDFError("download_failed", "Too many PDF redirects.")


def _read_local(file_path: str | None, settings: Settings) -> tuple[str, bytes]:
    if not isinstance(file_path, str) or not file_path.strip():
        raise PDFError("invalid_input", "file_path is required for local mode.")
    root = UPLOADS_DIR.resolve()
    supplied = Path(file_path)
    # Relative paths are relative to uploads; absolute paths within uploads are allowed.
    if ".." in supplied.parts:
        raise PDFError("path_not_allowed", "Parent directory traversal is not allowed.")
    path = (supplied if supplied.is_absolute() else root / supplied).resolve()
    if not path.is_relative_to(root):
        raise PDFError("path_not_allowed", "Local PDFs must be inside the project uploads directory.")
    if path.suffix.lower() != ".pdf":
        raise PDFError("not_pdf", "The local file must have a .pdf extension.")
    if not path.is_file():
        raise PDFError("file_not_found", "The requested PDF file does not exist.")
    if path.stat().st_size > settings.pdf_max_bytes:
        raise PDFError("size_limit", "PDF exceeds PDF_MAX_BYTES.")
    with path.open("rb") as handle:
        content = handle.read(settings.pdf_max_bytes + 1)
    if len(content) > settings.pdf_max_bytes:
        raise PDFError("size_limit", "PDF exceeds PDF_MAX_BYTES.")
    return path.relative_to(root).as_posix(), content


def _extract(content: bytes, result: PDFResult, settings: Settings) -> None:
    if not content.startswith(b"%PDF-"):
        raise PDFError("not_pdf", "File content does not start with a PDF header.")
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise PDFError("corrupt_pdf", "Unable to open the PDF; it may be damaged.") from exc
    with document:
        result.total_pages = document.page_count
        if document.needs_pass:
            raise PDFError("encrypted_pdf", "Password-protected PDFs are not supported.")
        if document.is_repaired:
            raise PDFError("corrupt_pdf", "PDF required structural repair; reliable extraction is not guaranteed.")
        if document.page_count > settings.pdf_max_pages:
            raise PDFError("page_limit", "PDF exceeds PDF_MAX_PAGES; no partial report is returned.")
        pages, chars = [], 0
        for index, page in enumerate(document):
            text = page.get_text("text")
            chars += len(text) + (2 if index else 0)
            if chars > settings.pdf_max_text_chars:
                raise PDFError("text_limit", "Extracted text exceeds PDF_MAX_TEXT_CHARS; no partial report is returned.")
            pages.append(PDFPage(page_number=index + 1, text=text))
            if not text.strip():
                result.warnings.append(f"Page {index + 1} has no extractable text; it may need OCR.")
        result.pages = pages
        result.full_text = "\n\n".join(p.text for p in pages)
        if not result.full_text.strip():
            raise PDFError("no_text", "No extractable text found. This may be a scanned PDF; OCR is not implemented.")
        result.success = True
        if result.warnings:
            result.warnings.append("Text extraction is incomplete on the indicated pages; no OCR was performed.")


def read_pdf(source_type: str, file_path: str | None = None,
             arxiv_id: str | None = None) -> PDFResult:
    result = PDFResult(source_type=source_type if isinstance(source_type, str) else "")
    try:
        settings = load_settings()
        if source_type == "local":
            if arxiv_id is not None:
                raise PDFError("invalid_input", "Do not supply arxiv_id in local mode.")
            result.document_id, content = _read_local(file_path, settings)
        elif source_type == "arxiv":
            if file_path is not None:
                raise PDFError("invalid_input", "Do not supply file_path in arxiv mode.")
            result.document_id = _validate_id(arxiv_id)
            content = _download_pdf(result.document_id, settings)
        else:
            raise PDFError("invalid_input", "source_type must be local or arxiv.")
        _extract(content, result, settings)
    except PDFError as exc:
        result.error = ToolError(code=exc.code, message=exc.message)
    except requests.RequestException:
        result.error = ToolError(code="download_failed", message="arXiv PDF download failed or timed out after retries.")
    except OSError:
        result.error = ToolError(code="file_error", message="Unable to read the local PDF file.")
    except Exception:
        logger.exception("Unexpected PDF tool error")
        result.error = ToolError(code="internal_error", message="Unable to extract PDF text reliably.")
    return result
