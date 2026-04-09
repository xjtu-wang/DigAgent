from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from digagent.models import MemoryHit
from digagent.storage.files import FileStorage

TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")
HIGH_SENSITIVITY = {"high", "secret", "restricted"}


@dataclass(frozen=True)
class _MemoryDoc:
    ref: str
    source_type: str
    title: str
    summary: str
    content: str
    sensitivity: str
    source_session_id: str | None
    source_run_id: str | None
    updated_at: str | None


class MemorySearchEngine:
    def __init__(self, storage: FileStorage) -> None:
        self.storage = storage

    def search(
        self,
        *,
        query: str,
        session_id: str | None = None,
        run_id: str | None = None,
        scope: str = "session",
        sensitivity: str = "normal",
        limit: int = 5,
    ) -> list[MemoryHit]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        docs = self._filter_docs(self._build_docs(), session_id=session_id, run_id=run_id, scope=scope, sensitivity=sensitivity)
        scored = self._score_docs(tokens, docs, session_id=session_id, run_id=run_id)
        return scored[:limit]

    def get(self, ref: str, *, session_id: str | None = None, sensitivity: str = "normal") -> MemoryHit:
        docs = self._filter_docs(self._build_docs(), session_id=session_id, run_id=None, scope="global", sensitivity=sensitivity)
        for doc in docs:
            if doc.ref == ref:
                return self._to_hit(doc, score=1.0)
        raise KeyError(f"Unknown memory ref: {ref}")

    def _build_docs(self) -> list[_MemoryDoc]:
        docs = [self._memory_markdown_doc()]
        docs.extend(self._memory_record_docs())
        docs.extend(self._wiki_docs())
        docs.extend(self._daily_docs())
        return [doc for doc in docs if doc and doc.content.strip()]

    def _memory_markdown_doc(self) -> _MemoryDoc | None:
        content = self.storage.load_memory_markdown()
        return _MemoryDoc(
            ref="memory:MEMORY.md",
            source_type="memory_markdown",
            title="MEMORY.md",
            summary="DigAgent 长期记忆摘要",
            content=content,
            sensitivity="low",
            source_session_id=None,
            source_run_id=None,
            updated_at=None,
        )

    def _memory_record_docs(self) -> list[_MemoryDoc]:
        docs: list[_MemoryDoc] = []
        for record in self.storage.list_memories():
            docs.append(
                _MemoryDoc(
                    ref=f"memory:{record.memory_id}",
                    source_type="memory_record",
                    title=record.summary,
                    summary=record.summary,
                    content=f"{record.summary}\n{record.content}",
                    sensitivity=record.sensitivity,
                    source_session_id=record.source_session_id,
                    source_run_id=record.source_run_id,
                    updated_at=record.updated_at,
                )
            )
        return docs

    def _wiki_docs(self) -> list[_MemoryDoc]:
        docs: list[_MemoryDoc] = []
        for entry in self.storage.list_wiki_entries():
            claims = "\n".join(claim.claim for claim in entry.claims)
            docs.append(
                _MemoryDoc(
                    ref=f"wiki:{entry.entry_id}",
                    source_type="wiki",
                    title=entry.title,
                    summary=entry.summary,
                    content=f"{entry.summary}\n{claims}",
                    sensitivity="low",
                    source_session_id=entry.source_session_id,
                    source_run_id=entry.source_run_id,
                    updated_at=entry.updated_at,
                )
            )
        return docs

    def _daily_docs(self) -> list[_MemoryDoc]:
        docs: list[_MemoryDoc] = []
        daily_dir = self.storage.root / "memory" / "daily"
        for path in sorted(daily_dir.glob("*.md")):
            sections = self._split_sections(path)
            for index, (title, content) in enumerate(sections):
                docs.append(
                    _MemoryDoc(
                        ref=f"daily:{path.stem}:{index}",
                        source_type="daily",
                        title=title,
                        summary=title,
                        content=content,
                        sensitivity="medium",
                        source_session_id=self._session_from_daily_content(content),
                        source_run_id=self._run_from_daily_content(content),
                        updated_at=f"{path.stem}T00:00:00Z",
                    )
                )
        return docs

    def _filter_docs(
        self,
        docs: list[_MemoryDoc],
        *,
        session_id: str | None,
        run_id: str | None,
        scope: str,
        sensitivity: str,
    ) -> list[_MemoryDoc]:
        filtered: list[_MemoryDoc] = []
        for doc in docs:
            if sensitivity != "elevated" and doc.sensitivity in HIGH_SENSITIVITY and doc.source_session_id not in {None, session_id}:
                continue
            if scope == "session" and doc.source_type == "daily" and doc.source_session_id not in {None, session_id}:
                continue
            if scope == "run" and doc.source_run_id not in {None, run_id}:
                continue
            filtered.append(doc)
        return filtered

    def _score_docs(
        self,
        query_tokens: list[str],
        docs: list[_MemoryDoc],
        *,
        session_id: str | None,
        run_id: str | None,
    ) -> list[MemoryHit]:
        doc_tokens = [self._tokenize(doc.content) for doc in docs]
        avg_len = max(1.0, sum(len(tokens) for tokens in doc_tokens) / max(1, len(doc_tokens)))
        document_freq = Counter(token for tokens in doc_tokens for token in set(tokens))
        hits: list[MemoryHit] = []
        for doc, tokens in zip(docs, doc_tokens):
            if not tokens:
                continue
            score = self._bm25_score(query_tokens, tokens, document_freq, len(doc_tokens), avg_len)
            if doc.source_session_id and session_id and doc.source_session_id == session_id:
                score += 0.35
            if doc.source_run_id and run_id and doc.source_run_id == run_id:
                score += 0.2
            if score <= 0:
                continue
            hits.append(self._to_hit(doc, score=round(score, 4)))
        return sorted(hits, key=lambda item: item.score, reverse=True)

    def _bm25_score(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        document_freq: Counter[str],
        total_docs: int,
        avg_len: float,
    ) -> float:
        k1 = 1.5
        b = 0.75
        tf = Counter(doc_tokens)
        score = 0.0
        doc_len = len(doc_tokens)
        for token in query_tokens:
            if token not in tf:
                continue
            df = max(1, document_freq[token])
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            freq = tf[token]
            denom = freq + k1 * (1 - b + b * doc_len / avg_len)
            score += idf * (freq * (k1 + 1) / denom)
        return score

    def _split_sections(self, path: Path) -> list[tuple[str, str]]:
        text = path.read_text(encoding="utf-8")
        chunks = re.split(r"^##\s+", text, flags=re.MULTILINE)
        sections: list[tuple[str, str]] = []
        for chunk in chunks:
            piece = chunk.strip()
            if not piece:
                continue
            lines = piece.splitlines()
            title = lines[0].strip()
            content = "\n".join(lines[1:]).strip() or title
            sections.append((title, content))
        return sections or [(path.stem, text.strip())]

    def _session_from_daily_content(self, content: str) -> str | None:
        match = re.search(r"source_session_id[:=]\s*([A-Za-z0-9_:-]+)", content)
        return match.group(1) if match else None

    def _run_from_daily_content(self, content: str) -> str | None:
        match = re.search(r"source_run_id[:=]\s*([A-Za-z0-9_:-]+)", content)
        return match.group(1) if match else None

    def _tokenize(self, text: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(text or "")]

    def _to_hit(self, doc: _MemoryDoc, *, score: float) -> MemoryHit:
        return MemoryHit(
            ref=doc.ref,
            source_type=doc.source_type,
            title=doc.title,
            summary=doc.summary,
            content=doc.content[:4000],
            score=score,
            sensitivity=doc.sensitivity,
            source_session_id=doc.source_session_id,
            source_run_id=doc.source_run_id,
            updated_at=doc.updated_at,
        )
