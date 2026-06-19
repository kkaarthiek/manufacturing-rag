"""
Structured store (spec 7.1).  STATUS: IMPLEMENTED (sqlite, exact lookup/aggregation).

Typed-ish tables in stdlib sqlite3 (suppliers, parts, purchase_orders,
work_orders, telemetry, ...) indexed on the record key — for EXACT lookup +
aggregation/comparison/absence (spec: structure any fact that can be structured).
Each StructuredRecord is stored with its raw + normalized + units + validity
JSON so nothing is lost. Idempotent: re-loading the same key upserts.

Postgres/DuckDB is the spec's hosted swap target; the interface is identical.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..contracts import StructuredRecord


class StructuredStore:
    def __init__(self, db_path: str | Path | None = None):
        # ":memory:" by default; pass a path for durability
        self.db_path = str(db_path) if db_path else ":memory:"
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the web server serves on multiple threads;
        # callers serialize access with a lock (the connection isn't used concurrently).
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                tbl TEXT NOT NULL, key TEXT NOT NULL,
                fields TEXT, raw TEXT, normalized TEXT, units TEXT,
                validity TEXT, source_doc_id TEXT,
                PRIMARY KEY (tbl, key)
            )""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_key ON records(key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tbl ON records(tbl)")
        self.conn.commit()

    def put(self, rec: StructuredRecord):
        self.conn.execute(
            "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?)",
            (rec.table, rec.key, json.dumps(rec.fields, ensure_ascii=False),
             json.dumps(rec.raw, ensure_ascii=False),
             json.dumps(rec.normalized, ensure_ascii=False),
             json.dumps(rec.units, ensure_ascii=False),
             json.dumps(rec.validity, ensure_ascii=False), rec.source_doc_id))

    def commit(self):
        self.conn.commit()

    def get(self, table: str, key: str) -> StructuredRecord | None:
        row = self.conn.execute(
            "SELECT tbl,key,fields,raw,normalized,units,validity,source_doc_id "
            "FROM records WHERE tbl=? AND key=?", (table, key)).fetchone()
        return self._row(row) if row else None

    def by_key(self, key: str) -> list[StructuredRecord]:
        rows = self.conn.execute(
            "SELECT tbl,key,fields,raw,normalized,units,validity,source_doc_id "
            "FROM records WHERE key=?", (key,)).fetchall()
        return [self._row(r) for r in rows]

    def all_keys(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT key FROM records").fetchall()}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def query(self, table: str, **predicate):
        """Exact predicate filter over a table's fields (full-store scan)."""
        out = []
        for r in self.conn.execute(
                "SELECT tbl,key,fields,raw,normalized,units,validity,source_doc_id "
                "FROM records WHERE tbl=?", (table,)).fetchall():
            rec = self._row(r)
            if all(rec.fields.get(k) == v for k, v in predicate.items()):
                out.append(rec)
        return out

    @staticmethod
    def _row(row) -> StructuredRecord:
        return StructuredRecord(
            table=row[0], key=row[1], fields=json.loads(row[2] or "{}"),
            raw=json.loads(row[3] or "{}"), normalized=json.loads(row[4] or "{}"),
            units=json.loads(row[5] or "{}"), validity=json.loads(row[6] or "{}"),
            source_doc_id=row[7] or "")


__all__ = ["StructuredStore"]
