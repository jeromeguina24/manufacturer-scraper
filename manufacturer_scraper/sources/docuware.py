"""DocuWare product-news blog (start.docuware.com/blog/product-news).

HubSpot blog with a server-rendered listing: `div.blog-listing.past-article`
cards with title, link, "Published: Aug 12, 2026" date, teaser text and a
teaser image in an inline `background:url(...)` style. Pagination is
`/page/N` until 404.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, absolute_url, parse_date, strip_html
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://start.docuware.com/blog/product-news"
PAGE_URL = LIST_URL + "/page/{page}"
_BG_IMAGE_RE = re.compile(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)')
_PUBLISHED_PREFIX_RE = re.compile(r"^published\s*:\s*", re.IGNORECASE)


@dataclass
class DocuWareListItem:
    date: str
    title: str
    url: str
    summary: str | None
    image_url: str | None


def parse_docuware_list(html: str, base_url: str = LIST_URL) -> list[DocuWareListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[DocuWareListItem] = []
    for card in soup.select("div.blog-listing"):
        title_link = card.select_one("h4 a")
        if title_link is None or not title_link.get("href"):
            continue
        title = strip_html(title_link.get_text())
        if not title:
            continue

        date = ""
        date_el = card.select_one("span.blog-post-date")
        if date_el is not None:
            date = _PUBLISHED_PREFIX_RE.sub("", strip_html(date_el.get_text())).strip()

        summary = None
        text_el = card.select_one("p")
        if text_el is not None:
            more_link = text_el.select_one("a.more-link")
            if more_link is not None:
                more_link.decompose()
            if strip_html(text_el.get_text()):
                summary = strip_html(text_el.get_text())

        image_url = None
        image_link = card.select_one("a.past-article-image")
        if image_link is not None:
            style = image_link.get("style") or ""
            match = _BG_IMAGE_RE.search(style)
            if match:
                image_url = absolute_url(match.group(1), base_url)

        items.append(
            DocuWareListItem(
                date=date,
                title=title,
                url=absolute_url(title_link["href"], base_url),
                summary=summary,
                image_url=image_url,
            )
        )
    return items


class DocuWareSource(BaseSource):
    name = "docuware"
    manufacturer = "DocuWare"

    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        delay = self.settings.scraping.request_delay_s
        retries = self.settings.scraping.retries

        page = 1
        while max_pages is None or page <= max_pages:
            url = LIST_URL if page == 1 else PAGE_URL.format(page=page)
            response = fetch(
                self.session, url, retries=retries, delay_s=delay, acceptable=(200, 404)
            )
            if response.status_code == 404:
                break
            items = parse_docuware_list(response.text, base_url=url)
            if not items:
                break

            for item in items:
                yield Article(
                    manufacturer=self.manufacturer,
                    url=item.url,
                    title=item.title,
                    published=parse_date(item.date, "%b %d, %Y"),
                    categories=("Product News",),
                    summary=item.summary,
                    image_url=item.image_url,
                )
            if all(is_seen(item.url) for item in items):
                log.debug("docuware: page %d fully seen — stopping", page)
                break
            page += 1
