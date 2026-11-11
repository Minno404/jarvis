"""The autopilot's chart watcher: free, no AI. Every 5-minute candle close it checks each pair for a setup, and only
then are the brains asked (so they're asked about real moments, not every 15 minutes, and it costs far fewer tokens).

A setup ("trigger") on the 5-minute candle that just closed, near a key level:
- Key levels: H1 swing highs and lows (a high or low with 3 lower highs / higher lows either side) from the last 4
  days, and yesterday's high and low. Levels closer than 0.3 H1 ATR are merged.
- Trend: H1 EMA 20 above EMA 50 with price above EMA 50 = up; the reverse = down; else range.
- Breakout: in an uptrend, a candle closing above a level the previous candle closed below, with a real body
  (at least half its range); the reverse in a downtrend.
- Rejection: price dips to within 0.25 M15 ATR of a level below and closes back above with a long lower wick
  (close in the top 40% of the candle) in an uptrend or range = support holding; the reverse at resistance.
The same pair and level isn't asked about again for 2 hours.
Candles are [time, open, high, low, close].
"""


def ema(values, n):
    k, out = 2 / (n + 1), None
    for v in values:
        out = v if out is None else out + k * (v - out)
    return out


def atr(c, n=14):
    trs = [max(h - lo, abs(h - p[4]), abs(lo - p[4])) for p, (_t, _o, h, lo, _c) in zip(c, c[1:])][-n:]
    return sum(trs) / len(trs) if trs else 0.0


def trend(h1):
    closes = [x[4] for x in h1]
    if len(closes) < 50:
        return "range"
    fast, slow, last = ema(closes, 20), ema(closes, 50), closes[-1]
    return "up" if fast > slow and last > slow else "down" if fast < slow and last < slow else "range"


def levels(h1, d1):
    """Key prices: H1 swing highs/lows from the last 96 H1 candles, yesterday's high and low; close ones merged."""
    h = h1[-96:]
    out = []
    for i in range(3, len(h) - 3):
        if all(h[i][2] > h[j][2] for j in range(i - 3, i + 4) if j != i):
            out.append(h[i][2])
        if all(h[i][3] < h[j][3] for j in range(i - 3, i + 4) if j != i):
            out.append(h[i][3])
    if len(d1) >= 2:
        out += [d1[-2][2], d1[-2][3]]
    gap = 0.3 * atr(h1)
    merged = []
    for v in sorted(out):
        if merged and v - merged[-1][-1] <= gap:
            merged[-1].append(v)
        else:
            merged.append([v])
    return [sum(g) / len(g) for g in merged]


def trigger(m5, h1, d1, atr_m15, lv=None, tr=None):
    """A setup on the last closed 5-minute candle -> {kind, side, level, trend, text}, or None. lv / tr: the key
    levels and trend if already worked out (they only change each hour; the test run reuses them)."""
    if len(m5) < 2 or not h1:
        return None
    p, b = m5[-2], m5[-1]
    _t, o, hi, lo, c = b
    rng = hi - lo
    if rng <= 0:
        return None
    tr = tr or trend(h1)
    for lv in (levels(h1, d1) if lv is None else lv):
        if tr == "up" and p[4] <= lv < c and abs(c - o) >= 0.5 * rng:
            return {"kind": "breakout", "side": "buy", "level": lv, "trend": tr,
                    "text": f"5-minute close broke above the key level {lv:g} in an H1 uptrend"}
        if tr == "down" and p[4] >= lv > c and abs(c - o) >= 0.5 * rng:
            return {"kind": "breakout", "side": "sell", "level": lv, "trend": tr,
                    "text": f"5-minute close broke below the key level {lv:g} in an H1 downtrend"}
        near = 0.25 * atr_m15
        if tr in ("up", "range") and lo <= lv + near and c > lv and c >= hi - 0.4 * rng and o > lv - near:
            return {"kind": "rejection", "side": "buy", "level": lv, "trend": tr,
                    "text": f"price dipped to support {lv:g} and closed back above with a long lower wick (H1 {tr})"}
        if tr in ("down", "range") and hi >= lv - near and c < lv and c <= lo + 0.4 * rng and o < lv + near:
            return {"kind": "rejection", "side": "sell", "level": lv, "trend": tr,
                    "text": f"price pushed up to resistance {lv:g} and closed back below with a long upper wick (H1 {tr})"}
    return None


class Cooldown:
    """Don't ask about the same pair and level twice within `hours`."""

    def __init__(self, hours=2.0):
        self.hours, self.seen = hours, {}

    def ok(self, symbol, level, now, step):
        key = (symbol, round(level / step) if step else level)
        if now - self.seen.get(key, -1e12) < self.hours * 3600:
            return False
        self.seen[key] = now
        return True


def currencies(symbol):
    """The currencies whose news moves a pair: gold follows USD; a forex pair, both of its currencies."""
    s = symbol.upper()
    return {"USD"} if s.startswith(("XAU", "XAG", "GOLD")) else {s[:3], s[3:6]}


if __name__ == "__main__":
    up = [[i * 3600, 100 + i * 0.5, 100.4 + i * 0.5, 99.8 + i * 0.5, 100.3 + i * 0.5] for i in range(60)]
    up[50][2] = 140  # a swing high at 140
    assert trend(up) == "up" and any(abs(v - 140) < 0.01 for v in levels(up, []))
    m5 = [[0, 139.0, 139.6, 138.9, 139.5], [300, 139.6, 141.0, 139.5, 140.9]]
    t = trigger(m5, up, [], 1.0)
    assert t and t["kind"] == "breakout" and t["side"] == "buy" and abs(t["level"] - 140) < 0.01, t
    # rejection off support in an uptrend: dips to 125.2 support area, closes high
    lvl = levels(up, [[0, 0, 200, 125.0, 0], [1, 0, 0, 0, 0]])
    assert any(abs(v - 125.0) < 0.01 for v in lvl)
    m5 = [[0, 126, 126.2, 125.8, 126.0], [300, 125.6, 126.1, 125.1, 126.0]]
    t = trigger(m5, up, [[0, 0, 200, 125.0, 0], [1, 0, 0, 0, 0]], 1.0)
    assert t and t["kind"] == "rejection" and t["side"] == "buy", t
    assert not trigger([[0, 130, 130.2, 129.9, 130.1], [300, 130.1, 130.3, 130.0, 130.2]], up, [], 1.0)
    cd = Cooldown(2)
    assert cd.ok("XAUUSD", 140, 0, 0.1) and not cd.ok("XAUUSD", 140.01, 3600, 0.1) and cd.ok("XAUUSD", 140, 7300, 0.1)
    assert currencies("GBPJPY") == {"GBP", "JPY"} and currencies("XAUUSD.a") == {"USD"}
    print("watcher self-test passed")
