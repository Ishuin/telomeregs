import sqlite3
import pytest
from promptquery.db import Database, SqliteDatabase, is_sqlite
from promptquery.schema import introspect


def test_is_sqlite():
    assert is_sqlite("sqlite:///test.db")
    assert is_sqlite("sqlite:test.db")
    assert is_sqlite("my_database.db")
    assert is_sqlite("my_database.sqlite")
    assert not is_sqlite("postgresql://localhost/mydb")
    assert not is_sqlite("postgres://user:pass@host:5432/db")


def test_sqlite_database_execution(tmp_path):
    db_file = tmp_path / "test.db"
    raw_conn = sqlite3.connect(db_file)
    raw_conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    raw_conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com'), (2, 'Bob', 'bob@test.com')")
    raw_conn.commit()
    raw_conn.close()

    db = Database(f"sqlite:///{db_file}")
    assert isinstance(db, SqliteDatabase)
    assert db.dialect == "sqlite"

    with db:
        cols, rows = db.execute("SELECT name, email FROM users ORDER BY id")
        assert cols == ["name", "email"]
        assert rows == [("Alice", "alice@test.com"), ("Bob", "bob@test.com")]

        dicts = db.fetch_dicts("SELECT name FROM users WHERE id = 1")
        assert dicts == [{"name": "Alice"}]

        # Safety: verify read-only pragma prevents mutations
        with pytest.raises(Exception):
            db.execute("INSERT INTO users VALUES (3, 'Charlie', 'charlie@test.com')")


def test_sqlite_introspection(tmp_path):
    db_file = tmp_path / "company.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, dept_name TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE employees ("
        "id INTEGER PRIMARY KEY, "
        "emp_name TEXT NOT NULL, "
        "dept_id INTEGER, "
        "FOREIGN KEY (dept_id) REFERENCES departments(id)"
        ")"
    )
    conn.commit()
    conn.close()

    with Database(f"sqlite:///{db_file}") as db:
        schema = introspect(db)
        by_name = {t.name: t for t in schema.tables}
        assert "departments" in by_name
        assert "employees" in by_name

        emp_table = by_name["employees"]
        col_names = [c.name for c in emp_table.columns]
        assert "id" in col_names
        assert "emp_name" in col_names
        assert "dept_id" in col_names

        fks = emp_table.foreign_keys
        assert len(fks) == 1
        assert fks[0].column == "dept_id"
        assert fks[0].referenced_table == "departments"
        assert fks[0].referenced_column == "id"
