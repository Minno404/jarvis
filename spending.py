"""Spending questions, answered from your Spend Breakdown app's own data and categories.

Jarvis loads spend_breakdown.pyw itself (it only runs its window when started directly), so the
categories, your drag-and-drop rules and the money-saving tips are exactly what the app shows.
"""
import datetime
import importlib.machinery
import importlib.util
import os
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(os.environ.get("JARVIS_SPEND_APP", Path.home() / "Downloads" / "SpendBreakdown" / "spend_breakdown.pyw"))
_app = None


def app():
    global _app
    if _app is None:
        if not APP.exists():
            raise FileNotFoundError(f"Can't find Spend Breakdown at {APP}. Set JARVIS_SPEND_APP to its .pyw file.")
        loader = importlib.machinery.SourceFileLoader("spend_breakdown", str(APP))
        spec = importlib.util.spec_from_loader("spend_breakdown", loader)
        _app = importlib.util.module_from_spec(spec)
        loader.exec_module(_app)
    return _app


def _txns():
    a = app()
    rules = a.load_json(a.RULES_FILE, {})
    txns = [dict(t, date=datetime.date.fromisoformat(str(t["date"])[:10])) for t in a.load_json(a.DATA_FILE, [])]
    for t in txns:
        t["cat"] = a.categorise(t["desc"], t["amount"], rules)
        t["shop"] = a.merchant_name(t["desc"])
    if not txns:
        raise ValueError("Spend Breakdown has no statements loaded yet")
    return txns


def spending(month=None, since=None, until=None, category=None):
    """Money out by category and shop for a month (YYYY-MM, default this month) or a date range."""
    a, txns = app(), _txns()
    if not (month or since):
        month = max(t["date"] for t in txns).strftime("%Y-%m")  # latest month with statements
    pick = lambda t: (t["date"].strftime("%Y-%m") == month if month else
                      str(t["date"]) >= since and (not until or str(t["date"]) <= until))
    rows = [t for t in txns if pick(t)]
    spend = [t for t in rows if t["amount"] < 0 and t["cat"] not in a.NOT_SPENDING]
    if category:
        spend = [t for t in spend if category.lower() in t["cat"].lower()]
    by_cat, by_shop = defaultdict(float), defaultdict(float)
    for t in spend:
        by_cat[t["cat"]] -= t["amount"]
        by_shop[t["shop"]] -= t["amount"]
    months = Counter(t["date"].strftime("%Y-%m") for t in txns if t["amount"] < 0 and t["cat"] not in a.NOT_SPENDING)
    other = [m for m in months if m != month]
    avg = {}
    for c in by_cat:  # the usual month, from the other months on file
        avg[c] = round(sum(-t["amount"] for t in txns if t["cat"] == c and t["amount"] < 0
                           and t["date"].strftime("%Y-%m") in other) / len(other), 2) if other else None
    top = lambda d, n: [{"name": k, "spent": round(v, 2)} for k, v in sorted(d.items(), key=lambda x: -x[1])[:n]]
    return {"period": month or f"{since} to {until or 'now'}", "total_spent": round(sum(by_cat.values()), 2),
            "income": round(sum(t["amount"] for t in rows if t["cat"] == "Income"), 2),
            "by_category": [dict(c, usual_month=avg.get(c["name"])) for c in top(by_cat, 15)],
            "top_shops": top(by_shop, 10), "statements_cover": f"{min(t['date'] for t in txns)} to "
                                                               f"{max(t['date'] for t in txns)}"}


def spending_tips():
    """The app's own money-saving review: subscriptions, fees, delivery, jumps in a category..."""
    a = app()
    income = a.monthly_income(a.load_json(a.SETTINGS_FILE, {}))
    return [{"title": i["title"], "detail": i["body"], "saves_a_year": round(i["save"])}
            for i in a.insights(_txns(), income)[:6]]


FUNCS = {"spending": spending, "spending_tips": spending_tips}
S = {"type": "string"}
TOOLS = [
    {"name": "spending", "description": "{USER}'s spending from his Spend Breakdown app (his bank "
     "statements): total, by category with his usual month for comparison, top shops. month = YYYY-MM "
     "(default: latest month loaded), or since/until = YYYY-MM-DD, optional category filter.",
     "input_schema": {"type": "object", "properties": {"month": S, "since": S, "until": S, "category": S}}},
    {"name": "spending_tips", "description": "Ways he could save money, from the app's own spending review.",
     "input_schema": {"type": "object", "properties": {}}},
]
