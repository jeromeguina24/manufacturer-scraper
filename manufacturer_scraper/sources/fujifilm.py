"""Fujifilm Business Innovation newsroom (fujifilm.com/fb/en/news)."""

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

LIST_URL = "https://www.fujifilm.com/fb/en/news"
PAGE_URL = "https://www.fujifilm.com/fb/en/news/all/all/all/all/p{page}"
INTERNAL_ARTICLE = re.compile(r"/fb/en/news/\d+e/?$")
# Images on article pages live in Vue bindings: <imgset :src="'https://asset-fb…'">
IMAGE_BINDING = re.compile(r":src=\"'(https://asset-fb\.fujifilm\.com[^']+)'\"")
# Lead paragraph: first <p> inside the first article-body template slot.
BODY_LEAD = re.compile(
    r"<template\s+v-slot:body[^>]*>\s*<div[^>]*m-wysiwyg[^>]*>\s*<p[^>]*>(.*?)</p>",
    re.DOTALL,
)
BOILERPLATE_PREFIXES = (
    "For customers with an inquiry",
    "For reporters with an inquiry",
    "* Product and service names",
)


@dataclass
class FujifilmListItem:
    date: str
    url: str
    title: str
    categories: tuple[str, ...]


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def parse_fujifilm_list(html: str, base_url: str = LIST_URL) -> list[FujifilmListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[FujifilmListItem] = []
    for dl in soup.select("dl.c-news-list__list"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            link = dd.find("a", class_="btn")
            if link is None or not link.get("href"):
                continue
            title = strip_html(link.get_text())
            if not title:
                span = link.find("span")
                title = strip_html(span.get_text()) if span else ""
            if not title:
                continue

            tags = [strip_html(t.get_text()) for t in dd.select("div.c-buttons__tags span.tag")]
            emphasis = [
                strip_html(t.get_text())
                for t in dd.select("div.c-buttons__tags span.tag.-emphasis")
            ]
            categories = _dedupe(emphasis + [t for t in tags if t not in emphasis])
            if not categories:
                categories = ("News",)

            items.append(
                FujifilmListItem(
                    date=strip_html(dt.get_text()),
                    url=absolute_url(link["href"], base_url),
                    title=title,
                    categories=categories,
                )
            )
    return items


def parse_fujifilm_detail(html: str) -> tuple[str | None, str | None]:
    """Return (summary, image_url) from an internal article page. Either may be None.

    Article paragraphs live in `div.m-wysiwyg` blocks inside Vue
    `<template v-slot:body>` slots; HTML parsers mangle <template> contents,
    so the lead paragraph is extracted from the raw HTML with a regex.
    """
    summary: str | None = None
    match = BODY_LEAD.search(html)
    if match:
        summary = strip_html(match.group(1)) or None

    if not summary:
        # Fallback for pages without the Vue img-paragraph markup: first
        # substantive paragraph that is not a stock boilerplate block.
        soup = BeautifulSoup(html, "lxml")
        for p in soup.find_all("p"):
            text = strip_html(p.get_text())
            if len(text) >= 80 and not text.startswith(BOILERPLATE_PREFIXES):
                summary = text
                break

    img = IMAGE_BINDING.search(html)
    image_url = img.group(1) if img else None
    return summary, image_url


class FujifilmSource(BaseSource):
    name = "fujifilm"
    manufacturer = "Fujifilm"

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
            items = parse_fujifilm_list(response.text, base_url=url)
            if not items:
                break

            articles = [
                Article(
                    manufacturer=self.manufacturer,
                    url=item.url,
                    title=item.title,
                    published=parse_date(item.date, "%b %d, %Y"),
                    categories=item.categories,
                )
                for item in items
            ]
            yield from articles
            if all(is_seen(article.url) for article in articles):
                log.debug("fujifilm: page %d fully seen — stopping", page)
                break
            page += 1

    def enrich(self, article: Article) -> Article:
        # External (holdings.fujifilm.com) items have no usable image/description.
        if not INTERNAL_ARTICLE.search(article.url):
            return article
        try:
            response = fetch(
                self.session,
                article.url,
                retries=self.settings.scraping.retries,
                delay_s=self.settings.scraping.request_delay_s,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("fujifilm: could not enrich %s: %s", article.url, exc)
            return article
        summary, image_url = parse_fujifilm_detail(response.text)
        return Article(
            manufacturer=article.manufacturer,
            url=article.url,
            title=article.title,
            published=article.published,
            categories=article.categories,
            summary=summary or article.summary,
            image_url=image_url or article.image_url,
            fetched_at=article.fetched_at,
        )
