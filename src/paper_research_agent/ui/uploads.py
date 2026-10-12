"""Session-owned upload files; never accept an arbitrary server path."""

import atexit
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import uuid

import pymupdf
from paper_research_agent.config import PROJECT_ROOT


@dataclass(frozen=True)
class Upload:
    digest: str
    name: str
    relative_path: str
    size: int
    pages: int


def validate_pdf(name, data, max_bytes, max_pages):
    if not isinstance(name,str) or any(c in name for c in '/\\:\x00') or name in ('.','..') or Path(name).suffix.lower() != '.pdf':
        raise ValueError('请选择名称有效的 PDF 文件，不能包含路径。')
    if not data or len(data) > max_bytes:
        raise ValueError('PDF 为空或超过上传大小上限。')
    if not data.startswith(b'%PDF-'):
        raise ValueError('文件内容不是 PDF。')
    try:
        with pymupdf.open(stream=data,filetype='pdf') as doc:
            if doc.needs_pass:
                raise ValueError('暂不支持加密 PDF。')
            if doc.is_repaired or not 1 <= doc.page_count <= max_pages:
                raise ValueError('PDF 损坏或超过页数上限。')
            return doc.page_count
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF 无法打开，可能已损坏。') from exc


class UploadStore:
    def __init__(self, session_id=None, root=None):
        self.session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r'[a-f0-9]{32}',self.session_id):
            raise ValueError('Invalid session identifier')
        requested = Path(root) if root is not None else PROJECT_ROOT / 'uploads'
        self.base = requested.resolve()
        if root is None and self.base != PROJECT_ROOT.resolve() / 'uploads':
            raise ValueError('Project uploads directory must not redirect outside the workspace')
        self.directory = self.base / ('web_' + self.session_id)
        self.files = {}
        atexit.register(self.cleanup)

    def save(self,name,data,settings):
        pages = validate_pdf(name,data,settings.pdf_max_bytes,settings.pdf_max_pages)
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.files and self.owns(self.files[digest].relative_path):
            return self.files[digest]
        if len(self.files) >= 5:
            raise ValueError('每个会话最多保留 5 个 PDF，请先清除会话文件。')
        if self.directory.is_symlink() or self.directory.resolve() != self.directory:
            raise ValueError('Unsafe upload directory')
        self.directory.mkdir(parents=True,exist_ok=True)
        path = self.directory / (uuid.uuid4().hex + '.pdf')
        with path.open('xb') as handle:
            handle.write(data)
        record = Upload(digest,name,path.relative_to(self.base).as_posix(),len(data),pages)
        self.files[digest] = record
        return record

    def owns(self,relative_path):
        if relative_path not in {r.relative_path for r in self.files.values()}:
            return False
        path = (self.base / relative_path).resolve()
        return self.directory.resolve() == self.directory and path.parent == self.directory and path.is_file() and not self.directory.is_symlink()

    def cleanup(self):
        # Delete only files recorded by THIS store, no recursive/shared deletion.
        for record in list(self.files.values()):
            try:
                if self.owns(record.relative_path):
                    (self.base / record.relative_path).unlink()
            except OSError:
                pass
        self.files.clear()
        try:
            if not self.directory.is_symlink() and self.directory.resolve() == self.directory and self.directory.parent == self.base:
                self.directory.rmdir()
        except OSError:
            pass
