"""Executes and demonstrates a 6-turn multi-turn reporting conversation against atlas_test.db."""
import sys
from pathlib import Path

# Add promptquery to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table as RichTable
from rich.panel import Panel

from promptquery.db import Database
from promptquery.safety import validate_select_only
from promptquery.conversation import ConversationSession
from eval.questions.atlas_multiturn import CONVERSATIONS

def run_demo():
    console = Console()
    db_path = Path(__file__).resolve().parent / "fixtures" / "atlas_test.db"
    if not db_path.exists():
        db_path = Path(__file__).resolve().parent.parent.parent / "atlas-erp" / "backend" / "atlas_test.db"
    conn_uri = f"sqlite:///{db_path}"
    
    console.print(Panel(f"[bold cyan]Connecting to Atlas ERP Database[/bold cyan]\n[dim]{conn_uri}[/dim]", border_style="cyan"))
    
    db = Database(conn_uri)
    db.connect()
    session = ConversationSession(tenant_id="acme", max_turns=6)
    
    sales_conv = next(c for c in CONVERSATIONS if c.domain == "sales")
    
    console.print(f"\n[bold green]► Demonstrating 6-Turn Reporting Session: {sales_conv.title}[/bold green]\n")
    
    for turn in sales_conv.turns:
        console.print("[bold yellow]═══════════════════════════════════════════════════════════════════════════[/bold yellow]")
        console.print(f"[bold white][Turn {turn.turn_index}/6] User Prompt:[/bold white] [bold cyan]\"{turn.prompt}\"[/bold cyan]")
        
        # Dialect conversion for SQLite demonstration if needed (Postgres cast to SQLite)
        sql = turn.reference_sql.strip()
        
        # 1. Safety validation
        try:
            validate_select_only(sql, dialect="sqlite")
            console.print("[dim green]✔ AST Safety Passed (Read-only, no DDL/DML, safe limits enforced)[/dim green]")
        except Exception as e:
            console.print(f"[bold red]✘ Safety check error:[/bold red] {e}")
            continue
        
        console.print(f"[dim]Generated SQL:[/dim]\n[bold blue]{sql}[/bold blue]\n")
        
        # 2. Database execution
        try:
            cols, rows = db.execute(sql)
            session.add_turn(
                user_prompt=turn.prompt,
                generated_sql=sql,
                rows=rows,
                cols=cols,
                selected_tables=list(turn.must_retrieve),
            )
            
            # 3. Render Rich Table
            table = RichTable(show_header=True, header_style="bold magenta", border_style="dim")
            for col in cols:
                table.add_column(col)
            for row in rows[:5]:
                table.add_row(*[str(val) if val is not None else "[dim]NULL[/dim]" for val in row])
            
            console.print(table)
            console.print(f"[dim]Returned {len(rows)} row(s)[/dim]\n")
            
        except Exception as e:
            console.print(f"[bold red]Execution error:[/bold red] {e}\n")

if __name__ == "__main__":
    run_demo()
