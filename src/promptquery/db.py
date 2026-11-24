from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore


class BaseDatabase(ABC):
    dialect: str

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def fetch_dicts(self, sql: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def execute(self, sql: str) -> tuple[list[str], list[tuple]]: ...

    def __enter__(self) -> BaseDatabase:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class PostgresDatabase(BaseDatabase):
    dialect = "postgres"

    def __init__(self, dsn: str):
        if psycopg is None:
            raise RuntimeError(
                "psycopg is not installed. Install it with: pip install 'promptquery[postgres]'"
            )
        self.dsn = dsn
        self.conn: psycopg.Connection | None = None

    def connect(self) -> None:
        self.conn = psycopg.connect(self.dsn, autocommit=True)
        with self.conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute("SET statement_timeout = '60s'")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require_conn(self) -> psycopg.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    def fetch_dicts(self, sql: str) -> list[dict[str, Any]]:
        conn = self._require_conn()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return list(cur.fetchall())

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                return [], []
            cols = [d.name for d in cur.description]
            rows = list(cur.fetchall())
        return cols, rows


class SqliteDatabase(BaseDatabase):
    dialect = "sqlite"

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.db_path = self._parse_path(dsn)
        self.conn: sqlite3.Connection | None = None

    @staticmethod
    def _parse_path(dsn: str) -> str:
        if dsn.startswith("sqlite:///"):
            return dsn[len("sqlite:///"):]
        if dsn.startswith("sqlite://"):
            return dsn[len("sqlite://"):]
        if dsn.startswith("sqlite:"):
            return dsn[len("sqlite:"):]
        return dsn

    def connect(self) -> None:
        if self.db_path != ":memory:" and not os.path.exists(self.db_path):
            raise FileNotFoundError(f"SQLite database file not found: {self.db_path}")

        # Connect with URI or file path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA query_only = ON")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    def fetch_dicts(self, sql: str) -> list[dict[str, Any]]:
        conn = self._require_conn()
        orig_factory = conn.row_factory
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.row_factory = orig_factory

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = self._require_conn()
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is None:
            return [], []
        cols = [d[0] for d in cur.description]
        rows = list(cur.fetchall())
        return cols, rows


def is_sqlite(dsn: str) -> bool:
    dsn_lower = dsn.lower().strip()
    return (
        dsn_lower.startswith("sqlite:")
        or dsn_lower.startswith("sqlite3:")
        or dsn_lower.endswith(".db")
        or dsn_lower.endswith(".sqlite")
        or dsn_lower.endswith(".sqlite3")
    )


def Database(dsn: str) -> BaseDatabase:
    """Factory returning PostgresDatabase or SqliteDatabase depending on DSN."""
    if is_sqlite(dsn):
        return SqliteDatabase(dsn)
    return PostgresDatabase(dsn)
