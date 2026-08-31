"""Predictive InSight — "In The Press" page (predictive-insight.com).

A hand-maintained list of press coverage. Each entry is a sequence of sibling
rows in document order: an <h1> title, a "Month, YYYY" date paragraph and a
"Read Here" button linking out to the article (often a PDF). Entries are
grouped by walking those markers in document order.
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

LIST_URL = "https://predictive-insight.com/pages/in-the-press/"
DATE_RE = re.compile(r"^[A-Z][a-z]+\s*,?\s*\d{4}$")


@dataclass
class PressListItem:
    title: str
    date: str
    url: str


def parse_press_list(html: str, base_url: str = LIST_URL) -> list[PressListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[PressListItem] = []
    pending_title: str | None = None
    pending_date = ""

    markers = soup.select(
        "div.nectar-responsive-text h1, div.nectar-responsive-text p, a.nectar-button"
    )
    for el in markers:
        if el.name == "h1":
            pending_title = strip_html(el.get_text()) or None
            pending_date = ""
        elif el.name == "p":
            text = strip_html(el.get_text())
            if DATE_RE.match(text):
                pending_date = text
        else:  # a.nectar-button
            href = (el.get("href") or "").strip()
            if not href or href.startswith("#") or not pending_title:
                continue
            items.append(
                PressListItem(
                    title=pending_title,
                    date=pending_date,
                    url=absolute_url(href, base_url),
                )
            )
            pending_title = None
            pending_date = ""
    return items


def parse_press_date(value: str):
    """'July, 2024' (day unknown) -> first of the month, UTC."""
    for fmt in ("%B, %Y", "%B %Y"):
        parsed = parse_date(value, fmt)
        if parsed is not None:
            return parsed
    return None


class PredictiveInsightSource(BaseSource):
    name = "predictive_insight"
    manufacturer = "Predictive InSight"

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
        for item in parse_press_list(response.text):
            yield Article(
                manufacturer=self.manufacturer,
                url=item.url,
                title=item.title,
                published=parse_press_date(item.date),
                categories=("In The Press",),
            )
