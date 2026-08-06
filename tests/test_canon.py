import json
from datetime import UTC, datetime

from manufacturer_scraper.sources.canon import parse_canon_categories, parse_canon_posts


def test_parse_categories(load_fixture):
    payload = json.loads(load_fixture("canon_categories.json"))
    cat_map = parse_canon_categories(payload)
    assert cat_map[4149] == "Security"
    assert cat_map[125] == "News"
    assert cat_map[2646] == "Product news"


def test_parse_posts_extracts_all_fields(load_fixture):
    cat_map = parse_canon_categories(json.loads(load_fixture("canon_categories.json")))
    posts = parse_canon_posts(json.loads(load_fixture("canon_posts_p1.json")), cat_map)

    assert len(posts) == 4
    first = posts[0]
    assert first.manufacturer == "Canon"
    assert first.title.startswith("Vulnerability in PRISMAproduction")
    assert first.url == "https://cpp.canon/vulnerability-in-prismaproduction-cve-2026-3245/"
    assert first.published == datetime(2026, 7, 30, 9, 1, 51, tzinfo=UTC)
    assert first.categories == ("Security",)
    assert first.summary and "deserialization vulnerability" in first.summary
    assert first.image_url == "https://cpp.canon/app/uploads/2021/12/security-news.jpg"


def test_parse_posts_maps_multiple_categories(load_fixture):
    cat_map = parse_canon_categories(json.loads(load_fixture("canon_categories.json")))
    posts = parse_canon_posts(json.loads(load_fixture("canon_posts_p1.json")), cat_map)
    second = posts[1]
    assert second.categories == ("News", "Press Releases", "Product news")


def test_parse_posts_without_featured_media_has_no_image(load_fixture):
    cat_map = parse_canon_categories(json.loads(load_fixture("canon_categories.json")))
    posts = parse_canon_posts(json.loads(load_fixture("canon_posts_p1.json")), cat_map)
    assert posts[-1].image_url is None


def test_parse_posts_skips_items_without_url_or_title():
    cat_map = {1: "News"}
    payload = [
        {"link": "", "title": {"rendered": "No url"}, "categories": []},
        {"link": "https://x/", "title": {"rendered": ""}, "categories": []},
        {
            "link": "https://x/ok/",
            "title": {"rendered": "Ok"},
            "date": "2026-01-01T00:00:00",
            "categories": [1],
            "excerpt": {"rendered": "<p>s</p>"},
        },
    ]
    posts = parse_canon_posts(payload, cat_map)
    assert len(posts) == 1
    assert posts[0].url == "https://x/ok/"
    assert posts[0].categories == ("News",)
