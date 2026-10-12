"""Lossless nonoverlapping page spans, bounded by UTF-8 bytes."""

from dataclasses import dataclass, field
import re
from paper_research_agent.agent.budget import ResourceError


@dataclass
class Span:
    page_number: int
    start: int
    end: int
    text: str
    section: str


@dataclass
class Chunk:
    id: int
    spans: list[Span] = field(default_factory=list)

    def payload(self):
        return {"chunk_id": self.id, "spans": [vars(s) for s in self.spans]}


HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\s+.{2,100}|(?:abstract|introduction|background|method(?:ology)?|experiments?|results?|discussion|conclusions?|limitations?|references|摘要|引言|方法|实验|结果|结论|局限性)\b.{0,60})$", re.I)


def chunk_pages(pages: list[dict], max_bytes: int, max_chunks: int) -> list[Chunk]:
    chunks, current, used = [], Chunk(1), 0
    section = "Unknown section"
    for page in pages:
        text = page["text"]
        if not text.strip():
            continue
        headings = [(m.start(), m.group().strip()) for m in re.finditer(r"[^\n]+", text) if HEADING.fullmatch(m.group().strip())]
        start = 0
        while start < len(text):
            capacity = max_bytes - used
            low, high = 0, len(text) - start
            while low < high:
                middle = (low + high + 1) // 2
                if len(text[start:start + middle].encode("utf-8")) <= capacity:
                    low = middle
                else:
                    high = middle - 1
            if low == 0:
                chunks.append(current)
                current, used = Chunk(len(chunks) + 1), 0
                continue
            end = start + low
            if end < len(text):
                newline = text.rfind("\n", start, end)
                if newline > start + low // 2:
                    end = newline + 1
            for offset, heading in headings:
                if offset <= start:
                    section = heading
            label = section
            encountered = [heading for offset, heading in headings if start <= offset < end]
            if encountered:
                label = " | ".join(dict.fromkeys([section] + encountered))
                section = encountered[-1]
            fragment = text[start:end]
            current.spans.append(Span(page["page_number"], start, end, fragment, label))
            used += len(fragment.encode("utf-8"))
            start = end
            if used == max_bytes:
                chunks.append(current)
                current, used = Chunk(len(chunks) + 1), 0
        if len(chunks) > max_chunks:
            raise ResourceError("chunk_budget", "Document requires too many chunks; no partial analysis is presented as complete.")
    if current.spans:
        chunks.append(current)
    if len(chunks) > max_chunks:
        raise ResourceError("chunk_budget", "Document requires too many chunks; no text was silently dropped.")
    return chunks
