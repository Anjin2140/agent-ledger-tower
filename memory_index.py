#!/usr/bin/env python3
"""Provenance-first local memory index for the Agent Ledger Tower.

This is not an LLM memory system. It indexes explicitly selected text files into
SQLite FTS5 and returns source-hashed excerpts with line ranges. A model may use
those excerpts as context, but the operator can always inspect the source.

Security defaults:
- only allowlisted text-like extensions are indexed;
- likely credential files are skipped by filename;
- files over the configured size limit are skipped;
- symlinks and paths escaping an indexed root are skipped.

No external packages. Python 3.9+ with SQLite FTS5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence


TEXT_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".cs", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".toml", ".yaml", ".yml", ".csv", ".html", ".css",
}
SECRET_NAME = re.compile(
    r"(^|[._-])(env|secret|credential|password|private|wallet|keystore|mnemonic|token|api[_-]?key)([._-]|$)|"
    r"\.(pem|key|pfx|p12|p8)$|id_(rsa|ed25519)",
    re.IGNORECASE,
)
WORD = re.compile(r"[A-Za-z0-9_]{2,}")
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_CHUNK_LINES = 36
NO_MATCH_CONTEXT = "(No relevant local source excerpts were found.)"
IGNORED_DIR_NAMES = {
    ".git", ".hg", ".svn", ".venv", "__pycache__", ".pytest_cache",
    "node_modules", "bin", "obj", "generated", "evidence_packets", "agent_work",
    "fleet", "logs", "build",
}


@dataclass(frozen=True)
class SearchHit:
    path: str
    sha256: str
    start_line: int
    end_line: int
    score: float
    text: str

    def citation(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line} sha256:{self.sha256[:12]}"


@dataclass(frozen=True)
class ContextPacket:
    """One deterministic evidence selection for a chat turn."""

    text: str
    hits: tuple[SearchHit, ...]
    sha256: str


@dataclass
class IndexStats:
    indexed: int = 0
    unchanged: int = 0
    skipped_secret: int = 0
    skipped_unsupported: int = 0
    skipped_large: int = 0
    skipped_error: int = 0
    removed: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_secret_name(path: Path) -> bool:
    return bool(SECRET_NAME.search(path.name))


def chunk_lines(text: str, size: int = DEFAULT_CHUNK_LINES) -> Iterator[tuple[int, int, str]]:
    lines = text.splitlines()
    for start in range(0, len(lines), size):
        piece = "\n".join(lines[start:start + size]).strip()
        if piece:
            yield start + 1, min(start + size, len(lines)), piece


def _safe_terms(query: str) -> list[str]:
    return sorted(set(term.lower() for term in WORD.findall(query)))


class MemoryIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _initialize(self) -> None:
        try:
            with self._lock:
                self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    content,
                    path UNINDEXED,
                    sha256 UNINDEXED,
                    start_line UNINDEXED,
                    end_line UNINDEXED,
                    tokenize='unicode61'
                );
                """
                )
        except sqlite3.OperationalError as exc:
            raise RuntimeError("SQLite FTS5 support is required for the memory index") from exc
        with self._lock:
            self.conn.commit()

    def _replace_document(self, path: Path, raw: bytes) -> None:
        digest = sha256_bytes(raw)
        text = raw.decode("utf-8", errors="replace")
        path_text = str(path)
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (path_text,))
            self.conn.execute("DELETE FROM documents WHERE path = ?", (path_text,))
            self.conn.execute(
                "INSERT INTO documents(path, sha256, size_bytes, indexed_at) VALUES(?, ?, ?, ?)",
                (path_text, digest, len(raw), utc_now()),
            )
            for start, end, piece in chunk_lines(text):
                self.conn.execute(
                    "INSERT INTO chunks(content, path, sha256, start_line, end_line) VALUES(?, ?, ?, ?, ?)",
                    (piece, path_text, digest, start, end),
                )

    def index_file(self, file_path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        path = Path(file_path).resolve()
        if path.is_symlink() or not path.is_file():
            return "unsupported"
        if is_secret_name(path):
            return "secret"
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return "unsupported"
        try:
            raw = path.read_bytes()
        except OSError:
            return "error"
        if len(raw) > max_bytes:
            return "large"
        digest = sha256_bytes(raw)
        with self._lock:
            row = self.conn.execute("SELECT sha256 FROM documents WHERE path = ?", (str(path),)).fetchone()
        if row and row["sha256"] == digest:
            return "unchanged"
        self._replace_document(path, raw)
        return "indexed"

    def index_root(self, root_path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> IndexStats:
        root = Path(root_path).resolve()
        if not root.is_dir():
            raise ValueError(f"not a directory: {root}")
        stats = IndexStats()
        seen: set[str] = set()
        # Walk top-down so generated/build/state directories are pruned before
        # touching their contents. This keeps an explicit working-set source
        # fast and prevents retrieval from absorbing stale runtime artifacts.
        for base, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            directories[:] = sorted(
                (name for name in directories if name.casefold() not in IGNORED_DIR_NAMES),
                key=str.casefold,
            )
            for name in sorted(filenames, key=str.casefold):
                candidate = Path(base) / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    continue
                status = self.index_file(resolved, max_bytes=max_bytes)
                if status in {"indexed", "unchanged"}:
                    seen.add(str(resolved))
                if status == "indexed":
                    stats.indexed += 1
                elif status == "unchanged":
                    stats.unchanged += 1
                elif status == "secret":
                    stats.skipped_secret += 1
                elif status == "unsupported":
                    stats.skipped_unsupported += 1
                elif status == "large":
                    stats.skipped_large += 1
                else:
                    stats.skipped_error += 1

        prefix = os.path.join(str(root), "")  # OS-portable trailing separator
        with self._lock:
            known = [row["path"] for row in self.conn.execute("SELECT path FROM documents WHERE path LIKE ?", (prefix + "%",))]
        stale = [path for path in known if path not in seen]
        if stale:
            with self._lock, self.conn:
                for path in stale:
                    self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
                    self.conn.execute("DELETE FROM documents WHERE path = ?", (path,))
            stats.removed = len(stale)
        return stats

    def search(self, query: str, *, limit: int = 6) -> list[SearchHit]:
        terms = _safe_terms(query)
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in terms)
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT path, sha256, start_line, end_line, content, bm25(chunks) AS rank
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY rank ASC, path ASC, start_line ASC, end_line ASC, sha256 ASC
                LIMIT ?
                """,
                (match, max(1, min(int(limit), 50))),
            ).fetchall()
        return [
            SearchHit(
                path=row["path"],
                sha256=row["sha256"],
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                score=round(-float(row["rank"]), 6),
                text=row["content"],
            )
            for row in rows
        ]

    def context_packet_for_hits(self, hits: Sequence[SearchHit], *, max_chars: int = 6000) -> ContextPacket:
        """Build one bounded packet from an already-selected, ordered hit list."""
        parts: list[str] = []
        selected: list[SearchHit] = []
        used = 0
        for hit in hits:
            block = f"[{hit.citation()}]\n{hit.text}\n"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            selected.append(hit)
            used += len(block)
        # The text is the exact evidence context handed to a model.  A stable
        # no-match marker avoids a hidden substitution later in the call path.
        text = "\n".join(parts) or NO_MATCH_CONTEXT
        return ContextPacket(text=text, hits=tuple(selected), sha256=sha256_bytes(text.encode("utf-8")))

    def context_packet(self, query: str, *, limit: int = 5, max_chars: int = 6000) -> str:
        """Compatibility helper for callers that only need the packet text."""
        return self.context_packet_for_hits(self.search(query, limit=limit), max_chars=max_chars).text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Source-hashed SQLite memory index")
    parser.add_argument("--db", default="memory_index.sqlite3", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="Index a selected folder")
    index.add_argument("root")
    index.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)

    search = sub.add_parser("search", help="Search indexed source excerpts")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    memory = MemoryIndex(args.db)
    try:
        if args.command == "index":
            print(json.dumps(asdict(memory.index_root(args.root, max_bytes=args.max_bytes)), indent=2))
        else:
            print(json.dumps([asdict(hit) | {"citation": hit.citation()} for hit in memory.search(args.query, limit=args.limit)], indent=2))
        return 0
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
