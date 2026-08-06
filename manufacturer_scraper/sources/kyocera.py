"""Kyocera Europe newsroom (europe.kyocera.com/news/).

Scrapes ALL Kyocera Europe news but only imports items tagged with one of the
printer-related categories (configurable via `include_categories`).
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

NEWS_BASE = "https://europe.kyocera.com/news/"
FIRST_PAGE = NEWS_BASE + "index.html"
PAGE_URL = NEWS_BASE + "index_{page}.html"

# Heuristics for the optional detail-image fetch (logos/common assets to skip).
_IMAGE_BLOCKLIST = ("_assets/img/common", "ogp", "logo", "icon", "statement")


@dataclass
class KyoceraListItem:
    date: str
    title: str
    url: str
    categories: tuple[str, ...]
    summary: str | None


def _norm_category(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def parse_kyocera_list(html: str, base_url: str = NEWS_BASE) -> list[KyoceraListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[KyoceraListItem] = []
    for li in soup.select("li.news-BoxA_Item"):
        link = li.select_one("a.news-BoxA_Link")
        title_el = li.select_one(".news-BoxA_Title")
        date_el = li.select_one(".news-BoxA_PostDate")
        if link is None or not link.get("href") or title_el is None or date_el is None:
            continue
        title = strip_html(title_el.get_text())
        if not title:
            continue

        categories = tuple(
            strip_html(cat.get_text())
            for cat in li.select("ul.news-BoxA_Categories > li.news-BoxA_Category")
            if strip_html(cat.get_text())
        )

        summary = None
        subtitle = li.select_one(".news-BoxA_SubTitle")
        if subtitle is not None and strip_html(subtitle.get_text()):
            summary = strip_html(subtitle.get_text())
        else:
            sumally = li.select_one(".news-BoxA_Sumally")
            if sumally is not None and strip_html(sumally.get_text()):
                summary = strip_html(sumally.get_text())

        items.append(
            KyoceraListItem(
                date=strip_html(date_el.get_text()),
                title=title,
                url=absolute_url(link["href"], base_url),
                categories=categories,
                summary=summary,
            )
        )
    return items


def matches_scope(categories: tuple[str, ...], include_categories: list[str]) -> bool:
    if not include_categories:
        return True
    wanted = {_norm_category(c) for c in include_categories}
    return any(_norm_category(cat) in wanted for cat in categories)


def extract_detail_image(html: str, base_url: str = NEWS_BASE) -> str | None:
    """First content <img> that is not a known logo/common asset (best effort)."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("main") or soup
    for img in main.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        absolute = absolute_url(src, base_url)
        lowered = absolute.lower()
        if any(block in lowered for block in _IMAGE_BLOCKLIST):
            continue
        return absolute
    return None


class KyoceraSource(BaseSource):
    name = "kyocera"
    manufacturer = "Kyocera"

    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        delay = self.settings.scraping.request_delay_s
        retries = self.settings.scraping.retries
        include_categories = list(self.extra.get("include_categories") or [])

        page = 1
        while max_pages is None or page <= max_pages:
            url = FIRST_PAGE if page == 1 else PAGE_URL.format(page=page)
            response = fetch(
                self.session, url, retries=retries, delay_s=delay, acceptable=(200, 404)
            )
            if response.status_code == 404:
                break
            items = parse_kyocera_list(response.text, base_url=url)
            if not items:
                break

            articles = [
                Article(
                    manufacturer=self.manufacturer,
                    url=item.url,
                    title=item.title,
                    published=parse_date(item.date, "%d %B %Y"),
                    categories=item.categories,
                    summary=item.summary,
                )
                for item in items
                if matches_scope(item.categories, include_categories)
            ]
            yield from articles

            # Stop condition uses ALL items on the page (including filtered-out
            # ones), otherwise we would page through years of non-printer news.
            if all(is_seen(item.url) for item in items):
                log.debug("kyocera: page %d fully seen — stopping", page)
                break
            page += 1

    def enrich(self, article: Article) -> Article:
        if not self.extra.get("fetch_detail_images") or article.image_url:
            return article
        try:
            response = fetch(
                self.session,
                article.url,
                retries=self.settings.scraping.retries,
                delay_s=self.settings.scraping.request_delay_s,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("kyocera: could not enrich %s: %s", article.url, exc)
            return article
        image_url = extract_detail_image(response.text, base_url=article.url)
        if not image_url:
            return article
        return Article(
            manufacturer=article.manufacturer,
            url=article.url,
            title=article.title,
            published=article.published,
            categories=article.categories,
            summary=article.summary,
            image_url=image_url,
            fetched_at=article.fetched_at,
        )
