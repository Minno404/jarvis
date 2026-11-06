"""Looking things up on the web, free (no search account): DuckDuckGo's plain results page, and reading a page.

Any brain can use these, and they're what the local AI uses for the internet.
"""
import html
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
S = {"type": "string"}


def _get(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


def _text(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def results(page):
    """DuckDuckGo's HTML results -> [{title, url, snippet}]."""
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                         page, re.S):
        url = html.unescape(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        url = q.get("uddg", [url])[0]  # DuckDuckGo's redirect -> the real address
        if "duckduckgo.com/y.js" in url:  # adverts
            continue
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', m.group(3), re.S)
        out.append({"title": _text(m.group(2)), "url": url, "snippet": _text(snip.group(1)) if snip else ""})
    return out


def web_search(query, n=6):
    """Search the web; the top results with a line from each."""
    page = _get("https://html.duckduckgo.com/html/", urllib.parse.urlencode({"q": query, "kl": "au-en"}).encode())
    found = results(page)[:max(1, min(10, int(n)))]
    return {"results": found} if found else {"error": "No results (or the search was blocked). Try other words."}


def read_page(url, max_chars=6000):
    """The readable text of a web page (scripts, menus and styling stripped)."""
    if not re.match(r"https?://", url):
        return {"error": "Give a full web address (https://...)"}
    page = _get(url)
    title = _text((re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I) or [None, ""])[1])
    body = re.sub(r"<(script|style|noscript|svg|nav|footer|header|form)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    body = re.sub(r"</(p|div|li|h\d|tr|br)>", "\n", body, flags=re.I)
    lines = [_text(x) for x in body.split("\n")]
    text = "\n".join(x for x in lines if len(x) > 30)
    return {"title": title, "url": url, "text": text[:int(max_chars)], "cut": len(text) > int(max_chars)}


FUNCS = {"web_search": web_search, "read_page": read_page}
TOOLS = [
    {"name": "web_search", "description": "Search the web (free, DuckDuckGo) for anything current: news, prices, how "
     "to fix something, opening hours. Then read_page the best result if the snippets aren't enough. Say where it "
     "came from.", "input_schema": {"type": "object", "required": ["query"], "properties": {
         "query": S, "n": {"type": "integer"}}}},
    {"name": "read_page", "description": "Read a web page's text (from web_search, or a link he gives).",
     "input_schema": {"type": "object", "required": ["url"], "properties": {"url": S}}},
]


def selftest():
    sample = ('<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2F'
              'example.com%2Fa&amp;rut=x">Example <b>A</b></a><a class="result__snippet" href="#">First &amp; best'
              '</a></div><div><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></div>'
              '<div><a class="result__a" href="https://b.org/">B site</a></div>')
    r = results(sample)
    assert r[0] == {"title": "Example A", "url": "https://example.com/a", "snippet": "First & best"}, r
    assert [x["url"] for x in r] == ["https://example.com/a", "https://b.org/"]
    assert "error" in read_page("not a link")
    print("web self-test passed")


if __name__ == "__main__":
    selftest()
