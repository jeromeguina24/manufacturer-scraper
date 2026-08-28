import json
from datetime import UTC, datetime

from manufacturer_scraper.sources.duplo import parse_duplo_categories, parse_duplo_posts


def test_parse_categories(load_fixture):
    payload = json.loads(load_fixture("duplo_categories.json"))
    cat_map = parse_duplo_categories(payload)
    assert cat_map[315] == "Press Release"
    assert cat_map[400] == "Embellishment Hub"
    assert cat_map[4] == "Duplo Finishing Blog"


def test_parse_posts_extracts_all_fields(load_fixture):
    cat_map = parse_duplo_categories(json.loads(load_fixture("duplo_categories.json")))
    posts = parse_duplo_posts(json.loads(load_fixture("duplo_posts_p1.json")), cat_map)

    assert len(posts) == 2
    first = posts[0]
    assert first.manufacturer == "Duplo"
    assert first.title == (
        "Duplo USA to Highlight Business Growth Solutions at Printing United 2026"
    )
    assert first.url == (
        "https://www.duplousa.com/2026/08/"
        "duplo-usa-to-highlight-business-growth-solutions-at-printing-united-2026/"
    )
    assert first.published == datetime(2026, 8, 10, 8, 0, 51, tzinfo=UTC)
    assert first.categories == ("Press Release",)
    assert first.summary and "PRINTING United 2026" in first.summary
    assert first.image_url == (
        "https://www.duplousa.com/wp-content/uploads/2026/07/Homepage-1-scaled.png"
    )


def test_parse_posts_maps_multiple_categories(load_fixture):
    cat_map = parse_duplo_categories(json.loads(load_fixture("duplo_categories.json")))
    posts = parse_duplo_posts(json.loads(load_fixture("duplo_posts_p1.json")), cat_map)
    assert posts[1].categories == ("Embellishment Hub", "Press Release")


def test_parse_posts_without_embedded_media_has_no_image():
    cat_map = {1: "News"}
    payload = [
        {
            "link": "https://www.duplousa.com/2026/01/some-post/",
            "title": {"rendered": "Some post"},
            "date": "2026-01-05T10:00:00",
            "categories": [1],
            "excerpt": {"rendered": "<p>Teaser</p>"},
        }
    ]
    posts = parse_duplo_posts(payload, cat_map)
    assert len(posts) == 1
    assert posts[0].image_url is None
    assert posts[0].summary == "Teaser"


def test_parse_posts_skips_items_without_url_or_title():
    payload = [
        {"link": "", "title": {"rendered": "No url"}, "categories": []},
        {"link": "https://x/", "title": {"rendered": ""}, "categories": []},
    ]
    assert parse_duplo_posts(payload, {}) == []
