from promptquery.conversation import ConversationSession


def test_conversation_turn_lifecycle():
    session = ConversationSession(tenant_id="acme", max_turns=6)
    assert session.current_turn_number == 1
    assert session.last_turn is None

    # Turn 1
    t1 = session.add_turn(
        user_prompt="What are our top 5 products by revenue?",
        generated_sql="SELECT name, SUM(line_total) FROM sales_order_lines GROUP BY name ORDER BY 2 DESC LIMIT 5;",
        cols=["name", "revenue"],
        rows=[("Laptop 15", 50000), ("Keyboard", 12000)],
        selected_tables=["sales_order_lines", "inv_items"],
    )
    assert t1.turn_index == 1
    assert session.current_turn_number == 2
    assert session.last_turn == t1
    assert session.get_recent_tables() == ["sales_order_lines", "inv_items"]

    # Turn 2: Follow-up
    t2 = session.add_turn(
        user_prompt="Filter that to only retail customers",
        generated_sql="SELECT name, SUM(line_total) FROM sales_order_lines JOIN sales_orders ON ... WHERE customer_group = 'Retail' GROUP BY name ORDER BY 2 DESC LIMIT 5;",
        cols=["name", "revenue"],
        rows=[("Laptop 15", 35000)],
        selected_tables=["sales_order_lines", "sales_orders", "sales_customers", "sales_customer_groups"],
    )
    assert t2.turn_index == 2
    assert session.current_turn_number == 3

    # Check history formatting
    history = session.format_history_for_prompt()
    assert "[Turn 1] User: What are our top 5 products by revenue?" in history
    assert "[Turn 2] User: Filter that to only retail customers" in history
    assert "Laptop 15" in history

    # Check serialization
    data = session.to_dict()
    assert data["tenant_id"] == "acme"
    assert data["total_turns"] == 2
    assert len(data["turns"]) == 2

    # Check reset
    session.clear()
    assert session.current_turn_number == 1
    assert session.last_turn is None
