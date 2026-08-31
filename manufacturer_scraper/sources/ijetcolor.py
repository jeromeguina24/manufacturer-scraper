"""iJetColor (Printware) News & Events page (ijetcolor.com/news-events-1).

Squarespace marketing page, hand-maintained: external press-coverage links
("iJetColor in the News") and press-release PDF downloads. There is no list
feed, so the source extracts external links with a meaningful anchor text
(plus PDF downloads, whose title is derived from the file name).

The listing itself carries no dates, so each new item's publication date is
looked up lazily: press-release PDFs usually have a date in the file name,
and news links are dated from the (external) article page. Items whose date
cannot be determined stay undated and are imported regardless of min_year.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import (
    Article,
    absolute_url,
    normalize_url,
    parse_iso_utc,
    strip_html,
)
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://www.ijetcolor.com/news-events-1"

# Anchor text shorter than this is not a usable title (e.g. "Read more").
MIN_TITLE_LEN = 12
# Video embeds, event registrations and own-site links are not news items.
_SKIPPED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "wistia.com",
    "vimeo.com",
    "printingunited.com",
    "nvytes.co",
)


@dataclass
class IJetColorItem:
    title: str
    url: str
    categories: tuple[str, ...]


def _title_from_pdf_url(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"(?i)\.pdf$", "", name)
    name = name.replace("_", " ").replace("+", " ")
    return re.sub(r"\s+", " ", name).strip()


def _host_skipped(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in _SKIPPED_HOSTS)


# ---------------------------------------------------------------------------
# publication-date lookup
# ---------------------------------------------------------------------------

# Machine-readable date sources, most reliable first.
_DATE_META_SELECTORS = (
    'meta[property="article:published_time"]',
    'meta[property="og:article:published_time"]',
    'meta[name="date"]',
    'meta[name="publish-date"]',
    'meta[name="pubdate"]',
    'meta[name="sailthru.date"]',
    'meta[name="parsely-pub-date"]',
)
# Human-readable date holders, tried in order. `[class*=...]` is broad, but a
# candidate only counts if it actually parses to a date.
_DATE_TEXT_SELECTORS = (
    ".published",
    ".publish-date",
    ".published-date",
    ".post-date",
    ".article-date",
    ".entry-date",
    ".date",
    ".byline",
    "[class*='date']",
    "[class*='publish']",
)

_WRITTEN_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"\.?\s+(\d{1,2})\s*,\s*(20\d\d)\b",
    re.IGNORECASE,
)
_MONTH_NUMBERS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _parse_written_date(text: str) -> datetime | None:
    """Find a written 'Month DD, YYYY' date in `text`; None if absent/invalid."""
    match = _WRITTEN_DATE_RE.search(text or "")
    if not match:
        return None
    month = _MONTH_NUMBERS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        return datetime(int(match.group(3)), month, int(match.group(2)), tzinfo=UTC)
    except ValueError:  # e.g. "February 30, 2024"
        return None


def extract_article_date(html: str) -> datetime | None:
    """Best-effort publication date of a news article page (UTC)."""
    soup = BeautifulSoup(html, "lxml")
    for selector in _DATE_META_SELECTORS:
        tag = soup.select_one(selector)
        if tag is not None and tag.get("content"):
            parsed = parse_iso_utc(tag["content"])
            if parsed:
                return parsed
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text() or ""
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', text)
        if match:
            parsed = parse_iso_utc(match.group(1))
            if parsed:
                return parsed
    for tag in soup.find_all("time", attrs={"datetime": True}):
        parsed = parse_iso_utc(tag["datetime"])
        if parsed:
            return parsed
    for selector in _DATE_TEXT_SELECTORS:
        for element in soup.select(selector):
            parsed = _parse_written_date(element.get_text(" ", strip=True))
            if parsed:
                return parsed
    return _parse_written_date((soup.body or soup).get_text(" ", strip=True))


def _date_from_pdf_url(url: str) -> datetime | None:
    """Extract a date embedded in a press-release file name, if any."""
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    # ISO-ish first (2026-07-20), then US order (7-20-2026), then a bare year.
    match = re.search(r"(20\d\d)[-._](\d{1,2})[-._](\d{1,2})", name)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12:
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                pass
    match = re.search(r"(\d{1,2})[-._](\d{1,2})[-._](20\d\d)", name)
    if match:
        month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12:
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                pass
    match = re.search(r"(20\d\d)", name)
    if match:
        return datetime(int(match.group(1)), 1, 1, tzinfo=UTC)
    return None


def _date_from_pdf_content(data: bytes) -> datetime | None:
    """Extract the embedded creation/modification date from raw PDF bytes."""
    for key in (b"/CreationDate", b"/ModDate"):
        match = re.search(key + rb"\s*\(D:(\d{4})(\d{2})(\d{2})", data or b"")
        if not match:
            continue
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12:
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                continue
    return None


def parse_ijetcolor_items(html: str, base_url: str = LIST_URL) -> list[IJetColorItem]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("main") or soup.body
    items: list[IJetColorItem] = []
    seen: set[str] = set()

    for anchor in main.find_all("a", href=True) if main is not None else []:
        url = absolute_url(anchor["href"], base_url)
        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            continue
        host = parts.netloc.lower()
        if host.endswith("ijetcolor.com") or _host_skipped(host):
            continue

        text = strip_html(anchor.get_text())
        is_pdf = parts.path.lower().endswith(".pdf")
        if is_pdf:
            # Generic anchors like "Download the press release" carry no
            # information; the file name is the better title then.
            if len(text) < MIN_TITLE_LEN or text.lower().startswith("download"):
                title = _title_from_pdf_url(url)
            else:
                title = text
            categories = ("Press Releases",)
        else:
            if len(text) < MIN_TITLE_LEN:
                continue
            title = text
            categories = ("In The News",)
        if not title:
            continue

        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        items.append(IJetColorItem(title=title, url=url, categories=categories))
    return items


class IJetColorSource(BaseSource):
    name = "ijetcolor"
    manufacturer = "iJetColor"

    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        response = fetch(
            self.session,
            LIST_URL,
            retries=self.settings.scraping.retries,
            delay_s=self.settings.scraping.request_delay_s,
        )
        for item in parse_ijetcolor_items(response.text):
            # Dates live on the linked pages / in the file names, not on the
            # listing. Look them up only for items we have not imported yet, so
            # min_year can filter out stale coverage without re-fetching the
            # external pages on every scheduled run.
            published = None
            if not is_seen(item.url):
                published = self._lookup_published(item)
            yield Article(
                manufacturer=self.manufacturer,
                url=item.url,
                title=item.title,
                published=published,
                categories=item.categories,
            )

    def _lookup_published(self, item: IJetColorItem) -> datetime | None:
        """Best-effort publication date; None (undated) on any failure."""
        try:
            if item.url.lower().endswith(".pdf"):
                return self._date_from_pdf(item)
            response = fetch(
                self.session,
                item.url,
                retries=1,
                delay_s=self.settings.scraping.request_delay_s,
            )
            return extract_article_date(response.text)
        except Exception as exc:  # noqa: BLE001 - dating must never abort the run
            log.warning("Could not determine date for %s (%s)", item.url, exc)
            return None

    def _date_from_pdf(self, item: IJetColorItem) -> datetime | None:
        """Date from the file name first, else from the PDF's own metadata."""
        dated = _date_from_pdf_url(item.url)
        if dated:
            return dated
        response = fetch(
            self.session,
            item.url,
            retries=1,
            delay_s=self.settings.scraping.request_delay_s,
        )
        return _date_from_pdf_content(response.content)
