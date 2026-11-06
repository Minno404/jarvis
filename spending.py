"""Spending questions, answered from Spend Breakdown's data and categories.

The Spend Breakdown engine is built into Jarvis (spendcore.py) and shares the app's saved data, so the
categories, your drag-and-drop rules and the money-saving tips are exactly what the app shows (and it works
without the app installed). The full-screen spending report on the HUD is spendview.py.
"""
import datetime
from collections import Counter, defaultdict
from pathlib import Path

import spendcore

_app = None  # a stand-in for tests


def app():
    return _app or spendcore


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


def _plan():
    return app().load_json(app().DATA_DIR / "plan.json", {"limits": {}, "warned": {}})


def _categories():
    a = app()
    return (set(a.CATEGORIES) | set(a.load_json(a.CATS_FILE, [])) | {"Other"}) - set(a.NOT_SPENDING)


def set_spending_plan(limits, savings_goal=None, note=None):
    """Monthly limits per category, e.g. {"Eating Out": 300}. 0 or null removes a limit; others are kept."""
    a, plan = app(), _plan()
    known = {c.lower(): c for c in _categories()}
    bad = [c for c in limits if c.lower() not in known]
    if bad:
        return {"error": f"Unknown categories {bad}", "categories": sorted(known.values())}
    for c, v in limits.items():
        if v:
            plan["limits"][known[c.lower()]] = round(float(v), 2)
        else:
            plan["limits"].pop(known[c.lower()], None)
    if savings_goal is not None:
        plan["savings_goal"] = round(float(savings_goal), 2) or None
    if note is not None:
        plan["note"] = note
    a.save_json(a.DATA_DIR / "plan.json", plan)
    return spending_plan()


def spending_plan(month=None):
    """This month's spending against the plan: spent, left and whether each category is on pace."""
    a, plan = app(), _plan()
    if not plan["limits"] and not plan.get("savings_goal"):
        return {"plan": None, "note": "No spending plan yet. Offer to make one from his usual months."}
    today = datetime.date.today()
    month = month or f"{today:%Y-%m}"
    txns = _txns()
    last = max(t["date"] for t in txns)
    y, m = map(int, month.split("-"))
    days = (datetime.date(y + m // 12, m % 12 + 1, 1) - datetime.date(y, m, 1)).days
    upto = min(last, today)
    gone = upto.day / days if upto.strftime("%Y-%m") == month else (1 if month < f"{upto:%Y-%m}" else 0)
    spent = defaultdict(float)
    for t in txns:
        if t["date"].strftime("%Y-%m") == month and t["amount"] < 0 and t["cat"] not in a.NOT_SPENDING:
            spent[t["cat"]] -= t["amount"]
    rows = []
    for c, lim in plan["limits"].items():
        sp = round(spent.get(c, 0), 2)
        status = ("over" if sp > lim else "ahead of pace" if gone and sp > lim * gone * 1.1 else "on track")
        rows.append({"category": c, "limit": lim, "spent": sp, "left": round(lim - sp, 2),
                     "used": f"{sp / lim:.0%}", "status": status})
    out = {"month": month, "statements_up_to": str(last), "month_gone": f"{gone:.0%}", "categories": rows,
           "planned_total": round(sum(plan["limits"].values()), 2),
           "spent_total": round(sum(spent.values()), 2), "note": plan.get("note")}
    income = a.monthly_income(a.load_json(a.SETTINGS_FILE, {}))
    if plan.get("savings_goal"):
        out["savings_goal"] = plan["savings_goal"]
        if income:
            out["on_course_to_save"] = round(income - out["spent_total"] / (gone or 1), 2)
    if last < today - datetime.timedelta(days=3):
        out["warning"] = f"Statements only go up to {last}: newer spending isn't counted. Import a fresh statement."
    return out


def plan_warnings():
    """New warnings for categories that just passed 80% or 100% of their limit this month (each said once)."""
    a, plan = app(), _plan()
    if not plan["limits"]:
        return []
    r, said = spending_plan(), []
    warned = plan["warned"].setdefault(r["month"], {})
    for c in r["categories"]:
        pct = c["spent"] / c["limit"]
        level = 100 if pct >= 1 else 80 if pct >= .8 else 0
        if level > warned.get(c["category"], 0):
            warned[c["category"]] = level
            said.append(f"{c['category']} is over its {c['limit']:.0f} dollar limit this month, at {c['spent']:.0f}."
                        if level == 100 else f"{c['category']} is at {c['used']} of its {c['limit']:.0f} dollar "
                        f"limit, with {c['left']:.0f} left this month.")
    plan["warned"] = {r["month"]: warned}  # older months no longer matter
    a.save_json(a.DATA_DIR / "plan.json", plan)
    return said


FUNCS = {"spending": spending, "spending_tips": spending_tips, "set_spending_plan": set_spending_plan,
         "spending_plan": spending_plan}
S = {"type": "string"}
TOOLS = [
    {"name": "spending", "description": "{USER}'s spending from his Spend Breakdown app (his bank "
     "statements): total, by category with his usual month for comparison, top shops. month = YYYY-MM "
     "(default: latest month loaded), or since/until = YYYY-MM-DD, optional category filter.",
     "input_schema": {"type": "object", "properties": {"month": S, "since": S, "until": S, "category": S}}},
    {"name": "spending_tips", "description": "Ways he could save money, from the app's own spending review.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_spending_plan", "description": "Save his monthly spending plan: limits per Spend Breakdown "
     "category (e.g. {\"Eating Out\": 300}; 0 removes one, others are kept), optional monthly savings goal and a "
     "note. To build one, look at spending and spending_tips first, propose limits, and save once he agrees. "
     "He's warned by himself at 80% and 100% of a limit.",
     "input_schema": {"type": "object", "required": ["limits"], "properties": {
         "limits": {"type": "object", "description": "category: dollars per month"},
         "savings_goal": {"type": "number"}, "note": S}}},
    {"name": "spending_plan", "description": "How this month is going against his spending plan: each "
     "category's limit, spent, left, and whether it's on pace. month = YYYY-MM (default now).",
     "input_schema": {"type": "object", "properties": {"month": S}}},
]


def selftest():
    import tempfile
    import types
    global _app
    d = Path(tempfile.mkdtemp())
    today = datetime.date.today()
    fake = types.SimpleNamespace(
        DATA_DIR=d, DATA_FILE=d / "t.json", RULES_FILE=d / "r.json", CATS_FILE=d / "c.json", SETTINGS_FILE=d / "s.json",
        CATEGORIES={"Eating Out": [], "Groceries": [], "Income": [], "Transfers": []}, NOT_SPENDING=("Income", "Transfers"),
        load_json=lambda p, dflt: __import__("json").loads(p.read_text()) if p.exists() else dflt,
        save_json=lambda p, data: p.write_text(__import__("json").dumps(data, default=str)),
        categorise=lambda desc, amt, rules: "Eating Out" if "uber" in desc else "Groceries",
        merchant_name=lambda desc: desc, monthly_income=lambda s: 4000)
    fake.save_json(fake.DATA_FILE, [{"date": str(today), "desc": "uber eats", "amount": -250},
                                    {"date": str(today), "desc": "coles", "amount": -100}])
    real, _app = _app, fake
    try:
        assert "error" in set_spending_plan({"Pokies": 50}) and "error" in set_spending_plan({"Income": 50})
        r = set_spending_plan({"eating out": 300, "Groceries": 600}, savings_goal=1000)
        assert [c["spent"] for c in r["categories"]] == [250, 100] and r["savings_goal"] == 1000
        assert plan_warnings() == ["Eating Out is at 83% of its 300 dollar limit, with 50 left this month."]
        assert plan_warnings() == []  # said once
        fake.save_json(fake.DATA_FILE, fake.load_json(fake.DATA_FILE, []) + [{"date": str(today), "desc": "uber", "amount": -60}])
        assert "over its 300" in plan_warnings()[0]
        assert list(set_spending_plan({"Groceries": 0})["categories"][0].values())[0] == "Eating Out"
    finally:
        _app = real
    print("spending self-test passed")


if __name__ == "__main__":
    selftest()
