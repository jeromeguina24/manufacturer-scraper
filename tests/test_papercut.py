from datetime import UTC, datetime

from manufacturer_scraper.sources.papercut import (
    extract_papercut_tiles,
    parse_papercut_detail,
    parse_papercut_tiles,
)


def test_extract_tiles_from_x_init_attribute(load_fixture):
    tiles = extract_papercut_tiles(load_fixture("papercut_blog.html"))
    assert len(tiles) == 4
    assert tiles[0]["card_link"] == "/blog/releases/new-in-papercut-hive-and-pocket-q2-2026/"


def test_extract_tiles_missing_returns_empty():
    assert extract_papercut_tiles("<html><body></body></html>") == []


def test_parse_tiles_extracts_all_fields(load_fixture):
    tiles = parse_papercut_tiles(extract_papercut_tiles(load_fixture("papercut_blog.html")))
    assert len(tiles) == 4

    first = tiles[0]
    assert first.title.startswith("PaperCut Hive Q2 2026")
    assert first.url == (
        "https://www.papercut.com/blog/releases/new-in-papercut-hive-and-pocket-q2-2026/"
    )
    assert first.published == datetime(2026, 8, 10, 0, 1, tzinfo=UTC)
    assert first.categories == ("Releases",)
    assert first.image_url and first.image_url.startswith("https://")


def test_parse_tiles_category_casing(load_fixture):
    tiles = parse_papercut_tiles(extract_papercut_tiles(load_fixture("papercut_blog.html")))
    assert tiles[1].categories == ("Print and Scan",)


def test_parse_tiles_sorted_newest_first(load_fixture):
    raw = extract_papercut_tiles(load_fixture("papercut_blog.html"))
    tiles = parse_papercut_tiles(list(reversed(raw)))  # shuffle input order
    dates = [t.published for t in tiles]
    assert dates == sorted(dates, reverse=True)
    assert tiles[-1].title == "The Start"
    assert tiles[-1].published == datetime(2004, 8, 9, tzinfo=UTC)
    assert tiles[-1].image_url is None


def test_parse_tiles_skips_entries_without_link_or_heading():
    tiles = parse_papercut_tiles(
        [
            {"card_link": "", "heading": "No link"},
            {"card_link": "/blog/x/", "heading": ""},
            {"card_link": "/blog/ok/", "heading": "Ok"},
        ]
    )
    assert len(tiles) == 1
    assert tiles[0].url == "https://www.papercut.com/blog/ok/"
    assert tiles[0].categories == ("Blog",)


def test_parse_detail_meta_description():
    html = (
        "<html><head>"
        '<meta name="description" content="A release summary.">'
        "</head><body></body></html>"
    )
    assert parse_papercut_detail(html) == "A release summary."
    assert parse_papercut_detail("<html><head></head></html>") is None
