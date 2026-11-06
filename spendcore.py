"""Spend Breakdown's engine inside Jarvis: reading bank statements (CSV and PDF), sorting them into categories,
the insights review and the take-home pay. Copied from the Spend Breakdown app (without its window and the pet),
and it uses the same saved data (%APPDATA%/SpendBreakdown), so statements, your categories and the shops you've
moved show up in both. The spending screen on the HUD is spendview.py + web/index.html.
"""
import csv, io, json, math, os, re, sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "SpendBreakdown"
DATA_FILE, RULES_FILE = DATA_DIR / "transactions.json", DATA_DIR / "rules.json"
CATS_FILE = DATA_DIR / "categories.json"  # categories you create
SETTINGS_FILE = DATA_DIR / "settings.json"  # your entered take-home pay
IMPORTED_FILE = DATA_DIR / "imported.json"  # statement files already read from the Statements folder


def documents_dir():
    """The real Documents folder (Windows may move it, e.g. into OneDrive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # 5 = My Documents
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


STATEMENTS_DIR = documents_dir() / "Statements"
PER_MONTH = {"week": 52 / 12, "fortnight": 26 / 12, "month": 1, "year": 1 / 12}


def monthly_income(settings):
    """Entered take-home pay as a monthly amount, or None if not entered."""
    return settings["income"] * PER_MONTH[settings.get("per", "month")] if settings.get("income") else None

# First match wins (your own rules are checked before these). Edit freely.
CATEGORIES = {
    "Transfers": ["transfer", "trf ", "tfr ", "osko", "pay anyone", "to savings", "from savings", "internal",
                  "fast payment", "npp "],
    "Income": ["salary", "wage", "payroll", "centrelink", "interest credit", "dividend"],
    "Cash": [" atm", "cash withdrawal", "cash out", "cashout", "eftpos cash"],  # before Eating Out: ATMs in pubs
    "Bills & Utilities": ["agl", "origin energy", "energyaustralia", "simply energy", "lumo", "sa water",
                          "sa power", "telstra", "optus", "vodafone", "tpg", "aussie broadband", "belong",
                          "amaysim", "boost mobile", "council", "insurance", "aami", "raa ", "allianz",
                          "budget direct", "youi", "bupa", "medibank", "hcf", "nib ", "rent", "real estate",
                          "strata", "mortgage", "loan", "latitude", "nimble", "afterpay", "zip pay", "bpay"],
    "Subscriptions": ["netflix", "spotify", "stan.com", "disney", "binge", "kayo", "youtube", "apple.com",
                      "itunes", "google one", "prime video", "amazon prime", "xbox", "playstation", "steam",
                      "nintendo", "patreon", "discord", "tradingview", "openai", "anthropic", "claude.ai", "microsoft", "adobe",
                      "anytime fitness", "revo fitness", "gym", "amznprime"],
    "Eating Out": ["uber eats", "ubereats", "uber *eats", "menulog", "doordash", "mcdonald", "kfc",
                   "hungry jack", "subway", "domino", "pizza", "guzman", "zambrero", "red rooster", "nando",
                   "grill'd", "oporto", "starbucks", "gloria jean", "bakery", "cafe", "coffee", "restaurant",
                   "pub ", "hotel", "sushi", "kebab"],
    "Transport & Fuel": ["bp ", "shell", "ampol", "caltex", "7-eleven", "7 eleven", "united petrol", "otr ",
                         "puma", "petrol", "coles express", "uber", "didi", "taxi", "adelaide metro", "rail", "metrocard", "parking",
                         "toll", "linkt", "rego", "service sa", "mechanic", "tyre", "repco", "supercheap",
                         "autobarn"],
    "Groceries": ["woolworths", "woolies", "coles", "aldi", "iga ", "foodland", "drakes", "costco",
                  "harris farm", "romeo", "foodworks", "butcher", "fruit"],
    "Health": ["chemist", "pharmacy", "priceline", "medical", "doctor", "dental", "dentist", "physio",
               "hospital", "pathology", "optometr", "specsavers"],
    "Shopping": ["amazon", "ebay", "kmart", "target", "big w", "jb hi", "harvey norman", "officeworks",
                 "bunnings", "myer", "david jones", "rebel", "temu", "shein", "good guys", "ikea"],
    "Entertainment": ["cinema", "hoyts", "palace nova", "wallis", "ticketek", "ticketmaster", "bowling",
                      "timezone", "bws", "dan murphy", "liquor", "first choice", "sportsbet", "ladbrokes"],
    "Fees": ["fee", "interest charged", "overdrawn", "overdraft"],
}
NOT_SPENDING = ("Income", "Transfers")

# Theme - neon game HUD
BG, PANEL, CARD, BORDER = "#07080f", "#0e1020", "#161a36", "#262b58"
FG, MUTED, ACCENT, GREEN, RED, GOLD, CYAN = "#eef1ff", "#7d84b2", "#ff2bd6", "#39ff88", "#ff3b6b", "#ffd23f", "#00e5ff"
COLOURS = ["#00e5ff", "#ff2bd6", "#ffd23f", "#39ff88", "#9d6bff", "#ff8a3d",
           "#3d8bff", "#ff3b6b", "#b8ff3d", "#3dffe0", "#ff6bd9", "#a0a8d0"]
FONT = "Bahnschrift"  # built into Windows 10/11

DATE_FMTS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %b %y", "%d-%b-%Y", "%d-%b-%y", "%d%b%y", "%d%b%Y")


def parse_date(s):
    s = s.strip().split(" ")[0] if re.match(r"\d{1,2}/\d{1,2}/\d{2,4} \d", s.strip()) else s.strip()
    for f in DATE_FMTS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass


def parse_amount(s):
    s = s.strip().upper().replace("$", "").replace(",", "").replace(" ", "")
    neg = (s.startswith("(") and s.endswith(")")) or s.endswith(("DR", "-"))
    s = s.strip("()").removesuffix("DR").removesuffix("CR").removesuffix("-")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    return -abs(float(s)) if neg else float(s)


def find_col(header, *words, avoid="$^"):
    for i, h in enumerate(header):
        if any(w in h.lower() for w in words) and not re.search(avoid, h, re.I):
            return i


def parse_csv(text):
    """Returns [{date, desc, amount}]. Handles headed exports (incl. separate debit/credit
    columns) and headerless ones like CommBank's: date, amount, description, balance."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    cols = {}
    if not any(parse_date(c) for c in rows[0]):  # first row is a header
        h = rows.pop(0)
        cols = dict(date=find_col(h, "date"),
                    desc=find_col(h, "description", "narrative", "details", "merchant", "payee",
                                  "transaction", "memo"),
                    amount=find_col(h, "amount", avoid="debit|credit|balance"),
                    debit=find_col(h, "debit", "withdrawal"),
                    credit=find_col(h, "credit", "deposit"))
    out = []
    for r in rows:
        cell = lambda k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else ""
        when = parse_date(cell("date")) if cols.get("date") is not None else next(
            (d for d in map(parse_date, r) if d), None)
        if not when:
            continue
        if cols.get("amount") is not None:
            amount = parse_amount(cell("amount"))
        elif cols.get("debit") is not None or cols.get("credit") is not None:
            amount = abs(parse_amount(cell("credit")) or 0) - abs(parse_amount(cell("debit")) or 0)
        else:  # headerless: first number after the date (balance comes later)
            amount = next((a for a in map(parse_amount, r) if a is not None), None)
        if amount is None:
            continue
        desc = cell("desc") or max((c for c in r if parse_amount(c) is None and not parse_date(c)),
                                   key=len, default="")
        out.append(dict(date=when, desc=" ".join(desc.split()), amount=amount))
    return out


MONEY = r"(?<![\d.])[-+]?\$?\d{1,3}(?:,\d{3})*\.\d{2}(?:\s?(?:CR|DR|Cr|Dr)(?![A-Za-z]))?(?!\d)"
DATE_TOKEN = r"\d{1,2}[A-Za-z]{3}\d{2,4}|\d{1,2}[ /.-](?:[A-Za-z]{3}|\d{1,2})(?:[ /.-](?:20)?\d{2}(?!\d))?"
LINE_DATE = re.compile(rf"({DATE_TOKEN})\s+(?:(?:{DATE_TOKEN})\s+)?(.*)")  # skips a 2nd "effective date" column
SKIP_LINE = re.compile(r"closing balance|current balance|carried forward|totals?\b|statement period", re.I)
SECTION = re.compile(r"(\d{6,})\s+([^$\d-][^$]*?)\s*(?:-?\$|$)")  # "200022222  Bonus Saver" under "ACCOUNT NO"
NOT_DESC = re.compile(r"page \d|e-\d+/s|account|date\b|statement|.*\(cont|.*balance", re.I)


def parse_pdf_text(text):
    """Pulls transactions out of a text-based PDF statement: lines that start with a date and hold
    an amount + running balance (in any order, description before or after). Debit vs credit comes
    from how the balance changes. Wrapped description lines are joined. Each row gets the account
    section it sits under, for PDFs that hold several accounts."""
    first = re.search(r"\b\d{1,2}[ /-](?:[A-Za-z]{3}|\d{1,2})[ /-]20\d{2}\b", text)
    year = (parse_date(first.group()) or date.today()).year if first else date.today().year
    out, prev_bal, last_month, section, wrap, want_section = [], None, None, None, 0, False
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        if re.match(r"account no\b", line, re.I):
            want_section, wrap = True, 0
            continue
        if want_section and (sec := SECTION.match(line)):
            section, prev_bal, want_section = sec.group(2), None, False
            continue
        if re.search(r"opening balance|brought forward", line, re.I):
            found = re.findall(MONEY, line)
            prev_bal, wrap = (parse_amount(found[-1]) if found else prev_bal), 0
            continue
        m = LINE_DATE.match(line)
        if not m:  # wrapped 2nd/3rd line of the previous description
            if wrap and not NOT_DESC.match(line):
                out[-1]["desc"] += " " + line
                wrap -= 1
            else:
                wrap = 0
            continue
        wrap = 0
        if SKIP_LINE.search(line):
            continue
        ds, rest = m.groups()
        spans = [(x.start(), x.end(), parse_amount(x.group()), x.group()) for x in re.finditer(MONEY, rest)]
        if not spans:
            continue
        pair = next(((x, y) for x, y in zip(spans, spans[1:]) if prev_bal is not None
                     and abs(abs(y[2] - prev_bal) - abs(x[2])) < 0.005), None)
        if pair:
            used, amount = pair, round(pair[1][2] - prev_bal, 2)
        else:  # ponytail: no balance to check against -> amount then balance, assume money out unless CR/+
            used = spans[-2:] if len(spans) >= 2 and not rest[spans[-1][1]:].strip() else spans[:2]
            amount = used[0][2] if re.search(r"^\+|CR$", used[0][3], re.I) else -abs(used[0][2])
        prev_bal = used[1][2] if len(used) == 2 else prev_bal
        for x in sorted(used, reverse=True):
            rest = rest[:x[0]] + " " + rest[x[1]:]
        desc = " ".join(rest.split())
        if not re.search("[A-Za-z]", desc):
            continue
        when = parse_date(ds)
        if not when:  # no year on the line, e.g. "01 Oct" (CommBank) - use the statement's year
            sep = "/" if "/" in ds else " "
            when = parse_date(f"{ds}{sep}{year}") or parse_date(f"{ds.replace('.', '/')}/{year}")
            if when and last_month and when.month < last_month:  # Dec -> Jan rollover
                year += 1
                when = when.replace(year=year)
        if not when:
            continue
        last_month = when.month
        out.append(dict(date=when, desc=desc, amount=amount, section=section))
        wrap = 2
    return out


def load_statement(path):
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        pages = PdfReader(path).pages
        return parse_pdf_text("\n".join(p.extract_text(extraction_mode="layout") or "" for p in pages))
    return parse_csv(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


PAY_PREFIX = re.compile(r"^(?:(?:visa|eftpos|debit card|card)\s+purchase|direct (?:debit|credit)|"
                        r"osko direct credit(?: osko)?|osko tfr to|ib tfr|pd dd-|osko)\s+(?:\(os\)\s+)?", re.I)


GENERIC_WORDS = {"dms", "transfer", "tfr", "trf", "to", "from", "osko"}


def merchant_name(desc):
    """Short shop/payee name for grouping: drops payment-type prefixes, card numbers and refs."""
    low = desc.lower()
    if re.search(r"\batm\b|cash withdrawal", low):
        return "ATM Withdrawal"
    if re.search(r"eftpos cash|cash ?out", low):
        return "Cash Out"
    if (own := re.search(r"\btfr\s+\d*(\d{4})\s+to\s+\d*(\d{4})", low)):
        return f"Own Transfer ..{own.group(1)} to ..{own.group(2)}"
    d = re.sub(r"\bOS Amt\b.*$", "", PAY_PREFIX.sub("", desc), flags=re.I)
    d = re.sub(r"^(?:sq|sp|lsp|zlr)\s*\*\s*", "", d, flags=re.I).replace("*", " ")  # Square etc. "SQ *SHOP"
    words = [w.strip(",.-") for w in d.split() if not re.search(r"\d{3,}", w)]
    words = [w for w in words if w and w.lower() not in GENERIC_WORDS]  # "DMS TRANSFER 123456 Rent" -> "Rent"
    return " ".join(words[:2]).title() or d.strip()[:28] or desc[:28]  # ponytail: first 2 words


def merge(txns, new, account):
    """Adds new rows to txns under `account`, skipping ones already loaded from an
    overlapping statement. Counts duplicates, so two identical same-day coffees both stay."""
    key = lambda t: (t["date"], t["amount"], t["desc"])
    have, seen, added = Counter(key(t) for t in txns if t["account"] == account), Counter(), 0
    for t in new:
        seen[key(t)] += 1
        if seen[key(t)] > have[key(t)]:
            txns.append(dict(t, account=account))
            added += 1
    return added


def categorise(desc, amount, rules):
    d, shop = f" {desc.lower()} ", None  # padded so short keywords like "bp " match at the ends
    for kw, cat in reversed(rules.items()):  # newest rule wins
        if kw.startswith("shop:"):  # made by dragging a shop: "shop:<name>" or "shop:<name>|in" / "|out"
            name, _, way = kw[5:].partition("|")
            shop = shop or merchant_name(desc).lower()
            if shop == name and way in ("", "in" if amount > 0 else "out"):
                return cat
        elif kw in d:
            return cat
    for cat, kws in CATEGORIES.items():
        if any(k in d for k in kws):
            return cat
    return "Income" if amount > 0 else "Other"  # ponytail: keyword matching; add rules for misses


STREAMING = ("netflix", "stan", "disney", "binge", "kayo", "prime video", "amznprime", "youtube", "paramount",
             "foxtel", "spotify", "apple.com")
DELIVERY = ("uber eats", "ubereats", "uber *eats", "menulog", "doordash")


def money(v):
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def insights(txns, income_month=None):
    """Plain-rules spending review. Returns [{kind, title, body, save}] (save = rough $/year), best first."""
    out, spend = [], [t for t in txns if t["amount"] < 0 and t["cat"] not in NOT_SPENDING]
    if not spend:
        return out
    months = sorted({t["date"].strftime("%Y-%m") for t in txns})
    n_months = max(1, len(months))
    by_shop = defaultdict(list)
    for t in spend:
        by_shop[merchant_name(t["desc"])].append(t)

    # recurring: shows up in 2+ months, about once a month, similar amount each time
    recurring = []
    for shop, rows in by_shop.items():
        rows.sort(key=lambda t: t["date"])
        ms = {t["date"].strftime("%Y-%m") for t in rows}
        amts = [-t["amount"] for t in rows]
        mid = sorted(amts)[len(amts) // 2]
        if len(ms) >= 2 and len(rows) <= len(ms) + 1 and max(amts) - min(amts) <= max(2, 0.25 * mid):
            recurring.append(dict(shop=shop, cat=rows[0]["cat"], first=amts[0], last=amts[-1],
                                  yearly=sum(amts) / len(ms) * 12, desc=rows[-1]["desc"].lower()))
    subs = sorted((r for r in recurring if r["cat"] in ("Subscriptions", "Entertainment", "Other", "Shopping")),
                  key=lambda r: -r["yearly"])
    bills = sorted((r for r in recurring if r not in subs), key=lambda r: -r["yearly"])
    if subs:
        total = sum(r["yearly"] for r in subs)
        lines = "\n".join(f"\u2022 {r['shop']}: {money(r['last'])}/mo  \u2192  {money(r['yearly'])}/yr" for r in subs[:8])
        out.append(dict(kind="cancel", save=subs[0]["yearly"], title=f"{len(subs)} regular charges cost you {money(total)} a year",
                        body=f"{lines}\n\nGo down this list and ask: did I use it last month? Cancel anything you "
                             f"haven't, you can always re-subscribe. Dropping just {subs[0]['shop']} saves "
                             f"{money(subs[0]['yearly'])}/yr."))
    streams = [r for r in recurring if any(k in r["desc"] or k in r["shop"].lower() for k in STREAMING)]
    if len(streams) >= 2:
        cheapest = min(streams, key=lambda r: r["yearly"])
        save = sum(r["yearly"] for r in streams) - cheapest["yearly"]
        out.append(dict(kind="cancel", save=save, title=f"{len(streams)} streaming services at once",
                        body=f"You're paying for {', '.join(r['shop'] for r in streams)}. Most people only watch one "
                             f"at a time. Keep one and rotate monthly (subscribe, binge, cancel) to save about "
                             f"{money(save)}/yr."))
    for r in recurring:
        if r["last"] > r["first"] * 1.05 and r["last"] - r["first"] >= 1:
            out.append(dict(kind="change", save=(r["last"] - r["first"]) * 12,
                            title=f"{r['shop']} went up {money(r['first'])} \u2192 {money(r['last'])}",
                            body=f"That's {money((r['last'] - r['first']) * 12)} more a year. Check if a cheaper plan "
                                 f"exists, or ring them and ask for the old price, it often works."))
    big_bills = [r for r in bills if r["yearly"] >= 600 and any(
        k in r["desc"] for k in ("insurance", "youi", "aami", "budget direct", "bupa", "medibank", "energy", "agl",
                                 "origin", "telstra", "optus", "vodafone", "broadband", "tpg"))]
    for r in big_bills[:3]:
        out.append(dict(kind="change", save=r["yearly"] * 0.15, title=f"Shop around: {r['shop']} ({money(r['yearly'])}/yr)",
                        body="Insurance, energy and phone/internet providers quietly raise prices on loyal customers. "
                             "Get two quotes before renewal and ask them to match, 10-20% savings are common."))

    fees = [t for t in spend if t["cat"] == "Fees" or re.search(r"overdraft|overdrawn|dishonour|late fee|account fee", t["desc"], re.I)]
    if fees:
        total = -sum(t["amount"] for t in fees)
        od = any(re.search("overdraft|overdrawn", t["desc"], re.I) for t in fees)
        out.append(dict(kind="warn", save=total / n_months * 12, title=f"{money(total)} in bank fees" + (" and overdraft interest" if od else ""),
                        body=("Your balance dipped below zero and the bank charged interest. Leaving a small buffer "
                              "(even $50) in accounts with direct debits stops this. " if od else "") +
                             "These are 100% avoidable money; check your account type for a fee-free option."))
    os_buys = [t for t in spend if re.search(r"\(os\)|os amt|usd|international", t["desc"], re.I)]
    if len(os_buys) >= 2:
        total = -sum(t["amount"] for t in os_buys)
        out.append(dict(kind="change", save=total * 0.03 / n_months * 12, title=f"{len(os_buys)} overseas purchases ({money(total)})",
                        body="Most bank cards add ~3% to foreign-currency purchases. A no-FX-fee card (e.g. Wise, "
                             "Revolut, Up, ING) used for these would save roughly " + money(total * 0.03 / n_months * 12) + "/yr."))
    deliv = [t for t in spend if any(k in t["desc"].lower() for k in DELIVERY)]
    if len(deliv) >= 3:
        total = -sum(t["amount"] for t in deliv)
        out.append(dict(kind="change", save=total / n_months * 6, title=f"Food delivery: {len(deliv)} orders, {money(total)}",
                        body=f"About {money(total / n_months)} a month. Delivery fees and menu mark-ups make the same "
                             f"meal ~30-40% dearer. Halving orders (pick-up or cooking instead) saves about "
                             f"{money(total / n_months * 6)}/yr."))
    small = [(shop, rows) for shop, rows in by_shop.items()
             if len(rows) >= 6 and all(-t["amount"] < 15 for t in rows) and shop not in [r["shop"] for r in recurring]]
    for shop, rows in sorted(small, key=lambda sr: sum(t["amount"] for t in sr[1]))[:2]:
        total = -sum(t["amount"] for t in rows)
        out.append(dict(kind="info", save=total / n_months * 6, title=f"Small but often: {shop} x{len(rows)}",
                        body=f"Each one is under $15 but together it's {money(total)} ({money(total / n_months)}/month). "
                             f"Not saying stop, just worth knowing."))
    if n_months >= 2:  # last month vs the average of earlier months, per category
        last = months[-1]
        per = defaultdict(lambda: defaultdict(float))
        for t in spend:
            per[t["cat"]][t["date"].strftime("%Y-%m")] -= t["amount"]
        for cat, by_m in per.items():
            before = [by_m.get(m, 0) for m in months[:-1]]
            avg, now = sum(before) / len(before), by_m.get(last, 0)
            if now > avg * 1.3 and now - avg >= 50:
                out.append(dict(kind="warn", save=0, title=f"{cat} jumped in {last}: {money(now)} vs usual {money(avg)}",
                                body="Expand the category and pick that month to see what drove it. One-off, or a new habit?"))
    out_total = -sum(t["amount"] for t in spend)
    if income_month:  # entered pay
        inc = income_month * n_months
        rate = 1 - out_total / inc
        out.append(dict(kind="info" if rate >= 0.2 else "warn", save=0,
                        title=f"You spend {min(999, round(100 * out_total / inc))}% of your pay "
                              f"({money(out_total / n_months)} of {money(income_month)} a month)",
                        body=("Nice, you're keeping " + f"{round(100 * rate)}% of your pay. " if rate > 0 else
                              "That's more than you earn, so the gap is coming from savings, cards or other accounts. ") +
                             "A common target is saving 20% (the 50/30/20 rule: 50% needs, 30% wants, 20% savings). "
                             + (f"20% of your pay is {money(income_month * 0.2)} a month." if rate < 0.2 else "")))
    else:
        inc = sum(t["amount"] for t in txns if t["cat"] == "Income")
    if inc and out_total > inc and not income_month:
        out.append(dict(kind="warn", save=0, title=f"Spending ({money(out_total)}) is more than income ({money(inc)})",
                        body="Over these statements more went out than came in. The cancel/change items above are the "
                             "quickest wins. Note: money from your other accounts shows as Transfers, not income."))
    order = {"warn": 0, "cancel": 1, "change": 2, "info": 3}
    return sorted(out, key=lambda i: (-i["save"], order[i["kind"]]))  # ponytail: rules, not a model; "Ask Claude" for depth


def claude_prompt(txns, income_month=None):
    """Plain-text summary (no account numbers) to paste into Claude for a deeper review."""
    months = sorted({t["date"].strftime("%Y-%m") for t in txns})
    cats, shops = defaultdict(float), defaultdict(lambda: [0.0, 0])
    for t in txns:
        cats[t["cat"]] += t["amount"]
        s = shops[(merchant_name(t["desc"]), t["cat"])]
        s[0] += t["amount"]
        s[1] += 1
    lines = [f"Here's my spending from {months[0]} to {months[-1]} ({len(months)} month(s)), Australian dollars.",
             "Please review it like a blunt but friendly financial coach: what should I cancel, cut back or change, "
             "and why? Give specific actions with estimated yearly savings, biggest first. Ask me questions if "
             "something's unclear (e.g. whether a transfer is rent)."]
    if income_month:
        lines.append(f"My take-home pay is about ${income_month:,.0f} a month.")
    lines += ["", "CATEGORY TOTALS (negative = money out):"]
    lines += [f"- {c}: {v:,.2f}" for c, v in sorted(cats.items(), key=lambda kv: kv[1])]
    lines += ["", "PAYEES (total, count, category):"]
    lines += [f"- {n} [{c}]: {v:,.2f} x{k}" for (n, c), (v, k) in sorted(shops.items(), key=lambda kv: kv[1][0])[:60]]
    return "\n".join(lines)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str))


