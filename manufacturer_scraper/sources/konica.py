"""Konica Minolta global newsroom — news releases.

The release list (one page, ~6 months of items) carries date, title, link,
category labels and a thumbnail. Article detail pages carry a rich
meta description and og:image, fetched per NEW item.
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

LIST_URL = "https://www.konicaminolta.com/global-en/newsroom/release/index.html"
DATE_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})")
GENERIC_THUMBNAIL = re.compile(r"default_thumbnail")


@dataclass
class KonicaListItem:
    date: str
    title: str
    url: str
    categories: tuple[str, ...]
    image_url: str | None


def parse_konica_list(html: str, base_url: str = LIST_URL) -> list[KonicaListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[KonicaListItem] = []
    for block in soup.select("div.newsroom-release-list"):
        title_link = block.select_one(".newsroom-release-list__txt__ttl a")
        if title_link is None or not title_link.get("href"):
            continue
        title = strip_html(title_link.get_text())
        if not title:
            continue

        date_text = ""
        date_el = block.select_one(".newsroom-release-list__txt__date")
        if date_el is not None:
            match = DATE_RE.search(date_el.get_text())
            date_text = match.group(1) if match else ""

        categories = tuple(
            strip_html(label.get_text())
            for label in block.select("a.newsroom-label")
            if strip_html(label.get_text())
        )

        image_url = None
        img = block.select_one(".newsroom-release-list__img img")
        if img is not None:
            src = img.get("data-src") or img.get("src") or ""
            if src and not GENERIC_THUMBNAIL.search(src):
                image_url = absolute_url(src, base_url)

        items.append(
            KonicaListItem(
                date=date_text,
                title=title,
                url=absolute_url(title_link["href"], base_url),
                categories=categories or ("News Release",),
                image_url=image_url,
            )
        )
    return items


def parse_konica_detail(html: str) -> tuple[str | None, str | None]:
    """Return (summary, og_image) from an article page. Either may be None."""
    soup = BeautifulSoup(html, "lxml")
    summary: str | None = None
    meta = soup.find("meta", attrs={"name": "description"})
    if meta is not None and strip_html(meta.get("content", "")):
        summary = strip_html(meta["content"])

    image_url: str | None = None
    og = soup.find("meta", attrs={"property": "og:image"})
    if og is not None and og.get("content"):
        image_url = og["content"].strip()
    return summary, image_url


class KonicaSource(BaseSource):
    name = "konica"
    manufacturer = "Konica Minolta"

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
        for item in parse_konica_list(response.text):
            yield Article(
                manufacturer=self.manufacturer,
                url=item.url,
                title=item.title,
                published=parse_date(item.date, "%Y.%m.%d"),
                categories=item.categories,
                image_url=item.image_url,
            )

    def enrich(self, article: Article) -> Article:
        if not article.url.startswith("https://www.konicaminolta.com/"):
            return article
        try:
            response = fetch(
                self.session,
                article.url,
                retries=self.settings.scraping.retries,
                delay_s=self.settings.scraping.request_delay_s,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("konica: could not enrich %s: %s", article.url, exc)
            return article
        summary, og_image = parse_konica_detail(response.text)
        return Article(
            manufacturer=article.manufacturer,
            url=article.url,
            title=article.title,
            published=article.published,
            categories=article.categories,
            summary=summary or article.summary,
            image_url=og_image or article.image_url,
            fetched_at=article.fetched_at,
        )
