"""Base class for manufacturer newsroom sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import ClassVar

import requests

from manufacturer_scraper.config import Settings
from manufacturer_scraper.models import Article


class BaseSource(ABC):
    """A manufacturer newsroom.

    `iter_articles` yields cheap list-page stubs and should STOP paginating as
    soon as a full page consists of already-seen URLs (newsrooms are
    reverse-chronological). `enrich` fetches the article detail page for
    summary/image and is only called for NEW articles.
    """

    name: ClassVar[str]  # short id, e.g. "fujifilm"
    manufacturer: ClassVar[str]  # display name, e.g. "Fujifilm"

    def __init__(self, settings: Settings, session: requests.Session) -> None:
        self.settings = settings
        self.session = session
        self.source_settings = settings.sources.get(self.name)

    @property
    def enabled(self) -> bool:
        return self.source_settings is None or self.source_settings.enabled

    @property
    def extra(self) -> dict:
        return self.source_settings.extra if self.source_settings else {}

    @abstractmethod
    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        """Yield articles from list pages, newest first."""

    def enrich(self, article: Article) -> Article:
        """Fetch detail-page data (summary/image) for one new article.

        Default is a no-op for sources whose list pages already carry everything.
        Implementations must be defensive: every field stays optional.
        """
        return article
