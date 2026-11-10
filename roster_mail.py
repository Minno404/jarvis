"""Roster from Gmail: Jarvis checks his Gmail for the email that carries his roster, downloads it, and pulls out the
text, so the brain can find his name and save his shifts (shifts.save_shifts).

Set up in Settings > Roster email: his Gmail address, a Google app password (myaccount.google.com/apppasswords,
needs 2-Step Verification; it only reads mail, and can be revoked there any time), the sender's address (whoever
emails the roster) and his name as the roster shows it. Kept in roster_mail.json on this PC, never sent to any AI.
Reading uses Gmail's IMAP, read-only (nothing is marked, moved or deleted).
"""
import datetime
import email
import imaplib
import io
import re
from email.header import decode_header
from pathlib import Path

import features

CONF = "roster_mail.json"
HERE = Path(__file__).resolve().parent
KEEP = HERE / "rosters"  # the downloaded roster files


def conf():
    return features._load(CONF, {})


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def due(now=None):
    """The weekly check: his chosen day, from 9 am, and not done yet today."""
    c, now = conf(), now or datetime.datetime.now()
    day = c.get("check_day", "")
    return (day in DAYS and DAYS.index(day) == now.weekday() and now.hour >= 9
            and c.get("last_check") != now.date().isoformat())


def checked(now=None):
    c = conf()
    c["last_check"] = (now or datetime.datetime.now()).date().isoformat()
    features._save(CONF, c)


def roster_email_settings(gmail=None, app_password=None, sender=None, name=None, check_day=None):
    """Save the roster email settings (any left out stay as they were). Returns them without the password.
    check_day: the weekday Jarvis looks for a new roster and loads it ('' for never)."""
    c = conf()
    if check_day is not None:
        c["check_day"] = str(check_day).lower() if str(check_day).lower() in DAYS else ""
    for k, v in (("gmail", gmail), ("sender", sender), ("name", name)):
        if v is not None:
            c[k] = str(v).strip()
    if app_password:
        c["app_password"] = re.sub(r"\s+", "", str(app_password))  # Google shows it in groups of four
    features._save(CONF, c)
    return public()


def public():
    c = conf()
    return {"gmail": c.get("gmail", ""), "sender": c.get("sender", ""), "name": c.get("name", ""),
            "check_day": c.get("check_day", ""),
            "password_saved": bool(c.get("app_password")), "last_uid": c.get("last_uid")}


def _text(part):
    raw = part.get_payload(decode=True) or b""
    return raw.decode(part.get_content_charset() or "utf-8", errors="replace")


def _pdf_text(data):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def _sheet_text(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"[sheet {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            if any(c is not None for c in row):
                out.append(" | ".join("" if c is None else str(c) for c in row))
    return "\n".join(out)


def _name(s):
    parts = []
    for b, enc in decode_header(s or ""):
        parts.append(b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b)
    return "".join(parts)


def _connect(c):
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    m.login(c["gmail"], c["app_password"])
    for box in ('"[Gmail]/All Mail"', '"[Google Mail]/All Mail"', "INBOX"):  # (UK and Australian accounts say Google Mail)
        if m.select(box, readonly=True)[0] == "OK":
            return m
    raise OSError("couldn't open the mailbox")


def _latest(m, sender):
    typ, data = m.uid("search", None, "FROM", f'"{sender}"')
    uids = (data[0] or b"").split()
    return uids[-1].decode() if uids else None


def check_new():
    """Is there a roster email newer than the last one loaded? (no AI, quick) -> uid or None."""
    c = conf()
    if not (c.get("gmail") and c.get("app_password") and c.get("sender")):
        return None
    m = _connect(c)
    try:
        uid = _latest(m, c["sender"])
    finally:
        m.logout()
    return uid if uid and uid != c.get("last_uid") else None


def get_roster():
    """Download the newest roster email and return its contents for the brain to read (attachments as text: PDF,
    Excel, CSV; pictures saved for the Read tool)."""
    c = conf()
    missing = [k for k, label in (("gmail", "Gmail address"), ("app_password", "Google app password"),
                                  ("sender", "the roster sender's address"), ("name", "his name on the roster"))
               if not c.get(k)]
    if missing:
        return {"error": "Roster email isn't set up: Settings > Roster email needs " + ", ".join(missing) + "."}
    try:
        m = _connect(c)
    except imaplib.IMAP4.error as e:
        return {"error": f"Gmail refused the login ({e}). Check the address and the app password "
                         "(myaccount.google.com/apppasswords)."}
    except OSError as e:
        return {"error": f"Couldn't reach Gmail: {e}"}
    try:
        uid = _latest(m, c["sender"])
        if not uid:
            return {"error": f"No emails from {c['sender']} in this Gmail."}
        typ, data = m.uid("fetch", uid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
    finally:
        m.logout()
    KEEP.mkdir(parents=True, exist_ok=True)
    texts, pictures, files = [], [], []
    for part in msg.walk():
        kind, fn = part.get_content_type(), part.get_filename()
        data = part.get_payload(decode=True) if not part.is_multipart() else None
        if not data:
            continue
        if fn:
            fn = re.sub(r"[^\w.\- ]", "_", _name(fn))[:80]
            (KEEP / fn).write_bytes(data)
            files.append(fn)
            low = fn.lower()
            try:
                if low.endswith(".pdf"):
                    texts.append(f"[attachment {fn}]\n" + _pdf_text(data))
                elif low.endswith((".xlsx", ".xlsm")):
                    texts.append(f"[attachment {fn}]\n" + _sheet_text(data))
                elif low.endswith((".csv", ".txt")):
                    texts.append(f"[attachment {fn}]\n" + data.decode("utf-8", errors="replace"))
                elif low.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    pictures.append(str(KEEP / fn))
            except ImportError as e:
                texts.append(f"[attachment {fn}: can't read this kind of file here ({e.name} isn't installed)]")
            except Exception as e:
                texts.append(f"[attachment {fn}: couldn't read it ({type(e).__name__})]")
        elif kind == "text/plain":
            texts.append("[email text]\n" + _text(part))
        elif kind == "text/html" and not any(t.startswith("[email text]") for t in texts):
            texts.append("[email text]\n" + re.sub(r"<[^>]+>", " ", _text(part)))
    c["last_uid"] = uid
    features._save(CONF, c)
    body = "\n\n".join(texts)
    return {"subject": _name(msg.get("Subject")), "sent": _name(msg.get("Date")), "name_on_roster": c["name"],
            "files": files, "pictures_to_read": pictures, "text": body[:20000],
            "next": (f"Find every shift for {c['name']} (only that person's row or entries; the roster may list "
                     "others) and save them with save_shifts in one call, then my_shifts. Work out the dates from the "
                     "roster's week and the email's date. Pictures: read them with the Read tool first.")}


FUNCS = {"get_roster": get_roster, "roster_email_settings": roster_email_settings}
S = {"type": "string"}
TOOLS = [{"name": "get_roster", "description": (
    "Get his newest roster from his Gmail ('get my roster', 'check my roster email', 'load the new roster'): downloads "
    "the latest email from the roster sender he set up and returns its text and attachments (PDF/Excel read as text, "
    "pictures as files to Read). Then find his name's shifts and save them with save_shifts."),
    "input_schema": {"type": "object", "properties": {}}}]


def selftest():
    import tempfile
    real = features.HERE
    features.HERE = Path(tempfile.mkdtemp())
    try:
        assert get_roster()["error"].startswith("Roster email isn't set up")
        r = roster_email_settings(gmail="h@gmail.com", app_password="abcd efgh ijkl mnop", sender="boss@shop.com", name="Halen")
        assert r["password_saved"] and "app_password" not in r and conf()["app_password"] == "abcdefghijklmnop"
        msg = email.message_from_string("Subject: =?utf-8?q?Roster_w/c_17_Nov?=\n\nhi")
        assert _name(msg.get("Subject")) == "Roster w/c 17 Nov"
        roster_email_settings(check_day="Wednesday")
        wed = datetime.datetime(2026, 11, 11, 10)  # a Wednesday
        assert due(wed) and not due(wed.replace(hour=8)) and not due(wed + datetime.timedelta(days=1))
        checked(wed)
        assert not due(wed)
        print("roster mail self-test passed")
    finally:
        features.HERE = real


if __name__ == "__main__":
    selftest()
