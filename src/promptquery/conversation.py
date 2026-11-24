from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationTurn:
    turn_index: int
    user_prompt: str
    generated_sql: str | None = None
    cols: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    selected_tables: list[str] = field(default_factory=list)
    error: str | None = None
    summary: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def format_results_preview(self, max_rows: int = 5) -> str:
        if not self.rows or not self.cols:
            if self.error:
                return f"Error: {self.error}"
            return "No rows returned."

        preview_rows = self.rows[:max_rows]
        lines = [", ".join(self.cols)]
        for r in preview_rows:
            lines.append(", ".join(str(v) if v is not None else "NULL" for v in r))
        if len(self.rows) > max_rows:
            lines.append(f"... and {len(self.rows) - max_rows} more rows ({len(self.rows)} total)")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "user_prompt": self.user_prompt,
            "generated_sql": self.generated_sql,
            "cols": self.cols,
            "row_count": len(self.rows),
            "rows_preview": [list(r) for r in self.rows[:10]],
            "selected_tables": self.selected_tables,
            "error": self.error,
            "summary": self.summary,
        }


class ConversationSession:
    """Maintains multi-turn conversation state across sequential reporting prompts (up to 6+)."""

    def __init__(self, tenant_id: str | None = None, max_turns: int = 6):
        self.turns: list[ConversationTurn] = []
        self.tenant_id: str | None = tenant_id
        self.max_turns = max_turns

    @property
    def current_turn_number(self) -> int:
        return len(self.turns) + 1

    @property
    def last_turn(self) -> ConversationTurn | None:
        return self.turns[-1] if self.turns else None

    def add_turn(
        self,
        user_prompt: str,
        generated_sql: str | None,
        cols: list[str],
        rows: list[tuple],
        selected_tables: list[str],
        error: str | None = None,
        summary: str | None = None,
    ) -> ConversationTurn:
        turn = ConversationTurn(
            turn_index=self.current_turn_number,
            user_prompt=user_prompt,
            generated_sql=generated_sql,
            cols=cols,
            rows=rows,
            selected_tables=selected_tables,
            error=error,
            summary=summary,
        )
        self.turns.append(turn)
        return turn

    def clear(self) -> None:
        self.turns.clear()

    def get_recent_tables(self, depth: int = 2) -> list[str]:
        """Collect table names referenced in recent turns for table selection retention."""
        tables: list[str] = []
        seen: set[str] = set()
        for turn in reversed(self.turns[-depth:]):
            for t in turn.selected_tables:
                if t not in seen:
                    tables.append(t)
                    seen.add(t)
        return tables

    def get_expanded_retrieval_query(self, current_question: str) -> str:
        """Enrich current question with context from previous turn without diluting current terms."""
        if not self.turns:
            return current_question

        # Repeat current question twice so its specific terms out-weight background context
        parts = [current_question, current_question]

        # Check if question has demonstratives / follow-up words that need prior context
        q_lower = current_question.lower()
        has_followup_cue = any(
            k in q_lower
            for k in ("filter", "break down", "group", "sort", "show only", "only")
        ) or bool(set(q_lower.split()) & {"that", "this", "it", "them"})

        last = self.turns[-1]
        if has_followup_cue and last.user_prompt:
            parts.append(last.user_prompt)

        return " ".join(parts)

    def format_history_for_prompt(self, max_turns: int = 5) -> str:
        """Format previous turns as structured conversation history for SQL generation prompt."""
        if not self.turns:
            return ""

        recent = self.turns[-max_turns:]
        blocks: list[str] = ["Conversation history (previous turns):"]
        for turn in recent:
            block = [f"[Turn {turn.turn_index}] User: {turn.user_prompt}"]
            if turn.generated_sql:
                block.append(f"Generated SQL:\n```sql\n{turn.generated_sql}\n```")
                block.append(f"Result summary: {turn.format_results_preview(max_rows=3)}")
            elif turn.error:
                block.append(f"Execution Error: {turn.error}")
            blocks.append("\n".join(block))

        return "\n\n".join(blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "total_turns": len(self.turns),
            "turns": [t.to_dict() for t in self.turns],
        }
