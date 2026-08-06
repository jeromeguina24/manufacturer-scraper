import json
from datetime import UTC, datetime

import pytest
import responses

from manufacturer_scraper.config import HubSpotSettings, ScrapingSettings, Settings
from manufacturer_scraper.hubspot.client import HubSpotClient
from manufacturer_scraper.hubspot.publisher import HubSpotPublisher, PublishError
from manufacturer_scraper.models import Article
from manufacturer_scraper.store import Store

BASE = "https://api.hubapi.com"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def settings():
    return Settings(
        hubspot=HubSpotSettings(
            blog_id="blog-guid",
            blog_author_id="author-1",
            image_folder_path="/news-import",
            post_state="PUBLISHED",
            tag_exclude=("News Release",),
            custom_properties=True,
            access_token="test-token",
        ),
        scraping=ScrapingSettings(),
        sources={},
    )


@pytest.fixture
def publisher(store, settings):
    return HubSpotPublisher(HubSpotClient("test-token"), store, settings)


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


@responses.activate
def test_publish_creates_post_with_linkback_and_metadata(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-9"}, status=201
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/blogs/posts",
        json={"id": "post-1"},
        status=201,
    )

    post_id, slug = publisher.publish(make_article())
    assert post_id == "post-1"
    assert slug.startswith("canon-2026-07-30-some-post")

    body = json.loads(responses.calls[-1].request.body)
    assert body["name"] == "Some Post"
    assert body["content_group_id"] == "blog-guid"
    assert body["blog_author_id"] == "author-1"
    assert body["state"] == "PUBLISHED"
    assert body["publish_date"].startswith("2026-07-30T09:01:51")
    assert body["tag_ids"] == ["tag-9"]
    # Linkback is always present in the body.
    assert 'href="https://cpp.canon/some-post"' in body["post_body"]
    assert "Read the full article on the Canon website" in body["post_body"]
    assert body["meta_description"] == "A short summary."
    # Custom properties carried alongside the linkback.
    assert body["properties"]["source_url"] == "https://cpp.canon/some-post"
    assert body["properties"]["manufacturer"] == "Canon"


@responses.activate
def test_tag_cache_avoids_second_creation(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-9"}, status=201
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p1"}, status=201
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p2"}, status=201
    )

    publisher.publish(make_article(url="https://x/1"))
    publisher.publish(make_article(url="https://x/2"))

    tag_creates = [c for c in responses.calls if c.request.url.endswith("/cms/v3/blogs/tags")
                   and c.request.method == "POST"]
    assert len(tag_creates) == 1  # cached the second time


@responses.activate
def test_slug_collision_gets_suffix(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-9"}, status=201
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"status": "error"}, status=409
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p1"}, status=201
    )

    post_id, slug = publisher.publish(make_article())
    assert post_id == "p1"
    assert slug.endswith("-2")


@responses.activate
def test_image_import_happy_path(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-1"}, status=201
    )
    responses.add(
        responses.POST,
        f"{BASE}/files/v3/files/import-from-url/async",
        json={"id": "task-1"},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE}/files/v3/files/import-from-url/async/tasks/task-1/status",
        json={
            "status": "COMPLETE",
            "files": [{"id": "file-7", "path": "/hubfs/news-import/pic.jpg"}],
        },
        status=200,
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p1"}, status=201
    )

    article = make_article(image_url="https://example.com/pic.jpg")
    publisher.publish(article)

    post_body = json.loads(responses.calls[-1].request.body)
    assert post_body["featured_image"] == "file-7"
    assert store.cached_image("https://example.com/pic.jpg") == (
        "file-7",
        "/hubfs/news-import/pic.jpg",
    )


@responses.activate
def test_image_import_failure_publishes_without_image(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-9"}, status=201
    )
    responses.add(
        responses.POST,
        f"{BASE}/files/v3/files/import-from-url/async",
        json={"status": "error", "message": "nope"},
        status=400,
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p1"}, status=201
    )

    article = make_article(image_url="https://example.com/pic.jpg")
    post_id, _ = publisher.publish(article)
    assert post_id == "p1"
    post_body = json.loads(responses.calls[-1].request.body)
    assert "featured_image" not in post_body


@responses.activate
def test_429_is_retried_with_backoff(publisher, store, monkeypatch):
    monkeypatch.setattr("manufacturer_scraper.hubspot.client.time.sleep", lambda _s: None)
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=429,
        headers={"Retry-After": "1"},
    )
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/posts", json={"id": "p1"}, status=201
    )

    post_id, _ = publisher.publish(make_article())
    assert post_id == "p1"


@responses.activate
def test_non_conflict_api_error_raises_publish_error(publisher, store):
    responses.add(
        responses.GET, f"{BASE}/cms/v3/blogs/tags", json={"results": []}, status=200
    )
    responses.add(
        responses.POST, f"{BASE}/cms/v3/blogs/tags", json={"id": "tag-9"}, status=201
    )
    responses.add(
        responses.POST,
        f"{BASE}/cms/v3/blogs/posts",
        json={"status": "error", "message": "invalid"},
        status=400,
    )
    with pytest.raises(PublishError):
        publisher.publish(make_article())
