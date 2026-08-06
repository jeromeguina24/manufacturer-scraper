"""Canon Production Printing newsroom — WordPress REST API (cpp.canon)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article, parse_iso_utc, strip_html
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

API_BASE = "https://cpp.canon/wp-json/wp/v2"


def parse_canon_categories(payload: list[dict]) -> dict[int, str]:
    return {int(cat["id"]): strip_html(cat.get("name", "")) for cat in payload}


def parse_canon_posts(payload: list[dict], cat_map: dict[int, str]) -> list[Article]:
    articles: list[Article] = []
    for post in payload:
        url = (post.get("link") or "").strip()
        title = strip_html(post.get("title", {}).get("rendered", ""))
        if not url or not title:
            continue

        summary = strip_html(post.get("excerpt", {}).get("rendered", "")) or None

        categories = tuple(
            cat_map[cid] for cid in post.get("categories", []) if cid in cat_map
        ) or ("Uncategorized",)

        image_url = None
        try:
            media = post["_embedded"]["wp:featuredmedia"][0]
            if isinstance(media, dict) and media.get("source_url"):
                image_url = media["source_url"]
        except (KeyError, IndexError, TypeError):
            image_url = None

        articles.append(
            Article(
                manufacturer="Canon",
                url=url,
                title=title,
                published=parse_iso_utc(post.get("date", "")),
                categories=categories,
                summary=summary,
                image_url=image_url,
            )
        )
    return articles


class CanonSource(BaseSource):
    name = "canon"
    manufacturer = "Canon"

    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        delay = self.settings.scraping.request_delay_s
        retries = self.settings.scraping.retries
        per_page = int(self.extra.get("per_page", 100))

        cat_response = fetch(
            self.session,
            f"{API_BASE}/categories",
            params={"per_page": 100},
            retries=retries,
            delay_s=delay,
        )
        cat_map = parse_canon_categories(cat_response.json())

        page = 1
        while max_pages is None or page <= max_pages:
            response = fetch(
                self.session,
                f"{API_BASE}/posts",
                params={"_embed": "1", "per_page": per_page, "page": page},
                retries=retries,
                delay_s=delay,
                acceptable=(200, 400),  # 400 = page out of range
            )
            if response.status_code == 400:
                break
            try:
                total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
            except ValueError:
                total_pages = page

            batch = parse_canon_posts(response.json(), cat_map)
            if not batch:
                break
            yield from batch
            if all(is_seen(article.url) for article in batch):
                log.debug("canon: page %d fully seen — stopping", page)
                break
            if page >= total_pages:
                break
            page += 1
