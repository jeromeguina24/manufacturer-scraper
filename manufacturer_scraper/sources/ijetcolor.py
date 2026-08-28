"""iJetColor (Printware) News & Events page (ijetcolor.com/news-events-1).

Squarespace marketing page, hand-maintained: external press-coverage links
("iJetColor in the News") and press-release PDF downloads. There is no list
feed, so the source extracts external links with a meaningful anchor text
(plus PDF downloads, whose title is derived from the file name). Items carry
no dates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, absolute_url, normalize_url, strip_html
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
            yield Article(
                manufacturer=self.manufacturer,
                url=item.url,
                title=item.title,
                published=None,
                categories=item.categories,
            )
