import json
from datetime import UTC, datetime

import pytest
import responses

from manufacturer_scraper.config import HubSpotSettings, ScrapingSettings, Settings
from manufacturer_scraper.hubspot.client import HubSpotClient
from manufacturer_scraper.hubspot.syncer import (
    EXPECTED_COLUMNS,
    HUBDB_COLUMNS,
    HubDbSyncer,
    SyncError,
)
from manufacturer_scraper.models import Article
from manufacturer_scraper.store import Store

BASE = "https://api.hubapi.com"
TABLE = "manufacturer_news"
TABLE_ID = "7001"
TABLE_URL = f"{BASE}/cms/v3/hubdb/tables/{TABLE}"
# Once the table is adopted, rows/publish are addressed by numeric id.
ID_URL = f"{BASE}/cms/v3/hubdb/tables/{TABLE_ID}"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Keep retry backoff from slowing tests when a mock doesn't match."""
    monkeypatch.setattr("manufacturer_scraper.hubspot.client.time.sleep", lambda _s: None)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def settings():
    return Settings(
        hubspot=HubSpotSettings(
            hubdb_table_name=TABLE,
            access_token="test-token",
        ),
        scraping=ScrapingSettings(),
        sources={},
    )


@pytest.fixture
def syncer(store, settings):
    return HubDbSyncer(HubSpotClient("test-token"), store, settings)


def make_article(**overrides) -> Article:
    base = {
        "manufacturer": "Canon",
        "url": "https://cpp.canon/some-post",
        "title": "Some Post",
        "published": datetime(2026, 7, 30, 9, 1, 51, tzinfo=UTC),
        "categories": ("Security",),
        "summary": "A short summary.",
        "image_url": None,
    }
    base.update(overrides)
    return Article(**base)


def table_json(table_id="7001", columns=None):
    if columns is None:
        columns = [{"name": name, "type": "TEXT"} for name in EXPECTED_COLUMNS]
    return {"id": table_id, "name": TABLE, "columns": columns}


def mock_existing_table(table_id="7001"):
    responses.add(responses.GET, TABLE_URL, json=table_json(table_id), status=200)


def row_posts(calls):
    return [
        c
        for c in calls
        if c.request.method == "POST" and c.request.url.endswith("/rows")
    ]


def push_lives(calls):
    return [
        c
        for c in calls
        if c.request.method == "POST" and c.request.url.endswith("/draft/push-live")
    ]


@responses.activate
def test_sync_happy_path_creates_rows_and_publishes_once(syncer, store):
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-2"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )

    a1 = make_article(url="https://x/1", title="First Post")
    a2 = make_article(url="https://x/2", title="Second Post", manufacturer="Kyocera")
    store.insert_new(a1)
    store.insert_new(a2)

    outcome = syncer.sync_articles([a1, a2])

    assert outcome.pushed == 2
    assert outcome.failed == 0
    assert outcome.error is None
    assert len(row_posts(responses.calls)) == 2
    assert len(push_lives(responses.calls)) == 1
    assert store.is_pushed(a1.url) and store.is_pushed(a2.url)
    assert store.row_id(a1.url) == "row-1"
    assert store.row_id(a2.url) == "row-2"

    values = json.loads(responses.calls[1].request.body)  # first row POST
    assert values["name"] == "First Post"
    assert values["values"]["title"] == "First Post"
    assert values["values"]["manufacturer"] == "Canon"
    assert values["values"]["announcement_type"] == "Security"
    assert values["values"]["summary"] == "A short summary."
    assert values["values"]["source_url"] == "https://x/1"
    assert "image_path" not in values["values"]
    # DATE column: milliseconds at UTC midnight of the announcement date.
    expected_ms = int(datetime(2026, 7, 30, tzinfo=UTC).timestamp() * 1000)
    assert values["values"]["published_date"] == expected_ms


@responses.activate
def test_blank_categories_fall_back_to_news(syncer, store):
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )

    article = make_article(categories=("", "   "))
    store.insert_new(article)
    outcome = syncer.sync_articles([article])
    assert outcome.pushed == 1

    values = json.loads(row_posts(responses.calls)[0].request.body)
    assert values["values"]["announcement_type"] == "News"


@responses.activate
def test_missing_published_date_falls_back_to_fetched_at(syncer, store):
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )

    fetched = datetime(2026, 8, 1, 15, 30, tzinfo=UTC)
    article = make_article(published=None, fetched_at=fetched)
    store.insert_new(article)
    outcome = syncer.sync_articles([article])
    assert outcome.pushed == 1

    values = json.loads(row_posts(responses.calls)[0].request.body)
    expected_ms = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
    assert values["values"]["published_date"] == expected_ms


@responses.activate
def test_image_urls_are_not_synced(syncer, store):
    """Images are scraped but not synced — rows carry no image data."""
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )

    article = make_article(image_url="https://example.com/pic.jpg")
    store.insert_new(article)
    outcome = syncer.sync_articles([article])
    assert outcome.pushed == 1

    # The only HTTP calls are HubDB row + publish; no image traffic.
    assert all("hubdb" in c.request.url for c in responses.calls)
    values = json.loads(row_posts(responses.calls)[0].request.body)
    assert "image_path" not in values["values"]


@responses.activate
def test_push_live_failure_then_retry_does_not_duplicate_rows(syncer, store):
    """The key retry flow: rows are cached, the retry only re-publishes."""
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-2"}, status=201
    )
    responses.add(
        responses.POST,
        f"{ID_URL}/draft/push-live",
        json={"status": "error"},
        status=400,
    )

    a1 = make_article(url="https://x/1")
    a2 = make_article(url="https://x/2")
    store.insert_new(a1)
    store.insert_new(a2)

    outcome = syncer.sync_articles([a1, a2])
    assert outcome.pushed == 0
    assert outcome.failed == 2
    assert "push-live" in (outcome.error or "")
    assert store.status(a1.url) == "failed"
    # Row ids survived the failure.
    assert store.row_id(a1.url) == "row-1"
    assert store.row_id(a2.url) == "row-2"

    # Retry: same table, no new rows needed, publish succeeds this time.
    # The table id is cached in the store, so it is looked up by id now.
    responses.add(responses.GET, ID_URL, json=table_json(), status=200)
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )
    outcome = syncer.sync_articles([a1, a2])
    assert outcome.pushed == 2
    assert outcome.failed == 0
    # calls 0-3 were the first attempt; the retry is calls 4+ (GET + push-live).
    assert row_posts(responses.calls[4:]) == []  # zero row POSTs on the retry
    assert len(push_lives(responses.calls[4:])) == 1
    assert store.is_pushed(a1.url) and store.is_pushed(a2.url)


@responses.activate
def test_one_bad_row_does_not_block_the_batch(syncer, store):
    mock_existing_table()
    responses.add(
        responses.POST, f"{ID_URL}/rows", json={"id": "row-1"}, status=201
    )
    responses.add(
        responses.POST,
        f"{ID_URL}/rows",
        json={"status": "error", "message": "invalid"},
        status=400,
    )
    responses.add(
        responses.POST, f"{ID_URL}/draft/push-live", json={"id": "7001"}, status=200
    )

    a1 = make_article(url="https://x/1")
    a2 = make_article(url="https://x/2")
    store.insert_new(a1)
    store.insert_new(a2)

    outcome = syncer.sync_articles([a1, a2])
    assert outcome.pushed == 1
    assert outcome.failed == 1
    assert store.is_pushed(a1.url)
    assert store.status(a2.url) == "failed"


@responses.activate
def test_missing_table_is_created_and_published(syncer, store):
    responses.add(responses.GET, TABLE_URL, json={"status": "error"}, status=404)
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables",
        json={"id": "9", "name": TABLE},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/9/draft/push-live",
        json={"id": "9"},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/9/rows",
        json={"id": "row-1"},
        status=201,
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/9/draft/push-live",
        json={"id": "9"},
        status=200,
    )

    article = make_article()
    store.insert_new(article)
    outcome = syncer.sync_articles([article])
    assert outcome.pushed == 1
    assert store.meta_get("hubdb_table_id") == "9"

    create_body = json.loads(responses.calls[1].request.body)
    assert create_body["name"] == TABLE
    assert create_body["columns"] == HUBDB_COLUMNS


@responses.activate
def test_recreated_table_clears_unpushed_row_ids(syncer, store):
    new_one = make_article(url="https://x/n")
    pushed = make_article(url="https://x/p")
    failed = make_article(url="https://x/f")
    for a in (new_one, pushed, failed):
        store.insert_new(a)
        store.set_row_id(a.url, f"stale-{a.url[-1]}")
    store.mark_pushed(pushed.url, "stale-p")
    store.mark_failed(failed.url, "boom")

    responses.add(responses.GET, TABLE_URL, json={"status": "error"}, status=404)
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables",
        json={"id": "10", "name": TABLE},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/10/draft/push-live",
        json={"id": "10"},
        status=200,
    )

    table_id = syncer.ensure_table()
    assert table_id == "10"
    assert store.meta_get("hubdb_table_id") == "10"
    assert store.row_id(new_one.url) is None  # stale id dropped
    assert store.row_id(failed.url) is None
    assert store.row_id(pushed.url) == "stale-p"  # pushed rows are left alone


@responses.activate
def test_stale_meta_id_adopts_table_by_name(syncer, store):
    store.meta_set("hubdb_table_id", "dead-id")
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables/dead-id",
        json={"status": "error"},
        status=404,
    )
    responses.add(responses.GET, TABLE_URL, json=table_json("new-id"), status=200)

    table_id = syncer.ensure_table()
    assert table_id == "new-id"
    assert store.meta_get("hubdb_table_id") == "new-id"
    # No table was created.
    assert not any(
        c.request.method == "POST" and c.request.url.endswith("/hubdb/tables")
        for c in responses.calls
    )


@responses.activate
def test_missing_column_raises_sync_error(syncer, store):
    partial = [{"name": name, "type": "TEXT"} for name in EXPECTED_COLUMNS[:-1]]
    responses.add(
        responses.GET, TABLE_URL, json=table_json(columns=partial), status=200
    )

    with pytest.raises(SyncError, match="source_url"):
        syncer.ensure_table()

    article = make_article()
    store.insert_new(article)
    outcome = syncer.sync_articles([article])
    assert outcome.failed == 1
    assert "missing columns" in (outcome.error or "")
    assert store.status(article.url) == "failed"
    assert len(row_posts(responses.calls)) == 0  # no row work after a schema mismatch


@responses.activate
def test_empty_batch_makes_no_api_calls(syncer):
    outcome = syncer.sync_articles([])
    assert outcome.pushed == 0
    assert outcome.failed == 0
    assert len(responses.calls) == 0
