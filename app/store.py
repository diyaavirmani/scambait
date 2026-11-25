"""SQLite store: one aiosqlite connection, WAL mode, every write behind one lock.

Tables: cases, messages, intel, events, evidence, investigations (Kane runs), seen (idempotency keys).
JSON columns in investigations (asked_for, final_state, steps) are decoded on read.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any, Optional

import aiosqlite

from app.models import Event, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, channel TEXT NOT NULL, external_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    verdict TEXT NOT NULL DEFAULT 'unknown', scam_type TEXT NOT NULL DEFAULT 'unknown',
    summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_by_external ON cases(external_id, status);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES cases(id),
    role TEXT NOT NULL CHECK (role IN ('scammer', 'persona')), text TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_case ON messages(case_id, id);
CREATE TABLE IF NOT EXISTS intel (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES cases(id), kind TEXT NOT NULL,
    value TEXT NOT NULL, norm TEXT NOT NULL, message_id INTEGER, first_seen TEXT NOT NULL,
    UNIQUE (case_id, kind, value)
);
CREATE INDEX IF NOT EXISTS intel_by_norm ON intel(kind, norm);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, case_id TEXT, channel TEXT NOT NULL,
    type TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_case ON events(case_id, id);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES cases(id), kind TEXT NOT NULL,
    path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
    verdict TEXT NOT NULL DEFAULT '', claims_to_be TEXT NOT NULL DEFAULT '', payee TEXT NOT NULL DEFAULT '',
    payee_kind TEXT NOT NULL DEFAULT '', amount TEXT NOT NULL DEFAULT '', asked_for TEXT NOT NULL DEFAULT '[]',
    final_state TEXT NOT NULL DEFAULT '{}', summary TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]', credits REAL, duration_s REAL, exit_code INTEGER,
    evidence_path TEXT NOT NULL DEFAULT '', evidence_sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, finished_at TEXT, used_at TEXT
);
CREATE INDEX IF NOT EXISTS investigations_by_case ON investigations(case_id, id);
CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, ts TEXT NOT NULL);
"""

CASE_FIELDS = {"status", "verdict", "scam_type", "summary"}
INVESTIGATION_FIELDS = {"status", "verdict", "claims_to_be", "payee", "payee_kind", "amount", "asked_for",
                        "final_state", "summary", "reason", "steps", "credits", "duration_s", "exit_code",
                        "evidence_path", "evidence_sha256", "finished_at", "used_at"}
JSON_FIELDS = {"asked_for": [], "final_state": {}, "steps": []}


def _decode(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    for key, empty in JSON_FIELDS.items():
        try:
            row[key] = json.loads(row.get(key) or json.dumps(empty))
        except ValueError:
            row[key] = type(empty)()
    return row


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "busy_timeout=5000", "foreign_keys=ON"):
            await self._db.execute(f"PRAGMA {pragma}")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store.init() was not called")
        return self._db

    async def ping(self) -> bool:
        try:
            return (await self._one("SELECT 1 AS ok"))["ok"] == 1
        except Exception:
            return False

    async def _write(self, sql: str, params: tuple = ()) -> tuple[int, int]:
        """(lastrowid, rowcount)"""
        async with self._lock:
            cur = await self.db.execute(sql, params)
            await self.db.commit()
            return cur.lastrowid, cur.rowcount

    async def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self.db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        async with self.db.execute(sql, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # ---------- cases ----------
    async def new_case(self, channel: str, external_id: str) -> dict:
        case_id = "c_" + secrets.token_hex(6)
        now = utc_now()
        await self._write("INSERT INTO cases (id, channel, external_id, created_at, updated_at) VALUES (?,?,?,?,?)",
                          (case_id, channel, external_id, now, now))
        return await self.get_case(case_id)

    async def open_case(self, channel: str, external_id: str) -> dict:
        """The newest case for this sender that is not closed, or a new one."""
        row = await self._one("SELECT * FROM cases WHERE external_id=? AND status!='closed' "
                              "ORDER BY created_at DESC LIMIT 1", (external_id,))
        return row or await self.new_case(channel, external_id)

    async def get_case(self, case_id: str) -> Optional[dict]:
        return await self._one("SELECT * FROM cases WHERE id=?", (case_id,))

    async def update_case(self, case_id: str, **fields: Any) -> None:
        unknown = set(fields) - CASE_FIELDS
        if unknown:
            raise ValueError(f"unknown case fields: {sorted(unknown)}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._write(f"UPDATE cases SET {cols}, updated_at=? WHERE id=?", (*fields.values(), utc_now(), case_id))

    async def list_cases(self, limit: int = 100) -> list[dict]:
        return await self._all(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.case_id=c.id AND m.role='scammer') AS turns "
            "FROM cases c ORDER BY c.updated_at DESC LIMIT ?", (limit,))

    # ---------- messages ----------
    async def add_message(self, case_id: str, role: str, text: str) -> int:
        rowid, _ = await self._write("INSERT INTO messages (case_id, role, text, ts) VALUES (?,?,?,?)",
                                     (case_id, role, text, utc_now()))
        await self._write("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        return rowid

    async def list_messages(self, case_id: str) -> list[dict]:
        return await self._all("SELECT * FROM messages WHERE case_id=? ORDER BY id", (case_id,))

    async def count_messages(self, case_id: str, role: str) -> int:
        return (await self._one("SELECT COUNT(*) AS n FROM messages WHERE case_id=? AND role=?", (case_id, role)))["n"]

    # ---------- intel ----------
    async def add_intel(self, case_id: str, kind: str, value: str, norm: str, message_id: Optional[int]) -> bool:
        """True when this identifier is new for the case."""
        _, count = await self._write(
            "INSERT OR IGNORE INTO intel (case_id, kind, value, norm, message_id, first_seen) VALUES (?,?,?,?,?,?)",
            (case_id, kind, value, norm, message_id, utc_now()))
        return count == 1

    async def list_intel(self, case_id: str) -> list[dict]:
        return await self._all("SELECT * FROM intel WHERE case_id=? ORDER BY id", (case_id,))

    async def cases_sharing(self, case_id: str) -> list[dict]:
        """Other cases holding the same identifier (kind and normalised value) as this one."""
        return await self._all(
            "SELECT DISTINCT b.case_id, b.kind, b.norm FROM intel a JOIN intel b "
            "ON a.kind=b.kind AND a.norm=b.norm AND a.case_id!=b.case_id "
            "WHERE a.case_id=? AND a.kind IN ('upi','phone','bank_account','card','email') ORDER BY b.case_id",
            (case_id,))

    # ---------- events ----------
    async def add_event(self, event: Event) -> int:
        rowid, _ = await self._write(
            "INSERT INTO events (ts, case_id, channel, type, data) VALUES (?,?,?,?,?)",
            (event.ts, event.case_id, event.channel, event.type, json.dumps(event.data, ensure_ascii=False)))
        return rowid

    def _events(self, rows: list[dict]) -> list[Event]:
        return [Event(id=r["id"], ts=r["ts"], case_id=r["case_id"], channel=r["channel"], type=r["type"],
                      data=json.loads(r["data"])) for r in rows]

    async def events_after(self, last_id: int, limit: int = 500) -> list[Event]:
        return self._events(await self._all("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (last_id, limit)))

    async def events_for_case(self, case_id: str, limit: int = 2000) -> list[Event]:
        return self._events(await self._all("SELECT * FROM events WHERE case_id=? ORDER BY id LIMIT ?",
                                            (case_id, limit)))

    # ---------- evidence ----------
    async def add_evidence(self, case_id: str, kind: str, path: str, sha256: str) -> None:
        await self._write("INSERT INTO evidence (case_id, kind, path, sha256, created_at) VALUES (?,?,?,?,?)",
                          (case_id, kind, path, sha256, utc_now()))

    async def list_evidence(self, case_id: str) -> list[dict]:
        return await self._all("SELECT * FROM evidence WHERE case_id=? ORDER BY id", (case_id,))

    # ---------- Kane investigations ----------
    async def add_investigation(self, case_id: Optional[str], url: str, status: str = "queued") -> int:
        rowid, _ = await self._write("INSERT INTO investigations (case_id, url, status, created_at) VALUES (?,?,?,?)",
                                     (case_id, url, status, utc_now()))
        return rowid

    async def update_investigation(self, inv_id: int, **fields: Any) -> None:
        unknown = set(fields) - INVESTIGATION_FIELDS
        if unknown:
            raise ValueError(f"unknown investigation fields: {sorted(unknown)}")
        if fields:
            values = [json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v for k, v in fields.items()]
            cols = ", ".join(f"{k}=?" for k in fields)
            await self._write(f"UPDATE investigations SET {cols} WHERE id=?", (*values, inv_id))

    async def get_investigation(self, inv_id: int) -> Optional[dict]:
        return _decode(await self._one("SELECT * FROM investigations WHERE id=?", (inv_id,)))

    async def find_investigation(self, case_id: Optional[str], url: str) -> Optional[dict]:
        where = "case_id IS NULL" if case_id is None else "case_id=?"
        params = (url,) if case_id is None else (case_id, url)
        return _decode(await self._one(f"SELECT * FROM investigations WHERE {where} AND url=? ORDER BY id DESC LIMIT 1",
                                       params))

    async def list_investigations(self, case_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        if case_id is None:
            rows = await self._all("SELECT * FROM investigations ORDER BY id DESC LIMIT ?", (limit,))
        else:
            rows = await self._all("SELECT * FROM investigations WHERE case_id=? ORDER BY id", (case_id,))
        return [_decode(r) for r in rows]

    async def unused_findings(self, case_id: str) -> list[dict]:
        """Payment pages Kane proved in this case that Meena has not talked about yet."""
        rows = await self._all("SELECT * FROM investigations WHERE case_id=? AND verdict='payment_request_found' "
                               "AND used_at IS NULL ORDER BY id", (case_id,))
        return [_decode(r) for r in rows]

    # ---------- idempotency ----------
    async def mark_seen(self, key: str) -> bool:
        """True the first time a key is seen (Telegram update ids)."""
        _, count = await self._write("INSERT OR IGNORE INTO seen (key, ts) VALUES (?,?)", (key, utc_now()))
        return count == 1
