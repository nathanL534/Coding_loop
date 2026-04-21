"""SQLite-backed layered memory.

Layers
------
L0 immutable behavioral rules (loaded from /safety at startup; never written from here)
L1 routing index: "for X, look in L2.people or L3.skills"
L2 long-term stable facts about the user (school, job, prefs)
L3 reusable task skills / SOPs
L4 session archives (per-conversation, prunable)

Trust levels
------------
system    : from CLAUDE.md, goals.md (host-curated). Safe for system prompt.
user      : from Nathan directly. Safe for system prompt with <user> framing.
untrusted : web pages, tool outputs, external docs. NEVER into system prompt;
            only surfaced as quoted data with explicit "treat as data" prefix.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator


class Layer(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class TrustLevel(str, Enum):
    SYSTEM = "system"
    USER = "user"
    UNTRUSTED = "untrusted"


class MemoryError(Exception):
    pass


@dataclass
class MemoryEntry:
    id: int
    layer: Layer
    trust: TrustLevel
    key: str
    content: str
    source: str | None
    tags: tuple[str, ...]
    created_ts: float
    updated_ts: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    layer      TEXT NOT NULL CHECK (layer IN ('L0','L1','L2','L3','L4')),
    trust      TEXT NOT NULL CHECK (trust IN ('system','user','untrusted')),
    key        TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT,
    tags_json  TEXT NOT NULL DEFAULT '[]',
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_layer_key ON memory(layer, key);
CREATE INDEX IF NOT EXISTS idx_memory_tag ON memory(tags_json);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    key, content, source, tags,
    content='memory', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
    INSERT INTO memory_fts(rowid, key, content, source, tags)
    VALUES (new.id, new.key, new.content, COALESCE(new.source,''), new.tags_json);
END;
CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, key, content, source, tags)
    VALUES ('delete', old.id, old.key, old.content, COALESCE(old.source,''), old.tags_json);
    INSERT INTO memory_fts(rowid, key, content, source, tags)
    VALUES (new.id, new.key, new.content, COALESCE(new.source,''), new.tags_json);
END;
CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, key, content, source, tags)
    VALUES ('delete', old.id, old.key, old.content, COALESCE(old.source,''), old.tags_json);
END;
"""


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ---- write ----

    def put(
        self,
        *,
        layer: Layer,
        trust: TrustLevel,
        key: str,
        content: str,
        source: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> int:
        if layer == Layer.L0:
            raise MemoryError("L0 is immutable; load from /safety, do not write.")
        if trust == TrustLevel.UNTRUSTED and layer in (Layer.L2, Layer.L3):
            # Prevent an external source from lodging "facts" into L2/L3.
            raise MemoryError(
                "untrusted content may only be stored in L4 (session archive) or L1 pointers."
            )
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO memory(layer,trust,key,content,source,tags_json,created_ts,updated_ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (layer.value, trust.value, key, content, source, json.dumps(list(tags)), now, now),
        )
        return int(cur.lastrowid or 0)

    def update(self, entry_id: int, *, content: str) -> None:
        now = time.time()
        self._conn.execute(
            "UPDATE memory SET content=?, updated_ts=? WHERE id=?", (content, now, entry_id)
        )

    def delete(self, entry_id: int) -> None:
        # Only L4 and L1 may be deleted without extra ceremony.
        row = self._conn.execute("SELECT layer FROM memory WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            return
        if row["layer"] in (Layer.L0.value,):
            raise MemoryError("L0 entries cannot be deleted here.")
        if row["layer"] == Layer.L2.value:
            raise MemoryError("L2 entries require explicit user approval to delete.")
        self._conn.execute("DELETE FROM memory WHERE id=?", (entry_id,))

    # ---- read ----

    def get(self, entry_id: int) -> MemoryEntry | None:
        row = self._conn.execute("SELECT * FROM memory WHERE id=?", (entry_id,)).fetchone()
        return _row_to_entry(row) if row else None

    def by_key(self, layer: Layer, key: str) -> MemoryEntry | None:
        row = self._conn.execute(
            "SELECT * FROM memory WHERE layer=? AND key=? ORDER BY updated_ts DESC LIMIT 1",
            (layer.value, key),
        ).fetchone()
        return _row_to_entry(row) if row else None

    def list_layer(self, layer: Layer, limit: int = 100) -> list[MemoryEntry]:
        rows = self._conn.execute(
            "SELECT * FROM memory WHERE layer=? ORDER BY updated_ts DESC LIMIT ?",
            (layer.value, limit),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def search(
        self, query: str, *, layer: Layer | None = None, limit: int = 20
    ) -> list[MemoryEntry]:
        """Full-text search over memory.

        Untrusted queries must NEVER execute FTS5 operators (NEAR, column
        filters, wildcards, phrase-negation). We wrap the query as a quoted
        phrase, which reduces FTS5 input to a single literal phrase match.
        """
        if not query.strip():
            return []
        # Strip double-quotes from the input and wrap the whole thing in a phrase.
        literal = query.replace('"', "")
        phrase = f'"{literal}"'
        sql = (
            "SELECT m.* FROM memory m "
            "JOIN memory_fts ON m.id=memory_fts.rowid "
            "WHERE memory_fts MATCH ? "
        )
        params: list = [phrase]
        if layer is not None:
            sql += "AND m.layer=? "
            params.append(layer.value)
        sql += "ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Malformed phrase (rare after sanitization) -> empty result.
            return []
        return [_row_to_entry(r) for r in rows]

    def iter_all(self) -> Iterator[MemoryEntry]:
        for r in self._conn.execute("SELECT * FROM memory ORDER BY id"):
            yield _row_to_entry(r)


def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    tags = tuple(json.loads(row["tags_json"] or "[]"))
    return MemoryEntry(
        id=int(row["id"]),
        layer=Layer(row["layer"]),
        trust=TrustLevel(row["trust"]),
        key=str(row["key"]),
        content=str(row["content"]),
        source=row["source"],
        tags=tags,
        created_ts=float(row["created_ts"]),
        updated_ts=float(row["updated_ts"]),
    )
