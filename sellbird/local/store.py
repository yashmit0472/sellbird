"""SQLite records, durable jobs and a local inference audit trail."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL, name TEXT NOT NULL, brief TEXT NOT NULL,
    exclusion_phrases TEXT NOT NULL DEFAULT '',
    UNIQUE(company, name)
);
CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    prospect_id INTEGER NOT NULL REFERENCES prospects(id),
    source TEXT NOT NULL, body TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prospect_id, source, body)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    prospect_id INTEGER REFERENCES prospects(id),
    status TEXT NOT NULL DEFAULT 'queued',
    model TEXT NOT NULL, input TEXT NOT NULL, results TEXT NOT NULL DEFAULT '{}',
    error TEXT, attempts INTEGER NOT NULL DEFAULT 0, resume_at INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS inference (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    step TEXT NOT NULL, model TEXT NOT NULL, endpoint TEXT NOT NULL,
    status TEXT NOT NULL, elapsed_ms INTEGER NOT NULL,
    output_tokens INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            columns = {column["name"] for column in conn.execute("PRAGMA table_info(products)")}
            if "exclusion_phrases" not in columns:
                conn.execute("ALTER TABLE products ADD COLUMN exclusion_phrases TEXT NOT NULL DEFAULT ''")

    def rows(self, query, params=()):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def write(self, query, params=()):
        with self.connection() as conn:
            return conn.execute(query, params).lastrowid

    def add_evidence(self, name, source, body):
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO prospects(name) VALUES (?)", (name,))
            prospect_id = conn.execute("SELECT id FROM prospects WHERE name = ?", (name,)).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO evidence(prospect_id, source, body) VALUES (?, ?, ?)",
                (prospect_id, source, body),
            )
            return prospect_id

    def claim(self):
        # One worker can hold the next ready job. The update is atomic.
        rows = self.rows(
            """UPDATE jobs SET status = 'running', attempts = attempts + 1, error = NULL
               WHERE id = (SELECT id FROM jobs WHERE status IN ('queued', 'waiting')
                           AND resume_at <= unixepoch() ORDER BY id LIMIT 1)
               RETURNING *"""
        )
        return rows[0] if rows else None

    def save(self, job_id, results, status, error=None, delay=0):
        self.write(
            """UPDATE jobs SET results = ?, status = ?, error = ?,
               resume_at = unixepoch() + ? WHERE id = ?""",
            (json.dumps(results, ensure_ascii=False), status, error, delay, job_id),
        )
