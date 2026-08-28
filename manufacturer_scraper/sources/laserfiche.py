"""Laserfiche press center (laserfiche.com/resources/press-center/).

WordPress site with the REST API locked down (401), so the HTML list is
scraped directly: `a.col-lg-6` cards with title, link and an
`<time class="entry-date" datetime="April 28, 2026">` text-format date.
Pagination runs through `?sf_paged=N`. The cards carry no summary or image;
`enrich` fetches meta description + og:image from each NEW article page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, absolute_url, parse_date, strip_html
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://www.laserfiche.com/resources/press-center/"
PAGE_URL = LIST_URL + "?sf_paged={page}"


@dataclass
class LaserficheListItem:
    date: str
    title: str
    url: str
    summary: str | None


def parse_laserfiche_list(html: str, base_url: str = LIST_URL) -> list[LaserficheListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[LaserficheListItem] = []
    for card in soup.select("a.col-lg-6"):
        href = card.get("href")
        title_el = card.select_one("h3.card__title")
        if not href or title_el is None:
            continue
        title = strip_html(title_el.get_text())
        if not title:
            continue

        date = ""
        time_el = card.select_one("time.entry-date")
        if time_el is not None:
            date = (time_el.get("datetime") or time_el.get_text()).strip()

        summary = None
        text_el = card.select_one("p.card-text")
        if text_el is not None and strip_html(text_el.get_text()):
            summary = strip_html(text_el.get_text())

        items.append(
            LaserficheListItem(
                date=date,
                title=title,
                url=absolute_url(href, base_url),
                summary=summary,
            )
        )
    return items


def parse_laserfiche_detail(html: str) -> tuple[str | None, str | None]:
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


class LaserficheSource(BaseSource):
    name = "laserfiche"
    manufacturer = "Laserfiche"

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
            items = parse_laserfiche_list(response.text, base_url=url)
            if not items:
                break

            for item in items:
                yield Article(
                    manufacturer=self.manufacturer,
                    url=item.url,
                    title=item.title,
                    published=parse_date(item.date, "%B %d, %Y"),
                    categories=("Press Release",),
                    summary=item.summary,
                )
            if all(is_seen(item.url) for item in items):
                log.debug("laserfiche: page %d fully seen — stopping", page)
                break
            page += 1

    def enrich(self, article: Article) -> Article:
        if not article.url.startswith("https://www.laserfiche.com/"):
            return article
        try:
            response = fetch(
                self.session,
                article.url,
                retries=self.settings.scraping.retries,
                delay_s=self.settings.scraping.request_delay_s,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("laserfiche: could not enrich %s: %s", article.url, exc)
            return article
        summary, og_image = parse_laserfiche_detail(response.text)
        if not summary and not og_image:
            return article
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
