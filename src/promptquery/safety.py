from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeQuery(Exception):
    """Raised when a generated SQL statement is not a pure read-only SELECT."""


_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,
)

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.With,
    exp.Subquery,
)

# Postgres and SQLite functions that can mutate state, execute shell commands, or access files.
_DANGEROUS_FUNCTIONS = {
    # Postgres
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "lo_import",
    "lo_export",
    "dblink_exec",
    "set_config",
    # SQLite
    "load_extension",
    "writefile",
    "readfile",
    "edit",
    "fts3_tokenizer",
}


def validate_select_only(
    sql: str,
    dialect: str = "postgres",
    allowed_tables: set[str] | None = None,
) -> None:
    """Validate that `sql` is a single, safe, read-only SELECT query.

    Checks:
    1. Single statement only
    2. Root statement is SELECT, UNION, INTERSECT, EXCEPT, or WITH
    3. Contains no DDL or DML nodes
    4. Calls no dangerous administrative / file-access functions
    5. Optionally verifies that all referenced tables belong to `allowed_tables`
    """
    sql = (sql or "").strip()
    if not sql:
        raise UnsafeQuery("empty SQL")

    read_dialect = "postgres" if dialect == "postgres" else "sqlite"
    try:
        statements = sqlglot.parse(sql, read=read_dialect)
    except Exception as e:
        # Fallback to postgres parser if sqlite parse fails on dialect nuances
        try:
            statements = sqlglot.parse(sql, read="postgres")
        except Exception as e2:
            raise UnsafeQuery(f"could not parse SQL: {e}") from e2

    statements = [s for s in statements if s is not None]
    if not statements:
        raise UnsafeQuery("empty SQL")
    if len(statements) > 1:
        raise UnsafeQuery("multiple statements are not allowed")

    stmt = statements[0]

    if not isinstance(stmt, _ALLOWED_ROOTS):
        raise UnsafeQuery(
            f"only SELECT queries are allowed (got {type(stmt).__name__})"
        )

    for forbidden in _FORBIDDEN_NODES:
        node = stmt.find(forbidden)
        if node is not None:
            raise UnsafeQuery(
                f"{type(node).__name__.upper()} statements are not allowed"
            )

    for func in stmt.find_all(exp.Anonymous):
        name = (func.name or "").lower()
        if name in _DANGEROUS_FUNCTIONS:
            raise UnsafeQuery(f"function {name!r} is not allowed")

    for func in stmt.find_all(exp.Func):
        name = (func.sql_name() or "").lower()
        if name in _DANGEROUS_FUNCTIONS:
            raise UnsafeQuery(f"function {name!r} is not allowed")

    if allowed_tables is not None:
        # Check referenced tables against known allowed tables
        lower_allowed = {t.lower() for t in allowed_tables}
        # Also allow without schema prefix
        unqualified_allowed = {t.rsplit(".", 1)[-1].lower() for t in allowed_tables}

        for table in stmt.find_all(exp.Table):
            t_name = table.name.lower()
            if not t_name:
                continue
            # CTE names are defined inside the query, not in schema
            # We don't flag CTE references
            if t_name not in lower_allowed and t_name not in unqualified_allowed:
                # Check if it's a CTE defined in this statement
                cte_names = {
                    cte.alias_or_name.lower()
                    for cte in stmt.find_all(exp.CTE)
                    if cte.alias_or_name
                }
                if t_name not in cte_names:
                    raise UnsafeQuery(
                        f"referenced table {table.name!r} is not present in available schema"
                    )


def ensure_safe_limit(sql: str, default_limit: int = 100) -> str:
    """Ensure non-aggregated queries have a reasonable LIMIT clause to prevent OOM."""
    sql_trimmed = sql.strip().rstrip(";")
    sql_upper = sql_trimmed.upper()

    if "LIMIT " in sql_upper:
        return sql_trimmed

    # If it's a pure scalar aggregation (e.g., SELECT COUNT(*) FROM ...), limit isn't needed
    if "GROUP BY" not in sql_upper and (
        "COUNT(" in sql_upper or "SUM(" in sql_upper or "AVG(" in sql_upper
    ):
        return sql_trimmed

    return f"{sql_trimmed} LIMIT {default_limit}"
