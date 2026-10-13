"""Display-only official PDF download; no extraction, analysis or LLM request."""
import re
import time
from urllib.parse import urljoin, urlsplit
import requests
from .backend import TaskOutcome


class PreviewError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def pdf_address(arxiv_id, page=1):
    if not isinstance(arxiv_id, str) or not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-zA-Z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?', arxiv_id):
        raise ValueError('Invalid arXiv ID')
    if page < 1:
        raise ValueError('Invalid page')
    return f'https://arxiv.org/pdf/{arxiv_id}#page={page}'


def trusted_url(url):
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == 'https' and parts.hostname in {'arxiv.org','www.arxiv.org','export.arxiv.org'}
                 and not parts.username and not parts.password and parts.port in (None,443))
    except ValueError:
        valid = False
    if not valid:
        raise PreviewError('unsafe_redirect', 'PDF preview redirect is not an allowed HTTPS arXiv address.')


def load_online_preview(arxiv_id, uploads, settings, progress=None, session_factory=requests.Session):
    started = time.monotonic()
    result = TaskOutcome()
    deadline = started + min(settings.agent_task_timeout_seconds, settings.agent_tool_timeout_seconds)
    try:
        url = pdf_address(arxiv_id).split('#')[0]
        if progress:
            progress('Downloading official PDF for page preview (no LLM call)')
        with session_factory() as session:
            session.trust_env = False
            for _ in range(6):
                trusted_url(url)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PreviewError('tool_timeout', 'PDF preview download exceeded its time limit.')
                timeout = min(settings.request_timeout_seconds, remaining)
                with session.get(url, stream=True, allow_redirects=False, timeout=(min(10,timeout),timeout)) as response:
                    if response.status_code in (301,302,303,307,308):
                        location = response.headers.get('Location')
                        if not location:
                            raise PreviewError('download_failed', 'PDF redirect has no target.')
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    mime = response.headers.get('Content-Type','').split(';')[0].strip().lower()
                    if mime not in {'application/pdf','application/octet-stream'}:
                        raise PreviewError('not_pdf', 'The official server returned a non-PDF response.')
                    length = response.headers.get('Content-Length')
                    if length and int(length) > settings.pdf_max_bytes:
                        raise PreviewError('size_limit', 'PDF preview exceeds the configured size limit.')
                    data = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        if time.monotonic() >= deadline:
                            raise PreviewError('tool_timeout', 'PDF preview download exceeded its time limit.')
                        data.extend(chunk)
                        if len(data) > settings.pdf_max_bytes:
                            raise PreviewError('size_limit', 'PDF preview exceeds the configured size limit.')
                    # Same size/page/password/corruption checks as local UI uploads.
                    upload = uploads.save('arxiv-preview.pdf', bytes(data), settings)
                    result.success = True
                    result.data = {'preview': {'digest': upload.digest, 'arxiv_id': arxiv_id, 'pages': upload.pages}}
                    break
            else:
                raise PreviewError('download_failed', 'Too many PDF preview redirects.')
    except PreviewError as exc:
        result.error = {'code': exc.code, 'message': exc.message}
    except requests.Timeout:
        result.error = {'code':'tool_timeout','message':'Official PDF preview request timed out.'}
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        result.error = {'code':'download_failed','message':f'Official PDF preview request failed (HTTP {status}).'}
    except requests.RequestException:
        result.error = {'code':'download_failed','message':'Cannot download the official PDF; check network and TLS certificates.'}
    except ValueError:
        result.error = {'code':'invalid_preview','message':'PDF ID, content or upload safety validation failed.'}
    except Exception:
        result.error = {'code':'preview_error','message':'Unable to prepare the PDF preview.'}
    result.elapsed = round(time.monotonic()-started,2)
    result.trace = [{'name':'pdf_preview','success':result.success,'error':result.error,'elapsed_seconds':result.elapsed}]
    return result
