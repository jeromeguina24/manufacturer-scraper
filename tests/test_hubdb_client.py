import json

import pytest
import responses

from manufacturer_scraper.hubspot.client import HubSpotClient, HubSpotError

BASE = "https://api.hubapi.com"


@pytest.fixture
def client():
    return HubSpotClient("test-token")


@responses.activate
def test_create_hubdb_table_payload(client):
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables",
        json={"id": "7001", "name": "manufacturer_news"},
        status=200,
    )
    columns = [
        {"name": "title", "label": "Title", "type": "TEXT"},
        {"name": "published_date", "label": "Published date", "type": "DATE"},
    ]
    table = client.create_hubdb_table("manufacturer_news", "Manufacturer News", columns)
    assert table["id"] == "7001"

    # requests auto-sets the JSON content type per request (no session-level
    # Content-Type header — that would break multipart file uploads).
    assert responses.calls[0].request.headers["Content-Type"] == "application/json"
    body = json.loads(responses.calls[0].request.body)
    assert body["name"] == "manufacturer_news"
    assert body["label"] == "Manufacturer News"
    assert body["columns"] == columns


@responses.activate
def test_create_hubdb_row_payload(client):
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/7001/rows",
        json={"id": "row-1"},
        status=201,
    )
    row = client.create_hubdb_row(
        "7001", {"title": "Some Post", "published_date": 1753833600000}, name="Some Post"
    )
    assert row["id"] == "row-1"

    body = json.loads(responses.calls[0].request.body)
    assert body["values"] == {"title": "Some Post", "published_date": 1753833600000}
    assert body["name"] == "Some Post"


@responses.activate
def test_create_hubdb_row_without_name_omits_key(client):
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/7001/rows",
        json={"id": "row-1"},
        status=201,
    )
    client.create_hubdb_row("7001", {"title": "x"})
    body = json.loads(responses.calls[0].request.body)
    assert "name" not in body


@responses.activate
def test_publish_hubdb_table_hits_push_live(client):
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/hubdb/tables/7001/draft/push-live",
        json={"id": "7001"},
        status=200,
    )
    result = client.publish_hubdb_table("7001")
    assert result["id"] == "7001"
    assert responses.calls[0].request.url.endswith("/cms/v3/hubdb/tables/7001/draft/push-live")


@responses.activate
def test_get_hubdb_table_404_returns_none(client):
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables/missing",
        json={"status": "error"},
        status=404,
    )
    assert client.get_hubdb_table("missing") is None


@responses.activate
def test_get_hubdb_table_other_error_raises(client):
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables/7001",
        json={"status": "error"},
        status=403,
    )
    with pytest.raises(HubSpotError):
        client.get_hubdb_table("7001")


@responses.activate
def test_list_hubdb_rows(client):
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables/7001/rows",
        json={"results": [{"id": "row-1"}, {"id": "row-2"}]},
        status=200,
    )
    rows = client.list_hubdb_rows("7001", limit=2)
    assert [r["id"] for r in rows] == ["row-1", "row-2"]


@responses.activate
def test_429_is_retried_with_backoff(client, monkeypatch):
    monkeypatch.setattr("manufacturer_scraper.hubspot.client.time.sleep", lambda _s: None)
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables",
        json={"results": []},
        status=429,
        headers={"Retry-After": "1"},
    )
    responses.add(
        responses.GET,
        f"{BASE}/cms/v3/hubdb/tables",
        json={"results": [{"id": "7001"}]},
        status=200,
    )
    tables = client.list_hubdb_tables()
    assert tables == [{"id": "7001"}]
    assert len(responses.calls) == 2
