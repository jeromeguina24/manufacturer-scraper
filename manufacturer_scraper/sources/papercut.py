"""PaperCut blog (papercut.com/blog/).

The blog index renders its full article list client-side (Alpine.js): the
whole tile array — link, heading, publish date, category filters and card
image — is embedded HTML-entity-encoded in an `x-init` attribute:

    x-init=" tiles = [{&#34;card_link&#34;:&#34;/blog/...&#34;, ...}], filteredTiles = ..."

There is no server-side pagination or RSS feed, so this single page is the
list source. Summaries are not in the tile data; `enrich` pulls the meta
description from each NEW article page.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, absolute_url, parse_iso_utc, strip_html
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://www.papercut.com/blog/"
BLOG_BASE = "https://www.papercut.com/blog/"
# Stop paginating once this many consecutive articles are already seen
# (tiles are sorted newest-first).
SEEN_STOP_WINDOW = 30

TILES_RE = re.compile(r"tiles\s*=\s*(\[.*?\])\s*,\s*filteredTiles", re.DOTALL)
_LOWERCASE = {"and", "or", "of", "the", "in", "for", "to", "at", "on"}


def _pretty_filter(value: str) -> str:
    """'PRINT_AND_SCAN' -> 'Print and Scan'."""
    words = value.replace("_", " ").split()
    pretty = [w.title() for w in words]
    for i, word in enumerate(pretty):
        if i > 0 and word.lower() in _LOWERCASE:
            pretty[i] = word.lower()
    return " ".join(pretty)


@dataclass
class PaperCutTile:
    url: str
    title: str
    published: datetime | None
    categories: tuple[str, ...]
    image_url: str | None


def extract_papercut_tiles(page_html: str) -> list[dict]:
    match = TILES_RE.search(page_html)
    if match is None:
        log.warning("papercut: embedded tile array not found in blog page")
        return []
    try:
        tiles = json.loads(html_module.unescape(match.group(1)))
    except ValueError as exc:
        log.warning("papercut: could not parse embedded tile array: %s", exc)
        return []
    return tiles if isinstance(tiles, list) else []


def parse_papercut_tiles(tiles: list[dict]) -> list[PaperCutTile]:
    parsed: list[PaperCutTile] = []
    for tile in tiles:
        link = (tile.get("card_link") or "").strip()
        title = strip_html(tile.get("heading") or "")
        if not link or not title:
            continue

        image = tile.get("image")
        image_url = None
        if isinstance(image, dict) and image.get("src"):
            image_url = absolute_url(str(image["src"]), BLOG_BASE)

        categories = tuple(
            _pretty_filter(str(f)) for f in tile.get("filters") or [] if str(f).strip()
        ) or ("Blog",)

        parsed.append(
            PaperCutTile(
                url=absolute_url(link, BLOG_BASE),
                title=title,
                published=parse_iso_utc(tile.get("publish_date") or ""),
                categories=categories,
                image_url=image_url,
            )
        )
    # Newest first; undated tiles last.
    parsed.sort(
        key=lambda t: t.published or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return parsed


def parse_papercut_detail(page_html: str) -> str | None:
    """Meta description of an article page, or None."""
    soup = BeautifulSoup(page_html, "lxml")
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta is not None and strip_html(meta.get("content", "")):
            return strip_html(meta["content"])
    return None


class PaperCutSource(BaseSource):
    name = "papercut"
    manufacturer = "PaperCut"

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
        tiles = parse_papercut_tiles(extract_papercut_tiles(response.text))

        consecutive_seen = 0
        for tile in tiles:
            yield Article(
                manufacturer=self.manufacturer,
                url=tile.url,
                title=tile.title,
                published=tile.published,
                categories=tile.categories,
                image_url=tile.image_url,
            )
            if is_seen(tile.url):
                consecutive_seen += 1
                if consecutive_seen >= SEEN_STOP_WINDOW:
                    log.debug("papercut: %d consecutive seen — stopping", consecutive_seen)
                    break
            else:
                consecutive_seen = 0

    def enrich(self, article: Article) -> Article:
        if not article.url.startswith(BLOG_BASE) or article.summary:
            return article
        try:
            response = fetch(
                self.session,
                article.url,
                retries=self.settings.scraping.retries,
                delay_s=self.settings.scraping.request_delay_s,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            log.warning("papercut: could not enrich %s: %s", article.url, exc)
            return article
        summary = parse_papercut_detail(response.text)
        if not summary:
            return article
        return Article(
            manufacturer=article.manufacturer,
            url=article.url,
            title=article.title,
            published=article.published,
            categories=article.categories,
            summary=summary,
            image_url=article.image_url,
            fetched_at=article.fetched_at,
        )
