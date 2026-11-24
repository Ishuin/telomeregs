from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .llm import LLMClient, extract_sql
from .safety import UnsafeQuery, validate_select_only

if TYPE_CHECKING:
    from .db import BaseDatabase


REPAIR_PROMPT = """\
The query below failed when run against the database. Fix it and return a corrected
query, following all the rules above (including the schema's enum value lists and table structure).

Question: {question}

Failed SQL:
{sql}

Database error:
{error}

Output ONLY the corrected SQL inside a ```sql code block."""


@dataclass
class RepairResult:
    sql: str                              # the SQL that was last attempted
    cols: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None              # None = executed successfully
    attempts: int = 0                     # repair rounds actually used
    declined: bool = False                # user declined a repaired query (REPL confirm)


def execute_with_repair(
    db: "BaseDatabase",
    llm: LLMClient,
    system_prompt: str,
    question: str,
    sql: str,
    *,
    max_repair: int = 2,
    dialect: str = "postgres",
    confirm_cb: Callable[[str], bool] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> RepairResult:
    """Execute `sql`; on a database error, ask the model to repair it (<= max_repair rounds).

    Repaired SQL goes through validate_select_only before it is ever executed.
    """
    attempts = 0
    current = sql
    while True:
        try:
            cols, rows = db.execute(current)
            return RepairResult(current, cols, rows, None, attempts)
        except Exception as e:
            error = str(e)

        if attempts >= max_repair:
            return RepairResult(current, error=error, attempts=attempts)
        attempts += 1
        if progress_cb:
            progress_cb(f"query failed ({error.splitlines()[0]}); repairing [{attempts}/{max_repair}]")

        try:
            raw = llm.generate(
                system_prompt,
                REPAIR_PROMPT.format(question=question, sql=current, error=error),
            )
        except Exception:
            return RepairResult(current, error=error, attempts=attempts)

        repaired = extract_sql(raw)
        if not repaired or repaired == current:
            return RepairResult(current, error=error, attempts=attempts)
        try:
            validate_select_only(repaired, dialect=dialect)
        except UnsafeQuery:
            return RepairResult(current, error=error, attempts=attempts)

        if confirm_cb is not None and not confirm_cb(repaired):
            return RepairResult(repaired, error=error, attempts=attempts, declined=True)
        current = repaired
