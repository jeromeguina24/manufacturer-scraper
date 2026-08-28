from datetime import UTC, datetime

from manufacturer_scraper.models import parse_date
from manufacturer_scraper.sources.docuware import parse_docuware_list


def test_parse_list_extracts_items(load_fixture):
    items = parse_docuware_list(load_fixture("docuware_list.html"))
    assert len(items) == 3

    first = items[0]
    assert first.title == "New in Connect to Mail: Automatic e-invoice validation"
    assert first.url == (
        "https://start.docuware.com/blog/product-news/automatic-e-invoice-validation"
    )
    assert first.date == "Aug 12, 2026"


def test_parse_list_dates_parseable(load_fixture):
    items = parse_docuware_list(load_fixture("docuware_list.html"))
    assert all(parse_date(i.date, "%b %d, %Y") for i in items)
    assert parse_date(items[0].date, "%b %d, %Y") == datetime(2026, 8, 12, tzinfo=UTC)


def test_parse_list_images_and_summaries(load_fixture):
    items = parse_docuware_list(load_fixture("docuware_list.html"))

    assert items[0].image_url == "https://start.docuware.com/hubfs/Haken-1.webp"
    assert items[1].image_url == (
        "https://start.docuware.com/hubfs/blog-images/Product_blog/Dos_and_donts_817x432.jpg"
    )

    assert items[0].summary and items[0].summary.startswith(
        "Companies receive many e-invoices"
    )
    # The trailing "Read more" link text must not leak into the summary.
    assert all(i.summary and "Read more" not in i.summary for i in items)


def test_parse_list_empty_html():
    assert parse_docuware_list("<html><body></body></html>") == []
