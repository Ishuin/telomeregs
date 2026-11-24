from __future__ import annotations

import math
import re
from collections import Counter

from .schema import Schema, Table


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with",
    "by", "from", "is", "are", "was", "were", "be", "been", "being",
    "id", "ids", "uuid", "fk", "pk", "ref",
    "how", "what", "when", "where", "who", "why", "which", "many", "much",
    "do", "does", "did", "have", "has", "had", "can", "could", "should",
    "show", "list", "get", "find", "give", "tell", "me",
}

# Domain semantic mapping for ERP terms (Atlas ERP, SAP S/4HANA, Odoo)
_DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "product": ["item", "inv", "merchandise"],
    "products": ["items", "inv", "merchandise"],
    "item": ["product", "inv_items"],
    "items": ["products", "inv_items"],
    "sku": ["item", "product"],
    "stock": ["quant", "inventory", "warehouse", "move", "inv_stock_quants"],
    "inventory": ["stock", "quant", "warehouse", "inv", "move", "inv_stock_quants"],
    "warehouse": ["warehouse", "location", "bin", "inv_warehouses"],
    "warehouses": ["warehouses", "locations", "bins", "inv_warehouses"],
    "sale": ["order", "billing", "revenue", "invoice"],
    "sales": ["order", "orders", "billing", "revenue", "sales_orders"],
    "customer": ["customer", "client", "buyer", "sales_customers"],
    "customers": ["customers", "clients", "buyers", "sales_customers"],
    "order": ["sales_orders", "proc_purchase_orders", "order_lines"],
    "orders": ["sales_orders", "proc_purchase_orders", "order_lines"],
    "delivery": ["delivery", "shipment", "sales_deliveries"],
    "deliveries": ["deliveries", "shipments", "sales_deliveries"],
    "lead": ["lead", "opportunity", "crm_leads"],
    "leads": ["leads", "opportunities", "crm_leads"],
    "opportunity": ["opportunity", "pipeline", "crm_opportunities"],
    "opportunities": ["opportunities", "pipeline", "crm_opportunities"],
    "vendor": ["vendor", "supplier", "proc_vendors", "purchase"],
    "vendors": ["vendors", "suppliers", "proc_vendors", "purchases"],
    "supplier": ["vendor", "proc_vendors", "purchase"],
    "suppliers": ["vendors", "proc_vendors", "purchases"],
    "purchase": ["purchase", "po", "proc_purchase_orders"],
    "purchases": ["purchases", "po", "proc_purchase_orders"],
    "invoice": ["billing", "invoice", "bill", "sales_billings", "fin_vendor_bills"],
    "invoices": ["billings", "invoices", "bills", "sales_billings", "fin_vendor_bills"],
    "bill": ["vendor_bills", "invoice", "fin_vendor_bills"],
    "bills": ["vendor_bills", "invoices", "fin_vendor_bills"],
    "payment": ["payment", "receipt", "fin_vendor_payments", "fin_customer_receipts"],
    "payments": ["payments", "receipts", "fin_vendor_payments", "fin_customer_receipts"],
    "revenue": ["revenue", "sales", "line_total", "total_amount", "amount"],
    "income": ["revenue", "sales", "amount", "debit", "credit"],
    "expense": ["expense", "bill", "cost", "fin_accounts"],
    "expenses": ["expenses", "bills", "costs", "fin_accounts"],
    "journal": ["journal", "entry", "ledger", "fin_journal_entries", "fin_journal_lines"],
    "journals": ["journals", "entries", "ledgers", "fin_journal_entries", "fin_journal_lines"],
    "ledger": ["journal", "ledger", "account", "fin_journal_lines"],
    "account": ["account", "fin_accounts"],
    "accounts": ["accounts", "fin_accounts"],
    "currency": ["currency", "rate", "fx", "fin_currencies"],
    "currencies": ["currencies", "rates", "fx", "fin_currencies"],
    "user": ["user", "creator", "core_users"],
    "users": ["users", "creators", "core_users"],
    "who": ["user", "employee", "customer", "vendor", "core_users"],
    "created": ["user", "creator", "core_users"],
    "time": ["time", "timesheet", "hr_time_entries"],
    "timesheet": ["timesheet", "time_entries", "hr_time_entries", "hr_timesheets"],
    "employee": ["employee", "staff", "worker", "hr_employees"],
    "employees": ["employees", "staff", "workers", "hr_employees"],
    "payroll": ["payroll", "salary", "wage", "hr_payroll_runs"],
    "salary": ["payroll", "salary", "compensation", "wage"],
    "leave": ["leave", "time_off", "vacation", "hr_leave_requests"],
    "attendance": ["timesheet", "time_entry", "hr_time_entries"],
    "project": ["project", "task", "ps_projects"],
    "projects": ["projects", "tasks", "ps_projects"],
    "bom": ["bom", "bill_of_materials", "mfg_boms"],
    "production": ["production", "routing", "mfg_production_orders"],
}

# Common ERP cross-module logical FK mappings (column_name -> preferred target table)
_LOGICAL_FK_TARGETS: dict[str, str] = {
    "item_id": "inv_items",
    "customer_id": "sales_customers",
    "customer_group_id": "sales_customer_groups",
    "vendor_id": "proc_vendors",
    "order_id": "sales_orders",
    "purchase_order_id": "proc_purchase_orders",
    "warehouse_id": "inv_warehouses",
    "account_id": "fin_accounts",
    "cost_center_id": "fin_cost_centers",
    "profit_center_id": "fin_profit_centers",
    "currency_id": "fin_currencies",
    "department_id": "hr_departments",
    "employee_id": "hr_employees",
    "position_id": "hr_positions",
    "project_id": "ps_projects",
    "user_id": "core_users",
    "created_by_user_id": "core_users",
    "category_id": "inv_item_categories",
    "journal_entry_id": "fin_journal_entries",
}


def _stem(word: str) -> str:
    """Light plural->singular normalisation so `leads` matches `lead` etc."""
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"          # companies -> company, categories -> category
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]                # addresses -> address
    if len(word) > 4 and word.endswith("xes"):
        return word[:-2]                # taxes -> tax
    if len(word) > 4 and word.endswith("ches"):
        return word[:-2]                # batches -> batch
    if len(word) > 4 and word.endswith("shes"):
        return word[:-2]                # wishes -> wish
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]                # leads -> lead, users -> user
    return word


def tokenize(text: str, expand_synonyms: bool = True) -> list[str]:
    if not text:
        return []
    expanded = _CAMEL_RE.sub(r"\1 \2", text).replace("_", " ").replace("-", " ")
    out: list[str] = []
    for raw in _WORD_RE.findall(expanded):
        t = raw.lower()
        if t in _STOPWORDS:
            continue
        stemmed = _stem(t)
        out.append(stemmed)

        if expand_synonyms and t in _DOMAIN_SYNONYMS:
            for syn in _DOMAIN_SYNONYMS[t]:
                syn_stemmed = _stem(syn)
                if syn_stemmed not in _STOPWORDS and syn_stemmed not in out:
                    out.append(syn_stemmed)

    return out


def _table_terms(table: Table) -> list[str]:
    terms: list[str] = []
    # Repeat name to weight it higher in TF
    terms.extend(tokenize(table.name, expand_synonyms=False) * 3)
    terms.extend(tokenize(table.schema, expand_synonyms=False))
    if table.comment:
        terms.extend(tokenize(table.comment, expand_synonyms=False) * 2)
    for col in table.columns:
        terms.extend(tokenize(col.name, expand_synonyms=False))
    for fk in table.foreign_keys:
        terms.extend(tokenize(fk.referenced_table, expand_synonyms=False))
    return terms


class TfIdfRetriever:
    def __init__(self, schema: Schema):
        self.schema = schema
        self.tables: list[Table] = list(schema.tables)
        self._docs: list[list[str]] = [_table_terms(t) for t in self.tables]
        self._n = max(len(self._docs), 1)

        df: Counter[str] = Counter()
        for doc in self._docs:
            for term in set(doc):
                df[term] += 1
        self._df = df

        self._vecs: list[dict[str, float]] = [self._tfidf(doc) for doc in self._docs]
        self._norms: list[float] = [_norm(v) for v in self._vecs]

    def _idf(self, term: str) -> float:
        return math.log((self._n + 1) / (self._df.get(term, 0) + 1)) + 1.0

    def _tfidf(self, doc: list[str]) -> dict[str, float]:
        tf = Counter(doc)
        return {term: count * self._idf(term) for term, count in tf.items()}

    def rank(
        self,
        query: str,
        top_k: int = 15,
        boost_tables: list[str] | None = None,
    ) -> list[tuple[Table, float]]:
        q_tokens = tokenize(query, expand_synonyms=True)
        if not q_tokens or not self.tables:
            return [(t, 0.0) for t in self.tables[:top_k]]
        q_vec = self._tfidf(q_tokens)
        q_norm = _norm(q_vec)
        scored: list[tuple[Table, float]] = []

        boost_set = set(t.lower() for t in (boost_tables or []))

        for table, vec, norm in zip(self.tables, self._vecs, self._norms):
            dot = 0.0
            shorter, longer = (q_vec, vec) if len(q_vec) < len(vec) else (vec, q_vec)
            for term, weight in shorter.items():
                other = longer.get(term)
                if other is not None:
                    dot += weight * other
            score = dot / (q_norm * norm) if q_norm and norm else 0.0

            # Boost tables from previous turns in multi-turn conversations
            if table.name.lower() in boost_set or table.qualified_name.lower() in boost_set:
                score += 1.0

            scored.append((table, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def _norm(v: dict[str, float]) -> float:
    return math.sqrt(sum(x * x for x in v.values())) or 1.0


def _fk_target_key(fk, default_schema: str = "public") -> tuple[str, str]:
    return (fk.referenced_schema or default_schema, fk.referenced_table)


def expand_via_fks(
    schema: Schema,
    seed: list[Table],
    max_total: int = 25,
    hops: int = 2,
) -> list[Table]:
    """Add tables connected to `seed` via physical and logical foreign keys until `max_total` is reached.

    Walks `hops` outward (seed -> referenced) AND inward (referencing -> seed).
    Preserves seed order; new tables are appended in discovery order.
    """
    if max_total <= 0:
        return []

    by_key: dict[tuple[str, str], Table] = {(t.schema, t.name): t for t in schema.tables}
    by_name: dict[str, Table] = {t.name.lower(): t for t in schema.tables}

    selected: dict[tuple[str, str], Table] = {}
    for t in seed:
        if len(selected) >= max_total:
            return list(selected.values())
        selected[(t.schema, t.name)] = t

    for _ in range(hops):
        current_round = list(selected.values())
        # Outbound physical foreign keys
        for table in current_round:
            for fk in table.foreign_keys:
                if len(selected) >= max_total:
                    return list(selected.values())
                key = _fk_target_key(fk, default_schema=table.schema)
                if key in by_key and key not in selected:
                    selected[key] = by_key[key]

            # Outbound logical cross-module FKs (e.g. item_id -> inv_items)
            for col in table.columns:
                target_table_name = _LOGICAL_FK_TARGETS.get(col.name)
                if target_table_name and target_table_name in by_name:
                    target_table = by_name[target_table_name]
                    key = (target_table.schema, target_table.name)
                    if key not in selected:
                        if len(selected) >= max_total:
                            return list(selected.values())
                        selected[key] = target_table

        # Inbound physical foreign keys
        selected_keys = set(selected.keys())
        selected_names = {name.lower() for _, name in selected_keys}

        for table in schema.tables:
            if len(selected) >= max_total:
                break
            key = (table.schema, table.name)
            if key in selected:
                continue
            if any(_fk_target_key(fk, default_schema=table.schema) in selected_keys for fk in table.foreign_keys):
                selected[key] = table
                continue

            # Inbound logical foreign keys (table has column referencing something in selected)
            for col in table.columns:
                ref_target = _LOGICAL_FK_TARGETS.get(col.name)
                if ref_target and ref_target.lower() in selected_names:
                    selected[key] = table
                    break

    return list(selected.values())


# --- LLM-assisted table selector ------------------------------------------

_SELECTOR_SYSTEM = """\
You select database tables relevant to a natural-language question.

Each candidate table is shown with up to five of its column names and any
table comment. Pick the tables that ANY correct SQL answer would need to
reference.

Consider semantic equivalents the table name doesn't spell out:
- In Atlas ERP: `sales_orders` and `sales_order_lines` hold sales orders, `inv_items` holds products/items,
  `sales_customers` holds customers, `proc_vendors` holds suppliers/vendors, `proc_purchase_orders` holds purchase orders,
  `inv_stock_quants` and `inv_stock_moves` hold inventory stock, `fin_journal_entries` and `fin_journal_lines` hold accounting/revenue,
  `sales_billings` and `sales_billing_lines` hold invoices, `hr_employees` and `hr_payroll_runs` hold HR data.

Output ONLY a JSON array of table names, ordered by relevance, with up to
{max_select} items.

Example: ["sales_orders", "sales_order_lines", "sales_customers"]

Candidate tables:
{candidate_block}
"""

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*?\]")


def _candidate_block(candidates: list[Table]) -> str:
    lines: list[str] = []
    for t in candidates:
        cols = ", ".join(c.name for c in t.columns[:6])
        more = f", +{len(t.columns) - 6}" if len(t.columns) > 6 else ""
        line = f"- {t.qualified_name}({cols}{more})"
        if t.comment:
            line += f"  -- {t.comment[:80]}"
        lines.append(line)
    return "\n".join(lines)


def llm_select_tables(
    question: str,
    candidates: list[Table],
    llm,
    max_select: int = 15,
) -> list[Table]:
    """Use the LLM to pick the relevant tables out of a TF-IDF candidate set.

    Falls back to the candidate prefix on any error.
    """
    if len(candidates) <= max_select:
        return candidates

    system = _SELECTOR_SYSTEM.format(
        max_select=max_select,
        candidate_block=_candidate_block(candidates),
    )

    try:
        response = llm.generate(system, question)
    except Exception:
        return candidates[:max_select]

    match = _JSON_ARRAY_RE.search(response)
    if not match:
        return candidates[:max_select]
    import json
    try:
        names = json.loads(match.group(0))
    except json.JSONDecodeError:
        return candidates[:max_select]
    if not isinstance(names, list):
        return candidates[:max_select]

    by_name: dict[str, Table] = {t.name.lower(): t for t in candidates}
    selected: list[Table] = []
    seen: set[str] = set()
    for n in names:
        if not isinstance(n, str):
            continue
        key = n.lower().rsplit(".", 1)[-1]
        if key in by_name and key not in seen:
            selected.append(by_name[key])
            seen.add(key)
        if len(selected) >= max_select:
            break

    return selected or candidates[:max_select]
