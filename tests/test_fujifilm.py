
from manufacturer_scraper.sources.fujifilm import parse_fujifilm_detail, parse_fujifilm_list


def test_parse_list_extracts_items(load_fixture):
    items = parse_fujifilm_list(load_fixture("fujifilm_list_p1.html"))
    assert len(items) >= 20

    titles = [i.title for i in items]
    assert any("Horizontal Closed-Loop Recycling" in t for t in titles)

    urls = [i.url for i in items]
    # Internal article links are absolutized.
    assert "https://www.fujifilm.com/fb/en/news/15455e" in urls
    # External holdings links are kept as-is.
    assert any(u.startswith("https://holdings.fujifilm.com/") for u in urls)


def test_parse_list_dates_and_categories(load_fixture):
    items = parse_fujifilm_list(load_fixture("fujifilm_list_p1.html"))
    by_url = {i.url: i for i in items}
    recycling = by_url["https://www.fujifilm.com/fb/en/news/15455e"]
    assert recycling.date == "Jul 23, 2026"
    # Emphasis tag (News Release) comes first, then other tags.
    assert recycling.categories[0] == "News Release"
    assert "Sustainability" in recycling.categories


def test_parse_detail_extracts_summary_and_image(load_fixture):
    summary, image_url = parse_fujifilm_detail(load_fixture("fujifilm_detail_internal.html"))
    # The lead paragraph — not the contact boilerplate further down the page.
    assert summary is not None
    assert summary.startswith("TOKYO, July 23, 2026")
    assert image_url is not None
    assert image_url.startswith("https://asset-fb.fujifilm.com/")


def test_parse_detail_handles_empty_page():
    summary, image_url = parse_fujifilm_detail("<html><body></body></html>")
    assert summary is None
    assert image_url is None
