from manufacturer_scraper.sources.fp import parse_fp_list


def test_parse_list_extracts_items(load_fixture):
    items = parse_fp_list(load_fixture("fp_newsroom.html"))
    assert len(items) == 3

    first = items[0]
    assert first.title == (
        "Navigating the USPS: How Smart Equipment Protects Your Bottom Line"
    )
    assert first.url == "https://www.fp-usa.com/navigating-the-usps"
    assert first.date == "2026-08-06T05:00:00.000Z"
    assert first.categories == ("FP News", "Mailroom Solutions", "USPS")
    assert first.summary and first.summary.startswith("If you work with mail")
    assert first.image_url and first.image_url.startswith("https://cdn0.scrvt.com/")


def test_parse_list_relative_links_absolutized(load_fixture):
    items = parse_fp_list(load_fixture("fp_newsroom.html"))
    assert all(item.url.startswith("https://www.fp-usa.com/") for item in items)


def test_parse_list_single_category(load_fixture):
    items = parse_fp_list(load_fixture("fp_newsroom.html"))
    assert items[2].title.startswith("FP Trax and the Operational Challenges")
    assert items[2].categories == ("Shipping Solutions",)


def test_parse_list_empty_html():
    assert parse_fp_list("<html><body></body></html>") == []
