"""The full-screen spending report on the HUD ("Jarvis, pull up my spending report"): Spend Breakdown inside Jarvis.

Everything the Spend Breakdown app does except the pet: add statements (CSV or PDF, several accounts, the
Statements folder), filter by account and month, spent / earned / net, the category donut, categories you can
open to see their shops, move a shop to another category (and every future statement follows), new and deleted
categories, re-categorise a transaction by its wording, your take-home pay, remove an account, and the insights
review. Plus Jarvis's spending plan. Same data as the app (spendcore.py), so both always agree.
"""
import base64
import datetime
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import features
import spendcore as sc

ALL_A, ALL_M = "All accounts", "All months"


def _state():
    rules = sc.load_json(sc.RULES_FILE, {})
    txns = [dict(t, date=datetime.date.fromisoformat(str(t["date"])[:10])) for t in sc.load_json(sc.DATA_FILE, [])]
    for t in txns:
        t["cat"] = sc.categorise(t["desc"], t["amount"], rules)
    return txns, rules, sc.load_json(sc.CATS_FILE, []), sc.load_json(sc.SETTINGS_FILE, {})


def _save_txns(txns):
    sc.save_json(sc.DATA_FILE, [{k: (str(v) if k == "date" else v) for k, v in t.items() if k != "cat"} for t in txns])


def _pick(txns, account, month):
    return [t for t in txns if (account in (None, "", ALL_A) or t["account"] == account)
            and (month in (None, "", ALL_M) or t["date"].strftime("%Y-%m") == month)]


def view(account=ALL_A, month=ALL_M):
    """Everything the spending screen shows for an account and month."""
    txns, rules, custom, settings = _state()
    accounts = sorted({t["account"] for t in txns})
    months = sorted({t["date"].strftime("%Y-%m") for t in txns}, reverse=True)
    account = account if account in accounts else ALL_A
    month = month if month in months else ALL_M
    rows = _pick(txns, account, month)
    totals, counts = defaultdict(float), Counter(t["cat"] for t in rows)
    shops = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for t in rows:
        totals[t["cat"]] += t["amount"]
        s = shops[t["cat"]][(sc.merchant_name(t["desc"]), "in" if t["amount"] > 0 else "out")]
        s[0] += t["amount"]
        s[1] += 1
    spend = sorted(((c, -v) for c, v in totals.items() if c not in sc.NOT_SPENDING), key=lambda kv: -kv[1])
    spent = sum(v for _, v in spend)
    n_months = 1 if month != ALL_M else max(1, len({t["date"].strftime("%Y-%m") for t in rows}))
    mi = sc.monthly_income(settings)
    earned = mi * n_months if mi else totals["Income"]
    deletable = set(custom) | set(rules.values())

    def cat(c, total, colour, kind):
        return {"name": c, "total": round(total, 2), "pct": round(100 * total / spent, 1) if spent > 0 and kind == "spend" else 0,
                "colour": colour, "count": counts[c], "kind": kind, "deletable": c in deletable,
                "shops": [{"name": n, "way": w, "amount": round(a, 2), "n": k}
                          for (n, w), (a, k) in sorted(shops[c].items(), key=lambda kv: -abs(kv[1][0]))]}
    cats = [cat(c, v, sc.COLOURS[i % len(sc.COLOURS)], "spend") for i, (c, v) in enumerate(spend)]
    cats += [cat(c, 0, sc.COLOURS[(len(spend) + j) % len(sc.COLOURS)], "empty")
             for j, c in enumerate(c for c in custom if c not in totals)]  # your new categories: drop targets
    cats += [cat(c, abs(totals[c]), "#7d84b2", "not") for c in sc.NOT_SPENDING if counts[c]]
    plan = None
    try:
        import spending
        p = spending.spending_plan(month if month != ALL_M else None)
        plan = p if p.get("categories") else None
    except Exception:
        pass
    return {"account": account, "month": month, "accounts": accounts, "months": months,
            "spent": round(spent, 2), "earned": round(earned, 2), "net": round(earned - spent, 2),
            "count": len(rows), "pay": {"income": settings.get("income"), "per": settings.get("per", "fortnight"),
                                        "months": n_months} if mi else None,
            "categories": cats, "all_categories": sorted(set(sc.CATEGORIES) | set(rules.values()) | set(custom) | {"Other"}),
            "statements_folder": str(sc.STATEMENTS_DIR), "has_data": bool(txns), "plan": plan}


def transactions(account=ALL_A, month=ALL_M, cat=None, shop=None, way=None, limit=400):
    """The transactions behind a category or a shop (newest first)."""
    txns, *_ = _state()
    shown = {id(t) for t in _pick(txns, account, month)}
    out = []
    for i, t in sorted(enumerate(txns), key=lambda it: it[1]["date"], reverse=True):
        if id(t) in shown and (not cat or t["cat"] == cat) and (not shop or sc.merchant_name(t["desc"]) == shop) \
                and (not way or way == ("in" if t["amount"] > 0 else "out")):
            out.append({"id": i, "date": t["date"].strftime("%d/%m/%Y"), "account": t["account"], "desc": t["desc"],
                        "shop": sc.merchant_name(t["desc"]),
                        "amount": round(t["amount"], 2), "cat": t["cat"]})
            if len(out) >= limit:
                break
    return out


def _rule(key, cat):
    rules = sc.load_json(sc.RULES_FILE, {})
    rules.pop(key, None)  # re-adding makes it the newest rule, so it wins
    rules[key] = cat
    sc.save_json(sc.RULES_FILE, rules)


def act(d):
    """The screen's buttons. d["action"] says which."""
    a = d.get("action")
    if a == "move":  # a shop dragged onto another category (applies to future statements too)
        if not d.get("to") or d["to"] == d.get("from"):
            return {"ok": True}
        _rule(f"shop:{d['shop'].lower()}|{d.get('way', 'out')}", d["to"])
        return {"ok": True, "note": f"Moved {d['shop']} to {d['to']}"}
    if a == "recategorise":  # anything whose wording contains this goes in that category
        if not d.get("words", "").strip() or not d.get("to", "").strip():
            return {"error": "Need some wording and a category"}
        _rule(d["words"].strip().lower(), d["to"].strip())
        return {"ok": True}
    if a == "new_category":
        name = d.get("name", "").strip()
        name = name.title() if name.islower() else name
        if not name:
            return {"error": "Give it a name"}
        custom = sc.load_json(sc.CATS_FILE, [])
        if name not in custom:
            sc.save_json(sc.CATS_FILE, custom + [name])
        return {"ok": True, "name": name}
    if a == "delete_category":  # what was moved into it goes back to where it was sorted automatically
        c = d.get("name")
        rules = sc.load_json(sc.RULES_FILE, {})
        sc.save_json(sc.RULES_FILE, {k: v for k, v in rules.items() if v != c})
        sc.save_json(sc.CATS_FILE, [x for x in sc.load_json(sc.CATS_FILE, []) if x != c])
        return {"ok": True}
    if a == "pay":
        try:
            amount = max(0.0, float(str(d.get("income", 0)).replace("$", "").replace(",", "")))
        except ValueError:
            return {"error": "That amount isn't a number"}
        if d.get("per") not in sc.PER_MONTH:
            return {"error": "Pick week, fortnight, month or year"}
        s = sc.load_json(sc.SETTINGS_FILE, {})
        s.update(income=amount, per=d["per"])
        sc.save_json(sc.SETTINGS_FILE, s)
        return {"ok": True}
    if a == "remove_account":
        txns, *_ = _state()
        keep = [t for t in txns if t["account"] != d.get("account")]
        if len(keep) == len(txns):
            return {"error": "No account by that name"}
        _save_txns(keep)
        return {"ok": True, "removed": len(txns) - len(keep)}
    if a == "import":
        return import_files(d.get("files", []), d.get("account", ""))
    if a == "scan":
        return scan_folder()
    if a == "insights":
        txns, *_ = _state()
        pool = [t for t in txns if d.get("account") in (None, "", ALL_A) or t["account"] == d.get("account")]
        income = sc.monthly_income(sc.load_json(sc.SETTINGS_FILE, {}))
        return {"insights": [{**i, "save": round(i["save"])} for i in sc.insights(pool, income)]}
    return {"error": f"Unknown action {a}"}


def _import(path, name, txns, rules):
    """One statement into txns (as the app does). Returns a report line."""
    p = Path(path)
    try:
        got = sc.load_statement(str(p))
    except Exception as e:
        return f"{p.name}: couldn't open it ({e})"
    if not got:
        return f"{p.name}: no transactions found" + (" (scanned PDFs can't be read; try the CSV export)"
                                                      if p.suffix.lower() == ".pdf" else "")
    groups = defaultdict(list)  # a PDF can hold several accounts: "<name> - <account>"
    for t in got:
        t["cat"] = sc.categorise(t["desc"], t["amount"], rules)
        groups[t.pop("section", None)].append(t)
    lines = []
    for sec, rows in groups.items():
        acct = f"{name} - {sec}" if sec else name
        added = sc.merge(txns, rows, acct)
        lines.append(f"{acct}: {added} new" + (f", {len(rows) - added} already loaded" if added < len(rows) else ""))
    return f"{p.name}: " + "; ".join(lines)


def import_files(files, account):
    """Statements uploaded from the screen: [{name, data (base64)}], all for one account name."""
    if not account.strip():
        return {"error": "Which bank or account are these from?"}
    txns, rules, *_ = _state()
    report = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in files[:20]:
            name = Path(f.get("name", "statement.csv")).name
            if Path(name).suffix.lower() not in (".csv", ".pdf"):
                report.append(f"{name}: only CSV and PDF statements")
                continue
            path = Path(tmp) / name
            path.write_bytes(base64.b64decode(f.get("data", "")))
            report.append(_import(path, account.strip(), txns, rules))
    _save_txns(txns)
    return {"ok": True, "report": report}


def scan_folder():
    """New files in Documents/Statements: Statements/<Account name>/file.csv goes to that account."""
    d = sc.STATEMENTS_DIR
    if not d.is_dir():
        return {"ok": True, "report": [], "note": f"Make a folder called Statements in Documents ({d}), with a "
                                                  "folder inside it for each account, and drop statements in."}
    imported = sc.load_json(sc.IMPORTED_FILE, {})
    txns, rules, *_ = _state()
    report = []
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.suffix.lower() in (".csv", ".pdf"):
            rel, st = str(f.relative_to(d)), f.stat()
            stamp = f"{st.st_mtime:.0f}:{st.st_size}"
            if imported.get(rel) == stamp:
                continue
            parts = Path(rel).parts
            imported[rel] = stamp
            report.append(_import(f, parts[0] if len(parts) > 1 else f.stem, txns, rules))
    sc.save_json(sc.IMPORTED_FILE, imported)
    if report:
        _save_txns(txns)
    return {"ok": True, "report": report}


def spending_report(open=True):
    """Switch the HUD to the full spending report (or back)."""
    try:
        features._panel({"type": "mode", "mode": "spending" if open else ""})
    except OSError:
        return {"error": "The HUD isn't open."}
    return {"shown": bool(open), "note": "It's on his screen. If he asked a question about his spending, answer it with the "
            "figures from the `spending` tool and say where on the report he can see it; otherwise a few words."}


FUNCS = {"spending_report": spending_report}
TOOLS = [{"name": "spending_report", "description": "Switch his screen to the full spending report (Spend Breakdown "
          "inside Jarvis: categories, shops, transactions, insights, adding statements), when he asks to pull up / "
          "show / open his spending report or breakdown, or asks a question about his spending in general ('what's my "
          "spending like'): then also call `spending` for the figures and answer the question itself, pointing to the "
          "part of the report that shows it. open=false switches back.",
          "input_schema": {"type": "object", "properties": {"open": {"type": "boolean"}}}}]


def selftest():
    import json
    real = (sc.DATA_FILE, sc.RULES_FILE, sc.CATS_FILE, sc.SETTINGS_FILE, sc.IMPORTED_FILE, sc.STATEMENTS_DIR, sc.DATA_DIR)
    d = Path(tempfile.mkdtemp())
    sc.DATA_DIR, sc.DATA_FILE, sc.RULES_FILE, sc.CATS_FILE = d, d / "t.json", d / "r.json", d / "c.json"
    sc.SETTINGS_FILE, sc.IMPORTED_FILE, sc.STATEMENTS_DIR = d / "s.json", d / "i.json", d / "Statements"
    try:
        csv = ("Date,Description,Amount\n01/10/2026,VISA PURCHASE UBER EATS SYDNEY,-35.50\n"
               "02/10/2026,WOOLWORTHS 1234 SYDNEY,-120.00\n03/10/2026,SALARY ACME PTY,2400.00\n"
               "04/11/2026,NETFLIX.COM,-18.99\n05/11/2026,BEANS CAFE DOWNTOWN,-6.50\n")
        r = import_files([{"name": "oct.csv", "data": base64.b64encode(csv.encode()).decode()}], "CommBank")
        assert "5 new" in r["report"][0], r
        assert "0 new" in import_files([{"name": "oct.csv", "data": base64.b64encode(csv.encode()).decode()}],
                                       "CommBank")["report"][0]  # same statement twice: nothing doubled
        v = view()
        assert v["accounts"] == ["CommBank"] and v["months"] == ["2026-11", "2026-10"] and v["count"] == 5
        assert v["spent"] == 180.99 and v["earned"] == 2400 and v["net"] == 2219.01
        assert [c["name"] for c in v["categories"] if c["kind"] == "spend"][:1] == ["Groceries"]
        assert view(month="2026-10")["count"] == 3
        uber = next(c for c in v["categories"] if c["name"] == "Eating Out")["shops"][0]
        assert act({"action": "new_category", "name": "takeaway"})["name"] == "Takeaway"
        act({"action": "move", "shop": uber["name"], "way": "out", "from": "Eating Out", "to": "Takeaway"})
        assert [t["cat"] for t in transactions(shop=uber["name"])] == ["Takeaway"]
        assert any(c["name"] == "Takeaway" and c["deletable"] for c in view()["categories"])
        act({"action": "delete_category", "name": "Takeaway"})
        assert transactions(shop=uber["name"])[0]["cat"] == "Eating Out"
        act({"action": "recategorise", "words": "beans cafe", "to": "Groceries"})
        assert transactions(cat="Groceries")[0]["desc"].startswith("BEANS")
        act({"action": "pay", "income": "2,000", "per": "fortnight"})
        v = view(month="2026-10")
        assert v["earned"] == round(2000 * 26 / 12, 2) and v["pay"]["per"] == "fortnight"
        assert isinstance(act({"action": "insights"})["insights"], list)
        (d / "Statements" / "ING Savings").mkdir(parents=True)
        (d / "Statements" / "ING Savings" / "nov.csv").write_text("Date,Description,Amount\n06/11/2026,BP SERVO,-60\n")
        assert "ING Savings: 1 new" in scan_folder()["report"][0] and scan_folder()["report"] == []
        assert act({"action": "remove_account", "account": "ING Savings"})["removed"] == 1
        assert "error" in import_files([], "  ") and "error" in act({"action": "pay", "income": "x", "per": "month"})
        json.dumps(view())  # all of it goes to the HUD as JSON
    finally:
        (sc.DATA_FILE, sc.RULES_FILE, sc.CATS_FILE, sc.SETTINGS_FILE, sc.IMPORTED_FILE, sc.STATEMENTS_DIR,
         sc.DATA_DIR) = real
    print("spending view self-test passed")


if __name__ == "__main__":
    selftest()
