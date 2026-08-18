"""FP (Francotyp-Postalia) USA newsroom — single-page press release list.

The whole archive (~100 items, reverse-chronological) is rendered on one page:
`div.PressReleaseOverview__single` cards with title, link, teaser image,
summary text, category pills and a `<time dateTime="...">` ISO timestamp.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, absolute_url, parse_iso_utc, strip_html
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://www.fp-usa.com/newsroom"


@dataclass
class FpListItem:
    date: str
    title: str
    url: str
    categories: tuple[str, ...]
    summary: str | None
    image_url: str | None


def parse_fp_list(html: str, base_url: str = LIST_URL) -> list[FpListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[FpListItem] = []
    for card in soup.select("div.PressReleaseOverview__single"):
        title_link = card.select_one("h3.card-title a")
        if title_link is None or not title_link.get("href"):
            continue
        title = strip_html(title_link.get_text())
        if not title:
            continue

        time_el = card.select_one("time.blog-timeline--badge")
        # HTML attributes are case-insensitive; BS4 lowercases `dateTime`.
        date = (time_el.get("datetime") or "").strip() if time_el is not None else ""

        categories = tuple(
            strip_html(pill.get_text())
            for pill in card.select(".PressReleaseOverview__single__details ul.nav li a")
            if strip_html(pill.get_text())
        )

        summary = None
        text_el = card.select_one("p.card-text")
        if text_el is not None and strip_html(text_el.get_text()):
            summary = strip_html(text_el.get_text())

        image_url = None
        img = card.select_one("img")
        if img is not None and (img.get("src") or img.get("data-src")):
            image_url = absolute_url(img.get("src") or img.get("data-src"), base_url)

        items.append(
            FpListItem(
                date=date,
                title=title,
                url=absolute_url(title_link["href"], base_url),
                categories=categories or ("FP News",),
                summary=summary,
                image_url=image_url,
            )
        )
    return items


class FPSource(BaseSource):
    name = "fp"
    manufacturer = "FP"

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
        for item in parse_fp_list(response.text):
            yield Article(
                manufacturer=self.manufacturer,
                url=item.url,
                title=item.title,
                published=parse_iso_utc(item.date),
                categories=item.categories,
                summary=item.summary,
                image_url=item.image_url,
            )
