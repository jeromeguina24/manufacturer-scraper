from datetime import UTC, datetime

from manufacturer_scraper.sources.hp import (
    extract_hp_archive,
    parse_hp_archive,
    parse_hp_categories,
)


def test_extract_archive_from_template(load_fixture):
    payload = extract_hp_archive(load_fixture("hp_newsroom.html"))
    assert len(payload) == 5
    assert payload[0]["t"].startswith("HP Brings Enterprise-Grade Android")


def test_extract_archive_missing_returns_empty():
    assert extract_hp_archive("<html><body>no archive here</body></html>") == []


def test_parse_archive_extracts_all_fields(load_fixture):
    articles = parse_hp_archive(extract_hp_archive(load_fixture("hp_newsroom.html")))
    assert len(articles) == 5

    first = articles[0]
    assert first.manufacturer == "HP"
    assert first.title.startswith("HP Brings Enterprise-Grade Android")
    assert first.url == (
        "https://www.hp.com/us-en/newsroom/blogs/2026/"
        "hp-brings-enterprise-grade-android-to-retail-and-hospitality.html"
    )
    assert first.published == datetime(2026, 7, 23, 15, 0, tzinfo=UTC)
    assert first.categories == ("Press Blogs",)
    assert first.summary and "HP Engage One Pro G2q" in first.summary
    # DAM path contains spaces; they must be percent-encoded.
    assert first.image_url and "%20" in first.image_url
    assert first.image_url.startswith("https://www.hp.com/content/dam/")


def test_parse_archive_pipe_separated_facets(load_fixture):
    articles = parse_hp_archive(extract_hp_archive(load_fixture("hp_newsroom.html")))
    financial = next(a for a in articles if "Fiscal 2026" in a.title)
    assert financial.categories == ("Financial", "Press Release")


def test_parse_archive_without_image(load_fixture):
    articles = parse_hp_archive(extract_hp_archive(load_fixture("hp_newsroom.html")))
    poly = next(a for a in articles if a.title.startswith("Poly's Award-Winning"))
    assert poly.image_url is None
    assert poly.categories == ("Press Release",)


def test_parse_archive_skips_entries_without_link_or_title():
    payload = [
        {"t": "", "l": "/us-en/newsroom/x.html"},
        {"t": "No link", "l": ""},
        {"t": "Ok", "l": "/us-en/newsroom/ok.html"},
    ]
    articles = parse_hp_archive(payload)
    assert len(articles) == 1
    assert articles[0].url == "https://www.hp.com/us-en/newsroom/ok.html"
    assert articles[0].categories == ("Newsroom",)


def test_parse_categories_cleanup():
    assert parse_hp_categories("topics-graphic_arts|categories-press_releases") == (
        "Graphic Arts",
        "Press Releases",
    )
    assert parse_hp_categories("newsroom-topics") == ("Newsroom",)
    assert parse_hp_categories("") == ("Newsroom",)
    # Duplicates are removed, order preserved.
    assert parse_hp_categories("topics-print|categories-print") == ("Print",)
