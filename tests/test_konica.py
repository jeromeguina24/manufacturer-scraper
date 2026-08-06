from datetime import UTC, datetime

from manufacturer_scraper.models import parse_date
from manufacturer_scraper.sources.konica import parse_konica_detail, parse_konica_list


def test_parse_list_extracts_items(load_fixture):
    items = parse_konica_list(load_fixture("konica_list.html"))
    assert len(items) == 26

    first = items[0]
    assert first.date == "2026.07.30"
    assert first.title.startswith("1st Quarter Financial Results")
    # Investor link with fragment is absolutized and kept intact.
    assert first.url.startswith(
        "https://www.konicaminolta.com/global-en/investors/ir_library/fr/index.html"
    )
    assert first.categories == ("Management",)


def test_parse_list_images_and_categories(load_fixture):
    items = parse_konica_list(load_fixture("konica_list.html"))
    by_title = {i.title: i for i in items}

    resilience = next(i for i in items if "Resilience Program" in i.title)
    assert resilience.categories == ("Management", "Sustainability")
    assert resilience.image_url == (
        "https://www.konicaminolta.com/global-en/newsroom/2026/img/0714-01-01-thumbnail.jpg"
    )
    del by_title

    # Generic default thumbnails are treated as "no image".
    financial = items[0]
    assert financial.image_url is None


def test_parse_list_dates_parseable(load_fixture):
    items = parse_konica_list(load_fixture("konica_list.html"))
    assert all(parse_date(i.date, "%Y.%m.%d") for i in items)
    assert parse_date(items[0].date, "%Y.%m.%d") == datetime(
        2026, 7, 30, tzinfo=UTC
    )


def test_parse_detail_extracts_summary_and_image(load_fixture):
    summary, image = parse_konica_detail(load_fixture("konica_detail.html"))
    assert summary and summary.startswith("Tokyo (July 14, 2026)")
    assert image == (
        "https://www.konicaminolta.com/global-en/newsroom/2026/img/0714-01-01-ogp.png"
    )


def test_parse_detail_missing_meta_returns_none():
    summary, image = parse_konica_detail("<html><head></head><body></body></html>")
    assert summary is None
    assert image is None
