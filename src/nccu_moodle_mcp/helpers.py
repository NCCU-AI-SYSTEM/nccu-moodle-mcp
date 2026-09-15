"""Small shared helpers used across tool modules."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

# NCCU is UTC+8; Moodle returns unix timestamps.
TAIPEI = timezone(timedelta(hours=8))


def fmt_time(epoch) -> str | None:
    """Unix timestamp -> 'YYYY-MM-DD HH:MM' in Taipei time, or None if unset (0)."""
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), TAIPEI).strftime("%Y-%m-%d %H:%M")


def strip_html(html: str | None) -> str:
    """Strip HTML to plain text (for summaries / feedback / messages)."""
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def browser_file_url(url: str | None) -> str | None:
    """Turn a Web-Services file URL (…/webservice/pluginfile.php/…) into the plain
    session form (…/pluginfile.php/…). WS responses rewrite file URLs to the
    /webservice variant, which needs a token; the plain form opens in a
    logged-in browser (session cookie). Non-pluginfile URLs are unchanged."""
    if not url:
        return url
    return url.replace("/webservice/pluginfile.php", "/pluginfile.php")


def term_code(text: str | None) -> str:
    """NCCU term code = the leading 4 digits of a course short/full name (e.g. '1151')."""
    m = re.match(r"\s*(\d{4})", text or "")
    return m.group(1) if m else ""


def select_by_sem(items: list[dict], sem: str | None, term_key: str = "semester") -> list[dict]:
    """Filter items (each carrying a term code under `term_key`) by `sem`:
    None/''/'latest' -> only the highest (latest) term; 'all' -> everything;
    otherwise -> exact term-code match."""
    want = (sem or "").strip().lower()
    terms = [it[term_key] for it in items if it.get(term_key)]
    latest = max(terms) if terms else ""
    if want in ("", "latest"):
        return [it for it in items if it.get(term_key) == latest]
    if want == "all":
        return list(items)
    return [it for it in items if (it.get(term_key) or "").lower() == want]
