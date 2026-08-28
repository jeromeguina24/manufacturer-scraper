from datetime import UTC, datetime

from manufacturer_scraper.models import parse_date
from manufacturer_scraper.sources.laserfiche import (
    parse_laserfiche_detail,
    parse_laserfiche_list,
)


def test_parse_list_extracts_items(load_fixture):
    items = parse_laserfiche_list(load_fixture("laserfiche_list.html"))
    assert len(items) == 4

    first = items[0]
    assert first.title.startswith("Laserfiche Launches Advanced Enterprise Security")
    assert first.url == (
        "https://www.laserfiche.com/resources/press-center/press/"
        "enterprise-security-launch/"
    )
    assert first.date == "August 06, 2026"


def test_parse_list_dates_parseable(load_fixture):
    items = parse_laserfiche_list(load_fixture("laserfiche_list.html"))
    # Zero-padded ("August 06, 2026") and plain ("July 14, 2026") both parse.
    assert all(parse_date(i.date, "%B %d, %Y") for i in items)
    assert parse_date(items[0].date, "%B %d, %Y") == datetime(2026, 8, 6, tzinfo=UTC)
    assert parse_date(items[1].date, "%B %d, %Y") == datetime(2026, 7, 14, tzinfo=UTC)


def test_parse_list_order_and_links(load_fixture):
    items = parse_laserfiche_list(load_fixture("laserfiche_list.html"))
    assert all(i.url.startswith("https://www.laserfiche.com/resources/press-center/press/") for i in items)
    assert items[-1].title.startswith("Laserfiche Launches on AWS Marketplace")


def test_parse_detail_extracts_summary_and_image(load_fixture):
    summary, image = parse_laserfiche_detail(load_fixture("laserfiche_detail.html"))
    assert summary and summary.startswith("Laserfiche is now available on AWS Marketplace")
    assert image == (
        "https://www.laserfiche.com/wp-content/uploads/2026/06/AWS-Announcement-1.png"
    )


def test_parse_detail_missing_meta_returns_none():
    summary, image = parse_laserfiche_detail("<html><head></head><body></body></html>")
    assert summary is None
    assert image is None
