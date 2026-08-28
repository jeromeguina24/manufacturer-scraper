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

    store.mark_pushed(article.url, "row-9")
    assert store.is_pushed(article.url)
    assert store.row_id(article.url) == "row-9"


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
    store.mark_pushed(article.url, "1")
    store.insert_new(article)  # must not reset status
    assert store.is_pushed(article.url)


def test_pending_articles_excludes_pushed_and_failed(store):
    a_new = make_article(url="https://example.com/new")
    a_pushed = make_article(url="https://example.com/pushed")
    a_failed = make_article(url="https://example.com/failed")
    store.insert_new(a_new)
    store.insert_new(a_pushed)
    store.insert_new(a_failed)
    store.mark_pushed(a_pushed.url, "row-1")
    store.mark_failed(a_failed.url, "boom")

    pending = store.pending_articles()
    assert [a.url for a in pending] == ["https://example.com/new"]


def test_row_id_helpers(store):
    article = make_article()
    store.insert_new(article)
    assert store.row_id(article.url) is None
    store.set_row_id(article.url, "row-7")
    assert store.row_id(article.url) == "row-7"


def test_clear_unpushed_row_ids(store):
    new_one = make_article(url="https://example.com/n")
    pushed = make_article(url="https://example.com/p")
    failed = make_article(url="https://example.com/f")
    for a in (new_one, pushed, failed):
        store.insert_new(a)
        store.set_row_id(a.url, f"row-{a.url[-1]}")
    store.mark_pushed(pushed.url, "row-p")
    store.mark_failed(failed.url, "boom")

    store.clear_unpushed_row_ids()

    assert store.row_id(new_one.url) is None  # cleared
    assert store.row_id(failed.url) is None  # cleared
    assert store.row_id(pushed.url) == "row-p"  # kept


def test_meta_get_set(store):
    assert store.meta_get("hubdb_table_id") is None
    store.meta_set("hubdb_table_id", "123")
    assert store.meta_get("hubdb_table_id") == "123"
    store.meta_set("hubdb_table_id", "456")  # upsert
    assert store.meta_get("hubdb_table_id") == "456"


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


def test_migration_adds_hubdb_row_id_to_old_schema(tmp_path):
    """A database created before the HubDB pivot gains hubdb_row_id + meta."""
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE articles (
            url             TEXT PRIMARY KEY,
            manufacturer    TEXT NOT NULL,
            title           TEXT NOT NULL,
            summary         TEXT,
            image_url       TEXT,
            published_at    TEXT,
            categories      TEXT,
            status          TEXT NOT NULL DEFAULT 'new',
            hubspot_post_id TEXT,
            hubspot_slug    TEXT,
            error           TEXT,
            first_seen_at   TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        INSERT INTO articles (url, manufacturer, title, first_seen_at, updated_at)
        VALUES ('https://example.com/old', 'Canon', 'Old article', '2026-01-01', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    store = Store(path)  # runs the migration
    assert store.has_seen("https://example.com/old")  # old data intact
    store.set_row_id("https://example.com/old", "row-1")
    assert store.row_id("https://example.com/old") == "row-1"
    store.meta_set("hubdb_table_id", "t-1")
    assert store.meta_get("hubdb_table_id") == "t-1"
    store.close()
