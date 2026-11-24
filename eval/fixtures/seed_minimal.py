"""Seeds realistic demonstration data for tenant 'acme' into atlas_test.db."""
import os
import sqlite3
import uuid
from datetime import datetime, date

backend_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(backend_dir, "atlas_test.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

TENANT = "acme"
NOW = datetime.now().isoformat()
TODAY = date.today().isoformat()

def uid():
    return uuid.uuid4().hex

print("Seeding Atlas ERP test database...")

# Clean existing records for idempotent runs
clean_tables = [
    'hr_time_entries', 'hr_timesheets', 'ps_projects', 'hr_payroll_run_lines',
    'hr_payroll_runs', 'hr_leave_requests', 'hr_leave_types', 'hr_employees',
    'hr_departments', 'fin_journal_lines', 'fin_journal_entries', 'fin_fiscal_periods',
    'fin_fiscal_years', 'fin_accounts', 'fin_cost_centers', 'proc_purchase_order_lines',
    'proc_purchase_orders', 'proc_vendors', 'sales_order_lines', 'sales_orders',
    'core_documents', 'inv_stock_quants', 'inv_bins', 'inv_warehouses', 'inv_items',
    'inv_item_categories', 'inv_uoms', 'sales_customers', 'sales_customer_groups',
    'fin_currencies', 'core_users', 'adm_tenants'
]
for t in clean_tables:
    try:
        cur.execute(f"DELETE FROM {t} WHERE tenant_id = '{TENANT}'")
    except Exception:
        pass

# Tenant
cur.execute("INSERT OR IGNORE INTO adm_tenants (id, slug, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (TENANT, "acme", "Acme Corporation", 1, NOW, NOW))

# Core User
u_id = uid()
cur.execute("INSERT OR IGNORE INTO core_users (id, tenant_id, email, password_hash, full_name, is_active, token_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (u_id, TENANT, "owner@acme.test", "hash123", "Acme Admin User", 1, 1, NOW, NOW))

# Currencies
usd_id = uid()
eur_id = uid()
cur.execute("INSERT OR IGNORE INTO fin_currencies (id, tenant_id, code, name, decimal_places, is_functional, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (usd_id, TENANT, "USD", "US Dollar", 2, 1, NOW, NOW))
cur.execute("INSERT OR IGNORE INTO fin_currencies (id, tenant_id, code, name, decimal_places, is_functional, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (eur_id, TENANT, "EUR", "Euro", 2, 0, NOW, NOW))

# Customer Groups
grp_retail = uid()
grp_wholesale = uid()
cur.execute("INSERT OR IGNORE INTO sales_customer_groups (id, tenant_id, code, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (grp_retail, TENANT, "RETAIL", "Retail Customers", NOW, NOW))
cur.execute("INSERT OR IGNORE INTO sales_customer_groups (id, tenant_id, code, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (grp_wholesale, TENANT, "WHOLESALE", "Wholesale Partners", NOW, NOW))

# Customers
cust_ids = []
customers = [
    ("Apex Global", "CUST-001", grp_wholesale, "sales@apexglobal.com"),
    ("Summit Retail", "CUST-002", grp_retail, "orders@summitretail.com"),
    ("Beacon Tech", "CUST-003", grp_wholesale, "purchasing@beacontech.com"),
    ("Horizon Consumer", "CUST-004", grp_retail, "contact@horizonconsumer.com"),
    ("Vanguard Enterprise", "CUST-005", grp_wholesale, "supply@vanguard.com"),
]
for name, code, grp, email in customers:
    cid = uid()
    cust_ids.append(cid)
    cur.execute("""
        INSERT OR IGNORE INTO sales_customers
        (id, tenant_id, customer_code, name, status, customer_group_id, default_currency_code, credit_limit, email, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (cid, TENANT, code, name, "ACTIVE", grp, "USD", 50000.0, email, NOW, NOW))

# UOM
uom_id = uid()
cur.execute("INSERT OR IGNORE INTO inv_uoms (id, tenant_id, code, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uom_id, TENANT, "EA", "Each", NOW, NOW))

# Item Categories
cat_elec = uid()
cat_office = uid()
cur.execute("INSERT OR IGNORE INTO inv_item_categories (id, tenant_id, code, name, default_costing_method, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cat_elec, TENANT, "ELEC", "Electronics", "FIFO", NOW, NOW))
cur.execute("INSERT OR IGNORE INTO inv_item_categories (id, tenant_id, code, name, default_costing_method, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cat_office, TENANT, "OFFICE", "Office Supplies", "FIFO", NOW, NOW))

# Items
items = [
    ("Pro Laptop 15", "ITEM-101", cat_elec, 1200.0),
    ("Ultra Monitor 27", "ITEM-102", cat_elec, 450.0),
    ("Ergonomic Keyboard", "ITEM-103", cat_elec, 95.0),
    ("Precision Mouse", "ITEM-104", cat_elec, 45.0),
    ("Standing Desk Mat", "ITEM-201", cat_office, 65.0),
]
item_ids = []
for name, code, cat, price in items:
    iid = uid()
    item_ids.append(iid)
    cur.execute("""
        INSERT OR IGNORE INTO inv_items
        (id, tenant_id, item_code, name, category_id, base_uom_id, item_type, costing_method, tracking_mode, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (iid, TENANT, code, name, cat, uom_id, "PURCHASED", "FIFO", "NONE", 1, NOW, NOW))

# Warehouses & Bins
wh_main = uid()
cur.execute("INSERT OR IGNORE INTO inv_warehouses (id, tenant_id, code, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (wh_main, TENANT, "WH-MAIN", "Central Distribution Center", 1, NOW, NOW))
bin_main = uid()
cur.execute("INSERT OR IGNORE INTO inv_bins (id, tenant_id, warehouse_id, code, name, is_default, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bin_main, TENANT, wh_main, "BIN-A1", "Primary Storage Bin", 1, 1, NOW, NOW))

# Stock Quants (On hand)
stock_quant_counts = [240, 180, 520, 480, 150]
for iid, qty in zip(item_ids, stock_quant_counts):
    cur.execute("""
        INSERT OR IGNORE INTO inv_stock_quants
        (id, tenant_id, item_id, bin_id, on_hand_qty, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid(), TENANT, iid, bin_main, qty, NOW, NOW))

# Sales Orders & Lines
order_amounts = [14400.0, 9200.0, 7800.0, 5600.0, 4200.0]
for i, (cid, amt) in enumerate(zip(cust_ids, order_amounts), start=1):
    doc_id = uid()
    cur.execute("INSERT OR IGNORE INTO core_documents (id, tenant_id, doc_type, doc_id, doc_number, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, TENANT, "SALES_ORDER", doc_id, f"SO-2026-{i:04d}", "CONFIRMED", NOW, NOW))

    oid = uid()
    cur.execute("""
        INSERT OR IGNORE INTO sales_orders
        (id, tenant_id, document_id, order_number, status, customer_id, currency_code, order_date, payment_terms_days, total_amount, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (oid, TENANT, doc_id, f"SO-2026-{i:04d}", "CONFIRMED", cid, "USD", TODAY, 30, amt, NOW, NOW))

    for line_idx, iid in enumerate(item_ids[:3], start=1):
        cur.execute("""
            INSERT OR IGNORE INTO sales_order_lines
            (id, tenant_id, order_id, line_number, item_id, description, ordered_quantity, uom_id, unit_price, line_amount, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid(), TENANT, oid, line_idx, iid, f"Line item {line_idx}", 10 * line_idx, uom_id, 120.0, 1200.0 * line_idx, NOW, NOW))

# Procurement Vendors & Purchase Orders
vendor_ids = []
vendors = [
    ("Global Tech Supplies", "VEND-001", 30, "USD"),
    ("Silicon Components Co", "VEND-002", 45, "USD"),
    ("EuroLogistics Gear", "VEND-003", 60, "EUR"),
]
for name, code, terms, curr in vendors:
    vid = uid()
    vendor_ids.append(vid)
    cur.execute("""
        INSERT OR IGNORE INTO proc_vendors
        (id, tenant_id, vendor_code, name, default_currency_code, payment_terms_days, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vid, TENANT, code, name, curr, terms, "ACTIVE", NOW, NOW))

    doc_po_id = uid()
    cur.execute("INSERT OR IGNORE INTO core_documents (id, tenant_id, doc_type, doc_id, doc_number, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_po_id, TENANT, "PURCHASE_ORDER", doc_po_id, f"PO-2026-{code[-3:]}", "RECEIVED", NOW, NOW))

    poid = uid()
    cur.execute("""
        INSERT OR IGNORE INTO proc_purchase_orders
        (id, tenant_id, document_id, po_number, status, vendor_id, currency_code, order_date, payment_terms_days, total_amount, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (poid, TENANT, doc_po_id, f"PO-2026-{code[-3:]}", "RECEIVED", vid, curr, TODAY, 30, 25000.0, NOW, NOW))

    cur.execute("""
        INSERT OR IGNORE INTO proc_purchase_order_lines
        (id, tenant_id, po_id, line_number, item_id, description, quantity, uom_id, unit_cost, line_amount, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid(), TENANT, poid, 1, item_ids[0], "Procured item", 50, uom_id, 500.0, 25000.0, NOW, NOW))

# Cost Centers & Accounts
cc_sales = uid()
cc_eng = uid()
cur.execute("INSERT OR IGNORE INTO fin_cost_centers (id, tenant_id, code, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cc_sales, TENANT, "CC-100", "Sales & Marketing", 1, NOW, NOW))
cur.execute("INSERT OR IGNORE INTO fin_cost_centers (id, tenant_id, code, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cc_eng, TENANT, "CC-200", "Engineering & Product", 1, NOW, NOW))

acc_rev = uid()
acc_exp = uid()
cur.execute("INSERT OR IGNORE INTO fin_accounts (id, tenant_id, code, name, account_type, normal_balance, is_postable, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (acc_rev, TENANT, "4000", "Sales Revenue", "REVENUE", "CREDIT", 1, 1, NOW, NOW))
cur.execute("INSERT OR IGNORE INTO fin_accounts (id, tenant_id, code, name, account_type, normal_balance, is_postable, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (acc_exp, TENANT, "5000", "Operational Expenses", "EXPENSE", "DEBIT", 1, 1, NOW, NOW))

# Fiscal Year & Period for accounting
fy_id = uid()
fp_id = uid()
cur.execute("""
    INSERT OR IGNORE INTO fin_fiscal_years
    (id, tenant_id, code, name, start_date, end_date, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (fy_id, TENANT, "FY-2026", "Fiscal Year 2026", "2026-01-01", "2026-12-31", "OPEN", NOW, NOW))

cur.execute("""
    INSERT OR IGNORE INTO fin_fiscal_periods
    (id, tenant_id, fiscal_year_id, period_number, name, start_date, end_date, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (fp_id, TENANT, fy_id, 1, "Period 1 - 2026", "2026-01-01", "2026-12-31", "OPEN", NOW, NOW))

doc_je_id = uid()
cur.execute("INSERT OR IGNORE INTO core_documents (id, tenant_id, doc_type, doc_id, doc_number, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_je_id, TENANT, "JOURNAL_ENTRY", doc_je_id, "JE-2026-0001", "POSTED", NOW, NOW))

je_id = uid()
cur.execute("""
    INSERT OR IGNORE INTO fin_journal_entries
    (id, tenant_id, document_id, entry_number, posting_date, fiscal_period_id, currency_code, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (je_id, TENANT, doc_je_id, "JE-2026-0001", TODAY, fp_id, "USD", "POSTED", NOW, NOW))

cur.execute("""
    INSERT OR IGNORE INTO fin_journal_lines
    (id, tenant_id, journal_entry_id, line_number, account_id, currency_code, cost_center_id, functional_debit_amount, functional_credit_amount, description, posting_date, is_posted, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (uid(), TENANT, je_id, 1, acc_exp, "USD", cc_sales, 45000.0, 0.0, "Marketing Campaign Q2", TODAY, 1, NOW, NOW))
cur.execute("""
    INSERT OR IGNORE INTO fin_journal_lines
    (id, tenant_id, journal_entry_id, line_number, account_id, currency_code, cost_center_id, functional_debit_amount, functional_credit_amount, description, posting_date, is_posted, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (uid(), TENANT, je_id, 2, acc_rev, "USD", None, 0.0, 45000.0, "Recognized Revenue", TODAY, 1, NOW, NOW))

# HR Departments, Employees, Leave & Payroll
dept_sales = uid()
dept_eng = uid()
cur.execute("INSERT OR IGNORE INTO hr_departments (id, tenant_id, code, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dept_sales, TENANT, "SALES", "Sales & Business Development", 1, NOW, NOW))
cur.execute("INSERT OR IGNORE INTO hr_departments (id, tenant_id, code, name, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dept_eng, TENANT, "ENG", "Engineering", 1, NOW, NOW))

emp_ids = []
employees = [
    ("Sarah", "Connor", "EMP-001", dept_eng, 125000.0),
    ("John", "Doe", "EMP-002", dept_eng, 115000.0),
    ("Alice", "Smith", "EMP-003", dept_sales, 95000.0),
    ("Bob", "Johnson", "EMP-004", dept_sales, 85000.0),
]
for fname, lname, code, dept, salary in employees:
    eid = uid()
    emp_ids.append(eid)
    cur.execute("""
        INSERT OR IGNORE INTO hr_employees
        (id, tenant_id, employee_code, first_name, last_name, email, department_id, hire_date, base_salary, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (eid, TENANT, code, fname, lname, f"{fname.lower()}@acme.test", dept, TODAY, salary, "ACTIVE", NOW, NOW))

# Leave requests
leave_type_id = uid()
cur.execute("INSERT OR IGNORE INTO hr_leave_types (id, tenant_id, code, name, accrual_frequency, accrual_amount, max_balance, unit, is_paid, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (leave_type_id, TENANT, "ANNUAL", "Annual Paid Vacation", "MONTHLY", 1.66, 30, "DAYS", 1, 1, NOW, NOW))
cur.execute("""
    INSERT OR IGNORE INTO hr_leave_requests
    (id, tenant_id, request_number, employee_id, leave_type_id, start_date, end_date, days, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (uid(), TENANT, "LR-2026-001", emp_ids[0], leave_type_id, TODAY, TODAY, 3, "APPROVED", NOW, NOW))

# Payroll
pay_run = uid()
doc_pay_id = uid()
cur.execute("INSERT OR IGNORE INTO core_documents (id, tenant_id, doc_type, doc_id, doc_number, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_pay_id, TENANT, "PAYROLL_RUN", doc_pay_id, "PAY-2026-06", "POSTED", NOW, NOW))

cur.execute("""
    INSERT OR IGNORE INTO hr_payroll_runs
    (id, tenant_id, document_id, run_number, status, period_start, period_end, pay_date, tax_rate_percent, currency_code, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (pay_run, TENANT, doc_pay_id, "PAY-2026-06", "POSTED", TODAY, TODAY, TODAY, 20.0, "USD", NOW, NOW))

for eid in emp_ids:
    cur.execute("""
        INSERT OR IGNORE INTO hr_payroll_run_lines
        (id, tenant_id, payroll_run_id, employee_id, gross_amount, net_amount, tax_amount, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid(), TENANT, pay_run, eid, 10000.0, 7500.0, 2500.0, NOW, NOW))

# Projects, Timesheets & Time Entries
proj_id = uid()
cur.execute("INSERT OR IGNORE INTO ps_projects (id, tenant_id, code, name, status, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (proj_id, TENANT, "PRJ-001", "NextGen ERP Rollout", "IN_PROGRESS", 1, NOW, NOW))

ts_id = uid()
cur.execute("""
    INSERT OR IGNORE INTO hr_timesheets
    (id, tenant_id, timesheet_number, employee_id, period_start, period_end, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (ts_id, TENANT, "TS-2026-01", emp_ids[0], TODAY, TODAY, "APPROVED", NOW, NOW))

cur.execute("""
    INSERT OR IGNORE INTO hr_time_entries
    (id, tenant_id, timesheet_id, entry_date, hours, project_id, is_billable, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (uid(), TENANT, ts_id, TODAY, 40.0, proj_id, 1, NOW, NOW))

conn.commit()
conn.close()
print("Successfully seeded Atlas ERP test database with realistic records across all modules!")
