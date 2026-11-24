import json
from click.testing import CliRunner
from promptquery.cli import main


class DummyLLM:
    name = "dummy"
    model = "mock-model"

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or [
            "```sql\nSELECT name, price FROM inv_items ORDER BY price DESC LIMIT 5;\n```",
            "```sql\nSELECT name, price FROM inv_items WHERE price > 500 ORDER BY price DESC LIMIT 5;\n```",
            "```sql\nSELECT count(*) FROM inv_items WHERE price > 500;\n```",
        ]
        self.call_count = 0
        self.last_system = None
        self.last_user = None

    def generate(self, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return resp


def test_cli_conversation_file(tmp_path, monkeypatch):
    # Create a dummy sqlite db with inv_items
    db_file = tmp_path / "test_atlas.db"
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE inv_items (id INTEGER PRIMARY KEY, name TEXT, price REAL, tenant_id TEXT)")
    conn.execute("INSERT INTO inv_items VALUES (1, 'Server Rack', 1200.0, 'acme'), (2, 'Laptop Pro', 850.0, 'acme'), (3, 'Mouse', 25.0, 'acme')")
    conn.commit()
    conn.close()

    # Create a conversation file with 3 sequential prompts
    conv_file = tmp_path / "conversation.json"
    conv_data = [
        "What are the top 5 most expensive items?",
        "Filter that to items over 500 dollars",
        "How many items meet that condition?",
    ]
    with open(conv_file, "w") as f:
        json.dump(conv_data, f)

    dummy_llm = DummyLLM()
    monkeypatch.setattr("promptquery.cli.make_client", lambda model=None: dummy_llm)

    runner = CliRunner()
    result = runner.invoke(main, [
        f"sqlite:///{db_file}",
        "--conversation-file", str(conv_file),
        "--tenant", "acme",
        "--no-selector",
    ])

    assert result.exit_code == 0
    # Extract json block from stdout
    json_start = result.output.find("{")
    json_end = result.output.rfind("}")
    assert json_start != -1 and json_end != -1
    json_str = result.output[json_start : json_end + 1]

    output = json.loads(json_str)
    assert output["tenant_id"] == "acme"
    assert output["total_turns"] == 3
    assert len(output["results"]) == 3

    # Turn 1
    t1 = output["results"][0]
    assert t1["turn"] == 1
    assert t1["outcome"] == "ok"
    assert t1["row_count"] == 3

    # Turn 2
    t2 = output["results"][1]
    assert t2["turn"] == 2
    assert t2["outcome"] == "ok"
    assert t2["row_count"] == 2

    # Turn 3
    t3 = output["results"][2]
    assert t3["turn"] == 3
    assert t3["outcome"] == "ok"
    assert t3["rows_preview"][0][0] == 2
