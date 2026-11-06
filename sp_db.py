"""Tiny DB layer. SQLite for local tests, Postgres (Neon/Supabase) in production.

Vercel functions cannot keep files, so production MUST use a Postgres DATABASE_URL.
"""
import json
import sqlite3
import threading
import time
import uuid

import sp_config as config

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        key TEXT UNIQUE NOT NULL,
        source TEXT NOT NULL,
        url TEXT,
        text TEXT,
        author TEXT,
        priority INTEGER DEFAULT 0,
        stage TEXT NOT NULL DEFAULT 'new',
        attempts INTEGER DEFAULT 0,
        next_try DOUBLE PRECISION DEFAULT 0,
        kind TEXT,
        name TEXT,
        score DOUBLE PRECISION,
        verdict TEXT,
        status TEXT DEFAULT 'new',
        notified INTEGER DEFAULT 0,
        data TEXT DEFAULT '{}',
        error TEXT,
        created_at DOUBLE PRECISION,
        updated_at DOUBLE PRECISION
    )""",
    "CREATE INDEX IF NOT EXISTS leads_stage ON leads(stage)",
]

UPDATABLE = {
    "stage", "kind", "name", "score", "verdict", "status",
    "notified", "data", "error", "attempts", "next_try", "priority",
}


def _is_conn_error(e):
    return type(e).__name__ in ("OperationalError", "InterfaceError")


class Db:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        self.url = url
        self.pg = url.startswith("postgresql://")
        self._pgc = None
        self._sq = None
        self._lock = threading.Lock()
        if not self.pg:
            path = url.replace("sqlite:///", "", 1) if url.startswith("sqlite:///") else url
            self._sq = sqlite3.connect(path, check_same_thread=False)
            self._sq.row_factory = sqlite3.Row
        for stmt in SCHEMA:
            self.run(stmt)

    def _pg_conn(self):
        import psycopg
        from psycopg.rows import dict_row

        if self._pgc is None or self._pgc.closed:
            self._pgc = psycopg.connect(
                self.url, autocommit=True, row_factory=dict_row, connect_timeout=10
            )
        return self._pgc

    def _exec(self, sql, params):
        with self._lock:
            if self.pg:
                for attempt in (1, 2):
                    try:
                        cur = self._pg_conn().execute(sql.replace("?", "%s"), params)
                        rows = list(cur.fetchall()) if cur.description else []
                        return rows, cur.rowcount
                    except Exception as e:  # reconnect once on a dropped connection
                        if attempt == 2 or not _is_conn_error(e):
                            raise
                        try:
                            self._pgc.close()
                        except Exception:
                            pass
                        self._pgc = None
            cur = self._sq.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            self._sq.commit()
            return rows, cur.rowcount

    def query(self, sql, params=()):
        return self._exec(sql, tuple(params))[0]

    def run(self, sql, params=()):
        return self._exec(sql, tuple(params))[1]


_DBS = {}


def get_db(url=None):
    url = url or config.cfg("DATABASE_URL")
    if url not in _DBS:
        _DBS[url] = Db(url)
    return _DBS[url]


def kv_get(db, key, default=None):
    rows = db.query("SELECT value FROM kv WHERE key=?", (key,))
    if not rows:
        return default
    try:
        return json.loads(rows[0]["value"])
    except Exception:
        return default


def kv_set(db, key, value):
    db.run(
        "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def lock(db, name, ttl):
    """Cross-invocation lock. True if we got it."""
    now = time.time()
    k = "lock:" + name
    db.run("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING", (k, "0"))
    n = db.run(
        "UPDATE kv SET value=? WHERE key=? AND CAST(value AS NUMERIC) < ?",
        (str(now + ttl), k, now),
    )
    return n == 1


def unlock(db, name):
    db.run("UPDATE kv SET value='0' WHERE key=?", ("lock:" + name,))


def insert_item(db, item):
    """Insert a raw item. Returns True if it was new."""
    now = time.time()
    n = db.run(
        "INSERT INTO leads(id,key,source,url,text,author,priority,stage,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO NOTHING",
        (
            uuid.uuid4().hex,
            item["key"],
            item["source"],
            item.get("url"),
            (item.get("text") or "")[:4000],
            item.get("author"),
            int(item.get("priority", 0)),
            "new",
            now,
            now,
        ),
    )
    return n == 1


def update_lead(db, lead_id, **fields):
    cols, vals = [], []
    for k, v in fields.items():
        if k not in UPDATABLE:
            raise ValueError("cannot update column " + k)
        if k == "data" and not isinstance(v, str):
            v = json.dumps(v)
        cols.append(k + "=?")
        vals.append(v)
    cols.append("updated_at=?")
    vals.append(time.time())
    vals.append(lead_id)
    db.run("UPDATE leads SET " + ", ".join(cols) + " WHERE id=?", tuple(vals))
