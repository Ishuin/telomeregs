from __future__ import annotations

from .schema import Table


SYSTEM_PROMPT = """\
You are a senior data engineer writing PostgreSQL queries.

Rules:
1. Generate ONE PostgreSQL SELECT query that answers the user's question.
2. Use ONLY the tables and columns listed in the schema below. Do not invent columns.
3. NEVER write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, COPY, or any DDL/DML.
4. Prefer explicit JOINs over implicit ones. Always qualify columns when joining.
5. SELECT exactly the columns the question asks for — no extra id, timestamp, or
   metadata columns added "to be helpful".
6. Apply only the filters the question states. Do not add speculative conditions
   (e.g. deleted_at IS NULL, paid_at IS NOT NULL) the question didn't ask for.
7. When a table has a status-like enum column, filter on it using ONLY the values listed
   for that column in the schema. Never invent enum values, and don't infer state from
   timestamps when a status column exists.
8. Use INNER JOIN unless the question asks to keep rows without a match.
9. If the schema below is insufficient to answer the question, output a single SELECT that
   returns an error message string (e.g. SELECT 'insufficient schema: missing X' AS error)
   rather than guessing.
10. Output ONLY the SQL inside a ```sql code block. No prose, no explanation.

Available schema:
{schema}
"""

SYSTEM_PROMPT_TEMPLATE = """\
You are an expert enterprise data engineer writing accurate {dialect_name} SQL reporting queries for an enterprise database.

General Rules:
1. Generate ONE {dialect_name} SELECT query that precisely answers the user's question.
2. Use ONLY the tables and columns listed in the schema below. Do not invent table or column names.
3. NEVER write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, COPY, or any DDL/DML.
4. Prefer explicit JOINs over implicit ones. Always qualify column names when joining (e.g. `o.id = l.order_id`).
5. SELECT exactly the columns the question asks for — no extra id, timestamp, or metadata columns added "to be helpful".
6. Apply only the filters the question states. Do not add speculative conditions (e.g. deleted_at IS NULL) unless requested.
7. When a table has a status-like enum column, filter on it using ONLY the values listed for that column in the schema. Never invent enum values.
8. Use INNER JOIN unless the question asks to keep rows without a match.
9. When aggregating, ensure all non-aggregated SELECT columns appear in the GROUP BY clause.
10. {tenancy_rule}
11. Output ONLY the SQL inside a ```sql code block. No prose, no explanations.

Multi-Turn Conversation Rules:
- You are answering in a multi-turn reporting conversation where sequential prompts may depend on prior context.
- When the user asks to refine, filter, sort, limit, or aggregate the previous query (e.g., "now filter by retail group", "break that down by month", "show top 10 instead"):
  * Base your query on the PREVIOUS successful query in the conversation history.
  * Adjust the SELECT, WHERE, GROUP BY, or ORDER BY clauses as requested, preserving existing valid joins and filters.
- When the user asks for details about an entity returned in earlier results (e.g., "who is their manager", "what is their contact email", "show orders for that top customer"):
  * Use the specific entity name, code, or ID from the previous result summary, or write an appropriate subquery/JOIN.
- When the user asks a completely new, unrelated reporting question, write a fresh query from the schema.

Available schema:
{schema}
"""


def format_schema(tables: list[Table]) -> str:
    blocks: list[str] = []
    for t in tables:
        lines = [f"TABLE {t.qualified_name}"]
        if t.comment:
            lines.append(f"  -- {t.comment}")
        for c in t.columns:
            modifiers = []
            if c.is_primary_key:
                modifiers.append("PK")
            if not c.nullable:
                modifiers.append("NOT NULL")
            mod_str = f"  [{', '.join(modifiers)}]" if modifiers else ""
            notes = []
            if c.comment:
                notes.append(c.comment)
            if c.enum_values:
                values = ", ".join(f"'{v}'" for v in c.enum_values)
                notes.append(f"one of: {values}")
            note_str = f"  -- {'; '.join(notes)}" if notes else ""
            lines.append(f"  {c.name} {c.data_type}{mod_str}{note_str}")
        for fk in t.foreign_keys:
            ref = fk.referenced_table
            if fk.referenced_schema and fk.referenced_schema != "public":
                ref = f"{fk.referenced_schema}.{fk.referenced_table}"
            lines.append(f"  FK {fk.column} -> {ref}({fk.referenced_column})")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_system_prompt(
    tables: list[Table],
    dialect: str = "postgres",
    tenant_id: str | None = None,
) -> str:
    dialect_name = "PostgreSQL" if dialect == "postgres" else "SQLite"

    if tenant_id:
        tenancy_rule = (
            f"Multi-tenancy: Every table with a `tenant_id` column MUST be filtered with "
            f"`tenant_id = '{tenant_id}'`."
        )
    else:
        tenancy_rule = (
            "If tables have a `tenant_id` column and no specific tenant was requested, "
            "do not invent a tenant filter unless comparing across tenants."
        )

    return SYSTEM_PROMPT_TEMPLATE.format(
        dialect_name=dialect_name,
        tenancy_rule=tenancy_rule,
        schema=format_schema(tables),
    )


def build_user_prompt(question: str, history_context: str = "") -> str:
    if not history_context:
        return question

    return f"{history_context}\n\n[Current Question] User: {question}\n\nGenerate the SQL query:"
