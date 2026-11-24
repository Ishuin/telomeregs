from pathlib import Path
from promptquery.conversation import ConversationSession
from promptquery.retrieval import TfIdfRetriever, expand_via_fks
from promptquery.schema import Schema


def _load_atlas_schema() -> Schema:
    fixture_path = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "atlas.schema.json"
    assert fixture_path.exists(), f"Atlas schema fixture missing at {fixture_path}"
    return Schema.from_file(fixture_path)


def test_atlas_schema_loads_all_tables():
    schema = _load_atlas_schema()
    assert len(schema.tables) >= 130
    by_name = {t.name: t for t in schema.tables}

    # Verify key Atlas ERP tables across business domains exist
    assert "sales_orders" in by_name
    assert "sales_order_lines" in by_name
    assert "sales_customers" in by_name
    assert "inv_items" in by_name
    assert "inv_stock_quants" in by_name
    assert "proc_vendors" in by_name
    assert "proc_purchase_orders" in by_name
    assert "fin_journal_entries" in by_name
    assert "fin_journal_lines" in by_name
    assert "hr_employees" in by_name


def test_atlas_domain_synonym_retrieval():
    schema = _load_atlas_schema()
    retriever = TfIdfRetriever(schema)

    # Question asking about "products" should retrieve inv_items (Atlas ERP uses item, not product)
    ranked = retriever.rank("top 5 selling products by quantity", top_k=10)
    top_table_names = [t.name for t, _ in ranked]
    assert "inv_items" in top_table_names or "sales_order_lines" in top_table_names

    # Question asking about "suppliers" should retrieve proc_vendors (Atlas uses vendor, not supplier)
    ranked_vendors = retriever.rank("list all active suppliers and their payment terms", top_k=10)
    vendor_table_names = [t.name for t, _ in ranked_vendors]
    assert "proc_vendors" in vendor_table_names

    # Question asking about "revenue" should retrieve sales or finance journal lines
    ranked_rev = retriever.rank("total quarterly revenue by sales customer", top_k=10)
    rev_table_names = [t.name for t, _ in ranked_rev]
    assert any(name in rev_table_names for name in ["sales_customers", "sales_orders", "sales_order_lines", "fin_journal_lines"])


def test_atlas_multiturn_context_boost():
    schema = _load_atlas_schema()
    retriever = TfIdfRetriever(schema)
    session = ConversationSession(tenant_id="acme")

    # Turn 1: user asks about customers
    session.add_turn(
        user_prompt="list top 10 customers by revenue",
        generated_sql="SELECT c.name, SUM(l.line_total) FROM sales_customers c ...",
        cols=["name", "total"],
        rows=[("Acme Corp", 10000)],
        selected_tables=["sales_customers", "sales_orders", "sales_order_lines"],
    )

    # Turn 2: Follow-up question has no explicit mention of customers or sales!
    followup = "now filter by the retail group"
    expanded = session.get_expanded_retrieval_query(followup)
    assert "customers" in expanded or "sales" in expanded

    # Boost tables from turn 1
    recent = session.get_recent_tables()
    ranked = retriever.rank(expanded, top_k=10, boost_tables=recent)
    top_names = [t.name for t, _ in ranked]

    # Verify that the primary tables from Turn 1 are retained in top candidates
    assert "sales_customers" in top_names or "sales_orders" in top_names
