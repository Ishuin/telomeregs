"""Atlas ERP Multi-Turn Benchmark Questions.

Provides realistic multi-turn reporting conversations (up to 6 turns each) across:
- Sales & Revenue
- Inventory & Stock Topology
- Procurement & Vendor Relations
- Finance & Universal Journal
- HR & Payroll

Used to evaluate PromptQuery's accuracy, table selection, join resolution, and context preservation
across sequential conversation turns.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Turn:
    turn_index: int
    prompt: str
    must_retrieve: tuple[str, ...]
    reference_sql: str
    category: str = "reporting"
    description: str = ""


@dataclass(frozen=True)
class MultiTurnConversation:
    id: str
    title: str
    domain: str
    turns: tuple[Turn, ...]


CONVERSATIONS: list[MultiTurnConversation] = [
    # ── Conversation 1: Sales & Revenue Analysis (6 turns) ──────────────────
    MultiTurnConversation(
        id="conv_sales_01",
        title="Top Customers & Sales Breakdown",
        domain="sales",
        turns=(
            Turn(
                turn_index=1,
                prompt="What are our top 5 customers by total sales order amount?",
                must_retrieve=("sales_customers", "sales_orders"),
                reference_sql="""
                    SELECT c.name, SUM(o.total_amount) AS total_sales
                    FROM sales_orders o
                    JOIN sales_customers c ON o.customer_id = c.id
                    GROUP BY c.id, c.name
                    ORDER BY total_sales DESC
                    LIMIT 5;
                """,
                description="Top customers by revenue",
            ),
            Turn(
                turn_index=2,
                prompt="Filter that to only confirmed orders",
                must_retrieve=("sales_customers", "sales_orders"),
                reference_sql="""
                    SELECT c.name, SUM(o.total_amount) AS total_sales
                    FROM sales_orders o
                    JOIN sales_customers c ON o.customer_id = c.id
                    WHERE o.status = 'CONFIRMED'
                    GROUP BY c.id, c.name
                    ORDER BY total_sales DESC
                    LIMIT 5;
                """,
                description="Filter previous query by confirmed status",
            ),
            Turn(
                turn_index=3,
                prompt="Break down that sales total by customer group",
                must_retrieve=("sales_customers", "sales_orders", "sales_customer_groups"),
                reference_sql="""
                    SELECT g.name AS group_name, SUM(o.total_amount) AS total_sales
                    FROM sales_orders o
                    JOIN sales_customers c ON o.customer_id = c.id
                    JOIN sales_customer_groups g ON c.customer_group_id = g.id
                    WHERE o.status = 'CONFIRMED'
                    GROUP BY g.id, g.name
                    ORDER BY total_sales DESC;
                """,
                description="Group previous confirmed sales by customer group",
            ),
            Turn(
                turn_index=4,
                prompt="Which items were ordered most frequently in those confirmed orders?",
                must_retrieve=("sales_orders", "sales_order_lines", "inv_items"),
                reference_sql="""
                    SELECT i.name, SUM(ol.quantity) AS total_quantity
                    FROM sales_order_lines ol
                    JOIN sales_orders o ON ol.order_id = o.id
                    JOIN inv_items i ON ol.item_id = i.id
                    WHERE o.status = 'CONFIRMED'
                    GROUP BY i.id, i.name
                    ORDER BY total_quantity DESC
                    LIMIT 5;
                """,
                description="Most ordered items in confirmed orders",
            ),
            Turn(
                turn_index=5,
                prompt="What is the current stock on hand across warehouses for that top item?",
                must_retrieve=("inv_items", "inv_stock_quants", "inv_warehouses"),
                reference_sql="""
                    SELECT w.name AS warehouse_name, sq.quantity
                    FROM inv_stock_quants sq
                    JOIN inv_warehouses w ON sq.warehouse_id = w.id
                    JOIN inv_items i ON sq.item_id = i.id
                    WHERE i.name = (
                        SELECT i2.name
                        FROM sales_order_lines ol2
                        JOIN sales_orders o2 ON ol2.order_id = o2.id
                        JOIN inv_items i2 ON ol2.item_id = i2.id
                        WHERE o2.status = 'CONFIRMED'
                        GROUP BY i2.id, i2.name
                        ORDER BY SUM(ol2.quantity) DESC
                        LIMIT 1
                    );
                """,
                description="Stock on hand for the top item identified in turn 4",
            ),
            Turn(
                turn_index=6,
                prompt="Are there any open purchase orders for that item?",
                must_retrieve=("inv_items", "proc_purchase_orders", "proc_purchase_order_lines"),
                reference_sql="""
                    SELECT po.order_number, po.status, pol.quantity, pol.unit_price
                    FROM proc_purchase_order_lines pol
                    JOIN proc_purchase_orders po ON pol.purchase_order_id = po.id
                    JOIN inv_items i ON pol.item_id = i.id
                    WHERE po.status NOT IN ('CANCELLED', 'CLOSED')
                      AND i.name = (
                        SELECT i2.name
                        FROM sales_order_lines ol2
                        JOIN sales_orders o2 ON ol2.order_id = o2.id
                        JOIN inv_items i2 ON ol2.item_id = i2.id
                        WHERE o2.status = 'CONFIRMED'
                        GROUP BY i2.id, i2.name
                        ORDER BY SUM(ol2.quantity) DESC
                        LIMIT 1
                    );
                """,
                description="Open purchase orders for the top item",
            ),
        ),
    ),

    # ── Conversation 2: Procurement & Vendor Management (6 turns) ───────────
    MultiTurnConversation(
        id="conv_proc_02",
        title="Vendor Spend & Purchase Order Analysis",
        domain="procurement",
        turns=(
            Turn(
                turn_index=1,
                prompt="Who are our top 5 vendors by total purchase order value?",
                must_retrieve=("proc_vendors", "proc_purchase_orders"),
                reference_sql="""
                    SELECT v.name, SUM(po.total_amount) AS total_spend
                    FROM proc_purchase_orders po
                    JOIN proc_vendors v ON po.vendor_id = v.id
                    GROUP BY v.id, v.name
                    ORDER BY total_spend DESC
                    LIMIT 5;
                """,
                description="Top vendors by PO spend",
            ),
            Turn(
                turn_index=2,
                prompt="Show only orders that have been received",
                must_retrieve=("proc_vendors", "proc_purchase_orders"),
                reference_sql="""
                    SELECT v.name, SUM(po.total_amount) AS received_spend
                    FROM proc_purchase_orders po
                    JOIN proc_vendors v ON po.vendor_id = v.id
                    WHERE po.status = 'RECEIVED'
                    GROUP BY v.id, v.name
                    ORDER BY received_spend DESC
                    LIMIT 5;
                """,
                description="Filter previous query by RECEIVED status",
            ),
            Turn(
                turn_index=3,
                prompt="What payment terms and currency do these top vendors have?",
                must_retrieve=("proc_vendors", "fin_currencies"),
                reference_sql="""
                    SELECT v.name, v.payment_terms_days, c.code AS currency_code
                    FROM proc_vendors v
                    LEFT JOIN fin_currencies c ON v.currency_id = c.id
                    WHERE v.id IN (
                        SELECT po.vendor_id
                        FROM proc_purchase_orders po
                        WHERE po.status = 'RECEIVED'
                        GROUP BY po.vendor_id
                        ORDER BY SUM(po.total_amount) DESC
                        LIMIT 5
                    );
                """,
                description="Vendor payment terms for top vendors",
            ),
            Turn(
                turn_index=4,
                prompt="Which items have we purchased most from the number one vendor?",
                must_retrieve=("proc_purchase_orders", "proc_purchase_order_lines", "inv_items"),
                reference_sql="""
                    SELECT i.name, SUM(pol.quantity) AS total_qty
                    FROM proc_purchase_order_lines pol
                    JOIN proc_purchase_orders po ON pol.purchase_order_id = po.id
                    JOIN inv_items i ON pol.item_id = i.id
                    WHERE po.vendor_id = (
                        SELECT po2.vendor_id
                        FROM proc_purchase_orders po2
                        WHERE po2.status = 'RECEIVED'
                        GROUP BY po2.vendor_id
                        ORDER BY SUM(po2.total_amount) DESC
                        LIMIT 1
                    )
                    GROUP BY i.id, i.name
                    ORDER BY total_qty DESC
                    LIMIT 5;
                """,
                description="Items purchased from top vendor",
            ),
            Turn(
                turn_index=5,
                prompt="What was the average unit price paid for each of those items?",
                must_retrieve=("proc_purchase_orders", "proc_purchase_order_lines", "inv_items"),
                reference_sql="""
                    SELECT i.name, AVG(pol.unit_price) AS avg_unit_price
                    FROM proc_purchase_order_lines pol
                    JOIN proc_purchase_orders po ON pol.purchase_order_id = po.id
                    JOIN inv_items i ON pol.item_id = i.id
                    WHERE po.vendor_id = (
                        SELECT po2.vendor_id
                        FROM proc_purchase_orders po2
                        WHERE po2.status = 'RECEIVED'
                        GROUP BY po2.vendor_id
                        ORDER BY SUM(po2.total_amount) DESC
                        LIMIT 1
                    )
                    GROUP BY i.id, i.name
                    ORDER BY SUM(pol.quantity) DESC
                    LIMIT 5;
                """,
                description="Average price paid for top vendor's items",
            ),
            Turn(
                turn_index=6,
                prompt="Show all pending vendor bills from this vendor",
                must_retrieve=("fin_vendor_bills", "proc_vendors"),
                reference_sql="""
                    SELECT b.bill_number, b.due_date, b.total_amount, b.status
                    FROM fin_vendor_bills b
                    WHERE b.vendor_id = (
                        SELECT po2.vendor_id
                        FROM proc_purchase_orders po2
                        WHERE po2.status = 'RECEIVED'
                        GROUP BY po2.vendor_id
                        ORDER BY SUM(po2.total_amount) DESC
                        LIMIT 1
                    )
                    AND b.status NOT IN ('PAID', 'CANCELLED');
                """,
                description="Unpaid vendor bills for top vendor",
            ),
        ),
    ),

    # ── Conversation 3: Financial Ledger & Controlling (6 turns) ────────────
    MultiTurnConversation(
        id="conv_finance_03",
        title="Universal Journal & Expense Tracking",
        domain="finance",
        turns=(
            Turn(
                turn_index=1,
                prompt="Show total debits and credits posted in the journal",
                must_retrieve=("fin_journal_entries", "fin_journal_lines"),
                reference_sql="""
                    SELECT SUM(jl.debit) AS total_debits, SUM(jl.credit) AS total_credits
                    FROM fin_journal_lines jl
                    JOIN fin_journal_entries je ON jl.journal_entry_id = je.id
                    WHERE je.is_posted = TRUE;
                """,
                description="Total debits and credits",
            ),
            Turn(
                turn_index=2,
                prompt="Break down total debits by account name",
                must_retrieve=("fin_journal_entries", "fin_journal_lines", "fin_accounts"),
                reference_sql="""
                    SELECT a.code, a.name, SUM(jl.debit) AS total_debit
                    FROM fin_journal_lines jl
                    JOIN fin_journal_entries je ON jl.journal_entry_id = je.id
                    JOIN fin_accounts a ON jl.account_id = a.id
                    WHERE je.is_posted = TRUE
                    GROUP BY a.id, a.code, a.name
                    ORDER BY total_debit DESC
                    LIMIT 10;
                """,
                description="Debits broken down by account",
            ),
            Turn(
                turn_index=3,
                prompt="Filter that to show only expense accounts",
                must_retrieve=("fin_journal_entries", "fin_journal_lines", "fin_accounts"),
                reference_sql="""
                    SELECT a.code, a.name, SUM(jl.debit) AS total_expense
                    FROM fin_journal_lines jl
                    JOIN fin_journal_entries je ON jl.journal_entry_id = je.id
                    JOIN fin_accounts a ON jl.account_id = a.id
                    WHERE je.is_posted = TRUE
                      AND a.account_type = 'EXPENSE'
                    GROUP BY a.id, a.code, a.name
                    ORDER BY total_expense DESC
                    LIMIT 10;
                """,
                description="Filter to expense accounts only",
            ),
            Turn(
                turn_index=4,
                prompt="Which cost center incurred the highest expense?",
                must_retrieve=("fin_journal_lines", "fin_cost_centers", "fin_accounts"),
                reference_sql="""
                    SELECT cc.name AS cost_center, SUM(jl.debit) AS total_expense
                    FROM fin_journal_lines jl
                    JOIN fin_cost_centers cc ON jl.cost_center_id = cc.id
                    JOIN fin_accounts a ON jl.account_id = a.id
                    WHERE a.account_type = 'EXPENSE'
                    GROUP BY cc.id, cc.name
                    ORDER BY total_expense DESC
                    LIMIT 1;
                """,
                description="Cost center with highest expense",
            ),
            Turn(
                turn_index=5,
                prompt="List the 5 largest journal lines posted to that cost center",
                must_retrieve=("fin_journal_lines", "fin_cost_centers", "fin_accounts"),
                reference_sql="""
                    SELECT jl.description, jl.debit, jl.posting_date, a.name AS account_name
                    FROM fin_journal_lines jl
                    JOIN fin_cost_centers cc ON jl.cost_center_id = cc.id
                    JOIN fin_accounts a ON jl.account_id = a.id
                    WHERE cc.id = (
                        SELECT cc2.id
                        FROM fin_journal_lines jl2
                        JOIN fin_cost_centers cc2 ON jl2.cost_center_id = cc2.id
                        JOIN fin_accounts a2 ON jl2.account_id = a2.id
                        WHERE a2.account_type = 'EXPENSE'
                        GROUP BY cc2.id
                        ORDER BY SUM(jl2.debit) DESC
                        LIMIT 1
                    )
                    ORDER BY jl.debit DESC
                    LIMIT 5;
                """,
                description="Top journal lines for top cost center",
            ),
            Turn(
                turn_index=6,
                prompt="Who created the journal entries for those largest lines?",
                must_retrieve=("fin_journal_lines", "fin_journal_entries", "core_users"),
                reference_sql="""
                    SELECT DISTINCT u.username, u.email
                    FROM fin_journal_lines jl
                    JOIN fin_journal_entries je ON jl.journal_entry_id = je.id
                    JOIN core_users u ON je.created_by_user_id = u.id
                    WHERE jl.id IN (
                        SELECT jl3.id
                        FROM fin_journal_lines jl3
                        JOIN fin_cost_centers cc3 ON jl3.cost_center_id = cc3.id
                        JOIN fin_accounts a3 ON jl3.account_id = a3.id
                        WHERE a3.account_type = 'EXPENSE'
                        ORDER BY jl3.debit DESC
                        LIMIT 5
                    );
                """,
                description="Users who created top expense journal entries",
            ),
        ),
    ),

    # ── Conversation 4: HR & Payroll Performance (6 turns) ──────────────────
    MultiTurnConversation(
        id="conv_hr_04",
        title="Department Headcount & Payroll Analysis",
        domain="hr",
        turns=(
            Turn(
                turn_index=1,
                prompt="List all active departments and their employee headcount",
                must_retrieve=("hr_departments", "hr_employees"),
                reference_sql="""
                    SELECT d.name, COUNT(e.id) AS headcount
                    FROM hr_departments d
                    LEFT JOIN hr_employees e ON e.department_id = d.id AND e.is_active = TRUE
                    WHERE d.is_active = TRUE
                    GROUP BY d.id, d.name
                    ORDER BY headcount DESC;
                """,
                description="Active departments and headcount",
            ),
            Turn(
                turn_index=2,
                prompt="Which department has the highest average employee salary?",
                must_retrieve=("hr_departments", "hr_employees"),
                reference_sql="""
                    SELECT d.name, AVG(e.base_salary) AS avg_salary
                    FROM hr_departments d
                    JOIN hr_employees e ON e.department_id = d.id
                    WHERE e.is_active = TRUE
                    GROUP BY d.id, d.name
                    ORDER BY avg_salary DESC
                    LIMIT 1;
                """,
                description="Department with highest average salary",
            ),
            Turn(
                turn_index=3,
                prompt="Show the employees in that highest-paying department",
                must_retrieve=("hr_departments", "hr_employees", "hr_positions"),
                reference_sql="""
                    SELECT e.first_name, e.last_name, p.title, e.base_salary
                    FROM hr_employees e
                    JOIN hr_departments d ON e.department_id = d.id
                    LEFT JOIN hr_positions p ON e.position_id = p.id
                    WHERE d.id = (
                        SELECT d2.id
                        FROM hr_departments d2
                        JOIN hr_employees e2 ON e2.department_id = d2.id
                        WHERE e2.is_active = TRUE
                        GROUP BY d2.id
                        ORDER BY AVG(e2.base_salary) DESC
                        LIMIT 1
                    )
                    AND e.is_active = TRUE
                    ORDER BY e.base_salary DESC;
                """,
                description="Employees in top paying department",
            ),
            Turn(
                turn_index=4,
                prompt="What is the total payroll cost for this department across payroll runs?",
                must_retrieve=("hr_payroll_runs", "hr_payroll_run_lines", "hr_employees"),
                reference_sql="""
                    SELECT SUM(prl.gross_pay) AS total_gross_pay, SUM(prl.net_pay) AS total_net_pay
                    FROM hr_payroll_run_lines prl
                    JOIN hr_employees e ON prl.employee_id = e.id
                    WHERE e.department_id = (
                        SELECT d2.id
                        FROM hr_departments d2
                        JOIN hr_employees e2 ON e2.department_id = d2.id
                        WHERE e2.is_active = TRUE
                        GROUP BY d2.id
                        ORDER BY AVG(e2.base_salary) DESC
                        LIMIT 1
                    );
                """,
                description="Payroll total for top paying department",
            ),
            Turn(
                turn_index=5,
                prompt="How many leave requests have employees in this department submitted?",
                must_retrieve=("hr_leave_requests", "hr_employees"),
                reference_sql="""
                    SELECT lr.status, COUNT(*) AS count
                    FROM hr_leave_requests lr
                    JOIN hr_employees e ON lr.employee_id = e.id
                    WHERE e.department_id = (
                        SELECT d2.id
                        FROM hr_departments d2
                        JOIN hr_employees e2 ON e2.department_id = d2.id
                        WHERE e2.is_active = TRUE
                        GROUP BY d2.id
                        ORDER BY AVG(e2.base_salary) DESC
                        LIMIT 1
                    )
                    GROUP BY lr.status;
                """,
                description="Leave requests breakdown for department",
            ),
            Turn(
                turn_index=6,
                prompt="List all billable project time entries logged by these employees",
                must_retrieve=("hr_time_entries", "hr_employees", "ps_projects"),
                reference_sql="""
                    SELECT p.name AS project_name, SUM(te.hours) AS total_hours
                    FROM hr_time_entries te
                    JOIN hr_employees e ON te.employee_id = e.id
                    JOIN ps_projects p ON te.project_id = p.id
                    WHERE te.is_billable = TRUE
                      AND e.department_id = (
                        SELECT d2.id
                        FROM hr_departments d2
                        JOIN hr_employees e2 ON e2.department_id = d2.id
                        WHERE e2.is_active = TRUE
                        GROUP BY d2.id
                        ORDER BY AVG(e2.base_salary) DESC
                        LIMIT 1
                    )
                    GROUP BY p.id, p.name
                    ORDER BY total_hours DESC;
                """,
                description="Time entries by project for department employees",
            ),
        ),
    ),
]
