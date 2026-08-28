"""HP newsroom (hp.com/us-en/newsroom.html).

The newsroom landing page embeds the ENTIRE article archive (~1000+ entries,
newest first) as a JSON array used by the faceted-search UI:

    [{"t": title, "d": description, "ad": epoch-ms date, "fi": image path,
      "l": article path, "f": "categories-...|topics-...", ...}, ...]

No pagination needed — one request gets everything. Items can optionally be
filtered with the `include_categories` source setting (see config.yaml).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from urllib.parse import quote

from manufacturer_scraper.http import fetch
from manufacturer_scraper.models import Article
from manufacturer_scraper.sources.base import BaseSource

log = logging.getLogger(__name__)

LIST_URL = "https://www.hp.com/us-en/newsroom.html"
SITE_ORIGIN = "https://www.hp.com"
ARCHIVE_MARKER = '[{"t":'
_FACET_PREFIXES = ("categories-", "topics-")
_SKIP_TOKENS = {"newsroom-topics"}


def extract_hp_archive(html: str) -> list[dict]:
    """Pull the embedded article array out of the newsroom page HTML."""
    start = html.find(ARCHIVE_MARKER)
    if start < 0:
        # Tolerate whitespace between the opening bracket and first object.
        match = re.search(r'\[\s*\{"t":', html)
        start = match.start() if match else -1
    if start < 0:
        log.warning("hp: embedded article archive not found in page")
        return []
    try:
        payload, _end = json.JSONDecoder().raw_decode(html[start:])
    except ValueError as exc:
        log.warning("hp: could not parse embedded article archive: %s", exc)
        return []
    return payload if isinstance(payload, list) else []


def _clean_facet_token(token: str) -> str:
    return token.replace("_", " ").strip().title()


def parse_hp_categories(facet: str) -> tuple[str, ...]:
    """`"topics-print|categories-press_release"` -> ("Print", "Press Release")."""
    categories: list[str] = []
    for group in (facet or "").split("|"):
        group = group.strip()
        for prefix in _FACET_PREFIXES:
            if group.startswith(prefix):
                group = group[len(prefix):]
                break
        for token in group.split(","):
            token = token.strip()
            if not token or token in _SKIP_TOKENS:
                continue
            cleaned = _clean_facet_token(token)
            if cleaned and cleaned not in categories:
                categories.append(cleaned)
    return tuple(categories) or ("Newsroom",)


def _epoch_ms_to_utc(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def parse_hp_archive(payload: list[dict]) -> list[Article]:
    articles: list[Article] = []
    for entry in payload:
        path = (entry.get("l") or "").strip()
        title = (entry.get("t") or "").strip()
        if not path or not title:
            continue

        image_url = None
        image_path = (entry.get("fi") or "").strip()
        if image_path:
            if not image_path.startswith("/"):
                image_path = "/" + image_path
            # DAM paths legitimately contain spaces; encode for a valid URL.
            image_url = SITE_ORIGIN + quote(image_path, safe="/%")

        summary = (entry.get("d") or "").strip() or None

        articles.append(
            Article(
                manufacturer="HP",
                url=SITE_ORIGIN + path,
                title=title,
                published=_epoch_ms_to_utc(entry.get("ad")),
                categories=parse_hp_categories(entry.get("f") or ""),
                summary=summary,
                image_url=image_url,
            )
        )
    return articles


def _norm_category(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


class HPSource(BaseSource):
    name = "hp"
    manufacturer = "HP"

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
        include_categories = list(self.extra.get("include_categories") or [])
        wanted = {_norm_category(c) for c in include_categories}

        for article in parse_hp_archive(extract_hp_archive(response.text)):
            if wanted and not any(_norm_category(c) in wanted for c in article.categories):
                continue
            yield article
