"""Normalized article model and shared parsing helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Article:
    """A normalized news item scraped from a manufacturer newsroom."""

    manufacturer: str
    url: str  # canonical original URL; dedupe key and linkback target
    title: str
    published: datetime | None  # tz-aware (UTC) when known
    categories: tuple[str, ...]
    summary: str | None = None  # plain text, HTML stripped
    image_url: str | None = None  # absolute URL, optional
    fetched_at: datetime = field(default_factory=utcnow)

    @property
    def dedupe_key(self) -> str:
        return self.url


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def strip_html(html: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    if not html:
        return ""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.parts)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str, fmt: str, *, default_tz: timezone = UTC) -> datetime | None:
    """Parse a date string; returns None if unparsable. Naive dates get default_tz."""
    if not value:
        return None
    try:
        # Naive result is intentional: a missing tzinfo gets default_tz below.
        dt = datetime.strptime(value.strip(), fmt)  # noqa: DTZ007
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def parse_iso_utc(value: str) -> datetime | None:
    """Parse ISO-8601 (e.g. WordPress `date` fields); naive values are UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_url(url: str) -> str:
    """Canonical form used as the dedupe key: lowercase scheme/host, query
    stripped (drops utm_* noise), no trailing slash. Fragments are KEPT —
    some newsrooms (Konica investor links) use #anchors as the identity."""
    parts = urlparse(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunparse(
        (parts.scheme.lower(), parts.netloc.lower(), path, "", "", parts.fragment)
    )


def absolute_url(href: str, base: str) -> str:
    return urljoin(base, href.strip())


def slugify(text: str, max_len: int = 180) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0].rstrip("-")
    return text


def truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
