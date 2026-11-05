"""Sums, tips, bill splits and conversions, answered instantly on the PC (no Claude, no tokens).

"what's 15% of 240", "12 times 7 plus 3", "split $142 four ways with a 10% tip", "10% tip on $80",
"180 celsius in fahrenheit", "5 km in miles", "100 US dollars to Aussie dollars". Anything else returns None.
"""
import ast
import json
import operator
import re
import time
import urllib.request

WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "hundred": 100, "a": 1, "an": 1, "half": 0.5}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(expr):
    def go(n):
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError("too big")
            return OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](go(n.operand))
        raise ValueError("not a sum")
    return go(ast.parse(expr, mode="eval"))


def _fmt(x, money=False):
    if money:
        return f"${x:,.2f}"
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.4f}".rstrip("0").rstrip(".") if abs(x) < 1000 else f"{x:,.2f}"


def _num(s):
    s = s.strip().replace(",", "").replace("$", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else WORDS.get(s)


def _prep(text):
    t = text.lower().strip()
    t = re.sub(r"^(hey |ok |okay )?jarvis[,.!]?\s*", "", t)
    t = re.sub(r"^(what'?s|what is|whats|how much is|calculate|work out|tell me)\s+", "", t)
    return re.sub(r"[?!]+$|\.$", "", t).strip()


# ---------- conversions ----------
LEN = {"mm": .001, "millimetre": .001, "millimeter": .001, "cm": .01, "centimetre": .01, "centimeter": .01,
       "m": 1, "metre": 1, "meter": 1, "km": 1000, "kilometre": 1000, "kilometer": 1000, "inch": .0254,
       "inches": .0254, "in": .0254, "foot": .3048, "feet": .3048, "ft": .3048, "yard": .9144, "mile": 1609.344}
MASS = {"g": 1, "gram": 1, "kg": 1000, "kilo": 1000, "kilogram": 1000, "oz": 28.3495, "ounce": 28.3495,
        "lb": 453.592, "pound": 453.592, "stone": 6350.29}
VOL = {"ml": 1, "millilitre": 1, "milliliter": 1, "l": 1000, "litre": 1000, "liter": 1000, "cup": 250,
       "tablespoon": 20, "tbsp": 20, "teaspoon": 5, "tsp": 5, "gallon": 3785.41, "pint": 568.26, "fl oz": 29.57}
TIME = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}
SPEED = {"kmh": 1, "km/h": 1, "kph": 1, "mph": 1.609344, "knot": 1.852}
TEMP = {"c": "C", "celsius": "C", "centigrade": "C", "degrees": "C", "f": "F", "fahrenheit": "F", "k": "K", "kelvin": "K"}
CUR = {"aud": "AUD", "australian dollar": "AUD", "aussie dollar": "AUD", "usd": "USD", "us dollar": "USD",
       "american dollar": "USD", "eur": "EUR", "euro": "EUR", "gbp": "GBP", "pound sterling": "GBP",
       "british pound": "GBP", "nzd": "NZD", "kiwi dollar": "NZD", "new zealand dollar": "NZD", "jpy": "JPY",
       "yen": "JPY", "japanese yen": "JPY", "cad": "CAD", "canadian dollar": "CAD", "cny": "CNY", "yuan": "CNY",
       "inr": "INR", "rupee": "INR", "sgd": "SGD", "singapore dollar": "SGD", "thb": "THB", "baht": "THB",
       "idr": "IDR", "rupiah": "IDR", "php": "PHP", "peso": "PHP", "krw": "KRW", "won": "KRW", "hkd": "HKD"}
_rates = {"at": 0, "rates": {}}


def _unit(u, table):
    u = u.strip().rstrip(".")
    for cand in (u, u.rstrip("s"), u[:-2] if u.endswith("es") else u, u.replace("degrees ", "")):
        if cand in table:
            return cand
    return None


def rates():
    if time.time() - _rates["at"] > 6 * 3600:
        req = urllib.request.Request("https://open.er-api.com/v6/latest/USD", headers={"User-Agent": "Jarvis"})
        with urllib.request.urlopen(req, timeout=6) as r:
            _rates.update(at=time.time(), rates=json.loads(r.read())["rates"])
    return _rates["rates"]


def convert(t):
    m = re.fullmatch(r"(-?[\d.,]+|\w+)\s*(.+?)\s+(?:in|to|into|as)\s+(.+)", t)
    if not m:
        return None
    n, a, b = _num(m.group(1).replace("$", "")), m.group(2).strip(), m.group(3).strip()
    if n is None:
        return None
    a = re.sub(r"^degrees?\s+", "", a)
    b = re.sub(r"^degrees?\s+", "", b)
    ta, tb = _unit(a, TEMP), _unit(b, TEMP)
    if ta and tb:
        fa, fb = TEMP[ta], TEMP[tb]
        c = {"C": n, "F": (n - 32) * 5 / 9, "K": n - 273.15}[fa]
        out = {"C": c, "F": c * 9 / 5 + 32, "K": c + 273.15}[fb]
        name = {"C": "degrees Celsius", "F": "degrees Fahrenheit", "K": "kelvin"}
        return f"{_fmt(n)} {name[fa]} is {round(out, 1):g} {name[fb]}."
    for table in (LEN, MASS, VOL, TIME, SPEED):
        ua, ub = _unit(a, table), _unit(b, table)
        if ua and ub:
            out = n * table[ua] / table[ub]
            return f"{_fmt(n)} {a} is {_fmt(round(out, 4) if abs(out) < 100 else round(out, 2))} {b}."
    ca = CUR.get(_unit(a.replace("dollars", "dollar").replace("bucks", "dollar"), CUR) or "")
    cb = CUR.get(_unit(b.replace("dollars", "dollar").replace("bucks", "dollar"), CUR) or "")
    if ca and cb:
        try:
            r = rates()
            out = n / r[ca] * r[cb]
        except Exception:
            return "I can't reach the exchange rates right now, {TITLE}."
        return f"{_fmt(n)} {ca} is about {_fmt(round(out, 2))} {cb} at today's rate."
    return None


# ---------- money ----------
def money(t):
    m = re.fullmatch(r"split \$?([\d.,]+) (?:dollars )?(?:between |by |into )?(\w+)(?: ways| people)?"
                     r"(?: (?:with|plus|and) (?:an? )?([\d.]+) ?% tip)?", t)
    if m and _num(m.group(1)) is not None and _num(m.group(2)):
        total, ways = _num(m.group(1)), _num(m.group(2))
        tip = float(m.group(3) or 0)
        each = total * (1 + tip / 100) / ways
        extra = f" including a {_fmt(tip)}% tip" if tip else ""
        return f"That's {_fmt(each, True)} each{extra}, {{TITLE}}."
    m = re.fullmatch(r"(?:an? )?([\d.]+) ?% tip on \$?([\d.,]+)|tip (?:of )?([\d.]+) ?% on \$?([\d.,]+)", t)
    if m:
        pc, amt = float(m.group(1) or m.group(3)), _num(m.group(2) or m.group(4))
        return f"The tip is {_fmt(amt * pc / 100, True)}, so {_fmt(amt * (1 + pc / 100), True)} all up."
    m = re.fullmatch(r"([\d.]+) ?% (?:of|off) \$?([\d.,]+)", t)
    if m:
        pc, amt = float(m.group(1)), _num(m.group(2))
        if " off " in t:
            return f"{_fmt(pc)}% off {_fmt(amt)} is {_fmt(amt * (1 - pc / 100))}, a saving of {_fmt(amt * pc / 100)}."
        return f"{_fmt(pc)}% of {_fmt(amt)} is {_fmt(amt * pc / 100)}."
    return None


# ---------- plain sums ----------
def sums(t):
    e = " " + t + " "
    for a, b in ((r" plus ", "+"), (r" (?:minus|take away|less) ", "-"), (r" (?:times|multiplied by|x) ", "*"),
                 (r" (?:divided by|over) ", "/"), (r" to the power of ", "**"), (r" squared ", "**2 "),
                 (r" cubed ", "**3 "), (r" mod(?:ulo)? ", "%")):
        e = re.sub(a, b, e)
    m = re.fullmatch(r"\s*(?:the )?square root of ([\d.]+)\s*", e)
    if m:
        return f"The square root of {m.group(1)} is {_fmt(round(float(m.group(1)) ** .5, 4))}."
    e = re.sub(r"\b(" + "|".join(k for k in WORDS if len(k) > 2) + r")\b", lambda w: str(WORDS[w.group(1)]), e)
    e = e.replace("$", "").replace(",", "").replace("×", "*").replace("÷", "/").strip()
    if not re.fullmatch(r"[\d.\s+\-*/%()]+", e) or not re.search(r"\d\s*[-+*/%]\s*[\d(]|\*\*", e):
        return None
    try:
        v = _eval(e)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
    return f"That's {_fmt(round(v, 6))}."


def answer(text):
    """The answer if this is a sum, money question or conversion, else None."""
    t = _prep(text)
    if not t or len(t) > 90:
        return None
    for f in (money, convert, sums):
        try:
            r = f(t)
        except Exception:
            r = None
        if r:
            return r
    return None


def selftest():
    cases = {"what's 12 times 7 plus 3": "That's 87.", "Jarvis, what is 15% of 240?": "15% of 240 is 36.",
             "split $142 four ways with a 10% tip": "That's $39.05 each including a 10% tip, {TITLE}.",
             "split 90 between 3": "That's $30.00 each, {TITLE}.",
             "10% tip on $80": "The tip is $8.00, so $88.00 all up.",
             "180 celsius in fahrenheit": "180 degrees Celsius is 356 degrees Fahrenheit.",
             "what's 5 km in miles": "5 km is 3.1069 miles.", "2 cups in ml": "2 cups is 500 ml.",
             "70 kg in pounds": "70 kg is 154.32 pounds.", "(4+6)/4": "That's 2.5.",
             "square root of 144": "The square root of 144 is 12.", "20% off $50": "20% off 50 is 40, a saving of 10."}
    for said, want in cases.items():
        assert answer(said) == want, (said, answer(said))
    rates_real = rates
    globals()["rates"] = lambda: {"USD": 1, "AUD": 1.5}
    assert answer("100 US dollars to Aussie dollars") == "100 USD is about 150 AUD at today's rate."
    globals()["rates"] = rates_real
    for said in ("what's the weather", "open discord", "how are you", "1 2 3", "add milk to my list",
                 "what's 5 o'clock in London", "play the next song", "remind me in 5 minutes"):
        assert answer(said) is None, (said, answer(said))
    print("calc self-test passed")


if __name__ == "__main__":
    selftest()
