"""Run a simulation: "Jarvis, simulate saving $50 a week for a year", "what if I pay $200 more a month off the car
loan?", "compare $50 and $100 a week". The maths is done here (exact), the brain only fills in the numbers, and the
HUD plays it as an animated projection with up to 3 scenarios side by side.

model "savings": start + a regular deposit, with interest (annual %, compounded monthly), over some years.
model "loan": a balance paid down by a regular payment, with interest; when it's paid off and the interest paid.
model "custom": any other projection the brain has worked out itself, as points.
"""
import features

PER_MONTH = {"week": 52 / 12, "fortnight": 26 / 12, "month": 1.0, "year": 1 / 12}
S, N = {"type": "string"}, {"type": "number"}


def _num(v, default=0.0):
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def savings(start=0, add=0, every="month", rate_pct=0, years=1, goal=None):
    months = max(1, min(600, round(_num(years, 1) * 12)))
    per, r = _num(add) * PER_MONTH.get(every, 1.0), _num(rate_pct) / 100 / 12
    bal, paid_in, pts, hit = _num(start), _num(start), [], None
    pts.append(round(bal, 2))
    for m in range(1, months + 1):
        bal = bal * (1 + r) + per
        paid_in += per
        pts.append(round(bal, 2))
        if goal and hit is None and bal >= _num(goal):
            hit = m
    return {"points": pts, "final": round(bal, 2), "paid_in": round(paid_in, 2), "interest": round(bal - paid_in, 2),
            "goal_month": hit}


def loan(balance=0, rate_pct=0, pay=0, every="month", years=30):
    per, r = _num(pay) * PER_MONTH.get(every, 1.0), _num(rate_pct) / 100 / 12
    bal, interest, pts = _num(balance), 0.0, [round(_num(balance), 2)]
    for m in range(1, max(1, min(600, round(_num(years, 30) * 12))) + 1):
        i = bal * r
        interest += i
        bal = bal + i - per
        if bal <= 0:
            pts.append(0.0)
            return {"points": pts, "paid_off_month": m, "interest": round(interest, 2), "final": 0.0}
        pts.append(round(bal, 2))
        if per <= bal * r and m > 1:  # the payment doesn't even cover the interest: it never ends
            return {"points": pts, "paid_off_month": None, "interest": round(interest, 2), "final": round(bal, 2),
                    "never": True}
    return {"points": pts, "paid_off_month": None, "interest": round(interest, 2), "final": round(bal, 2)}


def _when(months):
    if months is None:
        return None
    y, m = divmod(int(months), 12)
    return " and ".join(x for x in (f"{y} year{'s' * (y != 1)}" if y else "", f"{m} month{'s' * (m != 1)}" if m else "") if x)


def simulate(title, model="savings", base=None, scenarios=None, unit="$", insight="", points=None, labels=None):
    """Work out the projection and play it on the HUD (see the tool description)."""
    base = base or {}
    runs = []
    for sc in (scenarios or [{"name": "Plan"}])[:3]:
        p = {**base, **{k: v for k, v in sc.items() if k != "name"}}
        name = str(sc.get("name") or "Plan")[:30]
        if model == "loan":
            r = loan(**{k: p[k] for k in ("balance", "rate_pct", "pay", "every", "years") if k in p})
            tag = "never paid off" if r.get("never") else f"paid off in {_when(r['paid_off_month'])}" if r["paid_off_month"] \
                else f"{unit}{r['final']:,.0f} left"
            runs.append({"name": name, "points": r["points"], "end": tag, "interest": r["interest"], **r})
        elif model == "custom":
            pts = [_num(v) for v in (sc.get("points") or points or [])][:600]
            runs.append({"name": name, "points": pts, "end": f"{unit}{pts[-1]:,.0f}" if pts else ""})
        else:
            r = savings(**{k: p[k] for k in ("start", "add", "every", "rate_pct", "years", "goal") if k in p})
            tag = f"{unit}{r['final']:,.0f}" + (f", goal in {_when(r['goal_month'])}" if r["goal_month"] else "")
            runs.append({"name": name, "points": r["points"], "end": tag, **r})
    if not any(r["points"] for r in runs):
        return {"error": "Nothing to simulate: give the numbers (or points for a custom one)."}
    ev = {"type": "sim", "title": str(title)[:60], "model": model, "unit": unit, "insight": str(insight)[:200],
          "labels": labels if model == "custom" else None,
          "runs": [{"name": r["name"], "points": r["points"], "end": r["end"]} for r in runs]}
    try:
        features._panel(ev)
    except OSError:
        pass
    summary = [{k: r.get(k) for k in ("name", "end", "final", "paid_in", "interest", "goal_month", "paid_off_month")
                if r.get(k) is not None} for r in runs]
    return {"shown": True, "results": summary,
            "note": "Playing on the HUD. Tell him the headline result in a sentence (the numbers above are exact)."}


FUNCS = {"simulate": simulate}
TOOLS = [{"name": "simulate", "description": (
    "Run a simulation ('simulate saving $50 a week for a year', 'what if I pay the car loan off faster', 'compare...'): "
    "an animated projection on the HUD, with exact maths. model 'savings': base {start, add, every (week, fortnight, "
    "month, year), rate_pct (annual interest), years, goal}. model 'loan': base {balance, rate_pct, pay, every, "
    "years (max)}. scenarios: 1 to 3 variations, each {name, and any base field to change}, e.g. [{name: '$50 a "
    "week', add: 50}, {name: '$100 a week', add: 100}]. model 'custom' for anything else you've worked out: "
    "scenarios [{name, points: [numbers, one per step]}] and labels for the steps. insight: one line on what it "
    "shows. Use his spending report for real numbers when it helps."),
    "input_schema": {"type": "object", "required": ["title"], "properties": {
        "title": S, "model": {"type": "string", "enum": ["savings", "loan", "custom"]}, "unit": S, "insight": S,
        "base": {"type": "object"}, "scenarios": {"type": "array", "items": {"type": "object"}},
        "labels": {"type": "array", "items": S}}}}]


def selftest():
    r = savings(start=0, add=50, every="week", years=1)
    assert abs(r["final"] - 2600) < 0.01 and r["interest"] == 0, r["final"]
    r = savings(start=1000, add=0, rate_pct=12, years=1)
    assert abs(r["final"] - 1126.83) < 0.01, r["final"]  # 1% a month, 12 times
    assert savings(add=100, goal=550)["goal_month"] == 6
    l = loan(balance=12000, rate_pct=0, pay=1000)
    assert l["paid_off_month"] == 12 and l["interest"] == 0
    assert loan(balance=10000, rate_pct=12, pay=50)["never"]  # $100 a month interest, $50 paid
    sent = []
    real = features._panel
    features._panel = sent.append
    try:
        out = simulate("Saving", base={"add": 50, "every": "week", "years": 1},
                       scenarios=[{"name": "$50/wk"}, {"name": "$100/wk", "add": 100}])
        assert out["results"][1]["final"] == 5200 and sent[0]["runs"][0]["end"] == "$2,600"
        assert simulate("Loan", model="loan", base={"balance": 6000, "pay": 500})["results"][0]["end"] == "paid off in 1 year"
        assert "error" in simulate("x", model="custom")
    finally:
        features._panel = real
    print("simulate self-test passed")


if __name__ == "__main__":
    selftest()
