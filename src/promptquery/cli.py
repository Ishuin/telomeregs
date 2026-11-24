from __future__ import annotations

import csv
import io
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from . import __version__
from .conversation import ConversationSession, ConversationTurn
from .db import BaseDatabase, Database
from .llm import LLMClient, LLMError, extract_sql, make_client
from .prompts import build_system_prompt, build_user_prompt
from .render import render_results, render_sql
from .repair import execute_with_repair
from .retrieval import TfIdfRetriever, expand_via_fks, llm_select_tables
from .safety import UnsafeQuery, ensure_safe_limit, validate_select_only
from .schema import Schema, introspect


# -- Output formats --------------------------------------------------------

class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


def format_rows(cols: list[str], rows: list[tuple], fmt: OutputFormat) -> str:
    if fmt is OutputFormat.JSON:
        out = [dict(zip(cols, [_jsonify(v) for v in row])) for row in rows]
        return json.dumps(out, indent=2, default=str)
    if fmt is OutputFormat.CSV:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        for row in rows:
            writer.writerow(["" if v is None else str(v) for v in row])
        return buf.getvalue().rstrip("\n")
    raise ValueError(f"format_rows does not render {fmt!r}; use render_results for TABLE")


def _jsonify(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


# -- Query execution -------------------------------------------------------

class Outcome(str, Enum):
    OK = "ok"
    LLM_ERROR = "llm_error"
    EMPTY_SQL = "empty_sql"
    UNSAFE = "unsafe"
    EXEC_ERROR = "exec_error"
    SKIPPED = "skipped"


@dataclass
class QueryResult:
    outcome: Outcome
    sql: str | None
    cols: list[str]
    rows: list[tuple]
    error: str | None = None
    selected_tables: list[str] | None = None


def run_question(
    question: str,
    schema: Schema,
    retriever: TfIdfRetriever,
    llm: LLMClient,
    selector_llm: LLMClient | None,
    db: BaseDatabase,
    *,
    session: ConversationSession | None = None,
    top_k: int = 50,
    select_n: int = 15,
    max_tables: int = 30,
    confirm: bool = False,
    max_repair: int = 1,
    progress: Console | None = None,
    prompt_for_confirm=None,
) -> QueryResult:
    """Run a single NL question end-to-end, with multi-turn conversation context when provided."""
    # 1. Multi-turn retrieval query and table boosting
    boost_tables = session.get_recent_tables(depth=2) if session else None
    retrieval_query = session.get_expanded_retrieval_query(question) if session else question

    ranked = retriever.rank(retrieval_query, top_k=top_k, boost_tables=boost_tables)
    candidates = [t for t, score in ranked if score > 0] or [t for t, _ in ranked[:3]]

    # Ensure previous turn tables are present in candidates
    if boost_tables:
        schema_by_name = {t.name.lower(): t for t in schema.tables}
        for bt in boost_tables:
            bt_table = schema_by_name.get(bt.lower())
            if bt_table and bt_table not in candidates:
                candidates.insert(0, bt_table)

    # 2. Candidate pruning / LLM table selection
    if selector_llm is not None and len(candidates) > select_n:
        if progress:
            progress.print(f"[dim]Selecting from {len(candidates)} candidates...[/dim]")
        try:
            selected = llm_select_tables(retrieval_query, candidates, selector_llm, max_select=select_n)
            if selected:
                candidates = selected
        except Exception as e:
            if progress:
                progress.print(f"[yellow]Selector error, using TF-IDF only:[/yellow] {e}")
            candidates = candidates[:select_n]
    else:
        candidates = candidates[:select_n]

    # 3. Foreign key expansion (2 hops for deep ERP chains)
    relevant = expand_via_fks(schema, candidates, max_total=max_tables, hops=2)
    selected_table_names = [t.name for t in relevant]

    if progress:
        preview = ", ".join(t.qualified_name for t in relevant[:5])
        suffix = "..." if len(relevant) > 5 else ""
        progress.print(f"[dim]Using {len(relevant)} tables: {preview}{suffix}[/dim]")

    # 4. Prompt construction with conversation history
    dialect = getattr(db, "dialect", "postgres")
    tenant_id = session.tenant_id if session else None
    system_prompt = build_system_prompt(relevant, dialect=dialect, tenant_id=tenant_id)
    history_context = session.format_history_for_prompt() if session else ""
    user_prompt = build_user_prompt(question, history_context=history_context)

    # 5. LLM SQL Generation
    try:
        if progress:
            progress.print("[dim]Generating SQL...[/dim]")
        raw = llm.generate(system_prompt, user_prompt)
    except Exception as e:
        if session:
            session.add_turn(
                user_prompt=question,
                generated_sql=None,
                cols=[],
                rows=[],
                selected_tables=selected_table_names,
                error=str(e),
            )
        return QueryResult(Outcome.LLM_ERROR, None, [], [], str(e), selected_table_names)

    sql = extract_sql(raw)
    if not sql:
        if session:
            session.add_turn(
                user_prompt=question,
                generated_sql=None,
                cols=[],
                rows=[],
                selected_tables=selected_table_names,
                error="LLM returned an empty response.",
            )
        return QueryResult(Outcome.EMPTY_SQL, None, [], [], "LLM returned an empty response.", selected_table_names)

    # 6. Safety Validation
    try:
        validate_select_only(sql, dialect=dialect)
    except UnsafeQuery as e:
        if session:
            session.add_turn(
                user_prompt=question,
                generated_sql=sql,
                cols=[],
                rows=[],
                selected_tables=selected_table_names,
                error=str(e),
            )
        return QueryResult(Outcome.UNSAFE, sql, [], [], str(e), selected_table_names)

    # Enforce safe row limits for non-aggregated queries
    sql = ensure_safe_limit(sql, default_limit=100)

    if progress:
        render_sql(progress, sql)

    if confirm:
        if prompt_for_confirm is None:
            return QueryResult(Outcome.SKIPPED, sql, [], [], "no confirm callback", selected_table_names)
        answer = prompt_for_confirm().strip().lower()
        if answer not in {"y", "yes"}:
            return QueryResult(Outcome.SKIPPED, sql, [], [], "user declined", selected_table_names)

    def _confirm_repaired(repaired_sql: str) -> bool:
        if not confirm:
            return True
        if progress:
            render_sql(progress, repaired_sql)
        if prompt_for_confirm is None:
            return False
        return prompt_for_confirm().strip().lower() in {"y", "yes"}

    # 7. Execution with Self-Correction / Repair
    result = execute_with_repair(
        db,
        llm,
        system_prompt,
        user_prompt,
        sql,
        max_repair=max_repair,
        dialect=dialect,
        confirm_cb=_confirm_repaired if confirm else None,
        progress_cb=(lambda msg: progress.print(f"[yellow]{msg}[/yellow]")) if progress else None,
    )

    if result.declined:
        return QueryResult(Outcome.SKIPPED, result.sql, [], [], "user declined", selected_table_names)

    if result.error is not None:
        if session:
            session.add_turn(
                user_prompt=question,
                generated_sql=result.sql,
                cols=[],
                rows=[],
                selected_tables=selected_table_names,
                error=result.error,
            )
        return QueryResult(Outcome.EXEC_ERROR, result.sql, [], [], result.error, selected_table_names)

    if result.attempts and progress and not confirm:
        render_sql(progress, result.sql)

    # 8. Record successful turn into conversation history
    if session:
        session.add_turn(
            user_prompt=question,
            generated_sql=result.sql,
            cols=result.cols,
            rows=result.rows,
            selected_tables=selected_table_names,
        )

    return QueryResult(Outcome.OK, result.sql, result.cols, result.rows, None, selected_table_names)


# -- CLI -------------------------------------------------------------------

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("dsn", required=True)
@click.option(
    "--model",
    default=None,
    help="LLM model (e.g. claude-sonnet-4-6, gpt-4o, anthropic/claude-opus-4-7).",
)
@click.option(
    "--selector-model",
    default=None,
    help="LLM used for the table-selector step (defaults to --model).",
)
@click.option(
    "-q",
    "--query",
    default=None,
    help="Run a single question and exit (one-shot mode).",
)
@click.option(
    "--conversation-file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Run a multi-turn conversation from a JSON file (array of prompt strings or objects).",
)
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to pre-extracted schema JSON fixture (e.g., eval/fixtures/atlas.schema.json).",
)
@click.option(
    "--tenant",
    default=None,
    help="Tenant ID for multi-tenant ERP databases (e.g., acme, volume).",
)
@click.option(
    "--out",
    "out_format",
    type=click.Choice(["table", "json", "csv"], case_sensitive=False),
    default=None,
    help="Output format. Default: 'table' for REPL, 'json' for script modes.",
)
@click.option(
    "--top-k",
    default=50,
    show_default=True,
    help="Number of candidate tables to surface from TF-IDF before the LLM selector.",
)
@click.option(
    "--select",
    "select_n",
    default=15,
    show_default=True,
    help="Tables the LLM selector picks from the TF-IDF candidates.",
)
@click.option(
    "--max-tables",
    default=25,
    show_default=True,
    help="Maximum tables sent to the LLM after FK expansion.",
)
@click.option(
    "--max-repair",
    default=1,
    show_default=True,
    help="Repair rounds when a query fails: feed the database error back to the model and retry.",
)
@click.option(
    "--no-selector",
    is_flag=True,
    help="Disable the LLM table-selector and use TF-IDF + FK expansion only.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt before running queries (implied by --query).",
)
@click.version_option(__version__, prog_name="promptquery")
def main(
    dsn: str,
    model: str | None,
    selector_model: str | None,
    query: str | None,
    conversation_file: Path | None,
    schema_file: Path | None,
    tenant: str | None,
    out_format: str | None,
    top_k: int,
    select_n: int,
    max_tables: int,
    max_repair: int,
    no_selector: bool,
    yes: bool,
) -> None:
    """PromptQuery — AI Reporting Bot with multi-turn conversations and Atlas ERP support."""
    batch_mode = query is not None or conversation_file is not None
    progress = Console(stderr=batch_mode)
    out_fmt = OutputFormat(
        out_format.lower() if out_format
        else ("json" if batch_mode else "table")
    )

    try:
        llm = make_client(model)
    except LLMError as e:
        progress.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    if no_selector:
        selector_llm = None
    else:
        try:
            selector_llm = make_client(selector_model) if selector_model else llm
        except LLMError as e:
            progress.print(f"[red]Selector LLM error:[/red] {e}")
            sys.exit(1)

    progress.print(f"[dim]Connecting to[/dim] {_redact(dsn)} [dim]...[/dim]")
    try:
        db_ctx = Database(dsn).__enter__()
    except Exception as e:
        progress.print(f"[red]Connection failed:[/red] {e}")
        sys.exit(1)

    try:
        if schema_file:
            progress.print(f"[dim]Loading schema fixture from {schema_file}...[/dim]")
            schema = Schema.from_file(schema_file)
        else:
            progress.print("[dim]Introspecting schema...[/dim]")
            schema = introspect(db_ctx)

        if not schema.tables:
            progress.print("[yellow]No tables found in this database.[/yellow]")
            return

        selector_info = (
            f", selector: {selector_llm.name}/{selector_llm.model}"
            if selector_llm is not None and selector_llm is not llm
            else (" (selector: same)" if selector_llm is not None else " (selector: off)")
        )
        progress.print(
            f"[green]✓[/green] {len(schema.tables)} tables found "
            f"[dim](dialect: {getattr(db_ctx, 'dialect', 'postgres')}, sql: {llm.name}/{llm.model}{selector_info})[/dim]"
        )

        retriever = TfIdfRetriever(schema)

        if query:
            session = ConversationSession(tenant_id=tenant)
            sys.exit(_run_one_shot(
                question=query, schema=schema, retriever=retriever,
                llm=llm, selector_llm=selector_llm, db=db_ctx,
                session=session,
                top_k=top_k, select_n=select_n, max_tables=max_tables,
                max_repair=max_repair, out_fmt=out_fmt, progress=progress,
            ))

        if conversation_file:
            sys.exit(_run_conversation_file(
                conv_path=conversation_file, schema=schema, retriever=retriever,
                llm=llm, selector_llm=selector_llm, db=db_ctx,
                tenant_id=tenant, top_k=top_k, select_n=select_n, max_tables=max_tables,
                max_repair=max_repair, out_fmt=out_fmt, progress=progress,
            ))

        _run_repl(
            schema=schema, retriever=retriever,
            llm=llm, selector_llm=selector_llm, db=db_ctx,
            initial_tenant=tenant,
            top_k=top_k, select_n=select_n, max_tables=max_tables,
            max_repair=max_repair, out_fmt=out_fmt, yes=yes, progress=progress,
        )
    finally:
        db_ctx.close()


def _run_one_shot(*, question, schema, retriever, llm, selector_llm, db, session,
                  top_k, select_n, max_tables, max_repair,
                  out_fmt: OutputFormat, progress: Console) -> int:
    result = run_question(
        question=question, schema=schema, retriever=retriever,
        llm=llm, selector_llm=selector_llm, db=db,
        session=session,
        top_k=top_k, select_n=select_n, max_tables=max_tables,
        max_repair=max_repair, confirm=False, progress=progress,
    )

    if result.outcome is Outcome.LLM_ERROR:
        progress.print(f"[red]LLM error:[/red] {result.error}")
        return 1
    if result.outcome is Outcome.EMPTY_SQL:
        progress.print(f"[red]{result.error}[/red]")
        return 1
    if result.outcome is Outcome.UNSAFE:
        progress.print(f"[red]Refusing to run query:[/red] {result.error}")
        if result.sql:
            render_sql(progress, result.sql)
        return 2
    if result.outcome is Outcome.EXEC_ERROR:
        progress.print(f"[red]Query error:[/red] {result.error}")
        return 3

    if out_fmt is OutputFormat.TABLE:
        stdout_console = Console()
        render_results(stdout_console, result.cols, result.rows)
    else:
        sys.stdout.write(format_rows(result.cols, result.rows, out_fmt) + "\n")
    return 0


def _run_conversation_file(*, conv_path: Path, schema, retriever, llm, selector_llm, db,
                           tenant_id, top_k, select_n, max_tables, max_repair,
                           out_fmt: OutputFormat, progress: Console) -> int:
    with open(conv_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Allow either a list of string prompts: ["Prompt 1", "Prompt 2", ...]
    # or an object with "turns": [{"prompt": "..."}, ...] or list of conversations
    prompts: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                prompts.append(item)
            elif isinstance(item, dict) and "prompt" in item:
                prompts.append(item["prompt"])
            elif isinstance(item, dict) and "question" in item:
                prompts.append(item["question"])
    elif isinstance(data, dict):
        raw_turns = data.get("turns") or data.get("prompts") or []
        for item in raw_turns:
            if isinstance(item, str):
                prompts.append(item)
            elif isinstance(item, dict) and "prompt" in item:
                prompts.append(item["prompt"])
            elif isinstance(item, dict) and "question" in item:
                prompts.append(item["question"])

    session = ConversationSession(tenant_id=tenant_id, max_turns=len(prompts))
    conversation_results = []

    progress.print(f"[bold cyan]Running multi-turn conversation ({len(prompts)} turns):[/bold cyan]")

    for idx, prompt_text in enumerate(prompts, start=1):
        progress.print(f"\n[bold green]Turn {idx}/{len(prompts)}:[/bold green] {prompt_text}")
        res = run_question(
            question=prompt_text,
            schema=schema,
            retriever=retriever,
            llm=llm,
            selector_llm=selector_llm,
            db=db,
            session=session,
            top_k=top_k,
            select_n=select_n,
            max_tables=max_tables,
            max_repair=max_repair,
            confirm=False,
            progress=progress,
        )

        turn_report = {
            "turn": idx,
            "prompt": prompt_text,
            "outcome": res.outcome.value,
            "sql": res.sql,
            "error": res.error,
            "cols": res.cols,
            "row_count": len(res.rows),
            "rows_preview": [list(r) for r in res.rows[:5]],
        }
        conversation_results.append(turn_report)

    output_data = {
        "tenant_id": tenant_id,
        "total_turns": len(prompts),
        "results": conversation_results,
    }
    sys.stdout.write(json.dumps(output_data, indent=2, default=str) + "\n")
    return 0


def _run_repl(*, schema, retriever, llm, selector_llm, db, initial_tenant,
              top_k, select_n, max_tables, max_repair,
              out_fmt: OutputFormat, yes: bool, progress: Console) -> None:
    session = PromptSession(history=InMemoryHistory())
    conv = ConversationSession(tenant_id=initial_tenant, max_turns=6)

    tenant_info = f" [tenant: {conv.tenant_id}]" if conv.tenant_id else ""
    progress.print(
        f"\n[bold]PromptQuery AI Report Bot[/bold]{tenant_info} — ask reporting questions in plain English.\n"
        "Commands: [bold]/reset[/bold] (new conversation), [bold]/history[/bold] (show turns), "
        "[bold]/tenant <id>[/bold], [bold]exit[/bold] to quit.\n"
    )

    while True:
        turn_num = conv.current_turn_number
        prompt_label = f"[Turn {turn_num}/6] ? " if turn_num <= 6 else f"[Turn {turn_num}] ? "
        try:
            question = session.prompt(prompt_label).strip()
        except (KeyboardInterrupt, EOFError):
            progress.print("\n[dim]bye[/dim]")
            return

        if not question:
            continue

        q_lower = question.lower()
        if q_lower in {"exit", "quit", r"\q"}:
            return

        if q_lower in {"/reset", "reset", "/clear", "clear"}:
            conv.clear()
            progress.print("[dim]Conversation reset. Starting a new session.[/dim]\n")
            continue

        if q_lower in {"/history", "history"}:
            if not conv.turns:
                progress.print("[dim]No previous turns in this session.[/dim]\n")
            else:
                for t in conv.turns:
                    progress.print(f"[bold cyan]Turn {t.turn_index}:[/bold cyan] {t.user_prompt}")
                    if t.generated_sql:
                        render_sql(progress, t.generated_sql)
                    if t.rows:
                        progress.print(f"[dim]({len(t.rows)} rows returned)[/dim]")
                progress.print()
            continue

        if q_lower.startswith("/tenant ") or q_lower.startswith("tenant "):
            new_tenant = question.split(maxsplit=1)[1].strip()
            conv.tenant_id = new_tenant
            progress.print(f"[green]Active tenant set to:[/green] {new_tenant}\n")
            continue

        result = run_question(
            question=question, schema=schema, retriever=retriever,
            llm=llm, selector_llm=selector_llm, db=db,
            session=conv,
            top_k=top_k, select_n=select_n, max_tables=max_tables,
            max_repair=max_repair, confirm=not yes, progress=progress,
            prompt_for_confirm=(lambda: session.prompt("Run? [y/N] ")) if not yes else None,
        )

        if result.outcome is Outcome.LLM_ERROR:
            progress.print(f"[red]LLM error:[/red] {result.error}")
        elif result.outcome is Outcome.EMPTY_SQL:
            progress.print(f"[red]{result.error}[/red]")
        elif result.outcome is Outcome.UNSAFE:
            progress.print(f"[red]Refusing to run query:[/red] {result.error}")
            if result.sql:
                render_sql(progress, result.sql)
        elif result.outcome is Outcome.EXEC_ERROR:
            progress.print(f"[red]Query error:[/red] {result.error}\n")
        elif result.outcome is Outcome.SKIPPED:
            progress.print("[dim]Skipped.[/dim]\n")
        else:  # OK
            if out_fmt is OutputFormat.TABLE:
                render_results(progress, result.cols, result.rows)
            else:
                progress.print(format_rows(result.cols, result.rows, out_fmt))
            progress.print()


def _redact(dsn: str) -> str:
    if "://" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    if "@" in rest:
        creds, _, host = rest.partition("@")
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return dsn


if __name__ == "__main__":
    main()
