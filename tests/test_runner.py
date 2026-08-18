from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from manufacturer_scraper.models import Article
from manufacturer_scraper.runner import run_source
from manufacturer_scraper.sources.base import BaseSource


def _article(url: str, published: datetime | None) -> Article:
    return Article(
        manufacturer="Fake",
        url=url,
        title=f"Article {url}",
        published=published,
        categories=("News",),
    )


class FakeSource(BaseSource):
    name = "fake"
    manufacturer = "Fake"

    def __init__(self, articles: list[Article]) -> None:
        self._articles = articles

    def iter_articles(
        self,
        *,
        max_pages: int | None = None,
        is_seen: Callable[[str], bool] = lambda _url: False,
    ) -> Iterator[Article]:
        yield from self._articles


def test_min_year_skips_older_articles():
    source = FakeSource(
        [
            _article("https://x.test/2026", datetime(2026, 5, 1, tzinfo=UTC)),
            _article("https://x.test/2024", datetime(2024, 5, 1, tzinfo=UTC)),
            _article("https://x.test/2010", datetime(2010, 1, 1, tzinfo=UTC)),
        ]
    )
    result = run_source(source, None, dry_run=True, min_year=2026)
    assert result.found == 3
    assert result.new == 1
    assert result.skipped_old == 2


def test_min_year_boundary_is_inclusive():
    source = FakeSource([_article("https://x.test/a", datetime(2026, 1, 1, tzinfo=UTC))])
    result = run_source(source, None, dry_run=True, min_year=2026)
    assert result.new == 1
    assert result.skipped_old == 0


def test_no_min_year_imports_everything():
    source = FakeSource(
        [
            _article("https://x.test/a", datetime(2004, 8, 9, tzinfo=UTC)),
            _article("https://x.test/b", datetime(2026, 5, 1, tzinfo=UTC)),
        ]
    )
    result = run_source(source, None, dry_run=True, min_year=None)
    assert result.new == 2
    assert result.skipped_old == 0


def test_min_year_keeps_undated_articles():
    source = FakeSource(
        [
            _article("https://x.test/undated", None),
            _article("https://x.test/old", datetime(2001, 1, 1, tzinfo=UTC)),
        ]
    )
    result = run_source(source, None, dry_run=True, min_year=2026)
    assert result.new == 1
    assert result.skipped_old == 1
