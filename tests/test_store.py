from datetime import UTC, datetime

import pytest

from manufacturer_scraper.models import Article
from manufacturer_scraper.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def make_article(url="https://example.com/a", **overrides) -> Article:
    base = {
        "manufacturer": "Canon",
        "url": url,
        "title": "Title",
        "published": datetime(2026, 7, 30, tzinfo=UTC),
        "categories": ("News",),
        "summary": "Summary",
        "image_url": None,
    }
    base.update(overrides)
    return Article(**base)


def test_lifecycle_new_to_pushed(store):
    article = make_article()
    assert not store.has_seen(article.url)
    store.insert_new(article)
    assert store.has_seen(article.url)
    assert store.status(article.url) == "new"
    assert not store.is_pushed(article.url)

    store.mark_pushed(article.url, "12345", "some-slug")
    assert store.is_pushed(article.url)


def test_failed_rows_can_be_relisted(store):
    article = make_article(url="https://example.com/b")
    store.insert_new(article)
    store.mark_failed(article.url, "boom")
    failed = store.failed_articles()
    assert len(failed) == 1
    assert failed[0].url == article.url
    assert failed[0].title == "Title"
    assert failed[0].categories == ("News",)
    assert failed[0].published == article.published


def test_insert_is_idempotent(store):
    article = make_article()
    store.insert_new(article)
    store.mark_pushed(article.url, "1", "s")
    store.insert_new(article)  # must not reset status
    assert store.is_pushed(article.url)


def test_image_and_tag_caches(store):
    assert store.cached_image("https://img") is None
    store.cache_image("https://img", "42", "/hubfs/img.jpg")
    assert store.cached_image("https://img") == ("42", "/hubfs/img.jpg")

    assert store.cached_tag("Security") is None
    store.cache_tag("Security", "7")
    assert store.cached_tag("security") == "7"  # case-insensitive


def test_update_enrichment(store):
    article = make_article(summary=None, image_url=None)
    store.insert_new(article)
    store.update_enrichment(article.url, "new summary", "https://img/x.jpg")
    failed_or_not = store.failed_articles()  # not failed — check via raw row
    assert failed_or_not == []
    row = store._conn.execute(
        "SELECT summary, image_url FROM articles WHERE url = ?", (article.url,)
    ).fetchone()
    assert row["summary"] == "new summary"
    assert row["image_url"] == "https://img/x.jpg"


def test_record_run(store):
    store.record_run(
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        source="canon",
        dry_run=True,
        found=10,
        new=2,
        pushed=0,
        failed=0,
        skipped=8,
    )
    rows = store._conn.execute("SELECT * FROM runs").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "canon"
    assert rows[0]["dry_run"] == 1


def test_reopen_persistence(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.insert_new(make_article())
    store.close()

    store2 = Store(path)
    assert store2.has_seen("https://example.com/a")
    store2.close()
